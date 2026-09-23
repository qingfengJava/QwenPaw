# -*- coding: utf-8 -*-
"""Integration tests for open API governance (idempotency + audit).

Cover against a real PostgreSQL:
  - idempotency roundtrip: store → hit replay (same fingerprint),
    fingerprint mismatch → IdempotencyConflict, fresh key → None
  - overwrite semantics: same key re-execution refreshes cached response
  - audit write + list: key/expert filters and ordering
  - best-effort audit: write failure never raises

Runs only when ``QWENPAW_TEST_PG_DSN`` is set.

⚠️ 本机测试库与真实库同库：全部测试数据用 ``captest_`` 前缀的显式
ID/键创建，夹具按前缀定点清理，绝不触碰存量业务数据。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

# 定点清理（仅 captest_ 前缀；逐条静态语句，零插值）
_CLEANUP_STATEMENTS = (
    "DELETE FROM open_api_idempotency WHERE key_id LIKE 'captest_%'",
    "DELETE FROM open_api_audit WHERE key_id LIKE 'captest_%'",
)


@pytest.fixture
async def enterprise_env(monkeypatch):
    """Bootstrap the enterprise schema (applies alembic), then clean
    only this module's ``captest_``-prefixed rows."""
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
        yield
    finally:
        async with engine.begin() as conn:
            for statement in _CLEANUP_STATEMENTS:
                await conn.execute(text(statement))
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


@pytest.mark.asyncio
async def test_idempotency_roundtrip_replay(enterprise_env):
    """存 → 同指纹查命中回放；未存键查返回 None."""
    from qwenpaw.app.experts.openapi_governance import get_open_governance

    gov = get_open_governance()
    fresh = await gov.check_idempotency("captest_key1", "idem-a", "fp-a")
    assert fresh is None

    await gov.store_idempotent_response(
        "captest_key1",
        "idem-a",
        "fp-a",
        200,
        {"task_id": "captest-t1", "answer": "ok"},
    )
    cached = await gov.check_idempotency("captest_key1", "idem-a", "fp-a")
    assert cached is not None
    assert cached["status_code"] == 200
    assert cached["response"]["task_id"] == "captest-t1"


@pytest.mark.asyncio
async def test_idempotency_fingerprint_conflict(enterprise_env):
    """同键不同指纹 → IdempotencyConflict（409 语义）."""
    from qwenpaw.app.experts.openapi_governance import (
        IdempotencyConflict,
        get_open_governance,
    )

    gov = get_open_governance()
    await gov.store_idempotent_response(
        "captest_key1",
        "idem-b",
        "fp-b1",
        200,
        {"answer": "first"},
    )
    with pytest.raises(IdempotencyConflict):
        await gov.check_idempotency("captest_key1", "idem-b", "fp-other")


@pytest.mark.asyncio
async def test_idempotency_overwrite_refreshes(enterprise_env):
    """同键重新执行覆盖旧行（返回新响应、刷新指纹）."""
    from qwenpaw.app.experts.openapi_governance import get_open_governance

    gov = get_open_governance()
    await gov.store_idempotent_response(
        "captest_key2", "idem-c", "fp-old", 200, {"answer": "old"},
    )
    await gov.store_idempotent_response(
        "captest_key2", "idem-c", "fp-new", 200, {"answer": "new"},
    )
    cached = await gov.check_idempotency("captest_key2", "idem-c", "fp-new")
    assert cached is not None
    assert cached["response"]["answer"] == "new"


@pytest.mark.asyncio
async def test_idempotency_scope_is_per_key(enterprise_env):
    """幂等作用域=单密钥：不同 key 同幂等键互不可见."""
    from qwenpaw.app.experts.openapi_governance import get_open_governance

    gov = get_open_governance()
    await gov.store_idempotent_response(
        "captest_key3", "idem-shared", "fp-k3", 200, {"owner": "k3"},
    )
    other = await gov.check_idempotency("captest_key4", "idem-shared", "fp-k3")
    assert other is None


@pytest.mark.asyncio
async def test_audit_write_and_filters(enterprise_env):
    """审计写入 + key/expert 过滤 + 倒序."""
    from qwenpaw.app.experts.openapi_governance import get_open_governance

    gov = get_open_governance()
    await gov.record_audit(
        method="POST",
        path="/api/open/experts/captest_emp/tasks",
        status_code=200,
        latency_ms=42,
        key_id="captest_audk1",
        expert_id="captest_emp",
        idem_key="idem-x",
        client_ip="127.0.0.1",
    )
    await gov.record_audit(
        method="GET",
        path="/api/open/experts/captest_emp",
        status_code=404,
        latency_ms=3,
        key_id="captest_audk2",
        expert_id="captest_emp",
        client_ip="127.0.0.1",
    )

    by_key = await gov.list_audit(key_id="captest_audk1")
    assert len(by_key) == 1
    assert by_key[0]["status_code"] == 200
    assert by_key[0]["idem_key"] == "idem-x"

    by_expert = await gov.list_audit(expert_id="captest_emp", limit=10)
    assert len(by_expert) >= 2
    assert {row["key_id"] for row in by_expert} >= {"captest_audk1", "captest_audk2"}

    empty = await gov.list_audit(key_id="captest_no_such")
    assert empty == []


@pytest.mark.asyncio
async def test_audit_write_never_raises(enterprise_env, monkeypatch):
    """审计失败仅告警：引擎异常不向外传播（best-effort 语义）."""
    from qwenpaw.app.experts import openapi_governance as gov_mod

    gov = gov_mod.OpenGovernance()
    monkeypatch.setattr(
        gov_mod,
        "require_enterprise_engine",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # 不抛异常即通过（失败被吞，仅 log warning）
    await gov.record_audit(
        method="GET",
        path="/api/open/experts/x",
        status_code=500,
        latency_ms=1,
        key_id="captest_audfail",
    )
