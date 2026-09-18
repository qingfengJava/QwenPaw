# -*- coding: utf-8 -*-
"""Integration tests for the cron ledger convergence Phase 1 (T13a).

对真实 PostgreSQL（5433 隔离库）验证 cron 双表 EXPAND 补列（alembic
0040 / changelog 20260918/03）：

- ``cron_job_history`` 明细列（result_summary/run_id/session_id/
  scheduled_for）INSERT/SELECT 真实往返；
- ``cron_jobs.run_count`` 随 append_history 同事务 +1（决策 D3，
  不受 50 条修剪窗截断）；
- 旧式空记录读出归一 None（与 json 平面 model_dump 同形）。

仅在 ``QWENPAW_TEST_PG_DSN`` 设置时运行；数据用 ``captest_`` 前缀
定点清理，绝不触碰存量业务数据。

@author qingfeng
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_AGENT = "captest_cron_expand"

# 定点清理（仅本用例 agent；逐条静态语句，零插值）
_CLEANUP_STATEMENTS = (
    "DELETE FROM cron_job_history WHERE agent_id = 'captest_cron_expand'",
    "DELETE FROM cron_jobs WHERE agent_id = 'captest_cron_expand'",
)

_SELECT_RUN_COUNT = (
    "SELECT run_count FROM cron_jobs "
    "WHERE agent_id = 'captest_cron_expand' AND job_id = 'ct-j1'"
)


@pytest.fixture
async def cron_engine(monkeypatch):
    """Bootstrap schema to head (incl 0040), clean captest_ rows."""
    if not DSN:
        pytest.skip("QWENPAW_TEST_PG_DSN not set")
    monkeypatch.setenv("QWENPAW_PG_DSN", DSN)

    from qwenpaw.app import enterprise as ent_mod
    from qwenpaw.db import engine as engine_mod

    engine_mod._engines.clear()
    ent_mod._schema_ready = False
    ok = await ent_mod.bootstrap_enterprise()
    assert ok, "enterprise bootstrap failed against the test database"
    engine = engine_mod.create_pg_engine(DSN)
    async with engine.begin() as conn:
        for statement in _CLEANUP_STATEMENTS:
            await conn.execute(text(statement))
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            for statement in _CLEANUP_STATEMENTS:
                await conn.execute(text(statement))
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


def _repo(engine, tmp_path):
    """One PG repository bound to the captest agent plane."""
    from qwenpaw.app.crons.repo.pg_repo import PgJobRepository

    return PgJobRepository(
        agent_id=_AGENT,
        jobs_path=tmp_path / "jobs.json",
        engine=engine,
    )


def _spec(job_id: str = "ct-j1"):
    """One minimal agent cron job spec for the expand round-trip."""
    from qwenpaw.app.crons.models import (
        CronJobRequest,
        CronJobSpec,
        DispatchSpec,
        DispatchTarget,
        JobRuntimeSpec,
        ScheduleSpec,
    )

    return CronJobSpec(
        id=job_id,
        name="captest expand job",
        schedule=ScheduleSpec(type="cron", cron="0 9 * * *"),
        task_type="agent",
        request=CronJobRequest(input="ping"),
        dispatch=DispatchSpec(
            target=DispatchTarget(user_id="u1", session_id="console:u1"),
        ),
        runtime=JobRuntimeSpec(),
    )


async def _run_count(engine) -> int:
    """Read the redundant run counter straight from cron_jobs."""
    async with engine.connect() as conn:
        return (await conn.execute(text(_SELECT_RUN_COUNT))).scalar_one()


@pytest.mark.asyncio
async def test_history_detail_columns_roundtrip(cron_engine, tmp_path):
    """明细四列真实落库回读；空记录归一 None；run_count 精确累计。"""
    from qwenpaw.app.crons.models import CronExecutionRecord

    repo = _repo(cron_engine, tmp_path)
    await repo.upsert_job(_spec())

    run_at = datetime(2030, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    await repo.append_history(
        "ct-j1",
        CronExecutionRecord(
            run_at=run_at,
            status="success",
            trigger="scheduled",
            run_id="run-1",
            session_id="cron:ct-j1",
            result_summary="摘要文本",
            scheduled_for=run_at,
        ),
    )
    history = await repo.get_history("ct-j1")
    assert len(history) == 1
    rec = history[0]
    assert rec.result_summary == "摘要文本"
    assert rec.run_id == "run-1"
    assert rec.session_id == "cron:ct-j1"
    assert rec.scheduled_for == run_at
    # run_count 与 history 同事务 +1（决策 D3）
    assert await _run_count(cron_engine) == 1

    # 第二条旧式空记录：读出归一 None，计数继续累计
    await repo.append_history(
        "ct-j1",
        CronExecutionRecord(
            run_at=datetime(2030, 1, 2, 9, 0, 0, tzinfo=timezone.utc),
            status="error",
            error="boom",
            trigger="manual",
        ),
    )
    history = await repo.get_history("ct-j1")
    assert history[0].result_summary is None
    assert history[0].scheduled_for is None
    assert history[1].result_summary == "摘要文本"
    assert await _run_count(cron_engine) == 2


@pytest.mark.asyncio
async def test_history_seq_monotonic_under_expand(cron_engine, tmp_path):
    """补列后 seq 幂等锚语义不变：连续追加单调、新→旧读取。"""
    from qwenpaw.app.crons.models import CronExecutionRecord

    repo = _repo(cron_engine, tmp_path)
    await repo.upsert_job(_spec("ct-j2"))
    base = datetime(2030, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        await repo.append_history(
            "ct-j2",
            CronExecutionRecord(
                run_at=base.replace(minute=i),
                status="success",
                trigger="scheduled",
                scheduled_for=base.replace(minute=i),
            ),
        )
    history = await repo.get_history("ct-j2")
    assert [r.run_at for r in history] == [
        base.replace(minute=2),
        base.replace(minute=1),
        base.replace(minute=0),
    ]
    # scheduled_for 逐条随槽位落库（trigger=scheduled 语义）
    assert all(r.scheduled_for == r.run_at for r in history)
