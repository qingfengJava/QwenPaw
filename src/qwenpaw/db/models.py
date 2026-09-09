# -*- coding: utf-8 -*-
"""PostgreSQL table models for the M2 storage backend.

Three tables mirror the file-era storage planes one-to-one so the dual-write
migration is a faithful copy, not a remodel:

- ``chats``            ← ``chats.json`` rows (``ChatSpec``)
- ``session_states``   ← per-session ``*.json`` state files
- ``history_entries``  ← scroll ``conversation_history`` (SQLite FTS5 ->
  PostgreSQL ``tsvector``)

All user-data tables are RLS-enabled (see ``rls.py``); the application layer
remains the primary isolation enforcer during the PERMISSIVE rollout.
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

from .base import Base, TenantMixin


class ChatRow(TenantMixin, Base):
    """One chat spec (mirrors ``ChatSpec`` / a row of ``chats.json``).

    ``created_at``/``updated_at`` are application-assigned: a repository
    round-trip must preserve the exact values carried by the ``ChatSpec``
    so JSON and PG backends stay byte-equivalent in behavior.

    ``agent_id`` scopes the row to one digital employee: the JSON backend
    isolated workspaces by file layout, the PG backend needs the column.
    """

    __tablename__ = "chats"

    # 归属智能体：JSON 时代靠 workspace 目录隔离，PG 共表后由该列隔离
    agent_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="default",
        server_default="default",
    )
    id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    channel: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="console",
        server_default="console",
    )
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="New Chat",
        server_default="New Chat",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="idle",
        server_default="idle",
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="chat",
        server_default="chat",
    )
    # XianWork enterprise: project this chat belongs to (nullable — personal
    # chats carry no project). Written by the projects service only.
    project_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_chats"),
        Index("ix_chats_owner", "tenant_id", "owner_id"),
        Index(
            "ix_chats_owner_updated",
            "tenant_id",
            "owner_id",
            "updated_at",
        ),
        Index("ix_chats_project", "tenant_id", "project_id"),
        Index("ix_chats_tenant_agent", "tenant_id", "agent_id"),
        Index(
            "ix_chats_session",
            "tenant_id",
            "session_id",
            "channel",
            "user_id",
        ),
    )


class SessionStateRow(TenantMixin, Base):
    """One session state document (mirrors a ``*.json`` session file).

    The composite primary key is exactly the file-name identity of the JSON
    backend: ``(tenant_id, agent_id, channel, owner_id, session_id)`` —
    ``agent_id`` was added when the PG backend replaced per-workspace
    session directories, so two employees sharing a session id never
    overwrite each other's state.
    """

    __tablename__ = "session_states"

    # 归属智能体：与 chats.agent_id 同语义（会话状态跨员工隔离）
    agent_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="default",
        server_default="default",
    )
    channel: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    owner_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "agent_id",
            "channel",
            "owner_id",
            "session_id",
            name="pk_session_states",
        ),
    )


class HistoryRow(TenantMixin, Base):
    """One durable history event (mirrors scroll ``conversation_history``).

    ``seq`` keeps the global-watermark semantics of the SQLite AUTOINCREMENT
    primary key. ``created_at`` mirrors the entry payload (ISO text in the
    file era) and is stored as a real timestamp for range purges. The
    full-text index is a generated ``tsvector`` column over ``content``
    created by the initial Alembic migration (plain DDL, not reflected
    here).
    """

    __tablename__ = "history_entries"

    seq: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_input: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    tool_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    headline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocks: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    # ``metadata`` is reserved by the Declarative API; keep the column name
    # stable while exposing a non-colliding attribute.
    metadata_: Mapped[Optional[Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    dedup_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_history_session", "tenant_id", "session_id"),
        Index("ix_history_agent", "tenant_id", "agent_id"),
        Index("ix_history_owner", "tenant_id", "owner_id"),
        Index("ix_history_kind", "tenant_id", "kind"),
        Index("ix_history_created_at", "tenant_id", "created_at"),
        # NULL dedup keys never conflict — a partial unique index matches
        # the SQLite ``ux_dedup`` behavior exactly.
        Index(
            "ux_history_dedup",
            "tenant_id",
            "session_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("dedup_key IS NOT NULL"),
        ),
    )


class AgentRunRow(TenantMixin, Base):
    """One agent run (chat/cron execution) — the run-log list row.

    Replaces the file-era ``run_logs/index-YYYYMMDD.jsonl`` shard: the
    same fields power the list API but with SQL filtering/pagination.
    Detail spans live in :class:`AgentRunSpanRow`.
    """

    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Human-readable agent name (AgentProfileConfig.name) for display;
    # falls back to agent_id in the UI when NULL.
    display_name: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    session_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    root_session_id: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )
    chat_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    environment: Mapped[Optional[str]] = mapped_column(
        String(16),
        nullable=True,
    )
    query_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    app_version: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_agent_runs_agent_started",
            "tenant_id",
            "agent_id",
            "started_at",
        ),
    )


class AgentRunSpanRow(Base):
    """One execution span inside a run (system/llm/tool/reply).

    Captured by ``SpanRecorderMiddleware`` at AgentScope middleware
    boundaries; the span tree is rebuilt by ``parent_span_id``.
    """

    __tablename__ = "agent_run_spans"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    span_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_span_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    input: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    output: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_agent_run_spans_run", "run_id"),
    )
