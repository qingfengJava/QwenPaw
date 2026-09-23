# -*- coding: utf-8 -*-
"""业务动作账本测试（专家团 T4：外部动作幂等与恢复）。

覆盖：

1. **登记/执行闭环**（PG）：先落库后执行；同 action_key 重放命中
   既有记录（created=False）——外部副作用不重复发生；
2. **状态机**（PG）：registered → executed | failed；failed →
   reverted；终态幂等不变更；
3. **中断恢复**（PG）：recover_pending 只回收 registered（置
   reverted 留痕），executed/failed 不受影响；
4. **跨租户隔离**（PG）：org 上下文绑定的行对其他租户不可见。

@author qingfeng
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_TRUNCATE_SQL = (
    "TRUNCATE team_run_budget_reservations, team_run_actions, "
    "team_run_events, team_run_attempts, team_run_revisions, "
    "team_run_nodes, team_runs, feed_events, project_members, tasks, "
    "projects, expert_team_members, expert_skills, published_experts, "
    "expert_teams, experts, employee_governance, token_usage_events "
    "RESTART IDENTITY"
)


@pytest.fixture
async def enterprise_env(monkeypatch):
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
        await conn.execute(text(_TRUNCATE_SQL))
    try:
        yield
    finally:
        # dispose：释放池内 asyncpg 连接（pytest-asyncio 每用例新 loop）
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


async def _register(ledger, run_id="run-1", key="email.send:1", **kwargs):
    """登记一个默认动作（类型/节点/载荷可覆盖）。"""
    return await ledger.register_action(
        run_id=run_id,
        node_key=kwargs.pop("node_key", "task-1"),
        attempt_id=kwargs.pop("attempt_id", "att-1"),
        action_type=kwargs.pop("action_type", "external_email"),
        action_key=key,
        envelope=kwargs.pop("envelope", None),
        payload=kwargs.pop("payload", {"to": "ops@example.com"}),
    )


async def test_action_register_execute_roundtrip(enterprise_env):
    """登记 → 执行 → 重放命中：外部副作用只发生一次，结果可复用。"""
    from qwenpaw.app.workforce import action_ledger as ledger

    # 首次登记：created=True，状态 registered（先落库后执行）
    first = await _register(ledger)
    assert first["created"] is True
    assert first["status"] == "registered"
    assert first["action_id"]

    # 重放（同 run 同 key）：幂等命中既有登记——调用方不得重复执行
    replay = await _register(ledger, payload={"to": "other@example.com"})
    assert replay["created"] is False
    assert replay["action_id"] == first["action_id"]
    assert replay["status"] == "registered"
    assert replay["result"] == {}

    # 执行成功：registered → executed（结果落账）
    assert await ledger.mark_executed(
        first["action_id"], {"message_id": "m-1", "ok": True}
    ) is True
    row = await ledger.get_by_action_key("run-1", "email.send:1")
    assert row is not None
    assert row["status"] == "executed"
    assert row["result"] == {"message_id": "m-1", "ok": True}
    assert row["action_type"] == "external_email"
    assert row["node_key"] == "task-1"

    # 已执行后再次重放：created=False + status=executed（可直接复用 result）
    replay2 = await _register(ledger)
    assert replay2["created"] is False
    assert replay2["status"] == "executed"
    assert replay2["result"] == {"message_id": "m-1", "ok": True}

    # 终态幂等：再次 mark_* 不变更（executed 是终态）
    assert await ledger.mark_failed(first["action_id"], "late error") is False
    row = await ledger.get_by_action_key("run-1", "email.send:1")
    assert row["status"] == "executed"
    assert row["error"] == ""

    # 查询安全：未知 key → None；run 列表可见全部登记
    assert await ledger.get_by_action_key("run-1", "ghost") is None
    rows = await ledger.list_by_run("run-1")
    assert [r["action_key"] for r in rows] == ["email.send:1"]


async def test_action_failed_then_reverted(enterprise_env):
    """failed 可回收为 reverted；reverted 是终态。"""
    from qwenpaw.app.workforce import action_ledger as ledger

    reg = await _register(ledger, key="ticket.create:1")
    assert await ledger.mark_failed(reg["action_id"], "SMTP 5xx") is True
    row = await ledger.get_by_action_key("run-1", "ticket.create:1")
    assert row["status"] == "failed"
    assert row["error"] == "SMTP 5xx"
    assert row["result"] == {}

    # failed → reverted（人工处置/撤权语义）
    assert await ledger.mark_reverted(reg["action_id"], "人工撤回") is True
    row = await ledger.get_by_action_key("run-1", "ticket.create:1")
    assert row["status"] == "reverted"
    assert row["error"] == "人工撤回"

    # reverted 是终态：不可再推进
    assert await ledger.mark_executed(reg["action_id"], {}) is False
    assert await ledger.mark_failed(reg["action_id"], "again") is False


async def test_recover_pending_sweeps_only_registered(enterprise_env):
    """中断恢复：只回收 registered（置 reverted），executed/failed 不动。"""
    from qwenpaw.app.workforce import action_ledger as ledger

    a = await _register(ledger, key="k1")
    b = await _register(ledger, key="k2", run_id="run-2")
    c = await _register(ledger, key="k3", run_id="run-2")
    d = await _register(ledger, key="k4", run_id="run-2")
    # k2 执行成功、k3 执行失败（均非 registered，恢复不得触碰）
    assert await ledger.mark_executed(b["action_id"], {"ok": True}) is True
    assert await ledger.mark_failed(c["action_id"], "boom") is True

    # run-2 恢复：仅 1 个 registered（k4）被回收
    swept = await ledger.recover_pending("run-2", reason="run interrupted")
    assert swept == 1
    assert (await ledger.get_by_action_key("run-2", "k4"))["status"] == (
        "reverted"
    )
    assert (await ledger.get_by_action_key("run-2", "k2"))["status"] == (
        "executed"
    )
    assert (await ledger.get_by_action_key("run-2", "k3"))["status"] == "failed"
    # run-1 不受影响（恢复按 run 隔离）
    assert (await ledger.get_by_action_key("run-1", "k1"))["status"] == (
        "registered"
    )
    # 重复恢复幂等：无 registered 可回收 → 0
    assert await ledger.recover_pending("run-2") == 0

    # 回收后同 key 可重新登记（reverted 不占用幂等键语义——恢复留痕
    # 由 reverted 行承担，重放走新登记）
    again = await _register(ledger, key="k4", run_id="run-2")
    assert again["created"] is True


async def test_cross_tenant_isolation(enterprise_env):
    """org 上下文绑定的动作行对其他租户不可见（行级隔离硬边界）。"""
    from qwenpaw.app import enterprise as ent_mod
    from qwenpaw.app.workforce import action_ledger as ledger

    # org-b 登记动作
    ent_mod.set_current_org_id("org-b")
    try:
        reg = await _register(ledger, key="k-b")
        assert reg["created"] is True
        rows_b = await ledger.list_by_run("run-1")
        assert [r["action_key"] for r in rows_b] == ["k-b"]
    finally:
        ent_mod.set_current_org_id(None)

    # 默认租户视角：不可见 org-b 的登记（跨租户硬隔离）
    assert await ledger.get_by_action_key("run-1", "k-b") is None
    assert await ledger.list_by_run("run-1") == []
    # 默认租户同 key 登记：互不冲突（唯一约束含 tenant_id）
    reg_default = await _register(ledger, key="k-b")
    assert reg_default["created"] is True
    assert reg_default["action_id"] != reg["action_id"]
