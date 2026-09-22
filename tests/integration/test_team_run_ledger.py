# -*- coding: utf-8 -*-
"""Team run ledger integration tests（专家团运行账本 T2）。

覆盖三层：

1. **投影纯函数**（无 PG）：allowed_actions / waiting_reason /
   build_run_view 的动作权限与组合语义；
2. **账本 CRUD 往返**（``QWENPAW_TEST_PG_DSN``）：修订/尝试/事件/
   预算预留的落库、幂等与结算记账闭环（不双计）；
3. **引擎全路径账本**（LLM 接缝桩）：done 路径产生尝试/事件/计划
   修订；Re-plan 路径留下 plan v1/v2 + 旧图快照（重规划不删历史）。

@author qingfeng
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_TRUNCATE_SQL = (
    "TRUNCATE team_run_budget_reservations, team_run_events, "
    "team_run_attempts, team_run_revisions, team_run_nodes, team_runs, "
    "feed_events, project_members, tasks, projects, expert_team_members, "
    "expert_skills, published_experts, expert_teams, experts, "
    "employee_governance, token_usage_events RESTART IDENTITY"
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


@pytest.fixture
def run_store():
    from qwenpaw.app.workforce.run_store import get_run_store

    return get_run_store()


async def _seed_team(name: str = "账本测试团"):
    """建一个 draft 团队 + 两名成员专家（engine 不校验 published 状态）。"""
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore

    expert_store = ExpertStore()
    lead = await expert_store.create_expert(
        name="账本负责人", icon="🧭", description="lead"
    )
    member = await expert_store.create_expert(
        name="账本成员", icon="🎨", description="member"
    )
    team = await expert_store.create_team(
        name=name,
        description="T2 账本测试团队",
        mode="router",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, seq=1),
        ],
    )
    return team, lead, member


def _two_node_plan(lead_id: str, member_id: str, member_key: str = "task-1"):
    """两节点 DAG：member 任务节点 → final 汇总节点（lead 自执行）。"""
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan

    return DagPlan(
        nodes=[
            DagNode(
                node_key=member_key,
                deps=[],
                assignee_expert_id=member_id,
                node_type="task",
                objective="产出前端方案",
                expected_output=["结构化方案"],
            ),
            DagNode(
                node_key="final-summary",
                deps=[member_key],
                node_type="final",
                objective="汇总全部上游结果",
            ),
        ],
        source="orchestration",
    )


def _ok_result(text: str = "已完成") -> "ResultContract":  # noqa: F821
    from qwenpaw.app.workforce.contracts import RESULT_STATUS_COMPLETED, ResultContract

    return ResultContract(
        status=RESULT_STATUS_COMPLETED,
        result={"text": text},
        result_text=text,
        # 桩回执模拟真实 usage 采集（账本断言 usage_reported=True）
        token_cost=7,
        usage_reported=True,
    )


def _fail_kind_verdict(contract, kind: str) -> "Verdict":  # noqa: F821
    """构造带归因的 FAIL 裁决（Re-plan 用例共用）。"""
    from qwenpaw.app.workforce.contracts import VERDICT_FAIL, RepairContract
    from qwenpaw.app.workforce.verifier import Verdict

    return Verdict(
        VERDICT_FAIL,
        reason="上游产出与目标矛盾",
        repair=RepairContract(
            original_task=contract.task_id,
            issues=["上游架构产出与前端目标矛盾"],
            expected_change=["重新对齐上游"],
            preserve=[],
            acceptance=["与上游一致"],
            attempt=1,
        ),
        failure_kind=kind,
    )


def _patch_llm_seams(monkeypatch, plan, delegate_impl=None, verify_impl=None):
    """把 planner/delegator/verifier 三个 LLM 接缝替换为确定性桩。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.planner import PlanOutcome

    async def fake_plan_run(
        goal, team, members, bundle, member_skills=None, team_lessons=None
    ):
        return PlanOutcome(plan=plan, source="orchestration")

    async def fake_delegate(
        expert_id, contract, repair=None, session_id=None, timeout=None, envelope=None
    ):
        if delegate_impl is not None:
            return delegate_impl(expert_id, contract, repair)
        return _ok_result(f"{expert_id} 完成"), session_id or "sess_1"

    async def fake_verify(
        lead_id, contract, result, policy, repair_count=0, previous_repair=None
    ):
        if verify_impl is not None:
            return verify_impl(lead_id, contract, result, repair_count)
        from qwenpaw.app.workforce.contracts import VERDICT_PASS
        from qwenpaw.app.workforce.verifier import Verdict

        return Verdict(VERDICT_PASS, reason="符合验收标准")

    async def fake_brain(to_agent, prompt, session_id=None, timeout=None):
        # result 必须是合法结构（ResultContract.result: Dict），否则触发
        # 解析降级 needs_review → 引擎质量门拦截升级人工
        payload = (
            '{"status":"COMPLETED","result":{"text":"最终汇总产出"},'
            '"result_text":"最终汇总产出"}'
        )
        return payload, session_id or "sess_brain", 0

    monkeypatch.setattr(engine_mod, "plan_run", fake_plan_run)
    monkeypatch.setattr(engine_mod, "delegate", fake_delegate)
    monkeypatch.setattr(engine_mod, "verify", fake_verify)
    monkeypatch.setattr(engine_mod, "call_expert_text", fake_brain)


# ---------------------------------------------------------------------------
# 1. 投影纯函数（无 PG）
# ---------------------------------------------------------------------------


def test_projection_allowed_actions_and_waiting():
    """动作权限/等待原因由服务端唯一口径推导（前端不自创授权规则）。"""
    from qwenpaw.app.workforce.contracts import (
        RUN_STATUS_AWAITING_CONFIRM,
        RUN_STATUS_DONE,
        RUN_STATUS_INTERRUPTED,
        RUN_STATUS_RUNNING,
        WAIT_REASON_REQUIREMENT_CONFIRM,
    )
    from qwenpaw.app.workforce.projection import allowed_actions, waiting_reason

    # 运行中：只允许取消
    assert allowed_actions(RUN_STATUS_RUNNING) == ["cancel"]
    # 等待确认：澄清 + 取消
    assert allowed_actions(RUN_STATUS_AWAITING_CONFIRM) == ["clarify", "cancel"]
    # 中断：续跑 + 取消
    assert allowed_actions(RUN_STATUS_INTERRUPTED) == ["resume", "cancel"]
    # 终态：无动作（历史只读）
    assert allowed_actions(RUN_STATUS_DONE) == []
    # 未知状态：保守为空（不放大权限）
    assert allowed_actions("ghost_status") == []
    # 等待原因：确认态 → requirement_confirm；终态 → 空
    assert (
        waiting_reason(RUN_STATUS_AWAITING_CONFIRM) == WAIT_REASON_REQUIREMENT_CONFIRM
    )
    assert waiting_reason(RUN_STATUS_DONE) == ""
    # 非终态但带澄清挂起标记 → 同样给等待原因
    assert waiting_reason(RUN_STATUS_RUNNING, clarification_pending=True) == (
        WAIT_REASON_REQUIREMENT_CONFIRM
    )


def test_projection_build_run_view_composition():
    """build_run_view：兼容字段 + 账本增量 + 服务端动作与进度摘要。"""
    from qwenpaw.app.workforce.projection import build_run_view

    run = {"id": "r1", "status": "running", "goal": "G"}
    nodes = [
        {"node_key": "a", "status": "done"},
        {"node_key": "b", "status": "delegated"},
        {"node_key": "c", "status": "pending"},
    ]
    view = build_run_view(
        run,
        nodes,
        attempts=[{"id": "att1"}],
        revisions=[{"kind": "plan", "revision": 1}],
    )
    # 兼容字段保留
    assert view["goal"] == "G"
    assert view["nodes"] == nodes
    # 服务端动作权限（running → cancel）
    assert view["allowed_actions"] == ["cancel"]
    # 进度摘要（一次遍历统计）
    assert view["progress"] == {
        "done_nodes": 1,
        "total_nodes": 3,
        "finished": False,
    }
    # 传入的账本增量投影下发，未传入的不伪造
    assert view["attempts"] == [{"id": "att1"}]
    assert view["revisions"] == [{"kind": "plan", "revision": 1}]
    assert "events" not in view


# ---------------------------------------------------------------------------
# 2. 账本 CRUD 往返（PG）
# ---------------------------------------------------------------------------


async def test_run_store_ledger_roundtrip(enterprise_env, run_store):
    """修订/尝试/事件的落库往返与幂等语义。"""
    team, _lead, member = await _seed_team()
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    run_id = run["id"]

    # ---- 修订：同主键重录不重复（ON CONFLICT DO NOTHING）----
    await run_store.record_revision(
        run_id, kind="plan", revision=1, reason="orchestration", payload={"n": 1}
    )
    await run_store.record_revision(
        run_id, kind="plan", revision=1, reason="dup", payload={"n": 1}
    )
    await run_store.record_revision(
        run_id, kind="plan", revision=2, reason="replan", payload={"n": 2}
    )
    await run_store.record_revision(
        run_id, kind="context", revision=5, reason="re-plan: 依赖变化"
    )
    revisions = await run_store.list_revisions(run_id)
    # 排序实现按 (kind, revision)；断言内容而非偶然顺序
    assert sorted(
        (r["kind"], r["revision"]) for r in revisions
    ) == [
        ("context", 5),
        ("plan", 1),
        ("plan", 2),
    ]
    # kind 过滤
    only_plan = await run_store.list_revisions(run_id, kind="plan")
    assert [r["revision"] for r in only_plan] == [1, 2]

    # ---- 尝试：started → completed（用量落账）----
    attempt_id = await run_store.record_attempt(
        run_id, "task-1", 1, expert_id=member.id, session_id="sess-a"
    )
    attempts = await run_store.list_attempts(run_id)
    assert len(attempts) == 1
    assert attempts[0]["status"] == "started"
    assert attempts[0]["usage_reported"] is False
    ok = await run_store.finish_attempt(
        attempt_id, "completed", token_cost=123, usage_reported=True
    )
    assert ok is True
    attempts = await run_store.list_attempts(run_id)
    assert attempts[0]["status"] == "completed"
    assert attempts[0]["token_cost"] == 123
    assert attempts[0]["usage_reported"] is True
    # 关闭不存在的尝试 → False（幂等安全）
    assert await run_store.finish_attempt("att_missing", "failed") is False
    # 节点过滤
    assert await run_store.list_attempts(run_id, node_key="task-1")
    assert not await run_store.list_attempts(run_id, node_key="ghost")

    # ---- 事件：seq 单调递增（持久账本回放）----
    fresh = await run_store.get_run(run_id)
    await run_store.emit_event(fresh, "evt_a", {"i": 1})
    await run_store.emit_event(fresh, "evt_b", {"i": 2})
    await run_store.emit_event(fresh, "evt_c", {"i": 3})
    events = await run_store.list_events(run_id)
    assert [e["kind"] for e in events] == ["evt_a", "evt_b", "evt_c"]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


async def test_budget_reservation_no_double_count(enterprise_env, run_store):
    """预留记账闭环：预留即占额、结算后由节点行实际用量接棒（不双计）。"""
    from qwenpaw.app.workforce.budget import run_budget_usage

    team, lead, member = await _seed_team()
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    run_id = run["id"]
    # 物化两节点并给 task-1 写入已结算用量 100
    await run_store.save_plan(run_id, _two_node_plan(lead.id, member.id))
    await run_store.update_node(run_id, "task-1", token_cost=100)

    # 无预留：用量 = 节点行累计
    assert await run_budget_usage(run_store, run_id) == 100
    # 预留 300：预留即占额 → 400
    resv = await run_store.reserve_budget(run_id, "final-summary", 300, reason="委派前")
    assert await run_store.outstanding_tokens(run_id) == 300
    assert await run_budget_usage(run_store, run_id) == 400
    # 结算实际 100（节点行随后写入 100 的语义由引擎承担）：未决清零，
    # 用量回落到节点行累计——同一笔消耗不会被双计
    assert await run_store.settle_reservation(resv, 100) is True
    await run_store.update_node(run_id, "final-summary", token_cost=100)
    assert await run_store.outstanding_tokens(run_id) == 0
    assert await run_budget_usage(run_store, run_id) == 200
    # 释放分支：从未消耗的预留不计入
    resv2 = await run_store.reserve_budget(run_id, "final-summary", 50)
    assert await run_budget_usage(run_store, run_id) == 250
    assert await run_store.release_reservation(resv2) is True
    assert await run_budget_usage(run_store, run_id) == 200


# ---------------------------------------------------------------------------
# 3. 引擎全路径账本（LLM 接缝桩）
# ---------------------------------------------------------------------------


async def test_engine_full_path_writes_ledger(enterprise_env, run_store, monkeypatch):
    """done 全路径：尝试/事件/计划修订/投影动作完整入账。"""
    from qwenpaw.app.workforce import engine as engine_mod

    team, lead, member = await _seed_team()
    plan = _two_node_plan(lead.id, member.id)
    _patch_llm_seams(monkeypatch, plan)
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"

    # ---- 计划修订：首版计划 revision 1，快照含全部节点 ----
    revisions = await run_store.list_revisions(run["id"])
    plan_revs = [r for r in revisions if r["kind"] == "plan"]
    assert len(plan_revs) == 1
    assert plan_revs[0]["revision"] == 1
    assert plan_revs[0]["reason"] == "orchestration"
    assert [n["node_key"] for n in plan_revs[0]["payload"]["nodes"]] == [
        "task-1",
        "final-summary",
    ]

    # ---- 尝试账本：两节点各一次委派，全部 completed 且用量已明示 ----
    attempts = await run_store.list_attempts(run["id"])
    assert len(attempts) == 2
    by_node = {a["node_key"]: a for a in attempts}
    assert set(by_node) == {"task-1", "final-summary"}
    for att in attempts:
        assert att["status"] == "completed"
        assert att["usage_reported"] is True

    # ---- 持久事件：plan_ready / node_started / node_verdict 有序留痕 ----
    events = await run_store.list_events(run["id"])
    kinds = [e["kind"] for e in events]
    assert "plan_ready" in kinds
    assert kinds.count("node_started") == 2
    assert kinds.count("node_verdict") == 2
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    # ---- 投影：终态动作清空 + 进度 finished ----
    from qwenpaw.app.workforce.projection import build_run_view

    nodes = await run_store.list_nodes(run["id"])
    view = build_run_view(final, nodes, attempts=attempts, revisions=revisions)
    assert view["allowed_actions"] == []
    assert view["progress"]["finished"] is True
    assert view["progress"]["done_nodes"] == 2


async def test_engine_replan_records_revisions(enterprise_env, run_store, monkeypatch):
    """Re-plan 路径：plan v1/v2 修订留痕 + 旧图快照进入 context 修订。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import FAILURE_KIND_DEPENDENCY_CHANGED

    team, lead, member = await _seed_team()
    plan1 = _two_node_plan(lead.id, member.id, member_key="task-1")
    plan2 = _two_node_plan(lead.id, member.id, member_key="task-1-re")
    plan_calls = {"n": 0}

    async def seq_plan_run(goal, team_, members, bundle, **kwargs):
        # 每次重入规划交替产出 v1/v2（同一接缝桩覆盖两代计划）
        plan_calls["n"] += 1
        from qwenpaw.app.workforce.planner import PlanOutcome

        return PlanOutcome(
            plan=plan1 if plan_calls["n"] == 1 else plan2,
            source="orchestration",
        )

    # 验收序列：第 1 次（task-1）FAIL 归因 dependency_changed → Re-plan；
    # 之后（task-1-re / final）PASS
    verify_calls = {"n": 0}

    def seq_verify(lead_id, contract, result, repair_count):
        verify_calls["n"] += 1
        if verify_calls["n"] == 1:
            return _fail_kind_verdict(contract, FAILURE_KIND_DEPENDENCY_CHANGED)
        from qwenpaw.app.workforce.contracts import VERDICT_PASS
        from qwenpaw.app.workforce.verifier import Verdict

        return Verdict(VERDICT_PASS, reason="ok")

    _patch_llm_seams(monkeypatch, plan1, verify_impl=seq_verify)
    monkeypatch.setattr(engine_mod, "plan_run", seq_plan_run)
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"
    assert final["replan_count"] == 1

    # ---- 修订链：plan v1 + plan v2 + context（旧图快照）----
    revisions = await run_store.list_revisions(run["id"])
    plan_revs = [r for r in revisions if r["kind"] == "plan"]
    assert [(r["revision"]) for r in plan_revs] == [1, 2]
    assert [n["node_key"] for n in plan_revs[0]["payload"]["nodes"]] == [
        "task-1",
        "final-summary",
    ]
    assert [n["node_key"] for n in plan_revs[1]["payload"]["nodes"]] == [
        "task-1-re",
        "final-summary",
    ]
    # 旧图（被取代的 v1 完整快照）进入 context 修订 payload——节点行
    # 已被清空，账本里仍可回溯（重规划不删历史）
    ctx_revs = [r for r in revisions if r["kind"] == "context"]
    assert len(ctx_revs) == 1
    assert "re-plan" in ctx_revs[0]["reason"]
    superseded = ctx_revs[0]["payload"].get("superseded_plan") or {}
    assert [n["node_key"] for n in superseded.get("nodes", [])] == [
        "task-1",
        "final-summary",
    ]
    # 重规划事件持久留痕
    events = await run_store.list_events(run["id"])
    assert any(e["kind"] == "replan_started" for e in events)
