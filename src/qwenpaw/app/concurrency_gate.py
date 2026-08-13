# -*- coding: utf-8 -*-
"""Per-user turn concurrency gate (M3).

One user's turns are capped at ``per_user`` concurrent executions; excess
turns wait in a single global queue bounded by ``max_queue``. A turn that
would exceed the queue depth fails fast with :class:`TurnQueueFull`, which
the HTTP layer maps to ``429 + Retry-After`` and channels surface as a
plain error message.

The gate is a process-wide singleton: the deployment topology is one
worker, so in-process semaphores are the coordination mechanism (no Redis).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from ..constant import EnvVarLoader

logger = logging.getLogger(__name__)

USER_CONCURRENCY_ENV = "QWENPAW_USER_CONCURRENCY"
MAX_QUEUE_ENV = "QWENPAW_MAX_TURN_QUEUE"
QUEUE_TIMEOUT_ENV = "QWENPAW_TURN_QUEUE_TIMEOUT_S"

_DEFAULT_PER_USER = 3
_DEFAULT_MAX_QUEUE = 64
_DEFAULT_QUEUE_TIMEOUT_S = 30.0


class TurnQueueFull(Exception):
    """Raised when a turn cannot be admitted within queue limits."""

    def __init__(self, retry_after: float, reason: str) -> None:
        super().__init__(reason)
        self.retry_after = retry_after
        self.reason = reason


class ConcurrencyGate:
    """Per-user semaphore set plus one bounded global wait queue."""

    def __init__(
        self,
        per_user: int = _DEFAULT_PER_USER,
        max_queue: int = _DEFAULT_MAX_QUEUE,
        queue_timeout_s: float = _DEFAULT_QUEUE_TIMEOUT_S,
    ) -> None:
        self._per_user = max(1, per_user)
        self._max_queue = max(0, max_queue)
        self._queue_timeout_s = max(0.1, queue_timeout_s)
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._queued = 0
        self._queued_lock = asyncio.Lock()

    def _sem_for(self, user_id: str) -> asyncio.Semaphore:
        sem = self._sems.get(user_id)
        if sem is None:
            sem = asyncio.Semaphore(self._per_user)
            self._sems[user_id] = sem
        return sem

    @asynccontextmanager
    async def slot(self, user_id: str) -> AsyncIterator[None]:
        """Acquire one turn slot for ``user_id`` (queue-bounded)."""
        key = user_id or "system"
        sem = self._sem_for(key)
        if sem.locked() and self._queued >= self._max_queue:
            raise TurnQueueFull(
                retry_after=self._queue_timeout_s,
                reason="turn queue is full",
            )
        async with self._queued_lock:
            self._queued += 1
        try:
            await asyncio.wait_for(
                sem.acquire(),
                timeout=self._queue_timeout_s,
            )
        except asyncio.TimeoutError as exc:
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
        return (
            sem is not None
            and sem.locked()
            and self._queued >= self._max_queue
        )

    def stats(self) -> dict:
        """Snapshot for monitoring: per-user permits and queue depth."""
        return {
            "per_user": self._per_user,
            "max_queue": self._max_queue,
            "queued": self._queued,
            "users": len(self._sems),
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
        )
    return _default_gate


def reset_concurrency_gate() -> None:
    """Drop the singleton (tests)."""
    global _default_gate
    _default_gate = None
