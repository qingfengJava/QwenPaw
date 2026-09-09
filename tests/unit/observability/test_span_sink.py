# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for qwenpaw.observability.span_sink.

Covers: payload truncation, queue batching into the PG store (fake
recorded calls), no-op degradation when PG is unavailable, run-context
binding, and emission outside a run being dropped.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.observability import span_sink as sink_mod
from qwenpaw.observability.span_sink import (
    SpanSink,
    clear_run_context,
    get_run_context,
    set_run_context,
)


# ---------------------------------------------------------------------------
# helpers / fakes
# ---------------------------------------------------------------------------


class _Recorder:
    """Captures the calls each run_log_pg_store function would make."""

    def __init__(self):
        self.runs: list[dict] = []
        self.spans: list[dict] = []
        self.finishes: list[dict] = []

    async def start_run_pg(self, row, engine=None):
        self.runs.append(row)

    async def append_span_pg(self, span, engine=None):
        self.spans.append(span)

    async def finish_run_pg(self, run_id, **kwargs):
        self.finishes.append({"run_id": run_id, **kwargs})


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Patch the PG store functions used by the flush loop.

    The sink imports these lazily from the store module, so patch the
    source module attributes (not the sink module).
    """
    rec = _Recorder()
    monkeypatch.setattr(
        "qwenpaw.app.run_log_pg_store.start_run_pg",
        rec.start_run_pg,
    )
    monkeypatch.setattr(
        "qwenpaw.app.run_log_pg_store.append_span_pg",
        rec.append_span_pg,
    )
    monkeypatch.setattr(
        "qwenpaw.app.run_log_pg_store.finish_run_pg",
        rec.finish_run_pg,
    )
    return rec


async def _drain(sink: SpanSink, recorder: _Recorder) -> None:
    """Flush the queue immediately (bypass the background worker)."""
    queue = sink._queue
    assert queue is not None
    batch = []
    while not queue.empty():
        batch.append(queue.get_nowait())
    await sink._flush_batch(batch)


@pytest.fixture(autouse=True)
def _clean_ctx():
    clear_run_context()
    yield
    clear_run_context()


# ---------------------------------------------------------------------------
# cases
# ---------------------------------------------------------------------------


def test_truncate_payload_caps_oversize():
    big = {"text": "x" * (sink_mod._MAX_PAYLOAD_BYTES + 10)}
    out = sink_mod._truncate_payload(big)
    assert out["truncated"] is True
    assert len(out["preview"]) == sink_mod._PREVIEW_BYTES
    small = {"text": "hi"}
    assert sink_mod._truncate_payload(small) == small


def test_emit_outside_run_is_dropped():
    sink = SpanSink()
    assert (
        sink.emit_span(
            kind="llm",
            name="m",
            started_at=1.0,
            ended_at=2.0,
        )
        is None
    )
    assert sink._queue is None


def test_run_context_roundtrip():
    set_run_context("run-1", "root-1")
    ctx = get_run_context()
    assert ctx == {"run_id": "run-1", "root_span_id": "root-1"}
    clear_run_context()
    assert get_run_context() is None


async def test_emit_and_flush_batches(recorder: _Recorder):
    set_run_context("run-1")
    sink = SpanSink()
    span_id = sink.emit_span(
        kind="llm",
        name="qwen-max",
        started_at=1.0,
        ended_at=2.0,
        input={"message_count": 3},
        output={"blocks": []},
        tokens=42,
        duration_override_ms=995,
    )
    assert span_id
    sink.finish_run(
        status="success",
        finished_at=3.0,
        duration_ms=2000,
        total_tokens=55,
        model="qwen-max",
    )
    await _drain(sink, recorder)

    assert len(recorder.spans) == 1
    span = recorder.spans[0]
    assert span["run_id"] == "run-1"
    assert span["kind"] == "llm"
    assert span["duration_ms"] == 995
    assert span["tokens"] == 42
    assert span["input_json"] == '{"message_count": 3}'
    assert len(recorder.finishes) == 1
    assert recorder.finishes[0]["run_id"] == "run-1"
    assert recorder.finishes[0]["total_tokens"] == 55


async def test_flush_marks_noop_when_pg_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    def _raise():
        raise RuntimeError("no dsn")

    monkeypatch.setattr(
        "qwenpaw.db.engine.create_pg_engine",
        _raise,
        raising=False,
    )
    set_run_context("run-1")
    sink = SpanSink()
    sink.emit_span(kind="llm", name="m", started_at=1.0, ended_at=2.0)
    await _drain(sink, _Recorder())

    assert sink._noop is True
    # Further emissions are dropped without queueing.
    before = sink._queue.qsize() if sink._queue else 0
    sink.emit_span(kind="llm", name="m", started_at=2.0, ended_at=3.0)
    after = sink._queue.qsize() if sink._queue else 0
    assert after == before


async def test_flush_swallows_store_errors(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _boom(*args, **kwargs):
        raise RuntimeError("pg down")

    engine = SimpleNamespace()

    async def _fake_append(span, engine=None):
        _boom()

    monkeypatch.setattr(
        "qwenpaw.app.run_log_pg_store.append_span_pg",
        _fake_append,
    )
    monkeypatch.setattr(
        "qwenpaw.db.engine.create_pg_engine",
        lambda: engine,
        raising=False,
    )
    set_run_context("run-1")
    sink = SpanSink()
    sink.emit_span(kind="tool", name="bash", started_at=1.0, ended_at=1.5)
    await _drain(sink, _Recorder())
    # The error was swallowed; the sink stays usable.
    assert sink._noop is False
