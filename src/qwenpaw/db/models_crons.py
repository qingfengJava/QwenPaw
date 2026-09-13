# -*- coding: utf-8 -*-
"""PostgreSQL table models for the cron job plane.

``cron_jobs`` is the authoritative PG store of digital-employee cron
job specs (the ``jobs.json`` single-file plane demoted to a projection
cache); ``cron_job_history`` keeps the per-job execution records with a
monotonic ``seq`` so the "newest N" window survives trimming.

``QWENPAW_STORAGE_BACKEND`` 为 ``json``（默认）时不参与任何读写路径，
``dual``/``pg`` 时由 ``app/crons/repo/pg_repo.py`` 以本平面为唯一
权威（换设备/重装不丢；首次启用从 jobs.json 一次性 backfill）。

@author qingfeng
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin


class CronJobRow(TenantMixin, Base):
    """One cron job spec of one agent (mirror of a jobs.json entry)."""

    __tablename__ = "cron_jobs"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    # workspace 目录名（与 agent_documents.agent_id 同一约定）
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # CronJobSpec.id（jobs.json 内唯一）
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # CronJobSpec 完整序列化（权威载荷，含 schedule/dispatch/runtime）
    spec: Mapped[Any] = mapped_column(JSONB, nullable=False)
    # 序列化载荷的 SHA-256（幂等 upsert 判定，内容不变零写放大）
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
    )
    # jobs.json 里 disabled 状态的冗余可查询投影（spec.enabled 同源）
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_id",
            "job_id",
            name="uq_cron_jobs_job",
        ),
        Index("ix_cron_jobs_agent", "tenant_id", "agent_id"),
    )


class CronJobHistoryRow(TenantMixin, Base):
    """One execution record of one cron job (append-only, seq ordered)."""

    __tablename__ = "cron_job_history"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # 每 (tenant, agent, job) 单调递增；新→旧读取与超限修剪都按它
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    # success | error | running | skipped | cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # scheduled | manual
    trigger: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="scheduled",
        server_default="scheduled",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_id",
            "job_id",
            "seq",
            name="uq_cron_job_history_seq",
        ),
        Index(
            "ix_cron_job_history_job",
            "tenant_id",
            "agent_id",
            "job_id",
        ),
    )
