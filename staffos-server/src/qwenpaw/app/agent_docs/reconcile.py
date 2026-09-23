# -*- coding: utf-8 -*-
"""Startup reconciliation between PG identity documents and workspace files.

Phase B 权威裁决：PG ``agent_documents`` 是档案文档的持久权威，
工作区文件是可重建的物化缓存。本模块在应用启动时（lifespan 后台
任务，不阻塞启动）对每个已注册 agent 工作区逐一处理四个白名单文件：

- PG 有行 & 文件缺失或内容不一致 → **以 PG 覆盖文件**（缓存重建，
  权威裁决），并 WARN 列出被覆盖文件供人工核查；
- PG 无行 & 文件存在 → 读文件回填种子（首次升级存量环境）；
- 一致或双无 → 跳过；单 agent 异常隔离继续。

多实例语义天然成立：每个实例启动对账一次，运行期间写路径双写
保证缓存新鲜。无 PG 部署（无 DSN）本模块为 no-op。

本模块另含 **expert 身份列对账**（T14）：``experts`` 表是数字员工
身份列（``name``/``description``）的权威，发布物化将其写入工作区
``agent.json``；身份列漂移（手工编辑 / 跨机恢复 / 历史遗留）由
``reconcile_expert_identities`` 以 experts 为准修复并 WARN，保持
「experts 权威 → agent.json 物化」单向收敛。

@author qingfeng
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from ..enterprise import enterprise_engine
from ..experts.models import EXPERT_STATUS_PUBLISHED, expert_agent_id
from ..experts.store import get_expert_store
from .store import (
    DOC_TYPE_BY_FILENAME,
    AgentDocsStore,
    content_hash,
    get_agent_docs_store,
)

logger = logging.getLogger(__name__)


async def _reconcile_one_document(
    store: AgentDocsStore,
    agent_id: str,
    filename: str,
    doc_type: str,
    workspace_dir: Path,
) -> str:
    """对齐一个档案文档，返回动作标签（promote/restore/overwrite/skip）。"""
    file_path = workspace_dir / filename

    def _read_file() -> str | None:
        try:
            return file_path.read_text(encoding="utf-8")
        except OSError:
            return None

    file_content = await asyncio.to_thread(_read_file)
    row = await store.get_document(agent_id, doc_type)

    if row is not None:
        row_content = str(row.get("content") or "")
        if file_content is not None and content_hash(file_content) == row.get(
            "content_hash",
        ):
            return "skip"
        # PG 权威裁决：覆盖物化缓存（文件缺失 = 缓存丢失，静默重建；
        # 内容漂移 = 需人工关注，显式告警）
        drifted = file_content is not None
        await asyncio.to_thread(
            lambda: file_path.parent.mkdir(parents=True, exist_ok=True),
        )
        await asyncio.to_thread(
            lambda: file_path.write_text(row_content, encoding="utf-8"),
        )
        if drifted:
            logger.warning(
                "Agent docs reconcile overwrote drifted file with PG "
                "authority: agent=%s file=%s",
                agent_id,
                filename,
            )
        return "overwrite" if drifted else "restore"

    if file_content is None:
        return "skip"
    # PG 无行：文件回填种子（幂等 upsert，内容不变不递增版本）
    await store.upsert_document(
        agent_id,
        doc_type,
        file_content,
        updated_by="startup_reconcile",
    )
    return "promote"


async def reconcile_agent_docs() -> dict:
    """启动对账入口（lifespan 后台任务；无 PG 时静默返回）。

    Returns:
        统计字典 {"agents": n, "overwrite": n, "restore": n,
        "promote": n, "skip": n}；无 PG 返回空 dict。
    """
    store = get_agent_docs_store()
    if store is None:
        return {}

    from ...config.utils import load_config

    try:
        profiles = dict(load_config().agents.profiles)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Agent docs reconcile skipped (config load failed)",
            exc_info=True,
        )
        return {}

    stats = {
        "agents": 0,
        "overwrite": 0,
        "restore": 0,
        "promote": 0,
        "skip": 0,
    }
    for agent_id, ref in profiles.items():
        workspace_dir = getattr(ref, "workspace_dir", None)
        if not workspace_dir:
            continue
        stats["agents"] += 1
        for filename, doc_type in DOC_TYPE_BY_FILENAME.items():
            try:
                action = await _reconcile_one_document(
                    store,
                    agent_id,
                    filename,
                    doc_type,
                    Path(workspace_dir),
                )
            except Exception:  # pylint: disable=broad-except
                # 单文档异常隔离，不阻断其余文档对账
                logger.warning(
                    "Agent docs reconcile failed: agent=%s file=%s",
                    agent_id,
                    filename,
                    exc_info=True,
                )
                continue
            stats[action] = stats.get(action, 0) + 1

    if any(stats[key] for key in ("overwrite", "restore", "promote")):
        logger.info("Agent docs reconcile finished: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Expert 身份列对账（T14）：experts 权威 vs 工作区 agent.json 身份列
# ---------------------------------------------------------------------------

#: 发布物化（publish._build_expert_spec）写入 agent.json 的专家域身份列：
#: id（运行时 agent 身份）、name / description（展示身份）。
#: workspace_dir 属环境路径（跨机不同）不参与对账。
_IDENTITY_FIELDS = ("id", "name", "description")


def _expert_workspace_dir(expert_id: str) -> Path:
    """One expert's workspace dir — 与发布物化同一路径来源。"""
    from ..experts.publish import _expert_workspace_dir as _impl

    return _impl(expert_id)


def _read_identity_snapshot(path: Path) -> Any:
    """Read the raw agent.json payload（纯读取，无 schema 副作用）。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _identity_drift(
    raw: dict,
    agent_id: str,
    name: str,
    description: str,
) -> list[str]:
    """Compare identity columns; return drifted field names ([] = clean)."""
    expected = {
        "id": agent_id,
        "name": name or "",
        "description": description or "",
    }
    return [
        field
        for field in _IDENTITY_FIELDS
        if str(raw.get(field) or "") != expected[field]
    ]


def _repair_identity(agent_id: str, name: str, description: str) -> None:
    """Overwrite agent.json identity columns from experts authority.

    经 ``mutate_agent_config`` 原子事务写：工作区文件与
    ``agent_documents`` 影子行一起更新（与全部 agent.json 变更路径
    同一收口），避免档案读平面的 PG 权威把修复回滚。
    """
    from ...config.config import mutate_agent_config

    def _mutator(cfg) -> None:
        cfg.id = agent_id
        cfg.name = name
        cfg.description = description or ""

    mutate_agent_config(agent_id, _mutator)


async def _reconcile_one_expert_identity(record) -> str:
    """Align one published expert; returns clean/repaired/skipped/failed."""
    expert_id = str(record.id)
    agent_id = expert_agent_id(expert_id)
    config_path = _expert_workspace_dir(expert_id) / "agent.json"
    if not await asyncio.to_thread(config_path.is_file):
        # 工作区未物化（无需对齐）——文件重建由档案对账域负责
        return "skipped"
    try:
        raw = await asyncio.to_thread(_read_identity_snapshot, config_path)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Expert identity reconcile cannot read agent.json: "
            "expert=%s agent=%s",
            expert_id,
            agent_id,
            exc_info=True,
        )
        return "failed"
    if not isinstance(raw, dict):
        logger.warning(
            "Expert identity reconcile found non-object agent.json: "
            "expert=%s agent=%s",
            expert_id,
            agent_id,
        )
        return "failed"
    drifts = _identity_drift(raw, agent_id, record.name, record.description)
    if not drifts:
        return "clean"
    try:
        # 修复必须留在事件循环线程执行：save_agent_config 的影子双写
        # 需要与 PG 引擎同一事件循环（to_thread 会退到后台循环，跨
        # loop 失败导致影子行丢失、下次启动被 PG 权威回滚）。
        _repair_identity(agent_id, record.name, record.description)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Expert identity drift detected but repair failed: "
            "expert=%s agent=%s fields=%s",
            expert_id,
            agent_id,
            ",".join(drifts),
            exc_info=True,
        )
        return "failed"
    logger.warning(
        "Expert identity drift repaired from expert authority: "
        "expert=%s agent=%s fields=%s",
        expert_id,
        agent_id,
        ",".join(drifts),
    )
    return "repaired"


async def reconcile_expert_identities() -> dict:
    """Expert 身份列启动对账（lifespan 后台任务；无 PG 时静默返回）。

    仅扫描 ``status=published`` 的专家（draft 无工作区、archived 已
    卸载）：读取工作区 ``agent.json`` 原始负载，与 ``experts`` 权威列
    （id/name/description）比对——一致 → 跳过；漂移 → WARN 并**以
    experts 为准修复**（经 ``mutate_agent_config`` 原子写，文件 +
    agent_documents 影子行同步）；工作区或文件缺失 → 跳过（文件重建
    由档案对账域负责）；单专家异常隔离，不阻断其余专家。

    Returns:
        统计字典 {"experts": n, "clean": n, "repaired": n, "skipped": n,
        "failed": n}；enterprise 平面不可用时返回空 dict。
    """
    if enterprise_engine() is None:
        return {}
    store = get_expert_store()
    try:
        experts = await store.list_experts(status=EXPERT_STATUS_PUBLISHED)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Expert identity reconcile skipped (expert store unavailable)",
            exc_info=True,
        )
        return {}
    stats = {
        "experts": len(experts),
        "clean": 0,
        "repaired": 0,
        "skipped": 0,
        "failed": 0,
    }
    for record in experts:
        try:
            action = await _reconcile_one_expert_identity(record)
        except Exception:  # pylint: disable=broad-except
            # 单专家异常隔离，不阻断其余专家对账
            logger.warning(
                "Expert identity reconcile failed: expert=%s",
                getattr(record, "id", "?"),
                exc_info=True,
            )
            action = "failed"
        stats[action] = stats.get(action, 0) + 1
    if stats["repaired"] or stats["failed"]:
        logger.info("Expert identity reconcile finished: %s", stats)
    return stats
