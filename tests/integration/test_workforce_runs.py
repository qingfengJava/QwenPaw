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
        # dispose（而非仅清引用）：释放池内 asyncpg 连接，避免残留
        # 连接绑死已关闭的事件循环（pytest-asyncio 每用例新 loop）
        await engine_mod.dispose_engines()
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


def _spec_with_fast_chain() -> "OrchestrationSpec":  # noqa: F821
    from qwenpaw.app.workforce.contracts import OrchestrationSpec

    return OrchestrationSpec.model_validate(
        {
            "runtime_enabled": True,
            "nodes": [
                {
                    "node_key": "requirement",
                    "deps": [],
                    "assignee_expert_id": "exp_pm",
                    "node_type": "task",
                    "objective": "需求",
                },
                {
                    "node_key": "final-summary",
                    "deps": ["requirement"],
                    "node_type": "final",
                    "objective": "汇总",
                },
            ],
            "fast_nodes": [
                {
                    "node_key": "fast-impl",
                    "deps": [],
                    "assignee_expert_id": "exp_dev",
                    "node_type": "task",
                    "objective": "直接实现",
                },
                {
                    "node_key": "final-summary",
                    "deps": ["fast-impl"],
                    "node_type": "final",
                    "objective": "汇总",
                },
            ],
        }
    )


def test_pick_template_nodes_fast_vs_standard():
    from qwenpaw.app.workforce.planner import pick_template_nodes

    spec = _spec_with_fast_chain()
    # 复杂信号（多交付物）→ 标准链
    nodes, source = pick_template_nodes(spec, "帮我写一个方案和一份架构设计")
    assert source == "orchestration"
    assert [n.node_key for n in nodes] == ["requirement", "final-summary"]
    # 未命中复杂信号（小需求）→ 快速链
    nodes, source = pick_template_nodes(spec, "帮我改个按钮颜色")
    assert source == "orchestration_fast"
    assert [n.node_key for n in nodes] == ["fast-impl", "final-summary"]
    # 无快速链配置 → 标准链兜底
    spec_only_std = spec.model_copy(update={"fast_nodes": []})
    nodes, source = pick_template_nodes(spec_only_std, "帮我改个按钮颜色")
    assert source == "orchestration"
    assert [n.node_key for n in nodes] == ["requirement", "final-summary"]


async def test_plan_run_fast_chain_validated_like_standard():
    """快速链与标准链同一套校验：环依赖 / 未知成员均拒绝（可单测无 PG）。"""
    from qwenpaw.app.workforce.planner import plan_run

    team = SimpleNamespace(
        orchestration={
            "runtime_enabled": True,
            "nodes": [
                {
                    "node_key": "requirement",
                    "deps": [],
                    "assignee_expert_id": "exp_pm",
                    "node_type": "task",
                    "objective": "需求",
                },
                {
                    "node_key": "final-summary",
                    "deps": ["requirement"],
                    "node_type": "final",
                    "objective": "汇总",
                },
            ],
            # 环依赖：a→b→a（分层失败）
            "fast_nodes": [
                {
                    "node_key": "a",
                    "deps": ["b"],
                    "assignee_expert_id": "exp_dev",
                    "node_type": "task",
                    "objective": "A",
                },
                {
                    "node_key": "b",
                    "deps": ["a"],
                    "assignee_expert_id": "exp_dev",
                    "node_type": "task",
                    "objective": "B",
                },
                {
                    "node_key": "final-summary",
                    "deps": ["a", "b"],
                    "node_type": "final",
                    "objective": "汇总",
                },
            ],
        }
    )
    members = [SimpleNamespace(id="exp_pm"), SimpleNamespace(id="exp_dev")]
    bundle = SimpleNamespace()
    # 小需求触发快速链 → 环依赖被 validate_dag 拒绝，错误信息标记链来源
    outcome = await plan_run("帮我改个按钮颜色", team, members, bundle)
    assert outcome.plan is None
    assert outcome.error
    assert "orchestration_fast" in outcome.error

    # 未知成员：fast 节点指到团队之外 → 成员校验拒绝
    team.orchestration = {
        "runtime_enabled": True,
        "nodes": team.orchestration["nodes"],
        "fast_nodes": [
            {
                "node_key": "fast-impl",
                "deps": [],
                "assignee_expert_id": "exp_ghost",
                "node_type": "task",
                "objective": "实现",
            },
            {
                "node_key": "final-summary",
                "deps": ["fast-impl"],
                "node_type": "final",
                "objective": "汇总",
            },
        ],
    }
    outcome = await plan_run("帮我改个按钮颜色", team, members, bundle)
    assert outcome.plan is None
    assert outcome.error
    assert "orchestration_fast" in outcome.error

    # 合法快速链 → 小需求直达 fast 链（source=orchestration_fast）
    team.orchestration = {
        "runtime_enabled": True,
        "nodes": team.orchestration["nodes"],
        "fast_nodes": [
            {
                "node_key": "fast-impl",
                "deps": [],
                "assignee_expert_id": "exp_dev",
                "node_type": "task",
                "objective": "实现",
            },
            {
                "node_key": "final-summary",
                "deps": ["fast-impl"],
                "node_type": "final",
                "objective": "汇总",
            },
        ],
    }
    outcome = await plan_run("帮我改个按钮颜色", team, members, bundle)
    assert not outcome.error
    assert outcome.source == "orchestration_fast"
    assert [n.node_key for n in outcome.plan.nodes] == [
        "fast-impl",
        "final-summary",
    ]
    # 同一团队复杂需求 → 走标准链
    outcome = await plan_run(
        "帮我写一个方案和一份架构设计", team, members, bundle
    )
    assert not outcome.error
    assert outcome.source == "orchestration"


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


def test_ensure_final_node_includes_integration_deps():
    """自动补齐的 final 节点依赖纳入 integration 节点（防 final 先行）。"""
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan
    from qwenpaw.app.workforce.planner import _ensure_final_node

    # 仅含 integration 节点（无 task 节点）的 plan
    plan = DagPlan(
        nodes=[
            DagNode(
                node_key="integrate-1",
                deps=[],
                node_type="integration",
                objective="汇总各分支产出",
            )
        ],
        source="llm",
    )
    result = _ensure_final_node(plan)
    final = next(n for n in result.nodes if n.node_type == "final")
    assert final.deps == ["integrate-1"]


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
    from qwenpaw.app.enterprise import current_tenant_id

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
                expected_change=["补充细节"],
                preserve=[],
                acceptance=["细节完整"],
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
    # 异常路径（EscalateSignal）必须经 _guarded_run 收敛为 escalated
    # 终态——直接 await run_team_run 会把熔断信号裸抛给调用方。
    task = engine_mod.start_run_background(run["id"])
    await task
    final = await run_store.get_run(run["id"])
    # 熔断：max_repair_per_node=1 → 第二次 FAIL 升级人工
    assert final["status"] == "escalated"
    assert final["repair_count"] >= 1
    assert final.get("escalation_reason")
    node = await run_store.get_node(run["id"], "task-1")
    assert node["repair_count"] >= 1
    assert node["repair"], "返工契约必须留痕"


async def test_max_repair_boundary_result_is_verified(
    enterprise_env, run_store, monkeypatch
):
    """max_repair_per_node=1 时：第 2 次委派（首轮 FAIL 后）的结果必须被验收，
    PASS 则节点 done——不得在验收前直接熔断丢弃结果。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import verifier as verifier_mod
    from qwenpaw.app.workforce.contracts import RunPolicy

    team, lead, member = await _seed_team()
    _patch_llm_seams(monkeypatch, _two_node_plan(lead.id, member.id))
    # 换回真实 verifier（_patch_llm_seams 默认恒 PASS 桩会绕过被测的
    # 熔断预检），只在 verifier 内部 LLM 接缝注入脚本化裁决：
    # 第 1 次验收 FAIL（附返工问题），第 2 次验收 PASS。
    verify_replies = iter(
        [
            '```json\n{"verdict":"FAIL","reason":"缺少细节","issues":["缺少细节"],'
            '"expected_change":["补充细节"],"preserve":[]}\n```',
            '```json\n{"verdict":"PASS","reason":"补充细节后已达标"}\n```',
        ]
    )

    async def fake_verify_llm(to_agent, prompt, session_id=None):
        return next(verify_replies), session_id or "sess_verify"

    monkeypatch.setattr(verifier_mod, "call_expert_text", fake_verify_llm)
    monkeypatch.setattr(engine_mod, "verify", verifier_mod.verify)
    run = await run_store.create_run(
        team_id=team.id,
        goal="G",
        initiator_id="alice",
        policy=RunPolicy(max_repair_per_node=1).model_dump(),
    )
    # 经 _guarded_run 启动：熔断路径收敛为 escalated 终态而非裸抛信号
    task = engine_mod.start_run_background(run["id"])
    await task
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"
    # 边界语义留痕：repair_count 恰达上限 1，末轮结果仍被验收为 PASS
    node = await run_store.get_node(run["id"], "task-1")
    assert node["repair_count"] == 1
    assert node["verdict"] == "PASS"
    assert node["attempt"] == 2


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


async def test_interrupted_resume_recovers_midflight_node(enterprise_env, run_store, monkeypatch):
    """崩溃时节点卡在 delegated（无 result）：续跑后必须被重新执行并 done，
    不得静默跳过导致 run 带缺失产出收敛。"""
    from qwenpaw.app.workforce import engine as engine_mod

    team, lead, member = await _seed_team()
    _patch_llm_seams(monkeypatch, _two_node_plan(lead.id, member.id))
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    await run_store.save_plan(run["id"], _two_node_plan(lead.id, member.id))
    # 模拟崩溃现场：task-1 委派中断（delegated、无结果），final 未开始
    await run_store.update_node(
        run["id"], "task-1", status="delegated",
        contract={"task_id": "task-1", "objective": "产出方案"},
    )
    await run_store.set_run_status(run["id"], "running")
    await run_store.mark_interrupted_runs()
    # 续跑
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    nodes = {n["node_key"]: n for n in await run_store.list_nodes(run["id"])}
    assert final["status"] == "done"
    assert nodes["task-1"]["status"] == "done"


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


def _req(user: str):
    """构造带已认证用户的伪 Request（路由函数直调测试用）。"""
    return SimpleNamespace(state=SimpleNamespace(user=user))


async def test_create_run_rejects_unpublished_team(enterprise_env, monkeypatch):
    """draft 团队不可发起 run：与 admin 试运行通道一致返回 400。"""
    from qwenpaw.app.routers.xian.workforce import RunCreateBody, create_run
    from qwenpaw.app.workforce import engine as engine_mod

    # 只测守卫本身：屏蔽后台引擎启动，避免误触真实规划链路
    monkeypatch.setattr(engine_mod, "start_run_background", lambda run_id: None)
    team, _lead, _member = await _seed_team()  # draft 团队
    with pytest.raises(HTTPException) as exc:
        await create_run(
            RunCreateBody(team_id=team.id, goal="设计登录页"),
            _req("alice"),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "Team is not published"


class _HandoverFakeService:
    """伪造 ProjectService：bob 是项目成员，其余用户不是。"""

    async def get_project(self, project_id, username):
        return {"id": project_id} if username == "bob" else None


async def test_handover_rejects_unpublished_expert(enterprise_env, run_store):
    """移交目标专家未发布 → 400（对齐 docstring"必须存在且已发布"约束）。"""
    from qwenpaw.app.routers.xian.workforce import HandoverBody, handover_node

    team, _lead, member = await _seed_team()  # member 为 draft 专家
    run = await run_store.create_run(
        team_id=team.id,
        goal="G",
        initiator_id="alice",
        project_id="prj_1",
    )
    with pytest.raises(HTTPException) as exc:
        await handover_node(
            run["id"],
            "task-1",
            HandoverBody(target_user_id="bob", target_expert_id=member.id),
            _req("alice"),
            _HandoverFakeService(),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail == "Target expert is not published"


async def test_handover_rejects_active_node_race(
    enterprise_env, run_store, monkeypatch
):
    """节点执行中（delegated）不可移交：防止引擎并发委派的结果落地时
    覆盖移交写入（409 竞态守卫）。"""
    from qwenpaw.app.experts.store import ExpertStore
    from qwenpaw.app.routers.xian.workforce import HandoverBody, handover_node
    from qwenpaw.app.workforce import engine as engine_mod

    # 只测守卫本身：屏蔽后台引擎启动
    monkeypatch.setattr(engine_mod, "start_run_background", lambda run_id: None)
    team, lead, member = await _seed_team()
    # 目标专家须已发布（先过 published 守卫，再触达节点竞态守卫）
    await ExpertStore().set_expert_status(lead.id, "published")
    run = await run_store.create_run(
        team_id=team.id,
        goal="G",
        initiator_id="alice",
        project_id="prj_1",
    )
    await run_store.save_plan(run["id"], _two_node_plan(lead.id, member.id))
    await run_store.set_run_status(run["id"], "running")
    # 模拟引擎并发现场：task-1 已委派（delegated）尚未回执
    await run_store.update_node(run["id"], "task-1", status="delegated")
    with pytest.raises(HTTPException) as exc:
        await handover_node(
            run["id"],
            "task-1",
            HandoverBody(target_user_id="bob", target_expert_id=lead.id),
            _req("alice"),
            _HandoverFakeService(),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "节点执行中，请等待本轮完成或先取消任务"
