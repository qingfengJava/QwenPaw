# -*- coding: utf-8 -*-
"""PG-backed run-log store (``agent_runs`` + ``agent_run_spans``).

Replaces the file-era ``run_logs/index-*.jsonl`` list index with SQL
filtering/pagination, and adds per-run execution spans captured by
``SpanRecorderMiddleware``. All functions assume a configured
``QWENPAW_PG_DSN`` — availability is decided by the caller (see
:func:`pg_available`). Failures are swallowed with a warning: run
logging must never break the conversation.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from ..constant import EnvVarLoader
from ..db.base import DEFAULT_TENANT_ID
from ..db.engine import PG_DSN_ENV

logger = logging.getLogger(__name__)

_RUN_LIST_FIELDS = (
    "run_id",
    "agent_id",
    "display_name",
    "session_id",
    "root_session_id",
    "chat_id",
    "user_id",
    "channel",
    "source",
    "environment",
    "query_preview",
    "status",
    "started_at",
    "finished_at",
    "duration_ms",
    "total_tokens",
    "model",
    "version",
    "app_version",
    "error",
)

_SPAN_FIELDS = (
    "span_id",
    "parent_span_id",
    "kind",
    "name",
    "started_at",
    "ended_at",
    "duration_ms",
    "input",
    "output",
    "tokens",
    "status",
    "error",
)


def pg_available() -> bool:
    """Return True when a PG DSN is configured (engine creation deferred)."""
    return bool(EnvVarLoader.get_str(PG_DSN_ENV, "").strip())


def _to_dt(epoch: float | None) -> datetime | None:
    """Epoch seconds -> tz-aware datetime (asyncpg-native shape)."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc)


def _to_epoch(value: Any) -> float | None:
    """Tz-aware/naive datetime -> epoch seconds (file-era float shape)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    return float(value)


def _row_to_item(row: Any) -> dict[str, Any]:
    """One ``agent_runs`` row -> file-era list-item dict (epoch floats)."""
    item: dict[str, Any] = {}
    for idx, field in enumerate(_RUN_LIST_FIELDS):
        value = row[idx]
        if field in ("started_at", "finished_at"):
            value = _to_epoch(value)
        item[field] = value
    return item


def _span_row_to_dict(row: Any) -> dict[str, Any]:
    """One ``agent_run_spans`` row -> span dict (epoch floats)."""
    span: dict[str, Any] = {}
    for idx, field in enumerate(_SPAN_FIELDS):
        value = row[idx]
        if field in ("started_at", "ended_at"):
            value = _to_epoch(value)
        span[field] = value
    return span


async def start_run_pg(row: dict[str, Any], engine: Any = None) -> None:
    """Insert (or reset) one ``agent_runs`` row with status=running."""
    if engine is None:
        from ..db.engine import create_pg_engine

        engine = create_pg_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO agent_runs (tenant_id, run_id, agent_id, "
                    "display_name, session_id, root_session_id, chat_id, "
                    "user_id, channel, source, environment, query_preview, "
                    "status, started_at, model, version, app_version) "
                    "VALUES (:tenant_id, :run_id, :agent_id, :display_name, "
                    ":session_id, :root_session_id, :chat_id, :user_id, "
                    ":channel, :source, :environment, :query_preview, "
                    "'running', :started_at, :model, :version, :app_version) "
                    "ON CONFLICT (run_id) DO UPDATE SET "
                    "agent_id = EXCLUDED.agent_id, "
                    "display_name = COALESCE(EXCLUDED.display_name, "
                    "agent_runs.display_name), "
                    "session_id = EXCLUDED.session_id, "
                    "root_session_id = EXCLUDED.root_session_id, "
                    "chat_id = EXCLUDED.chat_id, "
                    "user_id = EXCLUDED.user_id, "
                    "channel = EXCLUDED.channel, "
                    "source = EXCLUDED.source, "
                    "environment = EXCLUDED.environment, "
                    "query_preview = EXCLUDED.query_preview, "
                    "status = 'running', "
                    "started_at = EXCLUDED.started_at, "
                    "finished_at = NULL, duration_ms = NULL, "
                    "total_tokens = NULL, error = NULL, "
                    "updated_at = now()",
                ),
                {
                    "tenant_id": DEFAULT_TENANT_ID,
                    "run_id": row.get("run_id") or "",
                    "agent_id": row.get("agent_id") or "default",
                    "display_name": row.get("display_name") or None,
                    "session_id": row.get("session_id") or None,
                    "root_session_id": row.get("root_session_id") or None,
                    "chat_id": row.get("chat_id") or None,
                    "user_id": row.get("user_id") or None,
                    "channel": row.get("channel") or None,
                    "source": row.get("source") or None,
                    "environment": row.get("environment") or None,
                    "query_preview": row.get("query_preview") or None,
                    "started_at": _to_dt(row.get("started_at")),
                    "model": row.get("model") or None,
                    "version": row.get("version") or None,
                    "app_version": row.get("app_version") or None,
                },
            )
    except Exception:  # pylint: disable=broad-except
        logger.warning("run-log pg start_run failed", exc_info=True)


async def append_span_pg(span: dict[str, Any], engine: Any = None) -> None:
    """Insert one ``agent_run_spans`` row."""
    if engine is None:
        from ..db.engine import create_pg_engine

        engine = create_pg_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO agent_run_spans (tenant_id, run_id, span_id, "
                    "parent_span_id, kind, name, started_at, ended_at, "
                    "duration_ms, input, output, tokens, status, error) "
                    "VALUES (:tenant_id, :run_id, :span_id, :parent_span_id, "
                    ":kind, :name, :started_at, :ended_at, :duration_ms, "
                    "CAST(:input AS JSONB), CAST(:output AS JSONB), "
                    ":tokens, :status, :error)",
                ),
                {
                    "tenant_id": DEFAULT_TENANT_ID,
                    "run_id": span.get("run_id") or "",
                    "span_id": span.get("span_id") or "",
                    "parent_span_id": span.get("parent_span_id") or None,
                    "kind": span.get("kind") or "llm",
                    "name": span.get("name") or None,
                    "started_at": _to_dt(span.get("started_at")),
                    "ended_at": _to_dt(span.get("ended_at")),
                    "duration_ms": span.get("duration_ms"),
                    # CAST requires text; json.dumps handled by the sink
                    "input": span.get("input_json"),
                    "output": span.get("output_json"),
                    "tokens": span.get("tokens"),
                    "status": span.get("status") or "success",
                    "error": span.get("error"),
                },
            )
    except Exception:  # pylint: disable=broad-except
        logger.warning("run-log pg append_span failed", exc_info=True)


async def finish_run_pg(
    run_id: str,
    *,
    status: str,
    finished_at: float,
    duration_ms: int,
    total_tokens: int | None,
    model: str | None = None,
    error: str | None = None,
    engine: Any = None,
) -> None:
    """Close one ``agent_runs`` row (status/tokens/duration)."""
    if engine is None:
        from ..db.engine import create_pg_engine

        engine = create_pg_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE agent_runs SET status = :status, "
                    "finished_at = :finished_at, duration_ms = :duration_ms, "
                    "total_tokens = :total_tokens, "
                    "model = COALESCE(:model, model), error = :error, "
                    "updated_at = now() WHERE run_id = :run_id",
                ),
                {
                    "status": status,
                    "finished_at": _to_dt(finished_at),
                    "duration_ms": duration_ms,
                    "total_tokens": total_tokens,
                    "model": model or None,
                    "error": error,
                    "run_id": run_id,
                },
            )
    except Exception:  # pylint: disable=broad-except
        logger.warning("run-log pg finish_run failed", exc_info=True)


async def query_run_logs_pg(
    *,
    agent_id: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    source: str | None = None,
    environment: str | None = None,
    keyword: str | None = None,
    start_ts: float | None = None,
    end_ts: float | None = None,
    limit: int = 50,
    offset: int = 0,
    engine: Any = None,
) -> tuple[list[dict[str, Any]], int]:
    """Query ``agent_runs`` newest-first; returns ``(page, total)``.

    Same signature and row shape as ``run_log_store.query_run_logs``.
    """
    if engine is None:
        from ..db.engine import create_pg_engine

        engine = create_pg_engine()

    clauses = ["tenant_id = :tenant_id"]
    params: dict[str, Any] = {"tenant_id": DEFAULT_TENANT_ID}
    if agent_id:
        clauses.append("agent_id = :agent_id")
        params["agent_id"] = agent_id
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if channel:
        clauses.append("channel = :channel")
        params["channel"] = channel
    if source:
        clauses.append("source = :source")
        params["source"] = source
    if environment:
        clauses.append("environment = :environment")
        params["environment"] = environment
    if keyword:
        clauses.append("query_preview ILIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    if start_ts is not None:
        clauses.append("started_at >= :start_ts")
        params["start_ts"] = _to_dt(start_ts)
    if end_ts is not None:
        clauses.append("started_at <= :end_ts")
        params["end_ts"] = _to_dt(end_ts)
    where = " AND ".join(clauses)

    fields = ", ".join(_RUN_LIST_FIELDS)
    async with engine.connect() as conn:
        total = (
            await conn.execute(
                text(f"SELECT COUNT(*) FROM agent_runs WHERE {where}"),
                params,
            )
        ).scalar() or 0
        result = await conn.execute(
            text(
                f"SELECT {fields} FROM agent_runs WHERE {where} "
                "ORDER BY started_at DESC NULLS LAST, run_id DESC "
                "LIMIT :limit OFFSET :offset",
            ),
            {**params, "limit": int(limit), "offset": int(offset)},
        )
        items = [_row_to_item(row) for row in result.fetchall()]
    return items, int(total)


async def get_run_trace_pg(
    run_id: str,
    engine: Any = None,
) -> dict[str, Any] | None:
    """Return one run + ordered spans; None when the run is unknown.

    Shape: ``{...list-item fields, spans: [span dicts]}`` — the frontend
    renders the span tree directly; empty spans fall back to the file
    trace on the caller side.
    """
    if engine is None:
        from ..db.engine import create_pg_engine

        engine = create_pg_engine()

    run_fields = ", ".join(_RUN_LIST_FIELDS)
    span_fields = ", ".join(_SPAN_FIELDS)
    async with engine.connect() as conn:
        run_row = (
            await conn.execute(
                text(f"SELECT {run_fields} FROM agent_runs WHERE run_id = :r"),
                {"r": run_id},
            )
        ).fetchone()
        if run_row is None:
            return None
        span_rows = (
            await conn.execute(
                text(
                    f"SELECT {span_fields} FROM agent_run_spans "
                    "WHERE run_id = :r AND tenant_id = :tid "
                    "ORDER BY started_at ASC NULLS LAST, id ASC",
                ),
                {"r": run_id, "tid": DEFAULT_TENANT_ID},
            )
        ).fetchall()

    trace = _row_to_item(run_row)
    trace["created_at"] = trace.get("started_at")
    trace["completed_at"] = trace.get("finished_at")
    trace["spans"] = [_span_row_to_dict(row) for row in span_rows]
    # File-era traces nest run labels under ``meta`` (the detail page
    # breadcrumb reads them there) — mirror that shape for PG runs.
    trace["meta"] = {
        "source": trace.get("source"),
        "session_id": trace.get("session_id"),
        "root_session_id": trace.get("root_session_id"),
        "agent_id": trace.get("agent_id"),
        "display_name": trace.get("display_name"),
        "user_id": trace.get("user_id"),
        "channel": trace.get("channel"),
        "environment": trace.get("environment"),
        "query": trace.get("query_preview"),
        "model": trace.get("model"),
        "version": trace.get("version"),
        "app_version": trace.get("app_version"),
    }
    return trace


async def purge_old_runs(days: int = 30, engine: Any = None) -> int:
    """Delete runs (and their spans) older than ``days``; return count."""
    if engine is None:
        from ..db.engine import create_pg_engine

        engine = create_pg_engine()

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM agent_runs WHERE started_at < :cutoff"),
            {"cutoff": cutoff},
        )
        removed = result.rowcount or 0
        # Orphan spans only exist after their run aged out — sweep them all.
        await conn.execute(
            text(
                "DELETE FROM agent_run_spans WHERE run_id NOT IN "
                "(SELECT run_id FROM agent_runs)",
            ),
        )
    return removed
