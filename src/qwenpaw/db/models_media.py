# -*- coding: utf-8 -*-
"""PostgreSQL table model for console chat media uploads.

``media_files`` persists the raw bytes of every file uploaded through
``POST /api/console/upload`` so that chat image recall (frontend preview,
history replay) survives local ``media_dir`` cleanup and works across
multi-host deployments. The local file under the workspace ``media/``
directory remains the working copy for agent tooling (``view_image``);
this table is the durable database copy.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin


class MediaFileRow(TenantMixin, TimestampMixin, Base):
    """One uploaded chat media file (bytes persisted in PostgreSQL)."""

    __tablename__ = "media_files"

    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="application/octet-stream",
        server_default="application/octet-stream",
    )
    size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "stored_name", name="pk_media_files"),
    )
