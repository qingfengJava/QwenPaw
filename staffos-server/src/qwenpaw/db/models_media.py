# -*- coding: utf-8 -*-
"""PostgreSQL table model for console chat media uploads.

``media_files`` persists the raw bytes of every file uploaded through
``POST /api/console/upload`` so that chat image recall (frontend preview,
history replay) survives local ``media_dir`` cleanup and works across
multi-host deployments. The local file under the workspace ``media/``
directory remains the working copy for agent tooling (``view_image``);
this table is the durable database copy.

0007_media_registry upgraded the table into a session file registry:
``chat_id``/``session_id`` associate each file with its conversation,
``source`` separates user uploads from agent-generated outputs, and
``storage_type``/``storage_uri`` record where the bytes live (local path,
database copy, or a future object store) so files can be listed and
restored per chat.
"""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin


class MediaFileRow(TenantMixin, TimestampMixin, Base):
    """One chat media file (bytes persisted in PostgreSQL)."""

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

    # ---- session file registry columns (0007_media_registry) ----

    # 关联会话 ID（console 面 chat_id；用户上传必填，Agent 产出可空）
    chat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 会话的 agent 侧 session_id（两条写入链路都能取到的可靠关联键）
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 归属账号（上传链路取登录用户；Agent 产出可空，读取时二次校验）
    owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 文件来源：upload=用户聊天上传；agent_output=Agent 任务产出
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="upload",
        server_default="upload",
    )
    # 存储方式：db=本地+PG 双写可恢复；local=仅本地；minio/oss=对象存储预留
    storage_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="db",
        server_default="db",
    )
    # 存储定位：本地为绝对路径；对象存储为 minio://bucket/key 等 URI
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 内容 SHA-256 指纹（Agent 产出以哈希前 16 位参与 stored_name 内容寻址）
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "stored_name", name="pk_media_files"),
        Index("ix_media_files_chat", "tenant_id", "chat_id"),
        Index("ix_media_files_session", "tenant_id", "session_id"),
    )
