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
    """

    __tablename__ = "chats"

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
    backend: ``(tenant_id, channel, owner_id, session_id)``.
    """

    __tablename__ = "session_states"

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
