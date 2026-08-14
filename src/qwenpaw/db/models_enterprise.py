# -*- coding: utf-8 -*-
"""PostgreSQL table models for the XianWork enterprise domains.

Eleven tables covering the enterprise collaboration plane (orgs /
departments / projects / tasks / feed) and the expert publishing plane
(experts / expert teams / published snapshots / token metering).

Design notes:

- Every table inherits :class:`~qwenpaw.db.base.TenantMixin`; ``tenant_id``
  carries the organization id (the deployment remains single-tenant until
  an org record says otherwise, in which case ``tenant_id == org.id``).
- Application-layer filtering on ``tenant_id`` is the primary isolation
  enforcer (same PERMISSIVE philosophy as the M2 RLS rollout).
- ``feed_events`` / ``token_usage_events`` are append-only with bigint
  identity primary keys — natural partition candidates once volume grows
  (deliberately not partitioned yet).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin


class OrgRow(TenantMixin, TimestampMixin, Base):
    """One enterprise organization (the tenant boundary).

    ``tenant_id`` equals ``id``: the org row is the root of its own
    tenant namespace.
    """

    __tablename__ = "orgs"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="standard",
        server_default="standard",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="active",
        server_default="active",
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_orgs"),
        Index("ux_orgs_slug", "tenant_id", "slug", unique=True),
    )


class DepartmentRow(TenantMixin, TimestampMixin, Base):
    """One department inside an org (tree via ``parent_id``).

    ``path`` is the materialized path of department ids (``a/b/c``) so
    subtree membership checks are a single prefix match.
    """

    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_departments"),
        Index("ix_departments_parent", "tenant_id", "parent_id"),
        Index("ix_departments_path", "tenant_id", "path"),
    )


class DepartmentMemberRow(TenantMixin, TimestampMixin, Base):
    """Membership of one user inside one department.

    The authoritative department relation lives here (PG), not on
    ``UserRecord`` — users.json stays a flat account store while the
    enterprise org chart is relational and joinable.
    """

    __tablename__ = "department_members"

    department_id: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "department_id",
            "username",
            name="pk_department_members",
        ),
        Index("ix_department_members_user", "tenant_id", "username"),
    )


class ProjectRow(TenantMixin, TimestampMixin, Base):
    """One collaboration project shared by org members.

    ``ai_binding`` holds ``{"kind": "expert"|"expert_team", "ref_id": ...}``
    describing which published expert powers the project-level AI.
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="active",
        server_default="active",
    )
    ai_binding: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    template_tag: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_projects"),
        Index("ix_projects_department", "tenant_id", "department_id"),
        Index("ix_projects_status", "tenant_id", "status"),
    )


class ProjectMemberRow(TenantMixin, TimestampMixin, Base):
    """Membership + role of one user inside one project.

    ``role`` is one of ``owner`` / ``editor`` / ``viewer``.
    """

    __tablename__ = "project_members"

    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="viewer",
        server_default="viewer",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "project_id",
            "username",
            name="pk_project_members",
        ),
        Index("ix_project_members_user", "tenant_id", "username"),
    )


class TaskRow(TenantMixin, TimestampMixin, Base):
    """One kanban task inside a project.

    ``status`` aligns with the four board columns: ``todo`` / ``doing`` /
    ``paused`` / ``done``. ``chat_id`` weakly references a ChatSpec id
    when the task was created from (or executed by) an AI conversation.
    """

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="todo",
        server_default="todo",
    )
    assignee: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creator: Mapped[str] = mapped_column(Text, nullable=False)
    chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_tasks"),
        Index(
            "ix_tasks_board",
            "tenant_id",
            "project_id",
            "status",
            "updated_at",
        ),
        Index("ix_tasks_assignee", "tenant_id", "assignee", "status"),
    )


class FeedEventRow(TenantMixin, Base):
    """One append-only activity event in a project feed.

    ``kind`` is one of ``task_created`` / ``task_status`` / ``comment`` /
    ``ai_reply`` / ``member_joined`` / ``member_left`` / ``project_updated``.
    """

    __tablename__ = "feed_events"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index(
            "ix_feed_project",
            "tenant_id",
            "project_id",
            text("id DESC"),
        ),
    )


class ExpertRow(TenantMixin, TimestampMixin, Base):
    """One managed expert (a publishable agent definition).

    ``agent_spec`` is structurally identical to a workspace ``agent.json``
    (an ``AgentProfileConfig`` dump). ``status`` is one of ``draft`` /
    ``published`` / ``archived``; publishing bumps ``version`` and stores
    an immutable snapshot in ``published_experts``.
    """

    __tablename__ = "experts"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    agent_spec: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="draft",
        server_default="draft",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_experts"),
        Index("ix_experts_status", "tenant_id", "status"),
    )


class ExpertTeamRow(TenantMixin, TimestampMixin, Base):
    """One expert team (a lightweight multi-agent orchestration).

    ``mode`` is ``router`` (an LLM picks one member per turn) or
    ``pipeline`` (members execute in sequence, outputs chained).
    """

    __tablename__ = "expert_teams"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    mode: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="router",
        server_default="router",
    )
    router_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="draft",
        server_default="draft",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_expert_teams"),
        Index("ix_expert_teams_status", "tenant_id", "status"),
    )


class ExpertTeamMemberRow(TenantMixin, Base):
    """Ordered membership of one expert inside one expert team."""

    __tablename__ = "expert_team_members"

    team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expert_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role_hint: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "team_id",
            "expert_id",
            name="pk_expert_team_members",
        ),
        Index("ix_expert_team_members_expert", "tenant_id", "expert_id"),
    )


class PublishedExpertRow(TenantMixin, Base):
    """Immutable published snapshot of one expert version.

    The user-facing API always reads the newest snapshot for an expert;
    publishing a new version invalidates nothing (snapshots are additive).
    """

    __tablename__ = "published_experts"

    expert_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_by: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "expert_id",
            "version",
            name="pk_published_experts",
        ),
    )


class ProjectBindingRow(TenantMixin, TimestampMixin, Base):
    """Binding of one external resource (connector / skill) to a project.

    ``kind`` is one of ``connector`` / ``skill``; ``ref_id`` names the
    resource inside its console-plane registry (MCP client key / skill
    name). The registry stays authoritative — this table only records
    which resources the project's AI may use.
    """

    __tablename__ = "project_bindings"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    ref_id: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_project_bindings"),
        Index(
            "ux_project_bindings",
            "tenant_id",
            "project_id",
            "kind",
            "ref_id",
            unique=True,
        ),
    )


class ProjectAutomationRow(TenantMixin, TimestampMixin, Base):
    """One scheduled automation inside a project.

    The authoritative schedule lives in the project agent's cron manager
    (``cron_job_id``); this row projects it onto the project plane and
    records the human-facing name/prompt for the right config panel.
    """

    __tablename__ = "project_automations"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    schedule: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    cron_job_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_project_automations"),
        Index(
            "ix_project_automations_project",
            "tenant_id",
            "project_id",
        ),
    )


class TokenUsageEventRow(TenantMixin, Base):
    """One metered LLM token usage event (enterprise dimensions).

    Append-only; aggregates replace the file-era single-file usage log for
    multi-tenant deployments. Partitioning by month is a documented future
    step (volume does not justify it yet).
    """

    __tablename__ = "token_usage_events"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    org_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    agent_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_usage_user", "tenant_id", "user_id", "created_at"),
        Index("ix_usage_day_model", "tenant_id", "created_at", "model"),
    )
