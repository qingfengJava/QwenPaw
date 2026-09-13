# -*- coding: utf-8 -*-
"""PostgreSQL-backed cron job repository (``cron_jobs`` plane).

全局数据架构（PG 唯一权威 + 本地物化缓存）在定时任务域的落地：
``QWENPAW_STORAGE_BACKEND`` 为 ``dual``/``pg`` 时由
``build_job_repository`` 选用本仓库 —— PG 是任务规格与执行历史的
唯一权威（换设备/重装不丢，B 机器登录可重建），``jobs.json`` 降级为
fire-and-forget 投影缓存（PG 故障时的人工回退面）。首次启用时
``load()`` 检测到表空且 jobs.json 存在会做一次性 backfill 导入，
之后文件仅作缓存、不再回灌权威。

与 ``app/agent_docs/store.py`` 同一套 Phase A 落地风格：裸参数化
SQL（``sqlalchemy.text``）、幂等 upsert（content_hash 拦截）、
idempotent backfill。

@author qingfeng
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..models import CronExecutionRecord, CronJobSpec, JobsFile
from .base import BaseJobRepository

logger = logging.getLogger(__name__)


def _payload_hash(payload: str) -> str:
    """SHA-256 hex of the serialized spec (idempotent upsert predicate)."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dump_spec(spec: CronJobSpec) -> str:
    """Serialize one job spec to a canonical JSON string (JSONB literal)."""
    return json.dumps(
        spec.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )


def _aware_utc(dt: datetime) -> datetime:
    """Normalize a naive datetime to aware UTC (TIMESTAMPTZ storage)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class PgJobRepository(BaseJobRepository):
    """PG-authoritative repository; ``jobs.json`` is a projection cache.

    All statements are parameterized and idempotent. JSONB columns are
    bound as canonical JSON strings via ``CAST(... AS JSONB)`` and read
    back through ``json.loads`` — asyncpg hands raw ``text()`` results
    back as strings, so no codec registration is required either way.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        jobs_path: Path | str,
        engine: Any = None,
        tenant_id: str = "default",
    ) -> None:
        if engine is None:
            # 与 agent_docs store 一致的延迟导入（避免模块级循环依赖）
            from ....db.engine import create_pg_engine

            engine = create_pg_engine()
        self._engine = engine
        self._agent_id = agent_id
        self._tenant_id = tenant_id
        self._jobs_path = (
            Path(jobs_path) if isinstance(jobs_path, str) else jobs_path
        )
        self._history_locks: dict[str, asyncio.Lock] = {}

    # -- internal helpers ---------------------------------------------------

    def _history_lock(self, job_id: str) -> asyncio.Lock:
        lock = self._history_locks.get(job_id)
        if lock is None:
            lock = asyncio.Lock()
            self._history_locks[job_id] = lock
        return lock

    async def _fetch_job_rows(self) -> list[Any]:
        """Load (job_id, spec) rows of this agent, ordered by insertion."""
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT job_id, CAST(spec AS TEXT) AS spec "
                    "FROM cron_jobs "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "ORDER BY id"
                ),
                {"tid": self._tenant_id, "aid": self._agent_id},
            )
            return list(result.mappings())

    async def _maybe_backfill_from_json(self) -> Optional[JobsFile]:
        """One-shot import from ``jobs.json`` when the plane is empty.

        Returns the imported ``JobsFile`` (so ``load()`` can serve it
        directly), or ``None`` when there was nothing to import (no
        file / unreadable file / empty plane). Never raises: a broken
        legacy file must not take the cron manager down.
        """
        if not self._jobs_path.exists():
            return None
        try:
            from ....utils.io_utils import read_json

            legacy = JobsFile.model_validate(read_json(self._jobs_path))
        except Exception:  # noqa: BLE001 - legacy file must not block boot
            logger.warning(
                "cron backfill skipped: unreadable jobs.json at %s",
                self._jobs_path,
            )
            return None
        if not legacy.jobs:
            return None
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            for spec in legacy.jobs:
                assert spec.id is not None
                payload = _dump_spec(spec)
                await conn.execute(
                    text(
                        "INSERT INTO cron_jobs (tenant_id, agent_id, "
                        "job_id, spec, content_hash, enabled) "
                        "VALUES (:tid, :aid, :jid, CAST(:spec AS JSONB), "
                        ":chash, :enabled) "
                        "ON CONFLICT (tenant_id, agent_id, job_id) "
                        "DO NOTHING"
                    ),
                    {
                        "tid": self._tenant_id,
                        "aid": self._agent_id,
                        "jid": spec.id,
                        "spec": payload,
                        "chash": _payload_hash(payload),
                        "enabled": bool(spec.enabled),
                    },
                )
        logger.warning(
            "cron backfill done: agent=%s imported=%d from %s "
            "(PG is now authoritative; file is a projection cache)",
            self._agent_id,
            len(legacy.jobs),
            self._jobs_path,
        )
        # 关键：把 legacy 文件重写为空平面。否则删除最后一个任务后
        # load() 见表空会再次触发 backfill，把投影缓存里的旧数据回灌
        # 权威（删除被“复活”）。重写后“文件→库”方向只在首启发生一次；
        # 重写失败也无害：DO NOTHING 幂等，下次启动重试。
        await self._project_to_json(JobsFile(version=2, jobs=[]))
        return legacy

    async def _project_to_json(self, jobs_file: JobsFile) -> None:
        """Best-effort projection of the authoritative plane to cache.

        The projection never blocks or fails the caller: PG stays the
        source of truth and the file is only a human-readable fallback.
        """
        try:
            from ....utils.io_utils import run_sync_io, write_json_atomic

            await run_sync_io(
                write_json_atomic,
                self._jobs_path,
                jobs_file.model_dump(mode="json"),
                sort_keys=True,
            )
        except Exception:  # noqa: BLE001 - projection is best-effort
            logger.warning(
                "cron jobs.json projection failed for agent %s",
                self._agent_id,
            )

    async def _project_from_db(self) -> None:
        """Refresh the projection cache from the authoritative rows."""
        jobs = await self.list_jobs()
        await self._project_to_json(JobsFile(version=2, jobs=jobs))

    # -- spec plane (BaseJobRepository contract) ----------------------------

    async def initialize(self) -> None:
        """One-time startup migration: import legacy jobs.json if empty.

        Explicitly invoked by ``CronManager.start()`` before the first
        ``load()`` — never from runtime reads. After this hook the file
        is demoted to a projection cache and the "file → PG" direction
        is closed for good, so a transient empty plane (e.g. right
        after deleting the last job) can never resurrect data from it.
        """
        rows = await self._fetch_job_rows()
        if not rows:
            await self._maybe_backfill_from_json()

    async def load(self) -> JobsFile:
        rows = await self._fetch_job_rows()
        jobs = [
            CronJobSpec.model_validate(json.loads(row["spec"]))
            for row in rows
        ]
        return JobsFile(version=2, jobs=jobs)

    async def save(self, jobs_file: JobsFile) -> None:
        """Full-plane reconcile inside one transaction.

        Rows whose canonical payload is unchanged are left untouched
        (hash predicate), missing rows are inserted, and rows absent
        from ``jobs_file`` are deleted.
        """
        from sqlalchemy import text

        payloads = {
            spec.id: _dump_spec(spec)
            for spec in jobs_file.jobs
            if spec.id is not None
        }
        jobs_by_id = {
            spec.id: spec for spec in jobs_file.jobs if spec.id is not None
        }
        hashes = {jid: _payload_hash(p) for jid, p in payloads.items()}
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT job_id, content_hash FROM cron_jobs "
                    "WHERE tenant_id = :tid AND agent_id = :aid"
                ),
                {"tid": self._tenant_id, "aid": self._agent_id},
            )
            existing = {
                row["job_id"]: row["content_hash"]
                for row in result.mappings()
            }
            for jid, payload in payloads.items():
                if existing.get(jid) == hashes[jid]:
                    continue
                spec = jobs_by_id[jid]
                await conn.execute(
                    text(
                        "INSERT INTO cron_jobs (tenant_id, agent_id, "
                        "job_id, spec, content_hash, enabled) "
                        "VALUES (:tid, :aid, :jid, CAST(:spec AS JSONB), "
                        ":chash, :enabled) "
                        "ON CONFLICT (tenant_id, agent_id, job_id) "
                        "DO UPDATE SET spec = EXCLUDED.spec, "
                        "content_hash = EXCLUDED.content_hash, "
                        "enabled = EXCLUDED.enabled, "
                        "updated_at = now()"
                    ),
                    {
                        "tid": self._tenant_id,
                        "aid": self._agent_id,
                        "jid": jid,
                        "spec": payload,
                        "chash": hashes[jid],
                        "enabled": bool(spec.enabled),
                    },
                )
            await conn.execute(
                text(
                    "DELETE FROM cron_jobs "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND job_id <> ALL(:ids)"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": self._agent_id,
                    "ids": sorted(payloads),
                },
            )
        await self._project_to_json(jobs_file)

    async def upsert_job(self, spec: CronJobSpec) -> None:
        """Single-row upsert (content-hash gated, no churn on replay)."""
        from sqlalchemy import text

        assert spec.id is not None
        payload = _dump_spec(spec)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO cron_jobs (tenant_id, agent_id, "
                    "job_id, spec, content_hash, enabled) "
                    "VALUES (:tid, :aid, :jid, CAST(:spec AS JSONB), "
                    ":chash, :enabled) "
                    "ON CONFLICT (tenant_id, agent_id, job_id) "
                    "DO UPDATE SET spec = EXCLUDED.spec, "
                    "content_hash = EXCLUDED.content_hash, "
                    "enabled = EXCLUDED.enabled, "
                    "updated_at = now() "
                    "WHERE cron_jobs.content_hash "
                    "IS DISTINCT FROM EXCLUDED.content_hash"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": self._agent_id,
                    "jid": spec.id,
                    "spec": payload,
                    "chash": _payload_hash(payload),
                    "enabled": bool(spec.enabled),
                },
            )
        await self._project_from_db()

    async def delete_job(self, job_id: str) -> bool:
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM cron_jobs "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND job_id = :jid"
                ),
                {"tid": self._tenant_id, "aid": self._agent_id, "jid": job_id},
            )
            deleted = (result.rowcount or 0) > 0
        if deleted:
            await self._project_from_db()
        return deleted

    # -- execution history plane -------------------------------------------

    async def get_history(self, job_id: str) -> list[CronExecutionRecord]:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT run_at, status, error, trigger "
                    "FROM cron_job_history "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND job_id = :jid "
                    "ORDER BY seq DESC"
                ),
                {"tid": self._tenant_id, "aid": self._agent_id, "jid": job_id},
            )
            rows = list(result.mappings())
        return [
            CronExecutionRecord(
                run_at=row["run_at"],
                status=row["status"],
                error=row["error"],
                trigger=row["trigger"],
            )
            for row in rows
        ]

    async def append_history(
        self,
        job_id: str,
        record: CronExecutionRecord,
        *,
        limit: int = 50,
    ) -> list[CronExecutionRecord]:
        """Append one record under the per-job lock, then trim to limit.

        ``seq`` is a per-job monotonic counter (MAX+1 under the in-process
        lock); retention deletes rows that fell out of the newest
        ``limit`` window.
        """
        from sqlalchemy import text

        lock = self._history_lock(job_id)
        async with lock:
            async with self._engine.begin() as conn:
                seq_row = await conn.execute(
                    text(
                        "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq "
                        "FROM cron_job_history "
                        "WHERE tenant_id = :tid AND agent_id = :aid "
                        "AND job_id = :jid"
                    ),
                    {
                        "tid": self._tenant_id,
                        "aid": self._agent_id,
                        "jid": job_id,
                    },
                )
                next_seq = (await seq_row.mappings().first())["next_seq"]
                await conn.execute(
                    text(
                        "INSERT INTO cron_job_history (tenant_id, "
                        "agent_id, job_id, seq, run_at, status, error, "
                        "trigger) "
                        "VALUES (:tid, :aid, :jid, :seq, :run_at, "
                        ":status, :error, :trigger)"
                    ),
                    {
                        "tid": self._tenant_id,
                        "aid": self._agent_id,
                        "jid": job_id,
                        "seq": next_seq,
                        "run_at": _aware_utc(record.run_at),
                        "status": record.status,
                        "error": record.error,
                        "trigger": record.trigger,
                    },
                )
                await conn.execute(
                    text(
                        "DELETE FROM cron_job_history "
                        "WHERE tenant_id = :tid AND agent_id = :aid "
                        "AND job_id = :jid AND seq <= :floor_seq"
                    ),
                    {
                        "tid": self._tenant_id,
                        "aid": self._agent_id,
                        "jid": job_id,
                        "floor_seq": next_seq - limit,
                    },
                )
            return await self.get_history(job_id)

    async def delete_history(self, job_id: str) -> None:
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM cron_job_history "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND job_id = :jid"
                ),
                {"tid": self._tenant_id, "aid": self._agent_id, "jid": job_id},
            )
        self._history_locks.pop(job_id, None)

    async def prune_orphan_history(self, valid_job_ids: set[str]) -> None:
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            # ``<> ALL('{}')`` is vacuously true, so an empty valid set
            # prunes every orphan row of this agent — same semantics as
            # the json repo's directory sweep.
            await conn.execute(
                text(
                    "DELETE FROM cron_job_history "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND job_id <> ALL(:ids)"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": self._agent_id,
                    "ids": sorted(valid_job_ids),
                },
            )


def build_job_repository(
    *,
    agent_id: str,
    jobs_path: Path | str,
    engine: Any = None,
) -> BaseJobRepository:
    """Select the cron repo by ``QWENPAW_STORAGE_BACKEND`` (json/dual/pg).

    ``dual``/``pg`` pick the PG-authoritative repository; when PG is not
    actually reachable (DSN unset / driver missing) the factory degrades
    to the json repo with a warning instead of blocking workspace boot.

    M2 收敛：判定改走 ``db.write_gateway``，消除 app 层对 providers
    域的反向依赖（三态开关本属存储层基础设施，不属于业务域）。
    """
    from ....db.write_gateway import resolve_storage_backend

    backend = resolve_storage_backend()
    if backend in ("dual", "pg"):
        try:
            return PgJobRepository(
                agent_id=agent_id,
                jobs_path=jobs_path,
                engine=engine,
            )
        except Exception as exc:  # noqa: BLE001 - boot must not break
            logger.warning(
                "PG cron repo unavailable (backend=%s), "
                "falling back to jobs.json: %s",
                backend,
                repr(exc),
            )
    from .json_repo import JsonJobRepository

    return JsonJobRepository(jobs_path)
