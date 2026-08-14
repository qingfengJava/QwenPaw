# -*- coding: utf-8 -*-
"""Expert-team orchestration: supervisor spec construction.

First-release strategy — *prompt-level orchestration with a runtime
hook point*: the team publishes as a supervisor agent whose system
prompt (SOUL.md) embeds the member roster, routing rules, and pipeline
sequencing contract. The supervisor is a regular qwenpaw agent, so the
existing runtime streams, memory, tools, and sandbox all work unchanged.

The ``TeamOrchestrator`` protocol below is the documented upgrade path
to runtime-level orchestration (router-mode member selection via a
lightweight LLM call, pipeline-mode chained ``run_turn`` across member
workspaces). The protocol is intentionally aligned with
``harnesses.base.HarnessAdapter.run_turn`` streaming semantics so a
future implementation can translate events transparently.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Protocol

from .models import (
    TEAM_MODE_PIPELINE,
    TEAM_MODE_ROUTER,
    ExpertRecord,
    ExpertTeamRecord,
    expert_agent_id,
)

logger = logging.getLogger(__name__)

_TEAM_SOUL_TEMPLATE = """# {name}

你是一个专家团协调者（supervisor），名称「{name}」。
{description}

## 专家成员

{member_roster}

## 协作规则

{mode_rules}

## 路由提示词

{router_prompt}
"""

_ROUTER_RULES = """当前模式：**router（按需路由）**

- 根据用户请求判断最匹配的成员专家；
- 以该专家的专业视角、遵循其 role_hint 完整作答；
- 当问题跨多个专业时，先给出结论，再分成员视角补充；
- 不要虚构成员不具备的能力。"""

_PIPELINE_RULES = """当前模式：**pipeline（流水线协作）**

- 按成员顺序依次完成各自阶段的产出；
- 每个阶段明确标注「【阶段 N：专家名】」；
- 后一阶段必须在前一阶段产出的基础上深化，而不是重复；
- 最终以「【汇总】」小节收束全流程结论。"""


class TeamOrchestrator(Protocol):
    """Runtime-level orchestration hook (future implementation).

    A future implementation selects/chains member agents per turn and
    yields the same streaming event shape as the console channel, so
    the chat proxy layer stays unchanged::

        class RuntimeTeamOrchestrator:
            async def run_turn(self, team, message, owner):
                # router: lightweight LLM picks one member agent
                # pipeline: chain member run_turns, outputs appended
                ...
    """

    async def run_turn(
        self,
        team: ExpertTeamRecord,
        message: str,
        owner: str,
    ):
        """Yield streaming events for one orchestrated turn."""


def _member_roster(
    team: ExpertTeamRecord,
    members: List[ExpertRecord],
) -> str:
    """Render the ordered member list with expert descriptions."""
    by_id = {m.expert_id: m for m in team.members}
    lines = []
    for index, expert in enumerate(members, start=1):
        binding = by_id.get(expert.id)
        hint = f"（{binding.role_hint}）" if binding and binding.role_hint else ""
        description = (expert.description or "（无描述）").strip()
        lines.append(
            f"{index}. **{expert.name}**{hint} — {description}\n"
            f"   运行时标识：`{expert_agent_id(expert.id)}`",
        )
    return "\n".join(lines) if lines else "（暂无成员）"


def build_team_supervisor_spec(
    agent_id: str,
    workspace_dir: str,
    team: ExpertTeamRecord,
    members: List[ExpertRecord],
) -> tuple[Dict[str, Any], str]:
    """Construct ``(agent_json_spec, soul_md)`` for one expert team.

    The spec is a plain ``AgentProfileConfig`` dict; the orchestration
    knowledge is injected through the workspace ``SOUL.md`` (one of the
    default ``system_prompt_files``), keeping the runtime untouched.
    """
    soul_md = _TEAM_SOUL_TEMPLATE.format(
        name=team.name,
        description=team.description or "",
        member_roster=_member_roster(team, members),
        mode_rules=(
            _PIPELINE_RULES
            if team.mode == TEAM_MODE_PIPELINE
            else _ROUTER_RULES
        ),
        router_prompt=team.router_prompt or "（未配置自定义路由提示词）",
    )
    spec = {
        "id": agent_id,
        "name": f"专家团：{team.name}",
        "description": team.description,
        "workspace_dir": workspace_dir,
        "backend": "qwenpaw",
        "language": "zh",
        "system_prompt_files": ["AGENTS.md", "SOUL.md", "PROFILE.md"],
    }
    return spec, soul_md
