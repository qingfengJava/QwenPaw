# -*- coding: utf-8 -*-
"""Expert publishing: materialize a draft expert as a live agent.

Publish chain (all idempotent per step):

1. register ``expert_{id}`` in the root config's ``agents.profiles``
   (atomic save under the existing config lock — concurrent publishes
   serialize on it);
2. initialize the workspace and write ``agent.json`` from the draft
   ``agent_spec`` (structurally an ``AgentProfileConfig``);
3. persist an immutable snapshot in ``published_experts`` and bump the
   expert version;
4. hot-reload the agent through ``MultiAgentManager.reload_agent`` (or
   unload it on archive).

Team publishing ensures every member expert is published first, then
materializes the supervisor agent whose prompt embeds the member
roster (see ``team_runtime``).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from ..enterprise import current_tenant_id
from ..agent_docs.store import (
    DOC_TYPE_BY_FILENAME,
    get_agent_docs_store,
    promote_documents,
)
from .models import (
    EXPERT_STATUS_ARCHIVED,
    EXPERT_STATUS_DRAFT,
    EXPERT_STATUS_PUBLISHED,
    TEAM_MODE_PIPELINE,
    TEAM_MODE_ROUTER,
    ExpertRecord,
    ExpertTeamRecord,
    expert_agent_id,
    expert_team_agent_id,
)
from .store import get_expert_store
from .team_runtime import build_team_supervisor_spec

logger = logging.getLogger(__name__)

#: Workspaces of published experts live under this directory.
EXPERTS_WORKSPACE_ROOT = "workspaces/experts"


async def _resolve_publish_content(
    agent_id: str,
    doc_type: str,
    generated: str,
    spec_updated_at=None,
) -> str:
    """发布时档案内容取用：调试调优成果优先，spec 权威兜底。

    - draft 行不存在 → 用本次发布生成内容；
    - draft 行存在且其更新时间晚于 spec 最后变更 → 用草稿内容
      （调试期 AI 调优/手工编辑的成果必须随发布固化，否则调试白做）；
    - 其余（spec 比草稿新，如后台改了档案表单后未经调试直接发布）
      → 用生成内容，避免陈旧草稿覆盖新 spec；
    - PG 不可用/异常 → 用生成内容（发布永不因 PG 故障阻断）。
    """
    docs = get_agent_docs_store()
    if docs is None:
        return generated
    try:
        row = await docs.get_document(
            agent_id,
            doc_type,
            environment="draft",
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "expert %s draft doc read failed; publish uses generated",
            agent_id,
            exc_info=True,
        )
        return generated
    if row is None:
        return generated

    def _epoch(value) -> float:
        """归一化 PG/ISO 两种时间格式为 epoch 秒（解析失败按 0）。"""
        if isinstance(value, (int, float)):
            return float(value)
        try:
            from datetime import datetime

            return datetime.fromisoformat(str(value).strip()).timestamp()
        except (TypeError, ValueError):
            return 0.0

    draft_updated = _epoch(row.get("updated_at"))
    spec_updated = _epoch(spec_updated_at)
    if draft_updated > spec_updated:
        return str(row.get("content") or generated)
    return generated


async def _promote_publish_documents(
    agent_id: str,
    documents: dict,
    published_by: str,
) -> None:
    """发布闸门：把最终档案内容写入 production 权威行 + 版本快照。

    best-effort：PG 故障时告警不阻断发布（文件物化照常，启动对账
    会以文件回填种子），保证发布主链路健壮性。
    """
    try:
        promoted = await promote_documents(
            agent_id,
            documents,
            environment="production",
            updated_by=published_by,
        )
        if not promoted:
            logger.info(
                "expert %s publish skipped doc promote (PG unavailable)",
                agent_id,
            )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "expert %s publish doc promote failed (file plane live)",
            agent_id,
            exc_info=True,
        )


def _experts_root() -> Path:
    from ...constant import WORKING_DIR

    return Path(WORKING_DIR) / "experts"


def _expert_workspace_dir(expert_id: str) -> Path:
    from ...constant import WORKING_DIR

    return Path(WORKING_DIR) / EXPERTS_WORKSPACE_ROOT / expert_id


def _register_agent_profile(
    agent_id: str,
    workspace_dir: Path,
) -> None:
    """Add (or refresh) the root-config profile entry for one agent."""
    from ...config.config import AgentProfileRef
    from ...config.utils import load_config, save_config

    config = load_config()
    config.agents.profiles[agent_id] = AgentProfileRef(
        id=agent_id,
        workspace_dir=str(workspace_dir),
        enabled=True,
    )
    if agent_id not in config.agents.agent_order:
        config.agents.agent_order = [
            *config.agents.agent_order,
            agent_id,
        ]
    save_config(config)


def _unregister_agent_profile(agent_id: str) -> None:
    """Remove the root-config profile entry (archive path)."""
    from ...config.utils import load_config, save_config

    config = load_config()
    config.agents.profiles.pop(agent_id, None)
    if agent_id in config.agents.agent_order:
        config.agents.agent_order = [
            a for a in config.agents.agent_order if a != agent_id
        ]
    save_config(config)


def _write_agent_json(
    agent_id: str,
    workspace_dir: Path,
    spec: dict,
) -> None:
    """Validate + persist the expert spec as the workspace agent.json."""
    from ...config.config import AgentProfileConfig, save_agent_config

    agent_config = AgentProfileConfig(**spec)
    save_agent_config(agent_id, agent_config)


def _init_workspace(
    workspace_dir: Path,
    language: str,
    skill_names: Optional[List[str]] = None,
) -> None:
    """Create the standard workspace skeleton (sessions/memory/skills)."""
    from ..routers.agents import _initialize_agent_workspace

    _initialize_agent_workspace(
        workspace_dir,
        skill_names=skill_names or [],
        language=language,
    )


def _default_workspace_dir() -> Optional[Path]:
    """The default agent workspace (shared skill source), if resolvable."""
    from ...config.utils import load_config

    try:
        ref = load_config().agents.profiles.get("default")
        if ref and ref.workspace_dir:
            return Path(ref.workspace_dir)
    except Exception:  # pylint: disable=broad-except
        logger.debug("default workspace resolution failed", exc_info=True)
    return None


def _sync_workspace_skills(
    workspace_dir: Path,
    desired: List[str],
) -> None:
    """Reconcile the workspace ``skills/`` directory with the bindings.

    First publishes install skills through ``_init_workspace``; once
    ``agent.json`` exists that initializer is skipped, so every publish
    runs this diff instead: stale directories are removed and missing
    ones are installed — from the shared pool first, falling back to a
    plain copy from the default workspace (the catalog the xian plane
    lists). Failures warn but never block publishing (same tolerance
    as ``_install_initial_skills``).
    """
    from ...agents.skill_system.pool_service import SkillPoolService
    from ...agents.skill_system.store import get_workspace_skills_dir

    skills_dir = get_workspace_skills_dir(workspace_dir)
    skills_dir.mkdir(parents=True, exist_ok=True)
    existing = {child.name for child in skills_dir.iterdir() if child.is_dir()}
    wanted = set(desired)

    for stale in sorted(existing - wanted):
        shutil.rmtree(skills_dir / stale, ignore_errors=True)
        logger.info(
            "removed stale skill %s from workspace %s",
            stale,
            workspace_dir.name,
        )

    default_skills: Optional[Path] = None
    default_dir = _default_workspace_dir()
    if default_dir is not None:
        candidate = get_workspace_skills_dir(default_dir)
        if candidate.is_dir():
            default_skills = candidate

    pool = SkillPoolService()
    for name in sorted(wanted - existing):
        result = pool.download_to_workspace(
            skill_name=name,
            workspace_dir=workspace_dir,
            overwrite=False,
        )
        if result.get("success"):
            continue
        if default_skills is not None:
            source = default_skills / name
            if source.is_dir():
                shutil.copytree(source, skills_dir / name)
                logger.info(
                    "copied skill %s from default workspace into %s",
                    name,
                    workspace_dir.name,
                )
                continue
        logger.warning(
            "skill %s unavailable for workspace %s (%s); "
            "publishing continues without it",
            name,
            workspace_dir.name,
            result.get("reason"),
        )


_PROFILE_TEMPLATE = """# {name}

{title_line}

## 角色设定

{persona}

## 工作方法（ReAct 循环）

对每个任务严格遵循以下循环，直至产出达标：

1. **理解**：复述任务目标与关键约束，识别歧义并向用户澄清；
2. **规划**：拆解为可执行的步骤，明确每步的产出与所需工具/技能；
3. **决策**：选择最合适的工具、技能或知识完成当前步骤；
4. **生成**：产出该步骤结果；
5. **核验**：对照目标检查结果，发现偏差则回到第 2 步重新规划并修正；
6. 循环期间可调用工具、查阅技能手册、回填记忆中的关键信息。

## 已配置技能

{skill_list}

> 技能位于工作区 ``skills/`` 目录，运行时按需渐进加载；使用技能能力前先阅读其 SKILL.md 说明。
{capability_sections}
"""

_SOP_SECTION_TEMPLATE = """
## 绑定 SOP（经验路径参考，非硬性状态机）

任务命中下列流程时优先按其步骤推进；可自主选择更优实现路径，
但产出需覆盖各步骤的验收要点。

{sop_list}
"""

_KB_SECTION_TEMPLATE = """
## 绑定知识库

回答涉及下列知识库的问题时优先检索引用，并给出来源：
{kb_list}
"""

_TOOL_SECTION_TEMPLATE = """
## 已挂载工具

以下工具已对本员工开放，按需选用：
{tool_list}
"""


def _capability_sections(caps: Optional[dict]) -> str:
    """Render the mounted-capability sections of PROFILE.md (P1 收尾).

    ``caps`` 为 capability snapshot（sops/kb_ids/tools，可能为空）：
    - SOP：目标 + 步骤验收要点（每 SOP 最多 8 步，紧凑渲染）；
    - 知识库/工具：清单级引用（运行时检索与工具可用性由平台面保证）。
    空快照返回空串（PROFILE.md 保持原形态）。
    """
    if not caps:
        return ""
    sections = ""
    sops = caps.get("sops") or []
    if sops:
        lines = []
        for sop in sops:
            goal = str(sop.get("goal") or "").strip()
            head = f"- **《{sop.get('name')}》**{('：' + goal) if goal else ''}"
            lines.append(head)
            for index, step in enumerate(sop.get("steps") or [], start=1):
                title = str(step.get("t") or "").strip()
                outcome = str(step.get("ok") or "").strip()
                line = f"  {index}. {title}" if title else f"  {index}."
                if outcome:
                    line += f"（验收：{outcome}）"
                lines.append(line)
        sections += _SOP_SECTION_TEMPLATE.format(sop_list="\n".join(lines))
    kb_ids = caps.get("kb_ids") or []
    if kb_ids:
        kb_list = "\n".join(f"- `{kb_id}`" for kb_id in kb_ids)
        sections += _KB_SECTION_TEMPLATE.format(kb_list=kb_list)
    tools = caps.get("tools") or []
    if tools:
        tool_list = "\n".join(f"- `{name}`" for name in tools)
        sections += _TOOL_SECTION_TEMPLATE.format(tool_list=tool_list)
    return sections


def _expert_profile_md(
    record,
    skill_names: List[str],
    caps: Optional[dict] = None,
) -> str:
    """Render the expert persona card materialized as PROFILE.md.

    ``caps``（能力挂载快照）非空时追加绑定 SOP/知识库/工具段
    （20260830 P1 收尾：直聊会话经 PROFILE.md 系统提示词生效）。
    """
    persona = (record.system_prompt or "").strip()
    if not persona:
        persona = (
            f"你是「{record.name}」，一位专业的 {(record.title or '领域').strip()}。"
            f"{record.description or ''}"
        ).strip()
    title_line = f"**职称**：{record.title}" if record.title else "**职称**：领域专家"
    if record.description:
        title_line += f"  \n**简介**：{record.description}"
    if skill_names:
        skill_list = "\n".join(f"- `{name}`" for name in skill_names)
    else:
        skill_list = "（未绑定技能，依赖通用能力）"
    return _PROFILE_TEMPLATE.format(
        name=record.name,
        title_line=title_line,
        persona=persona,
        skill_list=skill_list,
        capability_sections=_capability_sections(caps),
    )


def _build_expert_spec(
    record,
    agent_id: str,
    workspace_dir: Path,
) -> dict:
    """Assemble the workspace ``agent.json`` spec for one expert.

    Skills are deliberately absent: ``AgentProfileConfig`` has no skills
    field and silently drops unknown keys, so the binding set never
    enters the spec — it is materialized into the workspace ``skills/``
    directory instead (see ``_sync_workspace_skills``).
    """
    return {
        **record.agent_spec,
        "id": agent_id,
        "name": record.name,
        "description": record.description,
        "workspace_dir": str(workspace_dir),
    }


async def publish_expert(
    expert_id: str,
    published_by: str,
    manager=None,
) -> ExpertRecord:
    """Materialize one draft/published expert as a live agent.

    Args:
        expert_id: the expert record id.
        published_by: username performing the publish (audit trail).
        manager: optional ``MultiAgentManager`` for hot reload.

    Returns:
        The updated expert record (status=published, version bumped).

    Raises:
        ValueError: expert missing, or already archived.
    """
    store = get_expert_store()
    record = await store.get_expert(expert_id)
    if record is None:
        raise ValueError(f"expert {expert_id} not found")
    if record.status == EXPERT_STATUS_ARCHIVED:
        raise ValueError("archived experts cannot be re-published")

    agent_id = expert_agent_id(expert_id)
    workspace_dir = _expert_workspace_dir(expert_id)
    language = str(record.agent_spec.get("language") or "zh")
    # The enabled binding set is the materialization input: skills are
    # NEVER written into ``spec`` (AgentProfileConfig has no skills
    # field and silently drops unknown keys) — they live in the
    # workspace ``skills/`` directory the runtime auto-discovers.
    skill_names = await store.enabled_skill_names(expert_id)
    # 能力挂载快照（绑定 SOP/知识/工具）随 PROFILE.md 物化——直聊
    # 会话经系统提示词生效（P1 收尾）；快照失败降级为 None（原形态）
    caps: Optional[dict] = None
    try:
        from .capability import get_capability_store

        snapshot = await get_capability_store().member_capability_snapshot(
            [expert_id],
        )
        caps = snapshot.get(expert_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "expert %s capability snapshot failed; PROFILE.md w/o caps",
            expert_id,
            exc_info=True,
        )

    spec = _build_expert_spec(record, agent_id, workspace_dir)
    # 档案内容先渲染后落盘：供 _materialize 写文件与影子双写共用同一份
    profile_md = _expert_profile_md(record, skill_names, caps=caps)

    def _materialize() -> None:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        _register_agent_profile(agent_id, workspace_dir)
        if not (workspace_dir / "agent.json").exists():
            _init_workspace(workspace_dir, language, skill_names)
        _write_agent_json(agent_id, workspace_dir, spec)
        # Re-publishes (agent.json exists) land here: reconcile the
        # workspace skill set with the current bindings table.
        _sync_workspace_skills(workspace_dir, skill_names)
        # The persona card is refreshed on every publish (mirrors the
        # team SOUL.md policy below).
        (workspace_dir / "PROFILE.md").write_text(
            profile_md,
            encoding="utf-8",
        )

    await asyncio.to_thread(_materialize)
    # 发布闸门（Phase B）：production 权威行 + 版本快照。PROFILE.md
    # 取用规则见 _resolve_publish_content（调试调优成果 vs spec 生成）。
    profile_final = await _resolve_publish_content(
        agent_id,
        DOC_TYPE_BY_FILENAME["PROFILE.md"],
        profile_md,
        spec_updated_at=record.updated_at,
    )
    if profile_final != profile_md:
        # 草稿调优版胜出：把物化文件也换成草稿内容（与 PG 保持一致）
        await asyncio.to_thread(
            lambda: (workspace_dir / "PROFILE.md").write_text(
                profile_final,
                encoding="utf-8",
            ),
        )
    documents = {
        DOC_TYPE_BY_FILENAME["PROFILE.md"]: profile_final,
        DOC_TYPE_BY_FILENAME["agent.json"]: await asyncio.to_thread(
            lambda: (workspace_dir / "agent.json").read_text(
                encoding="utf-8",
            ),
        ),
    }
    # AGENTS.md / SOUL.md 无 spec 生成器（纯调优内容）：草稿行存在则随发布固化
    docs_store = get_agent_docs_store()
    for filename in ("AGENTS.md", "SOUL.md"):
        if docs_store is None:
            break
        try:
            row = await docs_store.get_document(
                agent_id,
                DOC_TYPE_BY_FILENAME[filename],
                environment="draft",
            )
        except Exception:  # pylint: disable=broad-except
            row = None
        if row is not None and row.get("content"):
            documents[DOC_TYPE_BY_FILENAME[filename]] = str(row["content"])
    await _promote_publish_documents(
        agent_id,
        documents,
        published_by,
    )

    await store.insert_snapshot(
        expert_id,
        record.version,
        spec,
        published_by,
    )
    updated = await store.set_expert_status(
        expert_id,
        EXPERT_STATUS_PUBLISHED,
        bump_version=True,
    )

    # 发布即物化员工分桶记忆到 workspace memory/（D4 注入通道；
    # best-effort：失败不阻断发布，下次记忆变更会重建）
    try:
        from .memories import materialize_expert_memory

        await materialize_expert_memory(expert_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "expert %s published but memory materialization failed",
            expert_id,
            exc_info=True,
        )

    if manager is not None:
        try:
            await manager.reload_agent(agent_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "expert %s published but hot-reload failed (loads lazily)",
                agent_id,
                exc_info=True,
            )

    # 发布成功后销毁草稿调试实例（若有）：线上已与草稿一致，
    # 调试通道完成使命（best-effort，不阻断发布结果）。
    try:
        from .preview import stop_expert_preview

        await stop_expert_preview(expert_id, manager=manager)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "expert %s published but preview stop failed",
            expert_id,
            exc_info=True,
        )

    logger.info(
        "Expert %s published as agent %s by %s (v%s)",
        expert_id,
        agent_id,
        published_by,
        record.version,
    )
    return updated or record


async def materialize_expert_profile(expert_id: str) -> Optional[Path]:
    """Re-materialize PROFILE.md for a published expert (binding changes).

    P1 收尾：能力挂载（SOP/知识/工具）变更后调用——直聊会话经
    PROFILE.md 系统提示词感知新绑定，无需整体重发布。best-effort：
    专家不存在/未发布（无 workspace）时静默返回 None。
    """
    store = get_expert_store()
    record = await store.get_expert(expert_id)
    if record is None or record.status != EXPERT_STATUS_PUBLISHED:
        return None
    workspace_dir = _expert_workspace_dir(expert_id)
    if not workspace_dir.is_dir():
        return None
    skill_names = await store.enabled_skill_names(expert_id)
    caps: Optional[dict] = None
    try:
        from .capability import get_capability_store

        snapshot = await get_capability_store().member_capability_snapshot(
            [expert_id],
        )
        caps = snapshot.get(expert_id)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "expert %s capability snapshot failed; PROFILE.md w/o caps",
            expert_id,
            exc_info=True,
        )
    profile_path = workspace_dir / "PROFILE.md"
    profile_md = _expert_profile_md(record, skill_names, caps=caps)
    await asyncio.to_thread(
        lambda: profile_path.write_text(profile_md, encoding="utf-8"),
    )
    # 能力绑定变更的档案同步 production 权威行（保持 PG 与文件一致；
    # best-effort：PG 故障不阻断文件物化，启动对账兜底）
    await _promote_publish_documents(
        expert_agent_id(expert_id),
        {DOC_TYPE_BY_FILENAME["PROFILE.md"]: profile_md},
        updated_by="capability_refresh",
    )
    return profile_path


async def archive_expert(
    expert_id: str,
    manager=None,
) -> Optional[ExpertRecord]:
    """Archive one expert and unload its runtime agent."""
    store = get_expert_store()
    agent_id = expert_agent_id(expert_id)
    if manager is not None:
        try:
            await manager.stop_agent(agent_id)
        except Exception:  # pylint: disable=broad-except
            logger.debug("stop agent on archive failed", exc_info=True)
    # 归档同时销毁草稿调试实例（若有，best-effort）。
    try:
        from .preview import stop_expert_preview

        await stop_expert_preview(expert_id, manager=manager)
    except Exception:  # pylint: disable=broad-except
        logger.debug(
            "stop preview on archive failed",
            exc_info=True,
        )
    await asyncio.to_thread(_unregister_agent_profile, agent_id)
    return await store.set_expert_status(expert_id, EXPERT_STATUS_ARCHIVED)


async def publish_expert_team(
    team_id: str,
    published_by: str,
    manager=None,
) -> ExpertTeamRecord:
    """Publish an expert team: members first, then the supervisor.

    Raises:
        ValueError: team missing, no members, or a member not published.
    """
    store = get_expert_store()
    team = await store.get_team(team_id)
    if team is None:
        raise ValueError(f"expert team {team_id} not found")
    if team.status == EXPERT_STATUS_ARCHIVED:
        raise ValueError("archived teams cannot be re-published")
    if not team.members:
        raise ValueError("an expert team needs at least one member")

    for member in team.members:
        expert = await store.get_expert(member.expert_id)
        if expert is None or expert.status != EXPERT_STATUS_PUBLISHED:
            raise ValueError(
                f"member expert {member.expert_id} must be published first",
            )

    # Resolve member metadata once for the supervisor prompt (five-step:
    # one batched list query instead of per-member lookups).
    published = {
        e.id: e for e in await store.list_experts(status=EXPERT_STATUS_PUBLISHED)
    }

    agent_id = expert_team_agent_id(team_id)
    workspace_dir = _expert_workspace_dir(f"team_{team_id}")
    spec, soul_md = build_team_supervisor_spec(
        agent_id=agent_id,
        workspace_dir=str(workspace_dir),
        team=team,
        members=[
            published[m.expert_id] for m in team.members if m.expert_id in published
        ],
    )

    def _materialize() -> None:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        _register_agent_profile(agent_id, workspace_dir)
        if not (workspace_dir / "agent.json").exists():
            _init_workspace(workspace_dir, "zh")
        _write_agent_json(agent_id, workspace_dir, spec)
        # The orchestration contract lives in SOUL.md (a default
        # system_prompt_files entry), refreshed on every publish.
        (workspace_dir / "SOUL.md").write_text(soul_md, encoding="utf-8")

    await asyncio.to_thread(_materialize)
    # 团队 SOUL.md 发布闸门：production 权威行 + 版本快照（团队无调试
    # 实例，生成内容即权威）
    await _promote_publish_documents(
        agent_id,
        {DOC_TYPE_BY_FILENAME["SOUL.md"]: soul_md},
        published_by,
    )

    updated = await store.set_team_status(
        team_id,
        EXPERT_STATUS_PUBLISHED,
        bump_version=True,
    )
    if manager is not None:
        try:
            await manager.reload_agent(agent_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning("team %s published but hot-reload failed", agent_id)
    logger.info("Expert team %s published by %s", team_id, published_by)
    return updated or team


async def archive_expert_team(
    team_id: str,
    manager=None,
) -> Optional[ExpertTeamRecord]:
    """Archive one expert team and unload its supervisor agent."""
    store = get_expert_store()
    agent_id = expert_team_agent_id(team_id)
    if manager is not None:
        try:
            await manager.stop_agent(agent_id)
        except Exception:  # pylint: disable=broad-except
            logger.debug("stop team agent on archive failed", exc_info=True)
    await asyncio.to_thread(_unregister_agent_profile, agent_id)
    return await store.set_team_status(team_id, EXPERT_STATUS_ARCHIVED)
