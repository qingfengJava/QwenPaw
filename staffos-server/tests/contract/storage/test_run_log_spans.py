# -*- coding: utf-8 -*-
"""PG contract tests for the run-log span store (agent_runs/spans).

Runs only when ``QWENPAW_TEST_PG_DSN`` points at a throwaway database;
skips otherwise, keeping the default test run hermetic.
"""
from __future__ import annotations

import time

import pytest

from qwenpaw.app import run_log_pg_store as store


pytestmark = pytest.mark.contract


@pytest.fixture
async def _clean(pg_engine):
    """Truncate both run-log tables around every test."""
    from sqlalchemy import text

    async with pg_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE agent_runs, agent_run_spans"),
        )
    yield
    async with pg_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE agent_runs, agent_run_spans"),
        )


async def test_run_span_lifecycle(pg_engine, _clean):
    """start_run -> spans -> finish -> trace assembly round-trip."""
    started = time.time() - 5
    await store.start_run_pg(
        {
            "run_id": "run-1",
            "agent_id": "agent-a",
            "session_id": "s-1",
            "user_id": "u-1",
            "channel": "console",
            "source": "chat",
            "environment": "online",
            "query_preview": "帮我排查",
            "started_at": started,
            "model": "qwen-max",
            "version": "1.0",
        },
        engine=pg_engine,
    )
    sid_llm = "span-llm-1"
    await store.append_span_pg(
        {
            "run_id": "run-1",
            "span_id": sid_llm,
            "parent_span_id": None,
            "kind": "llm",
            "name": "qwen-max",
            "started_at": started + 0.1,
            "ended_at": started + 1.1,
            "duration_ms": 1000,
            "input_json": '{"message_count": 3}',
            "output_json": '{"blocks": []}',
            "tokens": 42,
        },
        engine=pg_engine,
    )
    await store.append_span_pg(
        {
            "run_id": "run-1",
            "span_id": "span-tool-1",
            "parent_span_id": sid_llm,
            "kind": "tool",
            "name": "bash",
            "started_at": started + 1.2,
            "ended_at": started + 1.5,
            "duration_ms": 300,
            "input_json": '{"command": "ls"}',
            "output_json": '"files"',
        },
        engine=pg_engine,
    )
    await store.finish_run_pg(
        "run-1",
        status="success",
        finished_at=started + 6,
        duration_ms=6000,
        total_tokens=55,
        engine=pg_engine,
    )

    trace = await store.get_run_trace_pg("run-1", engine=pg_engine)
    assert trace is not None
    assert trace["status"] == "success"
    assert trace["total_tokens"] == 55
    kinds = [span["kind"] for span in trace["spans"]]
    assert kinds == ["llm", "tool"]
    tool_span = trace["spans"][1]
    assert tool_span["parent_span_id"] == sid_llm
    assert tool_span["name"] == "bash"
    assert isinstance(trace["started_at"], float)


async def test_query_filters_and_pagination(pg_engine, _clean):
    """Agent/status/keyword filters + newest-first ordering."""
    base = time.time() - 60
    for i, (agent, status_kw) in enumerate(
        [
            ("agent-a", "success"),
            ("agent-a", "failed"),
            ("agent-b", "success"),
        ],
    ):
        run_id = f"run-{i}"
        await store.start_run_pg(
            {
                "run_id": run_id,
                "agent_id": agent,
                "query_preview": f"query {run_id}",
                "started_at": base + i,
            },
            engine=pg_engine,
        )
        await store.finish_run_pg(
            run_id,
            status=status_kw,
            finished_at=base + i + 1,
            duration_ms=1000,
            total_tokens=i,
            engine=pg_engine,
        )

    items, total = await store.query_run_logs_pg(
        agent_id="agent-a",
        engine=pg_engine,
    )
    assert total == 2
    assert [item["run_id"] for item in items] == ["run-1", "run-0"]

    items, total = await store.query_run_logs_pg(
        agent_id="agent-a",
        status="failed",
        engine=pg_engine,
    )
    assert total == 1 and items[0]["run_id"] == "run-1"

    items, total = await store.query_run_logs_pg(
        keyword="run-2",
        engine=pg_engine,
    )
    assert total == 1 and items[0]["agent_id"] == "agent-b"

    items, total = await store.query_run_logs_pg(limit=1, engine=pg_engine)
    assert total == 3 and len(items) == 1 and items[0]["run_id"] == "run-2"


async def test_purge_old_runs(pg_engine, _clean):
    """Only runs older than the retention window are removed."""
    from sqlalchemy import text

    old = time.time() - 40 * 86400
    await store.start_run_pg(
        {"run_id": "run-old", "agent_id": "a", "started_at": old},
        engine=pg_engine,
    )
    await store.start_run_pg(
        {
            "run_id": "run-new",
            "agent_id": "a",
            "started_at": time.time(),
        },
        engine=pg_engine,
    )
    await store.append_span_pg(
        {
            "run_id": "run-old",
            "span_id": "span-old",
            "kind": "llm",
            "started_at": old,
            "ended_at": old + 1,
        },
        engine=pg_engine,
    )

    removed = await store.purge_old_runs(days=30, engine=pg_engine)
    assert removed == 1

    assert await store.get_run_trace_pg("run-old", engine=pg_engine) is None
    assert await store.get_run_trace_pg("run-new", engine=pg_engine) is not None
    async with pg_engine.connect() as conn:
        left = (
            await conn.execute(
                text("SELECT COUNT(*) FROM agent_run_spans"),
            )
        ).scalar()
    assert left == 0
