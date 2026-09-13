# -*- coding: utf-8 -*-
"""Cron job authoritative plane (``cron_jobs`` / ``cron_job_history``).

Revision ID: 0027_cron_jobs_pg
Revises: 0026_open_api_governance
Create Date: 2026-09-13

定时任务 PG 权威平面：``cron_jobs`` 承载任务规格的完整序列化载荷
（此前定时任务仅存于 workspace ``jobs.json`` 单文件，换设备/重装
即全丢）；``cron_job_history`` 承载执行历史（per-job 单调 ``seq``，
新→旧读取与超限修剪都按它）。``QWENPAW_STORAGE_BACKEND`` 为
``json``（默认）时不参与任何读写路径，``dual``/``pg`` 时由
``app/crons/repo/pg_repo.py`` 以本平面为唯一权威，jobs.json 降级为
投影缓存（首次启用从 jobs.json 一次性 backfill 导入）。
（psql twin: changelog 20260913/01，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0027_cron_jobs_pg"
down_revision = "0026_open_api_governance"
branch_labels = None
depends_on = None

_CREATE_CRON_JOBS = """
CREATE TABLE IF NOT EXISTS cron_jobs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    job_id VARCHAR(128) NOT NULL,
    spec JSONB NOT NULL,
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cron_jobs_job UNIQUE (tenant_id, agent_id, job_id)
)
"""

_CREATE_CRON_JOB_HISTORY = """
CREATE TABLE IF NOT EXISTS cron_job_history (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    agent_id VARCHAR(64) NOT NULL,
    job_id VARCHAR(128) NOT NULL,
    seq BIGINT NOT NULL,
    run_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(16) NOT NULL,
    error TEXT,
    trigger VARCHAR(16) NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cron_job_history_seq
        UNIQUE (tenant_id, agent_id, job_id, seq)
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_cron_jobs_agent "
    "ON cron_jobs (tenant_id, agent_id)",
    "CREATE INDEX IF NOT EXISTS ix_cron_job_history_job "
    "ON cron_job_history (tenant_id, agent_id, job_id)",
)

_COMMENTS = (
    "COMMENT ON TABLE cron_jobs IS "
    "'数字员工定时任务规格权威表（jobs.json 单文件平面的 PG 权威化，"
    "spec 为 CronJobSpec 完整序列化；json 后端零动作、dual/pg 权威，"
    "文件降级为投影缓存）'",
    "COMMENT ON COLUMN cron_jobs.tenant_id IS "
    "'租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN cron_jobs.agent_id IS "
    "'数字员工 ID（workspace 目录名，与 agent_documents 同约定）'",
    "COMMENT ON COLUMN cron_jobs.job_id IS "
    "'任务 ID（CronJobSpec.id，jobs.json 内唯一）'",
    "COMMENT ON COLUMN cron_jobs.spec IS "
    "'任务规格完整序列化 JSONB（schedule/dispatch/runtime/text 等全量"
    "载荷，权威数据源）'",
    "COMMENT ON COLUMN cron_jobs.content_hash IS "
    "'规格载荷 SHA-256（幂等 upsert 判定，内容不变零写放大）'",
    "COMMENT ON COLUMN cron_jobs.enabled IS "
    "'是否启用（spec.enabled 的冗余可查询投影，便于运维检索停用任务）'",
    "COMMENT ON COLUMN cron_jobs.created_at IS "
    "'创建时间（首次写入时生成）'",
    "COMMENT ON COLUMN cron_jobs.updated_at IS "
    "'更新时间（每次内容变更时刷新）'",
    "COMMENT ON TABLE cron_job_history IS "
    "'定时任务执行历史表（append-only，per-job 单调 seq 排序，"
    "超限惰性修剪）'",
    "COMMENT ON COLUMN cron_job_history.tenant_id IS "
    "'租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN cron_job_history.agent_id IS "
    "'数字员工 ID（workspace 目录名）'",
    "COMMENT ON COLUMN cron_job_history.job_id IS "
    "'任务 ID（CronJobSpec.id）'",
    "COMMENT ON COLUMN cron_job_history.seq IS "
    "'每任务单调递增序号（新→旧读取与保留窗口修剪的排序键）'",
    "COMMENT ON COLUMN cron_job_history.run_at IS "
    "'执行时间（timestamptz，naive 输入按 UTC 归一）'",
    "COMMENT ON COLUMN cron_job_history.status IS "
    "'执行状态: success-成功, error-失败, running-执行中, "
    "skipped-跳过, cancelled-取消'",
    "COMMENT ON COLUMN cron_job_history.error IS "
    "'失败原因（成功/跳过原因为空或跳过说明）'",
    "COMMENT ON COLUMN cron_job_history.trigger IS "
    "'触发方式: scheduled-定时触发, manual-手动触发'",
    "COMMENT ON COLUMN cron_job_history.created_at IS "
    "'入库时间'",
)


def upgrade() -> None:
    # 幂等 DDL（psql changelog 20260913/01 的等价 alembic 路径）
    op.execute(_CREATE_CRON_JOBS)
    op.execute(_CREATE_CRON_JOB_HISTORY)
    for statement in _CREATE_INDEXES:
        op.execute(statement)
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cron_job_history")
    op.execute("DROP TABLE IF EXISTS cron_jobs")
