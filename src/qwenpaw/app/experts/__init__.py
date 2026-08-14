# -*- coding: utf-8 -*-
"""Expert / expert-team domain (XianWork Phase 3).

An expert is a *publishable wrapper* around an agent definition: the
draft ``agent_spec`` is structurally identical to a workspace
``agent.json``; publishing materializes it as a real agent (root-config
profile + workspace) so the existing MultiAgentManager runs it. A team
is a thin orchestration over published experts (see ``team_runtime``).
"""
from .models import (
    EXPERT_STATUS_DRAFT,
    EXPERT_STATUS_PUBLISHED,
    EXPERT_STATUS_ARCHIVED,
    TEAM_MODE_ROUTER,
    TEAM_MODE_PIPELINE,
    ExpertRecord,
    ExpertTeamRecord,
    TeamMember,
)
from .publish import archive_expert, archive_expert_team, publish_expert
from .store import ExpertStore, get_expert_store

__all__ = [
    "EXPERT_STATUS_DRAFT",
    "EXPERT_STATUS_PUBLISHED",
    "EXPERT_STATUS_ARCHIVED",
    "TEAM_MODE_ROUTER",
    "TEAM_MODE_PIPELINE",
    "ExpertRecord",
    "ExpertStore",
    "ExpertTeamRecord",
    "TeamMember",
    "archive_expert",
    "archive_expert_team",
    "get_expert_store",
    "publish_expert",
]
