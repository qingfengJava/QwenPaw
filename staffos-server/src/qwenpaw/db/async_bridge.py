# -*- coding: utf-8 -*-
"""Shared sync-over-async bridge for PostgreSQL-backed stores.

Several storage contracts (scroll history, recall memory space) are
synchronous by design, while the M2 PostgreSQL backend is async (asyncpg).
This helper runs a daemon-thread event loop so those sync façades can drive
async work without imposing an event-loop affinity on their callers.

asyncpg connections are loop-affine: anything built on this loop must be
created and used exclusively through it, never shared with the FastAPI loop.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Coroutine, TypeVar

_T = TypeVar("_T")


class AsyncLoopThread:
    """A daemon-thread event loop executing coroutines synchronously."""

    def __init__(self, thread_name: str = "qwenpaw-pg-loop") -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever,
            name=thread_name,
            daemon=True,
        )
        self._thread.start()
        self._closed = False

    def run(self, coro: Coroutine[None, None, _T]) -> _T:
        """Run ``coro`` on the loop thread and block for its result."""
        if self._closed:
            raise RuntimeError("AsyncLoopThread is closed")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def close(self) -> None:
        """Stop the loop; pending coroutines are cancelled by abandonment."""
        if self._closed:
            return
        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
