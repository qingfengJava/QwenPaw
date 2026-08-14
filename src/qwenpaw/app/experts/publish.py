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
from pathlib import Path
from typing import Optional

from ..enterprise import current_tenant_id
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
    from ...config.config import AgentProfileRef, load_config, save_config

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
    from ...config.config import load_config, save_config

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


def _init_workspace(workspace_dir: Path, language: str) -> None:
    """Create the standard workspace skeleton (sessions/memory/...)."""
    from ..routers.agents import _initialize_agent_workspace

    _initialize_agent_workspace(
        workspace_dir,
        skill_names=[],
        language=language,
    )


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

    spec = {
        **record.agent_spec,
        "id": agent_id,
        "name": record.name,
        "description": record.description,
        "workspace_dir": str(workspace_dir),
    }

    def _materialize() -> None:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        _register_agent_profile(agent_id, workspace_dir)
        if not (workspace_dir / "agent.json").exists():
            _init_workspace(workspace_dir, language)
        _write_agent_json(agent_id, workspace_dir, spec)

    await asyncio.to_thread(_materialize)

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

    if manager is not None:
        try:
            await manager.reload_agent(agent_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "expert %s published but hot-reload failed (loads lazily)",
                agent_id,
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
        e.id: e
        for e in await store.list_experts(status=EXPERT_STATUS_PUBLISHED)
    }

    agent_id = expert_team_agent_id(team_id)
    workspace_dir = _expert_workspace_dir(f"team_{team_id}")
    spec, soul_md = build_team_supervisor_spec(
        agent_id=agent_id,
        workspace_dir=str(workspace_dir),
        team=team,
        members=[
            published[m.expert_id]
            for m in team.members
            if m.expert_id in published
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

    updated = await store.set_team_status(
        team_id,
        EXPERT_STATUS_PUBLISHED,
        bump_version=True,
    )
    if manager is not None:
        try:
            await manager.reload_agent(agent_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "team %s published but hot-reload failed", agent_id
            )
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
