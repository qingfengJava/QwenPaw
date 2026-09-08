# -*- coding: utf-8 -*-
"""Draft preview runtime: materialize an expert draft as a sandbox agent.

预览（调试）实例与线上发布实例完全隔离，保证「后台调试不影响前端业务」：

- agent id 使用 ``expert_{id}__draft``（见 ``expert_draft_agent_id``），
  与线上 ``expert_{id}`` 是两个不同的运行时 agent，前端业务经
  X-Agent-Id 直连线上 id，永远触达不到调试实例；
- workspace 物化在 ``workspaces/experts/.drafts/{expert_id}/``，不触碰
  线上 workspace 目录；调试会话/记忆/文件全部落在草稿工作区；
- 实例按需创建（``start_expert_preview``）、可随时销毁
  （``stop_expert_preview``）；发布成功后由 ``publish_expert`` 联动销毁；
- 仅 /api/admin/experts 平面（PERM_ADMIN_EXPERTS）可触达；xianwork
  读平面只读 published_experts 快照，草稿实例天然不进市场与员工列表。

物化步骤与 ``publish.py`` 同族（注册 profile → 初始化 workspace →
写 agent.json / PROFILE.md → 同步技能），但产物全部落在草稿目录。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from .models import (
    EXPERT_STATUS_ARCHIVED,
    expert_agent_id,
    expert_draft_agent_id,
)
from .publish import (
    EXPERTS_WORKSPACE_ROOT,
    _build_expert_spec,
    _expert_profile_md,
    _expert_workspace_dir,
    _init_workspace,
    _register_agent_profile,
    _sync_workspace_skills,
    _unregister_agent_profile,
    _write_agent_json,
)
from .store import get_expert_store

logger = logging.getLogger(__name__)

#: 草稿调试工作区根目录名（与线上 workspace 同级，前缀点号避免被枚举）。
DRAFT_WORKSPACE_DIRNAME = ".drafts"


def draft_workspace_dir(expert_id: str) -> Path:
    """草稿调试实例的 workspace 目录（从不与线上目录重叠）。"""
    from ...constant import WORKING_DIR

    return (
        Path(WORKING_DIR)
        / EXPERTS_WORKSPACE_ROOT
        / DRAFT_WORKSPACE_DIRNAME
        / expert_id
    )


async def start_expert_preview(
    expert_id: str,
    manager=None,
) -> dict:
    """按当前草稿物化调试实例并热加载（幂等：重复调用刷新草稿产物）。

    Returns:
        {"expert_id", "agent_id", "workspace_dir", "running": True}

    Raises:
        ValueError: expert 不存在（"not found"）或已归档（"archived"）。
    """
    store = get_expert_store()
    record = await store.get_expert(expert_id)
    if record is None:
        raise ValueError(f"expert {expert_id} not found")
    if record.status == EXPERT_STATUS_ARCHIVED:
        raise ValueError(f"expert {expert_id} is archived")

    agent_id = expert_draft_agent_id(expert_id)
    workspace_dir = draft_workspace_dir(expert_id)
    language = str(record.agent_spec.get("language") or "zh")
    skill_names = await store.enabled_skill_names(expert_id)
    caps = await _load_capability_snapshot(expert_id)

    # 调试实例 spec 以草稿 spec 为准，但 id/workspace 指向草稿域。
    spec = _build_expert_spec(record, agent_id, workspace_dir)

    def _materialize() -> None:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        _register_agent_profile(agent_id, workspace_dir)
        if not (workspace_dir / "agent.json").exists():
            _init_workspace(workspace_dir, language, skill_names)
        # 草稿可能随时改，agent.json 每次启动都重写（与 publish 一致）。
        _write_agent_json(agent_id, workspace_dir, spec)
        _sync_workspace_skills(workspace_dir, skill_names)
        (workspace_dir / "PROFILE.md").write_text(
            _expert_profile_md(record, skill_names, caps=caps),
            encoding="utf-8",
        )

    await asyncio.to_thread(_materialize)

    if manager is not None:
        try:
            await manager.reload_agent(agent_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "expert %s preview started but hot-reload failed (loads lazily)",
                expert_id,
                exc_info=True,
            )
    logger.info(
        "Expert %s preview instance materialized as agent %s",
        expert_id,
        agent_id,
    )
    return {
        "expert_id": expert_id,
        "agent_id": agent_id,
        "workspace_dir": str(workspace_dir),
        "running": True,
    }


async def stop_expert_preview(
    expert_id: str,
    manager=None,
    cleanup_workspace: bool = True,
) -> dict:
    """卸载调试实例并清理草稿 workspace（幂等：未运行时静默返回）。

    调试会话历史保留在后端会话存储中，仅销毁运行时实例与工作区。
    """
    agent_id = expert_draft_agent_id(expert_id)
    if manager is not None:
        try:
            await manager.stop_agent(agent_id)
        except Exception:  # pylint: disable=broad-except
            logger.debug("stop preview agent failed", exc_info=True)
    await asyncio.to_thread(_unregister_agent_profile, agent_id)
    if cleanup_workspace:
        workspace_dir = draft_workspace_dir(expert_id)
        if workspace_dir.is_dir():
            await asyncio.to_thread(
                shutil.rmtree, workspace_dir, ignore_errors=True
            )
    logger.info("Expert %s preview instance stopped", expert_id)
    return {
        "expert_id": expert_id,
        "agent_id": agent_id,
        "running": False,
    }


async def _is_profile_registered(agent_id: str) -> bool:
    """草稿实例是否仍在根配置 profiles 中注册（判定 running）。"""
    from ...config.utils import load_config

    def _check() -> bool:
        return agent_id in load_config().agents.profiles

    return await asyncio.to_thread(_check)


async def preview_status(expert_id: str) -> dict:
    """调试实例状态 + 草稿是否有未发布变更。

    ``has_unpublished_changes``：按当前草稿重建的 spec 与最新发布快照
    的 spec 做键序无关比较（spec 内嵌 live agent id/workspace，重建时
    使用与发布完全相同的入参，保证可比较）。
    """
    store = get_expert_store()
    record = await store.get_expert(expert_id)
    if record is None:
        raise ValueError(f"expert {expert_id} not found")

    agent_id = expert_draft_agent_id(expert_id)
    running = await _is_profile_registered(agent_id)

    snapshot = await store.latest_snapshot(expert_id)
    has_changes = False
    if snapshot is None:
        # 从未发布过：草稿本身即「未发布变更」。
        has_changes = True
    else:
        expected = _build_expert_spec(
            record,
            expert_agent_id(expert_id),
            _expert_workspace_dir(expert_id),
        )
        has_changes = _stable_json(expected) != _stable_json(snapshot.spec)

    return {
        "expert_id": expert_id,
        "agent_id": agent_id,
        "running": running,
        "has_unpublished_changes": has_changes,
        "expert_status": record.status,
        "published_version": snapshot.version if snapshot else None,
        "version": record.version,
    }


def _stable_json(value: Any) -> str:
    """键序无关的 JSON 序列化（DB JSONB 往返后的稳定比较基准）。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


async def _load_capability_snapshot(expert_id: str) -> Optional[dict]:
    """能力挂载快照（失败降级为 None，PROFILE.md 保持原形态）。"""
    try:
        from .capability import get_capability_store

        snapshot = await get_capability_store().member_capability_snapshot(
            [expert_id],
        )
        return snapshot.get(expert_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "expert %s capability snapshot failed; PROFILE.md w/o caps",
            expert_id,
            exc_info=True,
        )
        return None


async def refresh_expert_preview_profile(
    expert_id: str,
    manager=None,
) -> Optional[Path]:
    """能力绑定变更后重写草稿实例的 PROFILE.md（调试会话即时感知）。

    仅当草稿实例已启动（workspace 存在 agent.json）时执行；线上
    PROFILE.md 由发布流程物化，这里绝不触碰（发布边界收紧：
    后台调试期的绑定变更不再泄漏到线上）。best-effort：实例未运行
    返回 None，绑定随下次预览启动 / 发布生效。
    """
    store = get_expert_store()
    record = await store.get_expert(expert_id)
    if record is None:
        return None
    workspace_dir = draft_workspace_dir(expert_id)
    if not (workspace_dir / "agent.json").is_file():
        return None
    skill_names = await store.enabled_skill_names(expert_id)
    caps = await _load_capability_snapshot(expert_id)
    profile_path = workspace_dir / "PROFILE.md"
    await asyncio.to_thread(
        lambda: profile_path.write_text(
            _expert_profile_md(record, skill_names, caps=caps),
            encoding="utf-8",
        ),
    )
    if manager is not None:
        try:
            await manager.reload_agent(expert_draft_agent_id(expert_id))
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "expert %s preview profile refreshed but reload failed",
                expert_id,
                exc_info=True,
            )
    return profile_path
