# -*- coding: utf-8 -*-
"""PostgreSQL token-usage sink (enterprise multi-dimensional metering).

Mirrors the file-era ``TokenUsageManager`` fire-and-forget pattern: a
bounded in-memory buffer plus a background flush task. Events carry the
enterprise dimensions (tenant / user / project / agent) resolved from
the request-scoped context vars, enabling per-org and per-member usage
reports and quota evaluation.

The sink is a no-op (``None`` singleton) when PostgreSQL is not
configured — local deployments keep the single-file usage log exactly
as before.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Deque, Optional

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL_S = 10.0
_FLUSH_BATCH = 100
_BUFFER_BOUND = 2000


class PgUsageSink:
    """Buffered writer for the ``token_usage_events`` table."""

    def __init__(self) -> None:
        self._buffer: Deque[dict] = deque(maxlen=_BUFFER_BOUND)
        self._flush_task: Optional[asyncio.Task] = None
        self._dropped = 0

    def enqueue(self, event: dict) -> None:
        """Non-blocking enqueue; starts the flush loop lazily."""
        if len(self._buffer) == _BUFFER_BOUND:
            self._dropped += 1
        self._buffer.append(event)
        self._ensure_flush_task()

    def _ensure_flush_task(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            return
        try:
            self._flush_task = asyncio.get_running_loop().create_task(
                self._flush_loop(),
            )
        except RuntimeError:
            pass

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL_S)
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:  # pylint: disable=broad-except
                logger.debug("usage flush failed", exc_info=True)

    async def flush(self) -> None:
        """Drain the buffer into PG (executemany-style, one transaction)."""
        from sqlalchemy import text

        from ..app.enterprise import enterprise_engine

        engine = enterprise_engine()
        if engine is None or not self._buffer:
            return
        batch = []
        while self._buffer and len(batch) < _FLUSH_BATCH:
            batch.append(self._buffer.popleft())
        if not batch:
            return
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO token_usage_events (tenant_id, org_id, "
                    "user_id, project_id, agent_id, provider_id, model, "
                    "prompt_tokens, completion_tokens) VALUES "
                    "(:tenant_id, :org_id, :user_id, :project_id, "
                    ":agent_id, :provider_id, :model, :prompt_tokens, "
                    ":completion_tokens)"
                ),
                batch,
            )
        if self._dropped:
            logger.warning(
                "usage sink dropped %d events (buffer bound)",
                self._dropped,
            )
            self._dropped = 0

    def stats(self) -> dict:
        return {
            "buffered": len(self._buffer),
            "dropped": self._dropped,
        }


def build_usage_event(
    provider_id: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Optional[dict]:
    """Assemble one event row with the enterprise context dimensions."""
    from ..app.agent_context import get_current_agent_id, get_current_user_id

    def _ctx(fn) -> str:
        try:
            return fn() or ""
        except Exception:  # pylint: disable=broad-except
            return ""

    user_id = _ctx(get_current_user_id)
    agent_id = _ctx(get_current_agent_id)

    # Project-shared turns carry the synthetic ``project:{pid}`` owner;
    # split it so per-user and per-project reports stay disjoint.
    project_id = ""
    if user_id.startswith("project:"):
        project_id = user_id[len("project:"):]
        user_id = ""

    try:
        from ..app.enterprise import current_tenant_id

        tenant_id = current_tenant_id()
    except Exception:  # pylint: disable=broad-except
        tenant_id = "default"

    return {
        "tenant_id": tenant_id,
        "org_id": tenant_id,
        "user_id": user_id or None,
        "project_id": project_id or None,
        "agent_id": agent_id or None,
        "provider_id": provider_id,
        "model": model_name,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
    }


_sink: Optional[PgUsageSink] = None


def get_pg_usage_sink() -> Optional[PgUsageSink]:
    """Singleton sink; ``None`` when PG is not configured."""
    global _sink  # pylint: disable=global-statement
    if _sink is not None:
        return _sink
    from ..app.enterprise import enterprise_engine

    if enterprise_engine() is None:
        return None
    _sink = PgUsageSink()
    return _sink


def reset_pg_usage_sink() -> None:
    """Drop the singleton (tests)."""
    global _sink  # pylint: disable=global-statement
    if _sink is not None and _sink._flush_task is not None:
        _sink._flush_task.cancel()
    _sink = None


def now_ts() -> float:
    """Epoch seconds (diagnostics)."""
    return time.time()
