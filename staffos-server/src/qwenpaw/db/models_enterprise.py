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


class EmployeeGovernanceRow(TenantMixin, TimestampMixin, Base):
    """Governance row of one digital employee (org plane).

    The single authority for *department ownership* and *visibility*
    across every employee shape (plain agent / expert / expert team /
    future workflow), keyed by the runtime ``agent_id``. Runtime access
    control is untouched: the governance service projects each write
    onto the RBAC ``agent_grants`` plane (departments already mirror as
    ``dept:{path}`` teams), so this table only backs the editing and
    listing surface. A missing row means "unassigned + org-wide".
    """

    __tablename__ = "employee_governance"

    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="agent",
        server_default="agent",
    )
    entity_id: Mapped[str] = mapped_column(
        # 与 alembic 0031 / db/feature SQL 对齐（VARCHAR(64)），
        # 避免 create_all 引导出的结构与迁移产物漂移
        String(64),
        nullable=False,
        default="",
        server_default="",
    )
    department_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    visibility: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="org",
        server_default="org",
    )
    granted_departments: Mapped[list[Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    owner_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "agent_id",
            name="pk_employee_governance",
        ),
        Index(
            "ix_employee_governance_department",
            "tenant_id",
            "department_id",
        ),
        Index(
            "ix_employee_governance_visibility",
            "tenant_id",
            "visibility",
        ),
        Index("ix_employee_governance_kind", "tenant_id", "entity_kind"),
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


class FeedEventRow(TenantMixin, TimestampMixin, Base):
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

    Catalog columns (marketplace plane): ``owner_id`` anchors custom
    experts to their creator (NULL = admin/builtin) for the future
    permission rollout; ``visibility`` is ``org`` / ``private``;
    ``category`` / ``title`` / ``badge`` / ``tags`` drive the market
    cards; ``system_prompt`` is materialized into the workspace
    ``PROFILE.md`` at publish time; ``usage_count`` feeds the "hot"
    sort. Skill bindings live in ``expert_skills`` (never inside
    ``agent_spec`` — ``AgentProfileConfig`` has no skills field and
    silently drops unknown keys).
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
    owner_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="org",
        server_default="org",
    )
    is_builtin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    category: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="general",
        server_default="general",
    )
    badge: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    system_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    usage_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    featured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    #: "专家帮你做"任务模板 [{title, prompt}]（详情页点击即以 prompt
    #: 为 kickoff 召唤；管理端可编辑的运营位）
    sample_tasks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    #: 使用案例 [{title, desc, tags}]（静态运营位，与聊天直答无 run 依赖）
    showcase: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    #: 使用范围（P2 两级发布）：team_only=团队专属、shared=可独立授权使用。
    #: 存量员工迁移为 shared；团队内新建默认 team_only。
    usage_mode: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="shared",
        server_default="shared",
    )
    #: 员工最新已发布版本指针（P2）：指向 published_experts.version。
    #: None/0 表示从未发布；发布链成功后更新。
    published_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_experts"),
        Index("ix_experts_status", "tenant_id", "status"),
        Index(
            "ix_experts_market",
            "tenant_id",
            "status",
            "category",
            text("updated_at DESC"),
        ),
        Index("ix_experts_owner", "tenant_id", "owner_id"),
    )


class ExpertTeamRow(TenantMixin, TimestampMixin, Base):
    """One expert team (a lightweight multi-agent orchestration).

    ``mode`` is ``router`` (an LLM picks one member per turn) or
    ``pipeline`` (members execute in sequence, outputs chained).
    ``orchestration`` is a reserved JSONB for the future runtime
    orchestrator (parallel groups / DAG / per-member task templates).
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
    owner_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="general",
        server_default="general",
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    orchestration: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    #: "任务示例"模板 [{title, prompt}]（详情页点击即以 prompt 为 goal
    #: 创建专家团 run；管理端可编辑的运营位）
    sample_tasks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    #: 使用案例 [{title, desc, tags}]（静态运营位；与 team_runs 真实
    #: 交付投影"最近交付"分区并存）
    showcase: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    #: 草稿修订号（CAS 乐观锁）：每次 PATCH 成功递增；发布不重置。
    #: 客户端携带 expected_revision 提交 PATCH，服务端校验一致才写入，
    #: 冲突返回 409。与 version（发布版本号）独立。
    draft_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    #: 当前已发布团队版本指针（P2）：指向 expert_team_versions.version。
    #: 0 表示从未发布；原子发布激活时更新。
    published_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_expert_teams"),
        Index("ix_expert_teams_status", "tenant_id", "status"),
    )


class ExpertTeamMemberRow(TenantMixin, TimestampMixin, Base):
    """Ordered membership of one expert inside one expert team.

    ``member_role`` is ``lead`` (主理人， rendered with a badge) or
    ``member``.
    """

    __tablename__ = "expert_team_members"

    team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expert_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role_hint: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    member_role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="member",
        server_default="member",
    )
    seq: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    #: 草稿显式选定的成员发布版本（P2）：发布时禁止为空，
    #: 未发布草稿成员可为空。发布链据此固定成员版本组合。
    expert_version: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
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


class ExpertTeamVersionRow(TenantMixin, TimestampMixin, Base):
    """不可变团队发布配置快照（T1：expert_team_versions）。

    每次团队发布写入一行（version=发布时的团队版本号，team 内唯一），
    ``spec`` 保存成员职责与 orchestration 完整快照供审计与运行核对；
    行不可更新（重发布=新行）。快照只用于审计比对，执行时仍检查
    即时撤权——不成为新授权来源（计划 §8.1）。
    """

    __tablename__ = "expert_team_versions"

    team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 发布时的团队版本号（expert_teams.version 快照；team 内唯一）
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    spec: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    published_by: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: 来源草稿修订号（P2）：记录发布时基于哪个 draft_revision，
    #: 用于冲突检测和审计追溯。
    source_draft_revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    #: 发布包内容哈希（P2）：spec 的结构化摘要 hash，用于幂等发布
    # （同 hash 不重复发布）和完整性校验。
    spec_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
    )
    #: 发布请求幂等键（P2）：绑定确认请求 ID，重复请求返回原结果。
    publish_request_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="",
        server_default="",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "team_id",
            "version",
            name="pk_expert_team_versions",
        ),
        Index("ix_expert_team_versions_team", "tenant_id", "team_id"),
    )


class ExpertSkillRow(TenantMixin, TimestampMixin, Base):
    """Binding of one shared-registry skill to one expert.

    ``skill_name`` references the console-plane skill registry (the
    registry stays authoritative); publishing materializes the enabled
    set into the expert workspace's ``skills/`` directory. ``seq`` keeps
    a stable display/injection order and ``enabled`` supports toggling
    a skill off without losing the binding.
    """

    __tablename__ = "expert_skills"

    expert_id: Mapped[str] = mapped_column(String(64), nullable=False)
    skill_name: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
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
            "expert_id",
            "skill_name",
            name="pk_expert_skills",
        ),
        Index("ix_expert_skills_expert", "tenant_id", "expert_id"),
    )


class PublishedExpertRow(TenantMixin, TimestampMixin, Base):
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
    #: 发布包内容哈希（P2）：spec 摘要的 SHA-256，用于幂等发布和
    #: 完整性校验（发布记录与激活指针保持一致）。
    spec_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
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


class TokenUsageEventRow(TenantMixin, TimestampMixin, Base):
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


class TeamRunRow(TenantMixin, TimestampMixin, Base):
    """One workforce team-task execution (the L1 orchestration instance).

    The workforce engine (``app/workforce``) drives this state machine:
    planning → (awaiting_confirm) → running → verifying / repairing →
    aggregating → done | failed | escalated | canceled | interrupted.
    ``plan`` / ``policy`` / ``context_bundle`` are JSONB snapshots of the
    corresponding pydantic contracts — low-churn, migration-free evolution
    (same philosophy as ``agent_spec``).
    """

    __tablename__ = "team_runs"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    source_chat_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    initiator_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="planning",
        server_default="planning",
    )
    goal: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    plan: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    context_bundle: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    context_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    summary: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    clarification: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    repair_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    replan_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    #: 累计活跃执行时间（秒；T5）：各执行段累加，恢复/续跑不清零，
    #: 时间熔断按"累计 + 本段耗时"判定（人工等待不计时）
    active_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    error: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    escalation_reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_team_runs"),
        Index("ix_team_runs_team", "tenant_id", "team_id"),
        Index("ix_team_runs_status", "tenant_id", "status"),
        Index("ix_team_runs_project", "tenant_id", "project_id"),
    )


class TeamRunNodeRow(TenantMixin, TimestampMixin, Base):
    """Per-DAG-node execution ledger inside one team run.

    Each row carries the full contract lifecycle: ``contract`` (what the
    central brain delegated), ``result`` (what the member expert returned),
    ``repair`` (the latest RepairContract) and ``verdict`` (PASS / FAIL /
    ESCALATE). ``attempt`` increments on every delegation (rework rounds
    included) and doubles as the crash-resume cursor.
    """

    __tablename__ = "team_run_nodes"

    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    assignee_expert_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
    )
    assignee_user_id: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    node_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="task",
        server_default="task",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pending",
        server_default="pending",
    )
    contract: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    repair: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    verdict: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    repair_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    session_id: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    token_cost: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "run_id",
            "node_key",
            name="pk_team_run_nodes",
        ),
        Index("ix_team_run_nodes_run", "tenant_id", "run_id"),
    )


class TeamRunRevisionRow(TenantMixin, TimestampMixin, Base):
    """运行修订记录（T2：team_run_revisions，计划 §8.2）。

    requirement/plan/context 三类修订各自递增 revision；payload 保存
    完整契约或被取代的旧图（重规划不删除历史——旧图进入修订行，
    node 行层面的清理只服务于调度，不再销毁证据）。
    """

    __tablename__ = "team_run_revisions"

    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 修订对象类型: requirement | plan | context
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "run_id",
            "kind",
            "revision",
            name="pk_team_run_revisions",
        ),
        Index("ix_team_run_revisions_run", "tenant_id", "run_id"),
    )


class TeamRunAttemptRow(TenantMixin, TimestampMixin, Base):
    """实际执行尝试记录（T2：team_run_attempts，计划 §8.2）。

    规划、节点委派、汇总的每次真实执行一行：先落库（started）再启动
    成员；结束回写 completed/failed 与 usage（usage_reported=False 表
    示消耗未知，预算账本不得按零结算）。
    """

    __tablename__ = "team_run_attempts"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: 实际执行的员工专家（final/brain 自执行为空串）
    expert_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: started | completed | failed
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="started",
        server_default="started",
    )
    usage_reported: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    token_cost: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_team_run_attempts"),
        Index(
            "ix_team_run_attempts_node",
            "tenant_id",
            "run_id",
            "node_key",
        ),
    )


class TeamRunEventRow(TenantMixin, TimestampMixin, Base):
    """持久运行事件（T2：team_run_events，计划 §8.2/§8.6）。

    全部 run（含未挂项目）的有序留痕：run 内 seq 单调递增（与提交
    顺序一致），SSE 只是传输通道；回放/审计以本表为权威。
    """

    __tablename__ = "team_run_events"

    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "run_id",
            "seq",
            name="pk_team_run_events",
        ),
        Index("ix_team_run_events_seq", "tenant_id", "run_id", "seq"),
    )


class TeamRunBudgetReservationRow(TenantMixin, TimestampMixin, Base):
    """预算预留/结算记录（T2：team_run_budget_reservations，计划 §8.5）。

    调用前原子预留（pending），结算后按实际用量落 settled；并发请求
    通过 pending 预留之和参与预算判断，防止"各自看余额"超售。
    """

    __tablename__ = "team_run_budget_reservations"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    #: pending | settled | released
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    reserved_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    used_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_team_run_budget_resv"),
        Index(
            "ix_team_run_budget_resv_run",
            "tenant_id",
            "run_id",
            "status",
        ),
    )
