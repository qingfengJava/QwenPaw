# -*- coding: utf-8 -*-
"""PostgreSQL table model for governance audit events (SQLite retirement).

``audit_events`` replaces the legacy SQLite ``audit.db`` as the durable
store for every ``assert_policy`` + audit call. ``ts`` keeps the legacy
millisecond-since-epoch semantics so the facade's numeric range comparison
and the public query API stay unchanged.

@author qingfeng
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin


class AuditEventRow(TenantMixin, Base):
    """One governance audit record (mirrors the legacy audit.db row)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # Milliseconds since epoch, UTC — same numeric semantics as the
    # SQLite-era column so range filters compare identically.
    ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    workspace_dir: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    # allow | deny | ask | sandbox_fallback
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    extra: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    actor_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )

    __table_args__ = (
        Index("ix_audit_events_ts", "tenant_id", "ts"),
        Index("ix_audit_events_workspace", "tenant_id", "workspace_dir"),
        Index("ix_audit_events_agent", "tenant_id", "agent_id"),
        Index("ix_audit_events_tool", "tenant_id", "tool_name"),
    )
