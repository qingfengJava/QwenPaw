# -*- coding: utf-8 -*-
"""Team run decisions integration tests（专家团控制面 T3）。

覆盖计划 §T3 的验收路径（PG 门控 ``QWENPAW_TEST_PG_DSN``）：

1. **计划批准门**：v2 团队开启 require_plan_approval → 计划物化后
   挂起（awaiting_confirm + pending_decision），投影下发
   waiting_reason=plan_approval 与 approve_plan 动作；过期批准
   （expected_revision 不匹配）拒绝；正确批准放行至 done；
2. **幂等创建**：同幂等键重复提交不创建第二个 run；
3. **暂停/续跑**：pause 后台任务收敛 paused（不误判 canceled），
   resume 从持久视图恢复至 done；
4. **需求基线修订**：澄清答复递增需求修订号并留痕账本；
5. **决策通道生命周期**：resume / cancel 经 decisions 统一处置。

@author qingfeng
"""

from __future__ import annotations

import asyncio
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

#: v2 团队配置（计划批准门开启）
_V2_ORCHESTRATION = {
    "schema_version": "v2",
    "require_plan_approval": True,
    "runtime_enabled": True,
    "nodes": [],
}


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
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


@pytest.fixture
def run_store():
    from qwenpaw.app.workforce.run_store import get_run_store

    return get_run_store()


async def _seed_team(name: str = "决策测试团", v2: bool = False):
    """建团队 + 两名成员；v2=True 时开启计划批准门。"""
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore

    expert_store = ExpertStore()
    lead = await expert_store.create_expert(
        name="决策负责人", icon="🧭", description="lead"
    )
    member = await expert_store.create_expert(
        name="决策成员", icon="🎨", description="member"
    )
    team = await expert_store.create_team(
        name=name,
        description="T3 决策测试团队",
        mode="router",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, seq=1),
        ],
    )
    if v2:
        await expert_store.update_team(
            team.id, orchestration=dict(_V2_ORCHESTRATION)
        )
    return team, lead, member


def _two_node_plan(lead_id: str, member_id: str):
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
        token_cost=7,
        usage_reported=True,
    )


def _patch_llm_seams(monkeypatch, plan, delegate_impl=None):
    """LLM 接缝桩（planner/delegator/verifier/中央大脑）。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import VERDICT_PASS
    from qwenpaw.app.workforce.planner import PlanOutcome
    from qwenpaw.app.workforce.verifier import Verdict

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
        return Verdict(VERDICT_PASS, reason="符合验收标准")

    async def fake_brain(to_agent, prompt, session_id=None, timeout=None):
        payload = (
            '{"status":"COMPLETED","result":{"text":"最终汇总产出"},'
            '"result_text":"最终汇总产出"}'
        )
        return payload, session_id or "sess_brain", 0

    monkeypatch.setattr(engine_mod, "plan_run", fake_plan_run)
    monkeypatch.setattr(engine_mod, "delegate", fake_delegate)
    monkeypatch.setattr(engine_mod, "verify", fake_verify)
    monkeypatch.setattr(engine_mod, "call_expert_text", fake_brain)


async def _wait_status(store, run_id: str, status: str, timeout: float = 15.0):
    """轮询等待 run 进入指定状态（后台任务收敛是异步的）。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        run = await store.get_run(run_id)
        if run is not None and run["status"] == status:
            return run
        await asyncio.sleep(0.05)
    run = await store.get_run(run_id)
    raise AssertionError(
        f"等待状态 {status} 超时，当前 {run and run['status']}"
    )


def _starlette_request(user: str):
    """构造最小 Request（路由协程直调；发起人放行访问校验）。"""
    from starlette.requests import Request as StarletteRequest

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/runs/x",
        "headers": [],
        "query_string": b"",
        "state": {},
    }
    request = StarletteRequest(scope)
    request.state.user = user
    return request


# ---------------------------------------------------------------------------
# 1. 计划批准门（v2 require_plan_approval）
# ---------------------------------------------------------------------------


async def test_plan_approval_gate_full_flow(
    enterprise_env, run_store, monkeypatch
):
    """批准门：挂起 → 过期批准拒绝 → 正确批准放行至 done。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import service as service_mod
    from qwenpaw.app.workforce.contracts import (
        WAIT_REASON_PLAN_APPROVAL,
        HumanDecision,
    )
    from qwenpaw.app.workforce.projection import build_run_view

    team, lead, member = await _seed_team(v2=True)
    plan = _two_node_plan(lead.id, member.id)
    _patch_llm_seams(monkeypatch, plan)
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    # 同步跑完规划阶段：批准门挂起后 run_team_run 返回（非 RUNNING）
    await engine_mod.run_team_run(run["id"])
    pending_run = await run_store.get_run(run["id"])
    assert pending_run["status"] == "awaiting_confirm"

    # 挂起决策对象：绑定 plan 修订号与服务端摘要
    pending = pending_run["context_bundle"]["execution_ctx"]["pending_decision"]
    assert pending["kind"] == "plan"
    assert pending["revision"] == 1
    assert pending["decision_id"]

    # 投影：v2 等待原因与动作权限（approve_plan 前置）
    nodes = await run_store.list_nodes(run["id"])
    view = build_run_view(pending_run, nodes)
    assert view["waiting_reason"] == WAIT_REASON_PLAN_APPROVAL
    assert "approve_plan" in view["allowed_actions"]
    assert view["pending_decision"]["decision_id"] == pending["decision_id"]

    # 过期批准（版本不匹配）→ 冲突，且不放行
    with pytest.raises(service_mod.DecisionConflict):
        await service_mod.submit_decision(
            run["id"],
            HumanDecision(
                decision_id=pending["decision_id"],
                action="approve_plan",
                expected_revision=99,
                comment="越权版本",
            ),
        )
    still = await run_store.get_run(run["id"])
    assert still["status"] == "awaiting_confirm"

    # 正确批准 → 放行至 done
    result = await service_mod.submit_decision(
        run["id"],
        HumanDecision(
            decision_id=pending["decision_id"],
            action="approve_plan",
            expected_revision=1,
            comment="通过",
        ),
    )
    assert result["status"] == "running"
    final = await _wait_status(run_store, run["id"], "done")
    # 已批准决策留痕（approved revisions 语义）
    approved = final["context_bundle"]["execution_ctx"]["approved_decisions"]
    assert approved[-1]["decision_id"] == pending["decision_id"]
    assert approved[-1]["revision"] == 1
    # 挂起对象已清除
    assert not final["context_bundle"]["execution_ctx"].get("pending_decision")
    # 决策事件持久留痕
    events = await run_store.list_events(run["id"])
    assert any(e["kind"] == "plan_awaiting_approval" for e in events)
    assert any(e["kind"] == "decision_applied" for e in events)


async def test_plan_gate_invalid_decision_id(enterprise_env, run_store, monkeypatch):
    """伪造 decision_id → 404 语义（DecisionNotFound），不触碰状态。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import service as service_mod
    from qwenpaw.app.workforce.contracts import HumanDecision

    team, lead, member = await _seed_team(v2=True)
    _patch_llm_seams(monkeypatch, _two_node_plan(lead.id, member.id))
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    await engine_mod.run_team_run(run["id"])
    with pytest.raises(service_mod.DecisionNotFound):
        await service_mod.submit_decision(
            run["id"],
            HumanDecision(
                decision_id="dec_forged",
                action="approve_plan",
                expected_revision=1,
            ),
        )


# ---------------------------------------------------------------------------
# 2. 幂等创建
# ---------------------------------------------------------------------------


async def test_idempotent_create_same_key(enterprise_env, run_store, monkeypatch):
    """同幂等键重复提交：返回既有 run，不重复创建/启动。"""
    from qwenpaw.app.workforce import service as service_mod

    team, _lead, _member = await _seed_team()
    # 幂等创建走完整准入（含发布校验）：团队须先发布
    from qwenpaw.app.experts.store import ExpertStore

    await ExpertStore().set_team_status(team.id, "published")
    _patch_llm_seams(monkeypatch, _two_node_plan("lead", "member"))
    first = await service_mod.create_team_run(
        team_id=team.id,
        goal="G",
        initiator_id="alice",
        idempotency_key="idem-1",
    )
    second = await service_mod.create_team_run(
        team_id=team.id,
        goal="G",
        initiator_id="alice",
        idempotency_key="idem-1",
    )
    assert second["id"] == first["id"]
    assert second.get("idempotent_replay") is True
    runs = await run_store.list_runs(initiator_id="alice", team_id=team.id)
    assert len(runs) == 1


# ---------------------------------------------------------------------------
# 3. 暂停 / 续跑
# ---------------------------------------------------------------------------


async def test_pause_then_resume_converges_done(
    enterprise_env, run_store, monkeypatch
):
    """pause 收敛 paused（不误判 canceled），resume 恢复至 done。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import service as service_mod

    team, lead, member = await _seed_team()
    _patch_llm_seams(monkeypatch, _two_node_plan(lead.id, member.id))
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    engine_mod.start_run_background(run["id"])
    await _wait_status(run_store, run["id"], "running")

    # 暂停：后台任务收敛为 paused（协作挂起，非终态）
    result = await service_mod.pause_run(run["id"])
    assert result["status"] == "paused"
    paused = await _wait_status(run_store, run["id"], "paused")
    assert paused["status"] == "paused"

    # 续跑：从持久视图恢复至 done（done 节点跳过）
    await service_mod.resume_paused_run(run["id"])
    await _wait_status(run_store, run["id"], "done")


# ---------------------------------------------------------------------------
# 4. 需求基线修订（澄清答复）
# ---------------------------------------------------------------------------


async def test_clarify_records_requirement_revision(
    enterprise_env, run_store, monkeypatch
):
    """澄清答复：需求基线修订号递增 + 账本留痕 + inputs 回填。"""
    from qwenpaw.app.routers.xian.workforce import ClarifyBody, answer_clarification
    from qwenpaw.app.workforce.contracts import RUN_STATUS_AWAITING_CONFIRM

    # 只测账本与束更新：屏蔽后台引擎启动（无需真实规划）
    from qwenpaw.app.workforce import engine as engine_mod

    monkeypatch.setattr(engine_mod, "start_run_background", lambda rid: None)
    team, _lead, _member = await _seed_team()
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    # 进入澄清挂起态（带待答复问题）
    await run_store.update_run(
        run["id"], clarification={"questions": ["预算多少？"], "answers": {}}
    )
    await run_store.set_run_status(run["id"], RUN_STATUS_AWAITING_CONFIRM)
    await answer_clarification(
        run["id"],
        ClarifyBody(answers={"预算多少？": "5 万以内"}),
        _starlette_request("alice"),
        service=object(),
    )
    updated = await run_store.get_run(run["id"])
    brief = updated["context_bundle"]["task_ctx"]["requirement_brief"]
    assert brief["revision"] == 2
    assert any("5 万以内" in i for i in brief["inputs"])
    revisions = await run_store.list_revisions(run["id"], kind="requirement")
    assert [r["revision"] for r in revisions] == [2]


# ---------------------------------------------------------------------------
# 5. 决策通道生命周期（resume / cancel）
# ---------------------------------------------------------------------------


async def test_decision_channel_resume_and_cancel(
    enterprise_env, run_store, monkeypatch
):
    """decisions 统一通道：paused → resume；非终态 → cancel。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import service as service_mod
    from qwenpaw.app.workforce.contracts import HumanDecision

    team, lead, member = await _seed_team()
    _patch_llm_seams(monkeypatch, _two_node_plan(lead.id, member.id))
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    engine_mod.start_run_background(run["id"])
    await _wait_status(run_store, run["id"], "running")
    await service_mod.pause_run(run["id"])
    await _wait_status(run_store, run["id"], "paused")

    # decisions 通道 resume：放行至 done
    result = await service_mod.submit_decision(
        run["id"],
        HumanDecision(decision_id="n/a", action="resume", expected_revision=0),
    )
    assert result["status"] == "running"
    await _wait_status(run_store, run["id"], "done")

    # decisions 通道 cancel：非终态 → canceled
    run2 = await run_store.create_run(
        team_id=team.id, goal="G2", initiator_id="alice"
    )
    result2 = await service_mod.submit_decision(
        run2["id"],
        HumanDecision(decision_id="n/a", action="cancel", expected_revision=0),
    )
    assert result2["status"] == "canceled"
    # 终态重复 cancel：幂等返回历史状态
    result3 = await service_mod.submit_decision(
        run2["id"],
        HumanDecision(decision_id="n/a", action="cancel", expected_revision=0),
    )
    assert result3 == {"status": "canceled"}
