# -*- coding: utf-8 -*-
"""Declarative base and shared column mixins for PostgreSQL storage.

Every business table carries:

- ``tenant_id``: reserved for a future multi-tenant upgrade. The current
  single-enterprise deployment always writes ``"default"`` so no second
  ALTER is ever needed.
- ``created_at`` / ``updated_at``: UTC timestamps maintained by the
  database so row churn is auditable without application cooperation.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_TENANT_ID = "default"


class Base(DeclarativeBase):
    """Project-wide declarative base (naming convention kept default)."""


class TenantMixin:
    """Reserved tenant column; constant ``"default"`` in this topology."""

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=DEFAULT_TENANT_ID,
        server_default=DEFAULT_TENANT_ID,
    )


class TimestampMixin:
    """DB-maintained UTC creation/update timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
