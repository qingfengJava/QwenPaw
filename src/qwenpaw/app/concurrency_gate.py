# -*- coding: utf-8 -*-
"""Tiered turn concurrency gate (M3 + XianWork enterprise tiers).

One user's turns are capped at ``per_user`` concurrent executions;
enterprise deployments add two coarser tiers above it — a per-tenant
(org) cap and a process-wide global cap — so one heavy organization
cannot starve the whole deployment and one runaway deployment exhausts
no more than ``global_limit`` agent turns at once. Excess turns wait in
a single global queue bounded by ``max_queue``. A turn that would
exceed the queue depth fails fast with :class:`TurnQueueFull`, which
the HTTP layer maps to ``429 + Retry-After``.

The gate is a process-wide singleton: the deployment topology is one
worker, so in-process semaphores are the coordination mechanism (no
Redis). The public ``slot(user_id)`` signature is unchanged; the tenant
tier resolves the org from the request-scoped context var.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from ..constant import EnvVarLoader

logger = logging.getLogger(__name__)

USER_CONCURRENCY_ENV = "QWENPAW_USER_CONCURRENCY"
TENANT_CONCURRENCY_ENV = "QWENPAW_TENANT_CONCURRENCY"
GLOBAL_CONCURRENCY_ENV = "QWENPAW_GLOBAL_CONCURRENCY"
MAX_QUEUE_ENV = "QWENPAW_MAX_TURN_QUEUE"
QUEUE_TIMEOUT_ENV = "QWENPAW_TURN_QUEUE_TIMEOUT_S"

_DEFAULT_PER_USER = 3
_DEFAULT_PER_TENANT = 50
_DEFAULT_GLOBAL = 200
_DEFAULT_MAX_QUEUE = 64
_DEFAULT_QUEUE_TIMEOUT_S = 30.0


class TurnQueueFull(Exception):
    """Raised when a turn cannot be admitted within queue limits."""

    def __init__(self, retry_after: float, reason: str) -> None:
        super().__init__(reason)
        self.retry_after = retry_after
        self.reason = reason


class ConcurrencyGate:
    """Global + tenant + user semaphores plus one bounded wait queue."""

    def __init__(
        self,
        per_user: int = _DEFAULT_PER_USER,
        max_queue: int = _DEFAULT_MAX_QUEUE,
        queue_timeout_s: float = _DEFAULT_QUEUE_TIMEOUT_S,
        per_tenant: int = _DEFAULT_PER_TENANT,
        global_limit: int = _DEFAULT_GLOBAL,
    ) -> None:
        self._per_user = max(1, per_user)
        self._per_tenant = max(1, per_tenant)
        self._global_limit = max(1, global_limit)
        self._max_queue = max(0, max_queue)
        self._queue_timeout_s = max(0.1, queue_timeout_s)
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._tenant_sems: dict[str, asyncio.Semaphore] = {}
        self._global_sem = asyncio.Semaphore(self._global_limit)
        self._queued = 0
        self._queued_lock = asyncio.Lock()

    def _sem_for(self, user_id: str) -> asyncio.Semaphore:
        sem = self._sems.get(user_id)
        if sem is None:
            sem = asyncio.Semaphore(self._per_user)
            self._sems[user_id] = sem
        return sem

    def _tenant_sem_for(self, tenant_id: str) -> asyncio.Semaphore:
        sem = self._tenant_sems.get(tenant_id)
        if sem is None:
            sem = asyncio.Semaphore(self._per_tenant)
            self._tenant_sems[tenant_id] = sem
        return sem

    @staticmethod
    def _current_tenant() -> str:
        """Request-scoped org id (``default`` outside enterprise flows)."""
        try:
            from .enterprise import current_tenant_id

            return current_tenant_id()
        except Exception:  # pylint: disable=broad-except
            return "default"

    @asynccontextmanager
    async def slot(self, user_id: str) -> AsyncIterator[None]:
        """Acquire one turn slot (global → tenant → user, queue-bounded)."""
        key = user_id or "system"
        tenant = self._current_tenant()
        user_sem = self._sem_for(key)
        tenant_sem = self._tenant_sem_for(tenant)
        tiers = (self._global_sem, tenant_sem, user_sem)
        if (
            any(sem.locked() for sem in tiers)
            and self._queued >= self._max_queue
        ):
            raise TurnQueueFull(
                retry_after=self._queue_timeout_s,
                reason="turn queue is full",
            )
        async with self._queued_lock:
            self._queued += 1
        acquired: list[asyncio.Semaphore] = []
        try:
            try:
                for sem in tiers:
                    await asyncio.wait_for(
                        sem.acquire(),
                        timeout=self._queue_timeout_s,
                    )
                    acquired.append(sem)
            except asyncio.TimeoutError as exc:
                # Roll back only the partial acquisition (the success path
                # keeps the permits until the slot's own finally below).
                for sem in reversed(acquired):
                    sem.release()
                raise TurnQueueFull(
                    retry_after=self._queue_timeout_s,
                    reason="timed out waiting for a turn slot",
                ) from exc
        finally:
            async with self._queued_lock:
                self._queued -= 1
        try:
            yield
        finally:
            for sem in reversed(tiers):
                sem.release()

    @property
    def retry_after(self) -> float:
        """Suggested ``Retry-After`` seconds for rejected turns."""
        return self._queue_timeout_s

    def would_reject(self, user_id: str) -> bool:
        """Advisory pre-check: would a new turn be rejected right now?

        The HTTP layer uses this to fail fast with 429 instead of
        starting a background run that immediately fails. ``slot()``
        remains the authoritative check (this snapshot is TOCTOU-safe
        because ``slot()`` re-applies the same conditions).
        """
        key = user_id or "system"
        sem = self._sems.get(key)
        tenant_sem = self._tenant_sems.get(self._current_tenant())
        return (
            self._global_sem.locked()
            or (
                tenant_sem is not None
                and tenant_sem.locked()
            )
            or (
                sem is not None
                and sem.locked()
                and self._queued >= self._max_queue
            )
        )

    def stats(self) -> dict:
        """Snapshot for monitoring: tiers, permits and queue depth."""
        return {
            "per_user": self._per_user,
            "per_tenant": self._per_tenant,
            "global_limit": self._global_limit,
            "max_queue": self._max_queue,
            "queued": self._queued,
            "users": len(self._sems),
            "tenants": len(self._tenant_sems),
        }


_default_gate: Optional[ConcurrencyGate] = None


def get_concurrency_gate() -> ConcurrencyGate:
    """Return the process-wide gate, configured from the environment."""
    global _default_gate
    if _default_gate is None:
        _default_gate = ConcurrencyGate(
            per_user=EnvVarLoader.get_int(
                USER_CONCURRENCY_ENV,
                _DEFAULT_PER_USER,
            ),
            max_queue=EnvVarLoader.get_int(
                MAX_QUEUE_ENV,
                _DEFAULT_MAX_QUEUE,
            ),
            queue_timeout_s=EnvVarLoader.get_float(
                QUEUE_TIMEOUT_ENV,
                _DEFAULT_QUEUE_TIMEOUT_S,
            ),
            per_tenant=EnvVarLoader.get_int(
                TENANT_CONCURRENCY_ENV,
                _DEFAULT_PER_TENANT,
            ),
            global_limit=EnvVarLoader.get_int(
                GLOBAL_CONCURRENCY_ENV,
                _DEFAULT_GLOBAL,
            ),
        )
    return _default_gate


def reset_concurrency_gate() -> None:
    """Drop the singleton (tests)."""
    global _default_gate
    _default_gate = None
