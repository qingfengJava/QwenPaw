# -*- coding: utf-8 -*-
"""有界就绪调度与生命周期纯函数单元测试（专家团 T5）。

覆盖（无 PG，纯内存）：

1. ``ready_nodes``：依赖判定/顺序稳定/未知依赖保守处理；
2. ``BoundedDispatcher``：容量约束/完成驱动取出/drain/cancel_all；
3. ``drifted_members``：版本漂移判定（未钉版本不参与）；
4. ``recovery_class``：协议8.4 恢复分类表；
5. ``_check_time_budget``：累计基数 + 本段耗时的熔断判定。

@author qingfeng
"""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.app.workforce.contracts import DagNode, DagPlan
from qwenpaw.app.workforce.scheduler import (
    BoundedDispatcher,
    ready_nodes,
)
from qwenpaw.app.workforce.lifecycle import (
    RECOVERY_FRESH,
    RECOVERY_RECONCILE,
    RECOVERY_RETRY,
    RECOVERY_VERIFY,
    drifted_members,
    recovery_class,
)


def _plan(node_defs):
    """按 [(key, deps)] 构建 DagPlan（objective 占位）。"""
    return DagPlan(
        nodes=[
            DagNode(node_key=key, deps=deps, objective=f"do {key}")
            for key, deps in node_defs
        ],
        source="orchestration",
    )


# ---------------------------------------------------------------------------
# 1. ready_nodes
# ---------------------------------------------------------------------------


def test_ready_nodes_dep_semantics_and_order():
    """依赖全部 done 才就绪；输出按 plan 顺序稳定；未知依赖不派发。"""
    plan = _plan(
        [
            ("a", []),
            ("b", ["a"]),
            ("c", ["a"]),
            ("d", ["b", "c"]),
            ("e", ["ghost"]),
        ]
    )
    states = [
        {"node_key": "a", "status": "pending"},
        {"node_key": "b", "status": "pending"},
        {"node_key": "c", "status": "pending"},
        {"node_key": "d", "status": "pending"},
        {"node_key": "e", "status": "pending"},
    ]
    # 首轮：仅无依赖的 a 就绪
    assert ready_nodes(plan.nodes, states) == ["a"]
    # a 完成：b/c 按顺序就绪（d 依赖未全齐、e 依赖未知节点）
    states[0]["status"] = "done"
    assert ready_nodes(plan.nodes, states) == ["b", "c"]
    # b、c 完成：d 就绪
    states[1]["status"] = "done"
    states[2]["status"] = "done"
    assert ready_nodes(plan.nodes, states) == ["d"]
    # 非 pending（在途）不重复派发
    states[3]["status"] = "delegated"
    assert ready_nodes(plan.nodes, states) == []


# ---------------------------------------------------------------------------
# 2. BoundedDispatcher
# ---------------------------------------------------------------------------


async def test_dispatcher_capacity_and_completion_driven():
    """容量满载拒绝提交；完成一个立即取出释放调度位。"""
    dispatcher = BoundedDispatcher(limit=2)
    gate = asyncio.Event()

    async def blocker():
        await gate.wait()

    async def instant():
        return "ok"

    # 两个在途占满容量，第三个提交被拒
    assert dispatcher.submit("a", blocker) is True
    assert dispatcher.submit("b", blocker) is True
    assert dispatcher.submit("c", blocker) is False
    assert dispatcher.full and dispatcher.in_flight == 2
    assert dispatcher.keys == {"a", "b"}
    # 提交即时完成任务后，wait_completed 返回该任务并移出集合
    assert dispatcher.submit("c", instant) is False
    gate.set()
    done = await dispatcher.wait_completed()
    keys = {k for k, _t in done}
    assert keys == {"a", "b"}
    assert all(t.result() is None for _k, t in done)
    assert dispatcher.in_flight == 0
    # 空集等待属编程错误
    with pytest.raises(RuntimeError):
        await dispatcher.wait_completed()


async def test_dispatcher_collects_results_and_exceptions():
    """完成任务的异常留在 task 上（调用方检视），成功值可读。"""
    dispatcher = BoundedDispatcher(limit=3)

    async def ok():
        return 42

    async def boom():
        raise ValueError("x")

    dispatcher.submit("ok", ok)
    dispatcher.submit("bad", boom)
    done = await dispatcher.wait_completed()
    assert len(done) == 2
    by_key = dict(done)
    assert by_key["ok"].result() == 42
    assert isinstance(by_key["bad"].exception(), ValueError)


async def test_dispatcher_drain_and_cancel_all():
    """drain 等全部收敛；cancel_all 取消在途且可归因到节点键。"""
    dispatcher = BoundedDispatcher(limit=4)

    async def slow():
        await asyncio.sleep(30)

    async def quick():
        await asyncio.sleep(0.01)

    dispatcher.submit("slow", slow)
    dispatcher.submit("quick", quick)
    drained = await dispatcher.drain()
    assert {k for k, _t in drained} == {"slow", "quick"}
    assert dispatcher.empty

    # cancel_all：挂起任务被取消且返回 (key, task) 对
    dispatcher.submit("b1", slow)
    dispatcher.submit("b2", slow)
    cancelled = await dispatcher.cancel_all()
    assert {k for k, _t in cancelled} == {"b1", "b2"}
    for _k, task in cancelled:
        assert task.cancelled()
    assert dispatcher.empty


# ---------------------------------------------------------------------------
# 3. drifted_members / recovery_class
# ---------------------------------------------------------------------------


def test_drifted_members_comparison_semantics():
    """钉住版本与实际版本不一致才漂移；未钉版本/已删除成员不参与。"""
    pinned = {"m1": 1, "m2": 3, "m3": 2}
    live = {"m1": 1, "m2": 4, "m3": 2}
    drift = drifted_members(pinned, live)
    assert drift == [
        {"expert_id": "m2", "pinned_version": 3, "live_version": 4}
    ]
    # live 中不存在的成员（已删除）不误报
    assert drifted_members({"ghost": 1}, {}) == []
    # 无钉版本：空集合（旧 run 向后兼容）
    assert drifted_members({}, live) == []


def test_recovery_class_table():
    """协议8.4 恢复分类：verify > reconcile > retry/fresh。"""
    # 结果已持久化但未验收 → 继续验收
    assert (
        recovery_class({"status": "verifying", "result": {"text": "x"}}, False)
        == RECOVERY_VERIFY
    )
    # 在途外部动作优先于一切中间态 → 先核对
    assert recovery_class({"status": "delegated"}, True) == RECOVERY_RECONCILE
    assert recovery_class({"status": "verifying", "result": {}}, True) == (
        RECOVERY_RECONCILE
    )
    # 无结果中间态 → 有限重试；pending → 全新派发
    assert recovery_class({"status": "delegated"}, False) == RECOVERY_RETRY
    assert recovery_class({"status": "pending"}, False) == RECOVERY_FRESH


# ---------------------------------------------------------------------------
# 4. _check_time_budget（累计基数语义）
# ---------------------------------------------------------------------------


def test_time_budget_uses_cumulative_base():
    """时间熔断 = 累计基数 + 本段耗时；基数恢复不清零。"""
    import time as time_mod

    from qwenpaw.app.workforce.engine import EscalateSignal, _check_time_budget

    policy = type("P", (), {"max_total_seconds": 100})()
    # 本段刚起算 + 基数 90 → 未超限（等于上限也不熔断，本段仍可收尾）
    start = time_mod.monotonic()
    _check_time_budget(start, policy, base_seconds=90)
    _check_time_budget(start, policy, base_seconds=100)
    # 基数已超上限（101 > 100）→ 熔断
    with pytest.raises(EscalateSignal):
        _check_time_budget(start, policy, base_seconds=101)
    # 不限时（0）直接放行
    open_policy = type("P", (), {"max_total_seconds": 0})()
    _check_time_budget(start, open_policy, base_seconds=10**9)
