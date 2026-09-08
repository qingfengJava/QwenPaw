# -*- coding: utf-8 -*-
"""Run-log index store: one JSONL shard per day under ``WORKING_DIR/run_logs/``.

Complements :mod:`inbox_trace_store` (per-run detail files) with a light
append-only index that powers the run-log list API (filter / search /
pagination) without scanning trace payloads.

Layout: ``WORKING_DIR/run_logs/index-YYYYMMDD.jsonl`` — one JSON object per
line, one file per local day. The ``run_log_hook`` pair writes each row
twice: once at run start (``status="running"``) and rewritten in place when
the run finishes. Shards (and their companion trace files) older than
``RETENTION_DAYS`` are lazily purged at most once per day.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..constant import WORKING_DIR
from ..utils.io_utils import (
    read_json,
    run_sync_io,
    unlink_async,
    write_text_atomic,
)

logger = logging.getLogger(__name__)

_INDEX_DIR = WORKING_DIR / "run_logs"
_TRACE_DIR = WORKING_DIR / "inbox_traces"
_LOCK = asyncio.Lock()

# Run logs (and trace detail files) older than this are purged lazily.
RETENTION_DAYS = 30

# Purge sweep runs at most once per day (module-level guard).
_PURGE_INTERVAL_SECONDS = 24 * 3600
_last_purge_at: float = 0.0

# Shard-file dates are local days; one shard covers this many seconds.
_SECONDS_PER_DAY = 86400

# Long free-text fields are truncated before they hit the index.
_PREVIEW_MAX_CHARS = 200
_ERROR_MAX_CHARS = 500


def _shard_name(day: date) -> str:
    """Return the JSONL shard file name for one local day."""
    return f"index-{day.strftime('%Y%m%d')}.jsonl"


def _shard_path(day: date) -> Path:
    """Return the shard path for one local day."""
    return _INDEX_DIR / _shard_name(day)


def _shard_day(path: Path) -> date | None:
    """Parse the day encoded in a shard file name (``index-YYYYMMDD.jsonl``)."""
    stem = path.stem
    if not stem.startswith("index-"):
        return None
    try:
        return datetime.strptime(stem[len("index-"):], "%Y%m%d").date()
    except ValueError:
        return None


def _append_line(path: Path, line: str) -> None:
    """Append one pre-serialized line (blocking worker, runs off-loop)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _read_shard_rows(path: Path) -> list[dict[str, Any]]:
    """Read all rows from one shard, skipping corrupt lines."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _rewrite_shard(path: Path, rows: list[dict[str, Any]]) -> None:
    """Atomically replace one shard with the given rows."""
    lines = [json.dumps(row, ensure_ascii=False, default=str) for row in rows]
    write_text_atomic(path, "\n".join(lines) + ("\n" if lines else ""))


def _update_rows(
    rows: list[dict[str, Any]],
    run_id: str,
    updates: dict[str, Any],
) -> bool:
    """Patch the last row matching ``run_id`` in place; True when found."""
    for row in reversed(rows):
        if row.get("run_id") == run_id:
            row.update(updates)
            return True
    return False


def _update_shard_blocking(
    days: list[date],
    run_id: str,
    updates: dict[str, Any],
) -> bool:
    """Update the run row across candidate shards, newest day first."""
    for day in days:
        path = _shard_path(day)
        rows = _read_shard_rows(path)
        if _update_rows(rows, run_id, updates):
            _rewrite_shard(path, rows)
            return True
    return False


def _matches(
    row: dict[str, Any],
    *,
    agent_id: str | None,
    status: str | None,
    channel: str | None,
    source: str | None,
    environment: str | None,
    keyword: str | None,
    start_ts: float | None,
    end_ts: float | None,
) -> bool:
    """Return True when one index row passes every active filter."""
    if agent_id is not None and row.get("agent_id") != agent_id:
        return False
    if status is not None and row.get("status") != status:
        return False
    if channel is not None and row.get("channel") != channel:
        return False
    if source is not None and row.get("source") != source:
        return False
    if environment is not None and row.get("environment") != environment:
        return False
    started_at = row.get("started_at")
    if start_ts is not None and isinstance(started_at, (int, float)):
        if started_at < start_ts:
            return False
    if end_ts is not None and isinstance(started_at, (int, float)):
        if started_at > end_ts:
            return False
    if keyword:
        lowered = keyword.lower()
        preview = str(row.get("query_preview") or "").lower()
        run_id = str(row.get("run_id") or "").lower()
        if lowered not in preview and not run_id.startswith(lowered):
            return False
    return True


def _purge_expired_blocking(now: float) -> None:
    """Delete over-retention shards and their companion trace files."""
    cutoff_day = (
        datetime.fromtimestamp(now).date() - timedelta(days=RETENTION_DAYS)
    )
    if not _INDEX_DIR.exists():
        return
    stale_shards: list[Path] = []
    for path in _INDEX_DIR.glob("index-*.jsonl"):
        day = _shard_day(path)
        if day is not None and day < cutoff_day:
            stale_shards.append(path)
    for shard in stale_shards:
        # Companion trace detail files die together with their index shard.
        for row in _read_shard_rows(shard):
            run_id = row.get("run_id")
            if isinstance(run_id, str) and run_id:
                trace = _TRACE_DIR / f"{run_id}.json"
                if trace.exists():
                    try:
                        trace.unlink()
                    except OSError:
                        logger.debug(
                            "run-log purge: failed to unlink %s",
                            trace,
                            exc_info=True,
                        )
        try:
            shard.unlink()
        except OSError:
            logger.debug(
                "run-log purge: failed to unlink %s",
                shard,
                exc_info=True,
            )
    # Trace files with no surviving shard (e.g. aborted runs) age out by mtime.
    if _TRACE_DIR.exists():
        cutoff_ts = now - RETENTION_DAYS * 86400
        for trace in _TRACE_DIR.glob("*.json"):
            try:
                if trace.stat().st_mtime < cutoff_ts:
                    trace.unlink()
            except OSError:
                continue


async def _maybe_purge(now: float) -> None:
    """Run the retention sweep at most once per day."""
    global _last_purge_at
    if now - _last_purge_at < _PURGE_INTERVAL_SECONDS:
        return
    _last_purge_at = now
    try:
        await run_sync_io(_purge_expired_blocking, now)
    except Exception:  # pylint: disable=broad-except
        logger.debug("run-log purge failed", exc_info=True)


def normalize_index_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Clamp free-text fields and coerce timestamps for one index row."""
    normalized = dict(entry)
    preview = normalized.get("query_preview")
    if isinstance(preview, str) and len(preview) > _PREVIEW_MAX_CHARS:
        normalized["query_preview"] = preview[:_PREVIEW_MAX_CHARS]
    error = normalized.get("error")
    if isinstance(error, str) and len(error) > _ERROR_MAX_CHARS:
        normalized["error"] = error[:_ERROR_MAX_CHARS]
    return normalized


async def append_run_index(entry: dict[str, Any]) -> None:
    """Append one run row to today's shard (call at run start)."""
    row = normalize_index_entry(entry)
    line = json.dumps(row, ensure_ascii=False, default=str)
    async with _LOCK:
        await run_sync_io(_append_line, _shard_path(date.today()), line)
    await _maybe_purge(time.time())


async def update_run_index(
    run_id: str,
    *,
    run_day: date | None = None,
    **updates: Any,
) -> None:
    """Patch the matching row (run day, falling back to today/yesterday)."""
    if not run_id or not updates:
        return
    row = normalize_index_entry(updates)
    today = date.fromtimestamp(time.time())
    candidates = [today, today - timedelta(days=1)]
    # Runs finalized after midnight (or after a restart) may live in an
    # older shard; the caller knows the start day, so try it first.
    if run_day is not None and run_day not in candidates:
        candidates.insert(0, run_day)
    async with _LOCK:
        await run_sync_io(
            _update_shard_blocking,
            candidates,
            run_id,
            row,
        )


async def query_run_logs(
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
) -> tuple[list[dict[str, Any]], int]:
    """Query the index newest-first; returns ``(page, total_hint)``.

    ``total_hint`` counts every matching row within the retention window,
    not just the returned page.
    """
    # List shards newest-day first so the merge below is already time-ordered.
    if _INDEX_DIR.exists():
        shard_paths = sorted(
            (p for p in _INDEX_DIR.glob("index-*.jsonl")),
            key=lambda p: p.name,
            reverse=True,
        )
    else:
        shard_paths = []

    matches: list[dict[str, Any]] = []
    for path in shard_paths:
        # Shard names encode the local day, so whole files outside the
        # requested window can be skipped without parsing any line.
        day = _shard_day(path)
        if day is not None:
            day_start = datetime(day.year, day.month, day.day).timestamp()
            day_end = day_start + _SECONDS_PER_DAY
            if start_ts is not None and day_end <= start_ts:
                break
            if end_ts is not None and day_start > end_ts:
                continue
        rows = await run_sync_io(_read_shard_rows, path)
        for row in reversed(rows):
            if _matches(
                row,
                agent_id=agent_id,
                status=status,
                channel=channel,
                source=source,
                environment=environment,
                keyword=keyword,
                start_ts=start_ts,
                end_ts=end_ts,
            ):
                matches.append(row)

    total = len(matches)
    page = matches[offset : offset + max(limit, 0)]
    return page, total


__all__ = [
    "RETENTION_DAYS",
    "append_run_index",
    "normalize_index_entry",
    "query_run_logs",
    "update_run_index",
]
