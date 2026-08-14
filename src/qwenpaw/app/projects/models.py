# -*- coding: utf-8 -*-
"""Pydantic models for the project/task/feed domain."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Project member roles (three-tier data permission inside one project).
PROJECT_OWNER = "owner"
PROJECT_EDITOR = "editor"
PROJECT_VIEWER = "viewer"
MEMBER_ROLES = (PROJECT_OWNER, PROJECT_EDITOR, PROJECT_VIEWER)

#: Role ranking for "at least" checks (viewer < editor < owner).
_ROLE_RANK = {PROJECT_VIEWER: 0, PROJECT_EDITOR: 1, PROJECT_OWNER: 2}

# Kanban board columns (four-column board, WorkBuddy style).
TASK_STATUSES = ("todo", "doing", "paused", "done")


def role_at_least(role: str, minimum: str) -> bool:
    """True when *role* satisfies the *minimum* tier."""
    return _ROLE_RANK.get(role, -1) >= _ROLE_RANK.get(minimum, 99)


class AIBinding(BaseModel):
    """Which published expert powers a project's shared AI."""

    kind: str = "expert"  # expert | expert_team
    ref_id: str = ""


class ProjectRecord(BaseModel):
    """One project (org-scoped collaboration container)."""

    id: str
    department_id: Optional[str] = None
    name: str
    description: str = ""
    status: str = "active"
    ai_binding: AIBinding = Field(default_factory=AIBinding)
    template_tag: str = ""
    created_by: str = ""
    member_role: str = ""  # requesting user's role ("" = not a member)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectMemberView(BaseModel):
    """One project membership row."""

    project_id: str
    username: str
    role: str


class TaskRecord(BaseModel):
    """One kanban task."""

    id: str
    project_id: str
    title: str
    description: str = ""
    status: str = "todo"
    assignee: Optional[str] = None
    creator: str = ""
    chat_id: Optional[str] = None
    sort_order: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FeedEventView(BaseModel):
    """One project feed event."""

    id: int
    project_id: str
    actor: str
    kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class ProjectCreateBody(BaseModel):
    name: str
    description: str = ""
    department_id: Optional[str] = None
    template_tag: str = ""
    ai_binding: Optional[AIBinding] = None


class ProjectUpdateBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    department_id: Optional[str] = None
    ai_binding: Optional[AIBinding] = None


class MemberBody(BaseModel):
    username: str
    role: str = PROJECT_VIEWER


class MemberRoleBody(BaseModel):
    role: str


class TaskCreateBody(BaseModel):
    title: str
    description: str = ""
    status: str = "todo"
    assignee: Optional[str] = None
    chat_id: Optional[str] = None


class TaskUpdateBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    sort_order: Optional[int] = None


class CommentBody(BaseModel):
    text: str
