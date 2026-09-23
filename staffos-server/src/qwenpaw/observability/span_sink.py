# -*- coding: utf-8 -*-
"""Process-local span sink: fire-and-forget PG writes for run spans.

The sink decouples ``SpanRecorderMiddleware`` (hot conversation path)
from PostgreSQL: every emit is a non-blocking queue put, and a single
background worker batches rows into ``run_log_pg_store``. Any failure
(engine creation, flush, queue overflow) is logged and swallowed — run
logging must never break the conversation.

Also owns the run-scoped ``ContextVar`` state that middlewares use to
tag spans with the current ``run_id``/parent (middlewares cannot see
the lifecycle-hook ``HookContext``).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

# Per-payload guardrails: a serialized payload above ``_MAX_PAYLOAD_BYTES``
# is replaced by a truncated preview (LLM prompts reach 30k+ tokens).
_MAX_PAYLOAD_BYTES = 64 * 1024
_PREVIEW_BYTES = 4096

# Worker flush cadence / batch size.
_FLUSH_INTERVAL_S = 0.5
_FLUSH_BATCH = 32
_QUEUE_MAX = 4096

_run_ctx: ContextVar[dict[str, str] | None] = ContextVar(
    "qwenpaw_runlog_ctx",
    default=None,
)
_current_llm_span: ContextVar[str | None] = ContextVar(
    "qwenpaw_runlog_llm_span",
    default=None,
)


def set_run_context(run_id: str, root_span_id: str | None = None) -> None:
    """Bind the current task to one run (called by the start hook)."""
    _run_ctx.set({"run_id": run_id, "root_span_id": root_span_id or ""})


def get_run_context() -> dict[str, str] | None:
    """Return ``{"run_id", "root_span_id"}`` or None outside a run."""
    return _run_ctx.get()


def clear_run_context() -> None:
    """Drop the run binding (called by the finish hook)."""
    _run_ctx.set(None)
    _current_llm_span.set(None)


def set_current_llm_span(span_id: str | None) -> None:
    """Remember the innermost llm span so tool spans hang under it."""
    _current_llm_span.set(span_id)


def get_current_llm_span() -> str | None:
    """Return the current llm span id (tool-span parent), if any."""
    return _current_llm_span.get()


def _truncate_payload(value: Any) -> Any:
    """JSON-serializable payload with a size cap; returns JSONB-ready data."""
    if value is None:
        return None
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )
    except Exception:  # pylint: disable=broad-except
        return {"unserializable": repr(value)[:_PREVIEW_BYTES]}
    if len(serialized.encode("utf-8")) <= _MAX_PAYLOAD_BYTES:
        return value
    return {
        "truncated": True,
        "preview": serialized[:_PREVIEW_BYTES],
    }


def _dumps_payload(value: Any) -> str | None:
    """Serialize a payload to a JSON string (CAST target for JSONB)."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


class SpanSink:
    """Queue-backed async writer for runs and spans."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue | None = None
        self._worker: asyncio.Task | None = None
        self._noop = False
        self._engine = None

    # -- producers (non-blocking, never raise) ----------------------------

    def start_run(self, meta: dict[str, Any]) -> None:
        """Queue an ``agent_runs`` insert (status=running)."""
        self._put(("run", dict(meta)))

    def emit_span(
        self,
        *,
        kind: str,
        name: str | None,
        started_at: float,
        ended_at: float,
        input: Any = None,  # pylint: disable=redefined-builtin
        output: Any = None,  # pylint: disable=redefined-builtin
        tokens: int | None = None,
        parent_span_id: str | None = None,
        status: str = "success",
        error: str | None = None,
        duration_override_ms: int | None = None,
    ) -> str | None:
        """Queue one span row; returns the span id (None when dropped)."""
        ctx = get_run_context()
        if not ctx:
            # Outside a run (e.g. workbench warmup) there is nowhere to
            # attach the span — dropping keeps referential integrity.
            return None
        span_id = uuid.uuid4().hex
        self._put(
            (
                "span",
                {
                    "run_id": (ctx or {}).get("run_id", ""),
                    "span_id": span_id,
                    "parent_span_id": parent_span_id,
                    "kind": kind,
                    "name": name,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    # perf_counter-derived duration when the caller measured
                    # one (wall-clock epochs stay for display ordering).
                    "duration_ms": duration_override_ms
                    if duration_override_ms is not None
                    else int((ended_at - started_at) * 1000),
                    "input_json": _dumps_payload(_truncate_payload(input)),
                    "output_json": _dumps_payload(_truncate_payload(output)),
                    "tokens": tokens,
                    "status": status,
                    "error": error,
                },
            ),
        )
        return span_id

    def finish_run(
        self,
        *,
        status: str,
        finished_at: float,
        duration_ms: int,
        total_tokens: int | None,
        model: str | None = None,
        error: str | None = None,
    ) -> None:
        """Queue the ``agent_runs`` closing update."""
        ctx = get_run_context()
        if not ctx:
            return
        self._put(
            (
                "finish",
                {
                    "run_id": ctx.get("run_id", ""),
                    "status": status,
                    "finished_at": finished_at,
                    "duration_ms": duration_ms,
                    "total_tokens": total_tokens,
                    "model": model,
                    "error": error,
                },
            ),
        )

    # -- internals ---------------------------------------------------------

    def _put(self, item: tuple[str, dict[str, Any]]) -> None:
        """Enqueue without ever blocking or raising."""
        try:
            if self._noop:
                return
            if self._queue is None:
                self._queue = asyncio.Queue(maxsize=_QUEUE_MAX)
                self._ensure_worker()
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            logger.debug("span sink queue full; dropping one event")
        except Exception:  # pylint: disable=broad-except
            logger.debug("span sink put failed", exc_info=True)

    def _ensure_worker(self) -> None:
        """Start the background flusher once, on the running loop."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(
                self._flush_loop(),
            )

    async def _flush_loop(self) -> None:
        """Batch-drain the queue into the PG store forever."""
        while True:
            try:
                batch: list[tuple[str, dict[str, Any]]] = [
                    await self._queue.get(),
                ]
                deadline = time.monotonic() + _FLUSH_INTERVAL_S
                while len(batch) < _FLUSH_BATCH:
                    timeout = deadline - time.monotonic()
                    if timeout <= 0:
                        break
                    try:
                        batch.append(
                            await asyncio.wait_for(
                                self._queue.get(),
                                timeout=timeout,
                            ),
                        )
                    except asyncio.TimeoutError:
                        break
                await self._flush_batch(batch)
            except asyncio.CancelledError:
                return
            except Exception:  # pylint: disable=broad-except
                logger.warning("span sink flush failed", exc_info=True)
                await asyncio.sleep(1.0)

    async def _flush_batch(
        self,
        batch: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """Write one batch; enter no-op mode when PG is unusable."""
        if self._engine is None:
            try:
                from ..db.engine import create_pg_engine

                self._engine = create_pg_engine()
            except Exception:  # pylint: disable=broad-except
                logger.info(
                    "span sink disabled: no PostgreSQL DSN configured",
                )
                self._noop = True
                return
        from ..app.run_log_pg_store import (
            append_span_pg,
            finish_run_pg,
            start_run_pg,
        )

        for kind, payload in batch:
            if kind == "run":
                await start_run_pg(payload, engine=self._engine)
            elif kind == "span":
                await append_span_pg(payload, engine=self._engine)
            elif kind == "finish":
                await finish_run_pg(
                    payload.pop("run_id"),
                    status=payload["status"],
                    finished_at=payload["finished_at"],
                    duration_ms=payload["duration_ms"],
                    total_tokens=payload.get("total_tokens"),
                    model=payload.get("model"),
                    error=payload.get("error"),
                    engine=self._engine,
                )


_sink: SpanSink | None = None


def get_span_sink() -> SpanSink:
    """Return the process-wide sink singleton."""
    global _sink  # pylint: disable=global-statement
    if _sink is None:
        _sink = SpanSink()
    return _sink


def reset_span_sink() -> None:
    """Drop the singleton (test isolation)."""
    global _sink  # pylint: disable=global-statement
    _sink = None
