# -*- coding: utf-8 -*-
"""Pydantic models for the expert / expert-team domain."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

EXPERT_STATUS_DRAFT = "draft"
EXPERT_STATUS_PUBLISHED = "published"
EXPERT_STATUS_ARCHIVED = "archived"
EXPERT_STATUSES = (
    EXPERT_STATUS_DRAFT,
    EXPERT_STATUS_PUBLISHED,
    EXPERT_STATUS_ARCHIVED,
)

TEAM_MODE_ROUTER = "router"
TEAM_MODE_PIPELINE = "pipeline"
TEAM_MODES = (TEAM_MODE_ROUTER, TEAM_MODE_PIPELINE)

#: Pipeline chains are capped to keep turn latency bounded.
MAX_PIPELINE_MEMBERS = 3

# ---------------------------------------------------------------------------
# Catalog (market) constants — the expert marketplace plane.
# ---------------------------------------------------------------------------

#: Visibility of a custom expert. ``org`` is visible to every employee
#: (subject to RBAC grants); ``private`` restricts the market listing and
#: the detail view to the owner. ``department`` / ``shared`` are reserved
#: for the future permission rollout (no schema change needed).
EXPERT_VISIBILITY_ORG = "org"
EXPERT_VISIBILITY_PRIVATE = "private"
EXPERT_VISIBILITIES = (EXPERT_VISIBILITY_ORG, EXPERT_VISIBILITY_PRIVATE)

#: Market sort modes surfaced by ``GET /api/xian/experts?sort=``.
EXPERT_SORT_COMPOSITE = "composite"
EXPERT_SORT_HOT = "hot"
EXPERT_SORT_NEW = "new"
EXPERT_SORTS = (EXPERT_SORT_COMPOSITE, EXPERT_SORT_HOT, EXPERT_SORT_NEW)

#: Bound skills per expert are capped to keep the injected frontmatter
#: (≈100-300 tokens each) a bounded share of the context window.
MAX_EXPERT_SKILLS = 8

#: Builtin category dictionary for the market tabs (single source of
#: truth for both the API ``/expert-categories`` endpoint and the builtin
#: seed below). Keys are stored in ``experts.category``.
EXPERT_CATEGORIES: List[Dict[str, str]] = [
    {"key": "general", "label": "通用", "icon": "fa-solid fa-layer-group"},
    {"key": "research", "label": "研究分析", "icon": "fa-solid fa-magnifying-glass-chart"},
    {"key": "writing", "label": "内容创作", "icon": "fa-solid fa-pen-nib"},
    {"key": "dev", "label": "技术工程", "icon": "fa-solid fa-code"},
    {"key": "data", "label": "数据分析", "icon": "fa-solid fa-chart-line"},
    {"key": "business", "label": "商业咨询", "icon": "fa-solid fa-briefcase"},
    {"key": "office", "label": "办公提效", "icon": "fa-solid fa-bolt"},
]

#: Member roles inside an expert team (``lead`` renders the 主理人 badge).
TEAM_MEMBER_ROLE_LEAD = "lead"
TEAM_MEMBER_ROLE_MEMBER = "member"
TEAM_MEMBER_ROLES = (TEAM_MEMBER_ROLE_LEAD, TEAM_MEMBER_ROLE_MEMBER)


def expert_agent_id(expert_id: str) -> str:
    """Runtime agent id for one published expert."""
    return f"expert_{expert_id}"


def expert_team_agent_id(team_id: str) -> str:
    """Runtime agent id for one published expert team supervisor."""
    return f"team_{team_id}"


class ExpertSkillBinding(BaseModel):
    """One skill attached to an expert (the shared registry is authoritative)."""

    expert_id: str = ""
    skill_name: str
    enabled: bool = True
    seq: int = 0


class ExpertRecord(BaseModel):
    """One managed expert (draft or published agent definition)."""

    id: str
    name: str
    icon: str = ""
    description: str = ""
    agent_spec: Dict[str, Any] = Field(default_factory=dict)
    status: str = EXPERT_STATUS_DRAFT
    version: int = 1
    owner_id: Optional[str] = None
    visibility: str = EXPERT_VISIBILITY_ORG
    is_builtin: bool = False
    title: str = ""
    category: str = "general"
    badge: str = ""
    tags: List[str] = Field(default_factory=list)
    system_prompt: str = ""
    usage_count: int = 0
    featured: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    #: Skill bindings (populated by the detail endpoint / publish chain,
    #: not a persisted column on ``experts``).
    skills: List[ExpertSkillBinding] = Field(default_factory=list)


class TeamMember(BaseModel):
    """One expert inside a team (ordered)."""

    expert_id: str
    role_hint: str = ""
    member_role: str = TEAM_MEMBER_ROLE_MEMBER
    seq: int = 0


class ExpertTeamRecord(BaseModel):
    """One expert team (multi-agent orchestration)."""

    id: str
    name: str
    description: str = ""
    mode: str = TEAM_MODE_ROUTER
    router_prompt: str = ""
    status: str = EXPERT_STATUS_DRAFT
    version: int = 1
    owner_id: Optional[str] = None
    category: str = "general"
    tags: List[str] = Field(default_factory=list)
    #: Reserved for the runtime orchestrator (parallel groups / DAG /
    #: per-member task templates). Read by a future RuntimeTeamOrchestrator.
    orchestration: Dict[str, Any] = Field(default_factory=dict)
    members: List[TeamMember] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PublishedSnapshot(BaseModel):
    """One immutable published version of an expert."""

    expert_id: str
    version: int
    spec: Dict[str, Any] = Field(default_factory=dict)
    published_by: str = ""
    published_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class ExpertCreateBody(BaseModel):
    name: str
    icon: str = ""
    description: str = ""
    agent_spec: Dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    category: str = "general"
    badge: str = ""
    tags: List[str] = Field(default_factory=list)
    system_prompt: str = ""
    visibility: str = EXPERT_VISIBILITY_ORG
    skills: List[ExpertSkillBinding] = Field(default_factory=list)


class ExpertUpdateBody(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    agent_spec: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    category: Optional[str] = None
    badge: Optional[str] = None
    tags: Optional[List[str]] = None
    system_prompt: Optional[str] = None
    visibility: Optional[str] = None


class ExpertSkillsBody(BaseModel):
    """Whole-list replacement of one expert's skill bindings."""

    skills: List[ExpertSkillBinding] = Field(default_factory=list)


class TeamMemberBody(BaseModel):
    expert_id: str
    role_hint: str = ""
    member_role: str = TEAM_MEMBER_ROLE_MEMBER
    seq: int = 0


class ExpertTeamCreateBody(BaseModel):
    name: str
    description: str = ""
    mode: str = TEAM_MODE_ROUTER
    router_prompt: str = ""
    category: str = "general"
    tags: List[str] = Field(default_factory=list)
    members: List[TeamMemberBody] = Field(default_factory=list)


class ExpertTeamUpdateBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    router_prompt: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    members: Optional[List[TeamMemberBody]] = None
