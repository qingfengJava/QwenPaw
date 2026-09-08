# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for qwenpaw.app.run_log_store.

Real file IO through monkeypatched ``_INDEX_DIR`` / ``_TRACE_DIR`` —
no over-mocking. Covers: append/update index rows, cross-day update
fallback, query filters (agent/status/channel/source/environment/
keyword/time window), pagination + total hint, retention purge, and
text-field normalization.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from qwenpaw.app import run_log_store as store


def _row(run_id: str, **overrides: object) -> dict:
    """Build one minimal-but-complete index row."""
    row = {
        "run_id": run_id,
        "agent_id": "agent-a",
        "session_id": "s-1",
        "chat_id": "",
        "user_id": "u-1",
        "channel": "feishim",
        "source": "chat",
        "environment": "online",
        "query_preview": "帮我排查发货短信问题",
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "duration_ms": None,
        "total_tokens": 0,
        "version": "test",
        "error": None,
    }
    row.update(overrides)
    return row


@pytest.fixture
def index_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect module-level _INDEX_DIR/_TRACE_DIR to tmp and arm purge."""
    target = tmp_path / "run_logs"
    monkeypatch.setattr(store, "_INDEX_DIR", target)
    monkeypatch.setattr(store, "_TRACE_DIR", tmp_path / "inbox_traces")
    # Keep the retention sweep out of the way unless a test wants it.
    monkeypatch.setattr(store, "_last_purge_at", time.time())
    return target


# ---------------------------------------------------------------------------
# append / update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_writes_today_shard(index_dir: Path):
    await store.append_run_index(_row("run-1"))

    files = list(index_dir.glob("index-*.jsonl"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert saved["run_id"] == "run-1"
    assert saved["status"] == "running"


@pytest.mark.asyncio
async def test_update_patches_running_row(index_dir: Path):
    await store.append_run_index(_row("run-2"))

    await store.update_run_index(
        "run-2",
        status="success",
        duration_ms=1234,
        total_tokens=77,
    )

    shard = next(index_dir.glob("index-*.jsonl"))
    rows = [json.loads(l) for l in shard.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "success"
    assert rows[0]["duration_ms"] == 1234
    assert rows[0]["total_tokens"] == 77


@pytest.mark.asyncio
async def test_update_falls_back_to_yesterday_shard(
    index_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Simulate a run that started yesterday (its row lives in the older shard).
    yesterday_shard = index_dir / "index-20260101.jsonl"
    yesterday_shard.parent.mkdir(parents=True, exist_ok=True)
    yesterday_shard.write_text(
        json.dumps(_row("run-old"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Freeze "today" next to the shard so the fallback path is exercised.
    real_date = store.date

    class _FakeDate(real_date):
        @classmethod
        def fromtimestamp(cls, ts: float):
            return real_date(2026, 1, 2)

    monkeypatch.setattr(store, "date", _FakeDate)

    await store.update_run_index("run-old", status="failed", error="boom")

    rows = [
        json.loads(l)
        for l in yesterday_shard.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "boom"


@pytest.mark.asyncio
async def test_update_uses_run_day_shard(index_dir: Path):
    """Rows finalized long after midnight are patched via ``run_day``."""
    index_dir.mkdir(parents=True, exist_ok=True)
    run_day = store.date.today() - timedelta(days=3)
    shard = index_dir / store._shard_name(run_day)
    shard.write_text(
        json.dumps(_row("run-mid"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Without the run day the patch cannot reach the 3-day-old shard.
    await store.update_run_index("run-mid", status="failed")
    rows = [
        json.loads(l)
        for l in shard.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["status"] == "running"

    # With run_day the stale row is patched in place.
    await store.update_run_index(
        "run-mid",
        run_day=run_day,
        status="failed",
        error="late",
    )
    rows = [
        json.loads(l)
        for l in shard.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "late"


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_orders_newest_first_and_filters(index_dir: Path):
    base = time.time()
    await store.append_run_index(_row("run-1", started_at=base - 200))
    await store.append_run_index(_row("run-2", started_at=base - 100))
    await store.append_run_index(
        _row("run-3", started_at=base, status="failed"),
    )

    items, total = await store.query_run_logs(agent_id="agent-a")
    assert total == 3
    assert [i["run_id"] for i in items] == ["run-3", "run-2", "run-1"]

    items, total = await store.query_run_logs(status="failed")
    assert total == 1
    assert items[0]["run_id"] == "run-3"


@pytest.mark.asyncio
async def test_query_keyword_matches_preview_and_run_prefix(index_dir: Path):
    await store.append_run_index(_row("abcdef123456", query_preview="发货短信"))
    await store.append_run_index(_row("zzz987654321", query_preview="别的"))

    items, _ = await store.query_run_logs(keyword="发货")
    assert [i["run_id"] for i in items] == ["abcdef123456"]

    # Keyword also acts as a run-id prefix search (trace-id search box).
    items, _ = await store.query_run_logs(keyword="abc")
    assert [i["run_id"] for i in items] == ["abcdef123456"]


@pytest.mark.asyncio
async def test_query_pagination_and_total_hint(index_dir: Path):
    base = time.time()
    for idx in range(5):
        await store.append_run_index(
            _row(f"run-{idx}", started_at=base + idx),
        )

    page, total = await store.query_run_logs(limit=2, offset=1)
    assert total == 5
    assert [i["run_id"] for i in page] == ["run-3", "run-2"]


@pytest.mark.asyncio
async def test_query_environment_and_channel_filters(index_dir: Path):
    await store.append_run_index(
        _row(
            "run-dbg",
            agent_id="expert_x__draft",
            environment="debug",
            channel="console",
        ),
    )
    await store.append_run_index(
        _row("run-on", channel="feishim"),
    )

    items, _ = await store.query_run_logs(environment="debug")
    assert [i["run_id"] for i in items] == ["run-dbg"]

    items, _ = await store.query_run_logs(channel="feishim")
    assert [i["run_id"] for i in items] == ["run-on"]


@pytest.mark.asyncio
async def test_query_prunes_shards_outside_time_window(
    index_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Whole shards outside the window are never read at all."""
    index_dir.mkdir(parents=True, exist_ok=True)
    today = store.date.today()
    old_day = today - timedelta(days=7)
    old_shard = index_dir / store._shard_name(old_day)
    old_shard.write_text(
        json.dumps(
            _row("run-old", started_at=time.mktime(old_day.timetuple())),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    fresh_shard = index_dir / store._shard_name(today)
    fresh_shard.write_text(
        json.dumps(_row("run-new", started_at=time.time()), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    read_calls: list[str] = []
    real_read = store._read_shard_rows

    def _spy(path):
        read_calls.append(path.name)
        return real_read(path)

    monkeypatch.setattr(store, "_read_shard_rows", _spy)

    # Window: since today 00:00 local — the 7-day-old shard is pruned.
    day_start = datetime.combine(today, datetime.min.time()).timestamp()
    items, total = await store.query_run_logs(start_ts=day_start)
    assert [i["run_id"] for i in items] == ["run-new"]
    assert total == 1
    assert old_shard.name not in read_calls

    # No window → both shards are read as before.
    _, total_all = await store.query_run_logs()
    assert total_all == 2
    assert old_shard.name in read_calls


# ---------------------------------------------------------------------------
# normalization + retention
# ---------------------------------------------------------------------------


def test_normalize_truncates_long_fields():
    row = store.normalize_index_entry(
        {"query_preview": "x" * 500, "error": "e" * 1000},
    )
    assert len(row["query_preview"]) == store._PREVIEW_MAX_CHARS
    assert len(row["error"]) == store._ERROR_MAX_CHARS


def test_purge_removes_expired_shards_and_traces(
    index_dir: Path,
):
    # One stale shard (36 days old) + one fresh shard (today).
    stale_day = "index-20200101.jsonl"
    index_dir.mkdir(parents=True, exist_ok=True)
    stale_shard = index_dir / stale_day
    stale_shard.write_text(
        json.dumps(_row("run-stale"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fresh_shard = index_dir / store._shard_name(store.date.today())
    fresh_shard.write_text(
        json.dumps(_row("run-fresh"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    trace_dir = store._TRACE_DIR
    trace_dir.mkdir(parents=True, exist_ok=True)
    stale_trace = trace_dir / "run-stale.json"
    stale_trace.write_text("{}", encoding="utf-8")
    fresh_trace = trace_dir / "run-fresh.json"
    fresh_trace.write_text("{}", encoding="utf-8")
    # An old mtime on the fresh-named trace would also be purged; keep it new.
    assert fresh_trace.exists()

    store._purge_expired_blocking(time.time())

    assert not stale_shard.exists()
    assert not stale_trace.exists()
    assert fresh_shard.exists()
    assert fresh_trace.exists()


@pytest.mark.asyncio
async def test_maybe_purge_runs_at_most_once_per_day(index_dir: Path):
    calls: list[float] = []

    def _fake_purge(now: float) -> None:
        calls.append(now)

    import qwenpaw.app.run_log_store as store_mod

    original = store_mod._purge_expired_blocking
    store_mod._purge_expired_blocking = _fake_purge  # type: ignore[assignment]
    try:
        store_mod._last_purge_at = 0.0
        await store_mod._maybe_purge(time.time())
        await store_mod._maybe_purge(time.time() + 10)
        assert len(calls) == 1
    finally:
        store_mod._purge_expired_blocking = original  # type: ignore[assignment]
