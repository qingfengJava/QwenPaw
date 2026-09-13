# -*- coding: utf-8 -*-
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..models import CronExecutionRecord, CronJobSpec, JobsFile


class BaseJobRepository(ABC):
    """Abstract repository for cron job specs persistence."""

    async def initialize(self) -> None:
        """One-time startup hook (optional legacy-data migration).

        Called by ``CronManager.start()`` before the first ``load()``.
        Repositories that need a one-shot import (e.g. file → PG
        backfill) override this; the default is a no-op. Runtime
        reads must never trigger migration implicitly — otherwise a
        transient empty plane (e.g. right after deleting the last
        job) would resurrect data from the projection cache.
        """
        return None

    @abstractmethod
    async def load(self) -> JobsFile:
        """Load all jobs from storage."""
        raise NotImplementedError

    @abstractmethod
    async def save(self, jobs_file: JobsFile) -> None:
        """Persist all jobs to storage (should be atomic if possible)."""
        raise NotImplementedError

    @abstractmethod
    async def get_history(self, job_id: str) -> list[CronExecutionRecord]:
        """Get execution history for a single job."""
        raise NotImplementedError

    @abstractmethod
    async def append_history(
        self,
        job_id: str,
        record: CronExecutionRecord,
        *,
        limit: int = 50,
    ) -> list[CronExecutionRecord]:
        """Append one execution record and keep at most ``limit`` records."""
        raise NotImplementedError

    @abstractmethod
    async def delete_history(self, job_id: str) -> None:
        """Delete execution history of one job."""
        raise NotImplementedError

    @abstractmethod
    async def prune_orphan_history(self, valid_job_ids: set[str]) -> None:
        """Delete history files that no longer belong to existing jobs."""
        raise NotImplementedError

    # ---- Optional but commonly needed convenience ops ----

    async def list_jobs(self) -> list[CronJobSpec]:
        jf = await self.load()
        return jf.jobs

    async def get_job(self, job_id: str) -> Optional[CronJobSpec]:
        jf = await self.load()
        for job in jf.jobs:
            if job.id == job_id:
                return job
        return None

    async def upsert_job(self, spec: CronJobSpec) -> None:
        jf = await self.load()
        for i, j in enumerate(jf.jobs):
            if j.id == spec.id:
                jf.jobs[i] = spec
                break
        else:
            jf.jobs.append(spec)
        await self.save(jf)

    async def delete_job(self, job_id: str) -> bool:
        jf = await self.load()
        before = len(jf.jobs)
        jf.jobs = [j for j in jf.jobs if j.id != job_id]
        if len(jf.jobs) == before:
            return False
        await self.save(jf)
        return True
