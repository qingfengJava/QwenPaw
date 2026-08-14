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


def expert_agent_id(expert_id: str) -> str:
    """Runtime agent id for one published expert."""
    return f"expert_{expert_id}"


def expert_team_agent_id(team_id: str) -> str:
    """Runtime agent id for one published expert team supervisor."""
    return f"team_{team_id}"


class ExpertRecord(BaseModel):
    """One managed expert (draft or published agent definition)."""

    id: str
    name: str
    icon: str = ""
    description: str = ""
    agent_spec: Dict[str, Any] = Field(default_factory=dict)
    status: str = EXPERT_STATUS_DRAFT
    version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TeamMember(BaseModel):
    """One expert inside a team (ordered)."""

    expert_id: str
    role_hint: str = ""
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


class ExpertUpdateBody(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    agent_spec: Optional[Dict[str, Any]] = None


class TeamMemberBody(BaseModel):
    expert_id: str
    role_hint: str = ""
    seq: int = 0


class ExpertTeamCreateBody(BaseModel):
    name: str
    description: str = ""
    mode: str = TEAM_MODE_ROUTER
    router_prompt: str = ""
    members: List[TeamMemberBody] = Field(default_factory=list)


class ExpertTeamUpdateBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    router_prompt: Optional[str] = None
    members: Optional[List[TeamMemberBody]] = None
