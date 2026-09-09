# -*- coding: utf-8 -*-
"""PostgreSQL table model for agent identity documents (Phase A).

``agent_documents`` is the authoritative PostgreSQL store for the identity
files of every digital employee (``PROFILE.md`` / ``AGENTS.md`` /
``SOUL.md`` / ``agent.json``).

Phase A (dual-write shadow): the workspace file stays the primary read/write
surface — the system-prompt contributors read it synchronously on the hot
path — and every successful file write mirrors a fire-and-forget shadow row
here (see ``app/agent_docs/store.py``). Phase B will flip the read path to
this table with an in-process cache, demoting the file to a materialized
projection.

``environment`` reuses the expert draft/publish semantics: draft rows track
the debug preview instance (``expert_{id}__draft`` workspaces) while
production rows track the published line, so preview vs production isolation
is carried by the table itself.

@author qingfeng
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    BigInteger,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin


class AgentDocumentRow(TenantMixin, TimestampMixin, Base):
    """One identity document of one agent (mirrors a workspace file).

    The natural key is ``(tenant_id, agent_id, doc_type, environment)``;
    ``agent_id`` is the workspace directory name (same convention as
    ``AgentProfileRef.id``), not a UUID foreign key.
    """

    __tablename__ = "agent_documents"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # profile | agents | soul | agent_json
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # draft | production
    environment: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="production",
        server_default="production",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    # SHA-256 hex of content; drives idempotent upserts (no version churn
    # when a shadow write re-persists identical content).
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
    )
    # Monotonic per-document revision, bumped on every content change.
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    updated_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_id",
            "doc_type",
            "environment",
            name="uq_agent_documents_doc",
        ),
        Index("ix_agent_documents_agent", "tenant_id", "agent_id"),
    )
