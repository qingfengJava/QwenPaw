# -*- coding: utf-8 -*-
"""PostgreSQL table model for XianWork share links.

``xian_shares`` persists one capability-token share per chat: creating a
share mints a URL-safe token, and the public view endpoint grants read
access to that chat's transcript + registered files purely by holding the
token (no login required). The row is keyed by ``chat_id`` (unique per
tenant) so re-sharing a chat returns the same link instead of forking
tokens; deleting the chat invalidates the share naturally (view 404s).
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Index,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin


class XianShareRow(TenantMixin, TimestampMixin, Base):
    """One share link: token → chat (capability URL, owner-minted)."""

    __tablename__ = "xian_shares"

    token: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "token", name="pk_xian_shares"),
        # Partial unique: one ACTIVE share per chat — a revoked row must
        # not block re-sharing (mirrors the SQL changelog definition).
        Index(
            "ux_xian_shares_chat",
            "tenant_id",
            "chat_id",
            unique=True,
            postgresql_where=text("revoked = false"),
        ),
        Index("ix_xian_shares_owner", "tenant_id", "owner_id"),
    )
