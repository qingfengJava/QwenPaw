# -*- coding: utf-8 -*-
"""Integration tests for the workforce orchestration domain (XianWork workforce).

Two layers, mirroring the enterprise-experts suite conventions:

1. **Pure contract tests** (no PG): DAG validation / topological waves /
   OrchestrationSpec strictness / ResultContract parse fallback / token
   budget escalation / intent rules / ContextBundle versioning.
2. **PG-backed engine tests** (``QWENPAW_TEST_PG_DSN``): run_store
   lifecycle + event bus, and the engine state machine full paths
   (done / repair→escalate / canceled / interrupted resume) with the
   LLM seams (planner / delegator / verifier) monkeypatched — the
   engine is asserted as pure scheduling over the contracts.

@author qingfeng
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_TRUNCATE_SQL = (
    "TRUNCATE team_run_nodes, team_runs, feed_events, project_members, "
    "tasks, projects, expert_team_members, expert_skills, "
    "published_experts, expert_teams, experts, token_usage_events "
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
        engine_mod._engines.clear()
        ent_mod._schema_ready = False


@pytest.fixture
def run_store():
    from qwenpaw.app.workforce.run_store import get_run_store

    return get_run_store()


async def _seed_team(name: str = "技术专家团"):
    """建一个 draft 团队 + 两名成员专家（engine 不校验 published 状态）。"""
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore

    expert_store = ExpertStore()
    lead = await expert_store.create_expert(
        name="技术专家", icon="🧭", description="lead"
    )
    member = await expert_store.create_expert(
        name="前端专家", icon="🎨", description="member"
    )
    team = await expert_store.create_team(
        name=name,
        description="测试团队",
        mode="router",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, seq=1),
        ],
    )
    return team, lead, member


def _two_node_plan(lead_id: str, member_id: str):
    """两节点 DAG：member 任务节点 → final 汇总节点（lead 自执行）。"""
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan

    return DagPlan(
        nodes=[
            DagNode(
                node_key="task-1",
                deps=[],
                assignee_expert_id=member_id,
                node_type="task",
                objective="产出前端方案",
                expected_output=["结构化方案"],
            ),
            DagNode(
                node_key="final-summary",
                deps=["task-1"],
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
    )


# ---------------------------------------------------------------------------
# 1. Pure contract tests (no PG)
# ---------------------------------------------------------------------------


def test_dag_validation_rejects_cycle_and_unknown_dep():
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan, validate_dag

    def plan(nodes):
        return DagPlan(nodes=[DagNode.model_validate(n) for n in nodes])

    # 合法两节点
    validate_dag(
        plan(
            [
                {"node_key": "a", "deps": [], "node_type": "task"},
                {"node_key": "b", "deps": ["a"], "node_type": "final"},
            ]
        )
    )
    # 环 → 拒绝
    with pytest.raises(ValueError):
        validate_dag(
            plan(
                [
                    {"node_key": "a", "deps": ["b"], "node_type": "task"},
                    {"node_key": "b", "deps": ["a"], "node_type": "task"},
                ]
            )
        )
    # 未知依赖 → 拒绝
    with pytest.raises(ValueError):
        validate_dag(
            plan([{"node_key": "a", "deps": ["ghost"], "node_type": "task"}])
        )
    # 重复 node_key → 拒绝
    with pytest.raises(ValueError):
        validate_dag(
            plan(
                [
                    {"node_key": "a", "deps": [], "node_type": "task"},
                    {"node_key": "a", "deps": [], "node_type": "task"},
                ]
            )
        )


def test_topological_waves_layering():
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan, topological_waves

    plan = DagPlan(
        nodes=[
            DagNode(node_key="a", deps=[], node_type="task"),
            DagNode(node_key="b", deps=[], node_type="task"),
            DagNode(node_key="c", deps=["a", "b"], node_type="task"),
            DagNode(node_key="d", deps=["c"], node_type="final"),
        ]
    )
    waves = topological_waves(plan)
    assert waves == [["a", "b"], ["c"], ["d"]]


def test_orchestration_spec_strict_schema():
    from qwenpaw.app.workforce.contracts import OrchestrationSpec

    # 合法模板
    spec = OrchestrationSpec.model_validate(
        {
            "nodes": [
                {"node_key": "a", "deps": [], "node_type": "task"},
                {"node_key": "f", "deps": ["a"], "node_type": "final"},
            ],
            "runtime_enabled": True,
        }
    )
    assert spec.runtime_enabled is True
    assert len(spec.nodes) == 2
    # 非法 node_type → pydantic 严格拒绝（不静默修复）
    with pytest.raises(Exception):
        OrchestrationSpec.model_validate(
            {"nodes": [{"node_key": "a", "deps": [], "node_type": "wizard"}]}
        )


def test_parse_result_contract_fallback_chain():
    from qwenpaw.app.workforce.contracts import ResultContract
    from qwenpaw.app.workforce.delegator import parse_result_contract

    # 合法裸 JSON（result 为自由结构 dict；status 域 COMPLETED/PARTIAL/FAILED）
    ok = parse_result_contract(
        '{"status":"COMPLETED","result":{"text":"R1"},"evidence":["e"]}', "t1"
    )
    assert ok.status == "COMPLETED"
    assert ok.needs_review is False
    # 围栏 JSON
    fenced = parse_result_contract(
        '```json\n{"status":"COMPLETED","result":{"text":"R2"}}\n```', "t2"
    )
    assert fenced.status == "COMPLETED"
    # 坏 JSON → 降级自由文本 + needs_review（绝不阻塞链路）
    raw = parse_result_contract("这不是 JSON，只是自由文本产出", "t3")
    assert isinstance(raw, ResultContract)
    assert raw.needs_review is True
    assert "自由文本" in (raw.result_text or str(raw.result))


def test_token_budget_escalation_signal():
    from qwenpaw.app.workforce.budget import check_token_budget
    from qwenpaw.app.workforce.contracts import RunPolicy
    from qwenpaw.app.workforce.engine import EscalateSignal

    # 0 = 不限
    check_token_budget(10**9, RunPolicy(max_total_tokens=0))
    # 未超限放行
    check_token_budget(100, RunPolicy(max_total_tokens=1000))
    # 超限 → 熔断信号
    with pytest.raises(EscalateSignal):
        check_token_budget(1001, RunPolicy(max_total_tokens=1000))


def test_intent_rule_classification():
    from qwenpaw.app.workforce.intent import (
        INTENT_COMPLEX,
        INTENT_SIMPLE,
        classify_by_rules,
    )

    # 多交付物 → complex
    assert classify_by_rules("帮我写一个方案和一份架构设计").intent == INTENT_COMPLEX
    # 跨专业协作 → complex
    assert (
        classify_by_rules("需要前端和后端配合完成").intent == INTENT_COMPLEX
    )
    # 编排动词 → complex
    assert classify_by_rules("请把这个需求拆解分工").intent == INTENT_COMPLEX
    # 简单问题：无规则信号 → None（交由 LLM 兜底；自动升级关闭时
    # classify() 保守按 simple 直答）；空文本直接 simple
    assert classify_by_rules("今天天气怎么样") is None
    assert classify_by_rules("   ").intent == INTENT_SIMPLE


def test_bundle_versioning_and_minimal_projection():
    from qwenpaw.app.workforce.bundle import (
        build_initial_bundle,
        bump,
        record_upstream_result,
        upstream_summaries,
    )
    from qwenpaw.app.workforce.contracts import DagNode

    bundle = build_initial_bundle("目标G", "团队T", [], "alice")
    assert bundle.version == 1
    # bump 产生新版本（不可变语义：原束不变）
    bumped = bump(bundle)
    assert bumped.version == 2
    assert bundle.version == 1
    # 上游摘要只投影 deps 声明的节点（最小充分，并行分支互不可见）
    b2 = record_upstream_result(bundle, "node-a", "A·产出", _ok_result("A结果"))
    b3 = record_upstream_result(b2, "node-b", "B·产出", _ok_result("B结果"))
    consumer = DagNode(node_key="c", deps=["node-a"], node_type="task")
    projection = upstream_summaries(b3, consumer)
    assert "node-a" in projection
    assert "node-b" not in projection


# ---------------------------------------------------------------------------
# 2. run_store lifecycle + events (PG required)
# ---------------------------------------------------------------------------


async def test_run_store_lifecycle_and_event_bus(enterprise_env, run_store):
    from qwenpaw.app.events.bus import get_event_bus
    from qwenpaw.app.workforce.contracts import (
        NODE_STATUS_PENDING,
        RUN_STATUS_RUNNING,
    )
    from qwenpaw.app.workforce.run_store import run_topic

    team, lead, member = await _seed_team()
    # 创建（planning 态）
    run = await run_store.create_run(
        team_id=team.id,
        goal="设计一个登录页",
        initiator_id="alice",
    )
    assert run["status"] == "planning"
    assert run["goal"] == "设计一个登录页"
    # 订阅 run topic（事件序列断言）
    from qwenpaw.enterprise import current_tenant_id

    tid = current_tenant_id()
    topic = run_topic(tid, run["id"])
    subscription = get_event_bus().subscribe(topic)
    events: list[dict] = []
    collector = asyncio.create_task(
        _drain_subscription(subscription, events)
    )
    await asyncio.sleep(0)
    # 物化 plan → 节点行生成
    await run_store.save_plan(run["id"], _two_node_plan(lead.id, member.id))
    nodes = await run_store.list_nodes(run["id"])
    assert {n["node_key"] for n in nodes} == {"task-1", "final-summary"}
    assert all(n["status"] == NODE_STATUS_PENDING for n in nodes)
    # 状态流转 + 节点更新 + repair 计数
    await run_store.set_run_status(run["id"], RUN_STATUS_RUNNING)
    await run_store.update_node(
        run["id"], "task-1", status="done", token_cost=42
    )
    await run_store.add_repair_count(run["id"])
    got = await run_store.get_run(run["id"])
    assert got["status"] == "running"
    assert got["repair_count"] == 1
    node = await run_store.get_node(run["id"], "task-1")
    assert node["status"] == "done"
    assert node["token_cost"] == 42
    # 发射事件 → 总线可观测
    await run_store.emit_event(got, "node_verdict", {"node_key": "task-1"})
    await asyncio.sleep(0.05)
    collector.cancel()
    kinds = [e["kind"] for e in events]
    assert "node_verdict" in kinds
    # 列表过滤
    mine = await run_store.list_runs(initiator_id="alice")
    assert any(r["id"] == run["id"] for r in mine)
    others = await run_store.list_runs(initiator_id="bob")
    assert not any(r["id"] == run["id"] for r in others)


async def _drain_subscription(subscription, sink: list[dict], max_events: int = 50):
    """把总线订阅排干到 sink（测试辅助）。"""
    async for bus_event in subscription:
        sink.append(bus_event.data)
        if len(sink) >= max_events:
            return


# ---------------------------------------------------------------------------
# 3. Engine state machine full paths (PG + monkeypatched LLM seams)
# ---------------------------------------------------------------------------


def _patch_llm_seams(monkeypatch, plan, delegate_impl=None, verify_impl=None):
    """把 planner/delegator/verifier 三个 LLM 接缝替换为确定性桩。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.planner import PlanOutcome

    async def fake_plan_run(goal, team, members, bundle):
        return PlanOutcome(plan=plan, source="orchestration")

    async def fake_delegate(expert_id, contract, repair=None, session_id=None, timeout=None):
        if delegate_impl is not None:
            return delegate_impl(expert_id, contract, repair)
        return _ok_result(f"{expert_id} 完成"), session_id or "sess_1"

    async def fake_verify(lead_id, contract, result, policy, repair_count=0, previous_repair=None):
        if verify_impl is not None:
            return verify_impl(lead_id, contract, result, repair_count)
        from qwenpaw.app.workforce.contracts import VERDICT_PASS
        from qwenpaw.app.workforce.verifier import Verdict

        return Verdict(VERDICT_PASS, reason="符合验收标准")

    async def fake_brain(to_agent, prompt, session_id=None, timeout=None):
        payload = '{"status":"done","result":"最终汇总产出","result_text":"最终汇总产出"}'
        return payload, session_id or "sess_brain", 0

    monkeypatch.setattr(engine_mod, "plan_run", fake_plan_run)
    monkeypatch.setattr(engine_mod, "delegate", fake_delegate)
    monkeypatch.setattr(engine_mod, "verify", fake_verify)
    monkeypatch.setattr(engine_mod, "call_expert_text", fake_brain)


async def test_engine_full_done_path(enterprise_env, run_store, monkeypatch):
    from qwenpaw.app.workforce import engine as engine_mod

    team, lead, member = await _seed_team()
    _patch_llm_seams(monkeypatch, _two_node_plan(lead.id, member.id))
    run = await run_store.create_run(
        team_id=team.id, goal="设计登录页", initiator_id="alice"
    )
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"
    assert "最终汇总产出" in (final["summary"] or "")
    # 节点全 done + 留痕（契约/结果/裁决）
    nodes = await run_store.list_nodes(run["id"])
    assert {n["status"] for n in nodes} == {"done"}
    task_node = next(n for n in nodes if n["node_key"] == "task-1")
    assert task_node["contract"], "契约 checkpoint 必须持久化"
    assert task_node["result"], "结果 checkpoint 必须持久化"
    assert task_node["verdict"] == "PASS"


async def test_engine_repair_then_escalate(enterprise_env, run_store, monkeypatch):
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import (
        RepairContract,
        RunPolicy,
        VERDICT_FAIL,
    )
    from qwenpaw.app.workforce.verifier import Verdict

    team, lead, member = await _seed_team()
    policy = RunPolicy(max_repair_per_node=1, max_total_tokens=0)
    plan = _two_node_plan(lead.id, member.id)
    # 永远 FAIL：第一次给返工契约（repair_count 0→1），第二次触发
    # verifier 的超限双保险（repair_count >= max_repair_per_node → ESCALATE）
    def always_fail(lead_id, contract, result, repair_count):
        return Verdict(
            VERDICT_FAIL,
            reason="不达标",
            repair=RepairContract(
                original_task=contract.objective,
                issues=["缺少细节"],
                expected_change="补充细节",
                preserve=[],
                acceptance="细节完整",
                attempt=repair_count + 1,
            ),
        )

    _patch_llm_seams(
        monkeypatch, plan, verify_impl=always_fail
    )
    run = await run_store.create_run(
        team_id=team.id,
        goal="设计登录页",
        initiator_id="alice",
        policy=policy.model_dump(),
    )
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    # 熔断：max_repair_per_node=1 → 第二次 FAIL 升级人工
    assert final["status"] == "escalated"
    assert final["repair_count"] >= 1
    assert final.get("escalation_reason")
    node = await run_store.get_node(run["id"], "task-1")
    assert node["repair_count"] >= 1
    assert node["repair"], "返工契约必须留痕"


async def test_engine_canceled_mid_run(enterprise_env, run_store, monkeypatch):
    from qwenpaw.app.workforce import engine as engine_mod

    team, lead, member = await _seed_team()
    plan = _two_node_plan(lead.id, member.id)
    # 委派内阻塞 → 主测试协程 cancel_run 传播取消
    delegate_started = asyncio.Event()

    async def slow_delegate(expert_id, contract, repair=None, session_id=None, timeout=None):
        delegate_started.set()
        await asyncio.sleep(30)
        return _ok_result(), session_id or "sess"

    _patch_llm_seams(monkeypatch, plan, delegate_impl=None)
    from qwenpaw.app.workforce import engine as em

    monkeypatch.setattr(em, "delegate", slow_delegate)
    run = await run_store.create_run(
        team_id=team.id, goal="设计登录页", initiator_id="alice"
    )
    task = engine_mod.start_run_background(run["id"])
    await asyncio.wait_for(delegate_started.wait(), timeout=5)
    assert await engine_mod.cancel_run(run["id"]) is True
    await asyncio.wait_for(task, timeout=5)
    final = await run_store.get_run(run["id"])
    assert final["status"] == "canceled"


async def test_engine_interrupted_resume(enterprise_env, run_store, monkeypatch):
    from qwenpaw.app import experts as store_mod
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import NODE_STATUS_DONE

    team, lead, member = await _seed_team()
    _patch_llm_seams(monkeypatch, _two_node_plan(lead.id, member.id))
    run = await run_store.create_run(
        team_id=team.id, goal="设计登录页", initiator_id="alice"
    )
    # 模拟崩溃前：plan 已物化、task-1 已完成、run 被启动恢复扫描置 interrupted
    await run_store.save_plan(run["id"], _two_node_plan(lead.id, member.id))
    await run_store.update_node(
        run["id"],
        "task-1",
        status=NODE_STATUS_DONE,
        contract={"task_id": "task-1", "objective": "产出前端方案"},
        result={"status": "done", "result": "A结果"},
        verdict="PASS",
    )
    await run_store.set_run_status(run["id"], "interrupted")
    # 续跑：done 节点跳过，仅执行 final 汇总 → done 终态
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"
    assert "最终汇总产出" in (final["summary"] or "")


async def test_mark_interrupted_runs_scan(enterprise_env, run_store):
    team, lead, member = await _seed_team()
    run = await run_store.create_run(
        team_id=team.id, goal="G", initiator_id="alice"
    )
    await run_store.set_run_status(run["id"], "running")
    done_run = await run_store.create_run(
        team_id=team.id, goal="G2", initiator_id="alice"
    )
    await run_store.set_run_status(done_run["id"], "done")
    # 启动恢复扫描：running → interrupted，终态不动
    count = await run_store.mark_interrupted_runs()
    assert count >= 1
    assert (await run_store.get_run(run["id"]))["status"] == "interrupted"
    assert (await run_store.get_run(done_run["id"]))["status"] == "done"


# ---------------------------------------------------------------------------
# 4. Access control: initiator or project member, 404 otherwise
# ---------------------------------------------------------------------------


async def test_ensure_run_access_404_semantics():
    from qwenpaw.app.routers.xian.workforce import _ensure_run_access

    class FakeService:
        async def get_project(self, project_id, username):
            # 只有 bob 是项目成员
            return {"id": project_id} if username == "bob" else None

    def req(user):
        return SimpleNamespace(state=SimpleNamespace(user=user))

    run_alice = {"initiator_id": "alice", "project_id": None}
    run_proj = {"initiator_id": "alice", "project_id": "prj_1"}

    # 发起人放行
    await _ensure_run_access(run_alice, req("alice"), FakeService())
    # 项目成员放行（跨用户协同）
    await _ensure_run_access(run_proj, req("bob"), FakeService())
    # 无关用户：无项目 → 404；有项目但非成员 → 404（不泄露存在性）
    with pytest.raises(HTTPException) as no_project:
        await _ensure_run_access(run_alice, req("mallory"), FakeService())
    assert no_project.value.status_code == 404
    with pytest.raises(HTTPException) as not_member:
        await _ensure_run_access(run_proj, req("mallory"), FakeService())
    assert not_member.value.status_code == 404
