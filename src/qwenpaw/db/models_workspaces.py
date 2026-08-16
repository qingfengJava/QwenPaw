# -*- coding: utf-8 -*-
"""PostgreSQL table model for XianWork user workspaces.

``xian_workspaces`` registers the disk directories a user has claimed as
workspaces. A workspace is purely a directory-to-name mapping: chat
binding reuses the existing ``chats.meta.runtime_context.project_dir``
mechanism (``ChatManager.set_project_dir``), so this table never stores
chat foreign keys and the ``chats`` schema stays untouched. Sidebar
task/workspace grouping matches ``dir_path`` against each chat's
``project_dir`` server-side after ``normalize_project_dir``.
"""
from __future__ import annotations

from sqlalchemy import (
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin


class XianWorkspaceRow(TenantMixin, TimestampMixin, Base):
    """One registered user workspace (a named disk directory)."""

    __tablename__ = "xian_workspaces"

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    dir_path: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "id", name="pk_xian_workspaces"),
        Index(
            "ux_xian_workspaces_owner_dir",
            "tenant_id",
            "owner_id",
            "dir_path",
            unique=True,
        ),
        Index("ix_xian_workspaces_owner", "tenant_id", "owner_id"),
    )
