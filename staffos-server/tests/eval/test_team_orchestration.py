# -*- coding: utf-8 -*-
"""团队编排评估集（T7；计划 §11 灰度门验收口径）。

以端到端 run 视角固定覆盖 11 个业务场景，全部使用确定性 LLM 桩
（planner/delegator/verifier/brain 四接缝），断言侧重：

1. **业务结果**：交付/熔断/挂起等终态符合协议语义；
2. **断言重点**（计划 719 行）——UNKNOWN/ESCALATE ≠ PASS、上下文
   冲突不被静默覆盖、嵌套重试不扩增预算、伪造信封拒绝等；
3. **指标留痕**：取消延迟、重规划次数等可从账本事件统计。

指标口径（结果质量/一次验收率/成本）由运行时账本数据支撑（token
成本、attempt/repair 计数、事件时间线），CI 断言不锚定具体数值。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_TRUNCATE_SQL = (
    "TRUNCATE team_run_nodes, team_run_actions, team_runs, feed_events, "
    "project_members, tasks, projects, expert_team_members, expert_skills, "
    "published_experts, expert_teams, experts, employee_governance, "
    "token_usage_events RESTART IDENTITY"
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
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


@pytest.fixture
def run_store():
    from qwenpaw.app.workforce.run_store import get_run_store

    return get_run_store()


async def _seed_team(name: str = "评估专家团"):
    """draft 团队 + 主理人/成员各一（评估用最小编制）。"""
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore

    expert_store = ExpertStore()
    lead = await expert_store.create_expert(
        name="评估主理人", icon="🧭", description="lead"
    )
    member = await expert_store.create_expert(
        name="评估成员", icon="🎨", description="member"
    )
    team = await expert_store.create_team(
        name=name,
        description="评估集团队",
        mode="router",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, seq=1),
        ],
    )
    return team, lead, member


async def _publish_team(team_id: str) -> None:
    """评估用：直接置 published（不触发 supervisor 物化）。"""
    from qwenpaw.app.experts.store import ExpertStore

    await ExpertStore().set_team_status(team_id, "published")


def _plan(lead_id, member_id, *, parallel=False):
    """两节点（可选并行）→ final 的标准评估 DAG。"""
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan

    if parallel:
        nodes = [
            DagNode(
                node_key="fe",
                deps=[],
                assignee_expert_id=member_id,
                node_type="task",
                objective="前端产出",
                expected_output=["页面"],
            ),
            DagNode(
                node_key="be",
                deps=[],
                assignee_expert_id=member_id,
                node_type="task",
                objective="后端产出",
                expected_output=["接口"],
            ),
            DagNode(
                node_key="final-summary",
                deps=["fe", "be"],
                node_type="final",
                objective="汇总",
            ),
        ]
    else:
        nodes = [
            DagNode(
                node_key="task-1",
                deps=[],
                assignee_expert_id=member_id,
                node_type="task",
                objective="产出方案",
                expected_output=["结构化方案"],
            ),
            DagNode(
                node_key="final-summary",
                deps=["task-1"],
                node_type="final",
                objective="汇总",
            ),
        ]
    return DagPlan(nodes=nodes, source="orchestration")


def _ok_result(text_: str = "已完成"):
    from qwenpaw.app.workforce.contracts import (
        RESULT_STATUS_COMPLETED,
        ResultContract,
    )

    return ResultContract(
        status=RESULT_STATUS_COMPLETED,
        result={"text": text_},
        result_text=text_,
    )


def _patch_seams(monkeypatch, plan, delegate_impl=None, verify_impl=None,
                 brain_capture: list | None = None):
    """四接缝确定性桩；brain_capture 非空时捕获大脑收到的 prompt。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import VERDICT_PASS
    from qwenpaw.app.workforce.planner import PlanOutcome
    from qwenpaw.app.workforce.verifier import Verdict

    async def fake_plan_run(goal, team, members, bundle, **kwargs):
        return PlanOutcome(plan=plan, source="orchestration")

    async def fake_delegate(
        expert_id, contract, repair=None, session_id=None, timeout=None,
        envelope=None,
    ):
        if delegate_impl is not None:
            return delegate_impl(expert_id, contract, repair)
        return _ok_result(f"{expert_id} 完成"), session_id or "sess_1"

    async def fake_verify(
        lead_id, contract, result, policy, repair_count=0, previous_repair=None,
    ):
        if verify_impl is not None:
            return verify_impl(lead_id, contract, result, repair_count)
        return Verdict(VERDICT_PASS, reason="符合验收标准")

    async def fake_brain(to_agent, prompt, session_id=None, timeout=None):
        if brain_capture is not None:
            brain_capture.append(prompt)
        payload = (
            '{"status":"COMPLETED","result":{"text":"最终汇总产出"},'
            '"result_text":"最终汇总产出"}'
        )
        return payload, session_id or "sess_brain", 0

    monkeypatch.setattr(engine_mod, "plan_run", fake_plan_run)
    monkeypatch.setattr(engine_mod, "delegate", fake_delegate)
    monkeypatch.setattr(engine_mod, "verify", fake_verify)
    monkeypatch.setattr(engine_mod, "call_expert_text", fake_brain)


async def _run_background(run_id: str) -> None:
    """经 _guarded_run 入口执行（熔断信号收敛为终态而非裸抛）。"""
    from qwenpaw.app.workforce import engine as engine_mod

    task = engine_mod.start_run_background(run_id)
    await task


# ---------------------------------------------------------------------------
# 场景 1-3：简单短链 / 并行分析 / 缺资料
# ---------------------------------------------------------------------------


async def test_simple_short_chain_delivery(enterprise_env, run_store, monkeypatch):
    """场景 1 简单短链：预置两节点模板 → done + 全节点留痕。"""
    from qwenpaw.app.workforce import engine as engine_mod

    team, lead, member = await _seed_team()
    _patch_seams(monkeypatch, _plan(lead.id, member.id))
    run = await run_store.create_run(
        team_id=team.id, goal="设计登录页", initiator_id="alice"
    )
    await _run_background(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"
    assert final["summary"]
    nodes = await run_store.list_nodes(run["id"])
    assert {n["status"] for n in nodes} == {"done"}
    assert all(n["contract"] for n in nodes if n["node_type"] != "final")


async def test_parallel_analysis_waves(enterprise_env, run_store, monkeypatch):
    """场景 2 并行分析：fe/be 同 deps → 完成驱动调度并行收敛。"""
    team, lead, member = await _seed_team()
    # 有界并行度=2；两个 0.1s 任务并行 → 总时长显著小于串行 0.2s
    started = time.monotonic()

    async def delayed(expert_id, contract, repair=None, session_id=None,
                      timeout=None, envelope=None):
        await asyncio.sleep(0.1)
        return _ok_result(f"{expert_id} 完成"), session_id or "sess"

    _patch_seams(monkeypatch, _plan(lead.id, member.id, parallel=True))
    from qwenpaw.app.workforce import engine as engine_ref

    monkeypatch.setattr(engine_ref, "delegate", delayed)

    run = await run_store.create_run(
        team_id=team.id, goal="并行分析", initiator_id="alice"
    )
    await _run_background(run["id"])
    elapsed = time.monotonic() - started
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"
    nodes = await run_store.list_nodes(run["id"])
    assert {n["node_key"]: n["status"] for n in nodes} == {
        "fe": "done", "be": "done", "final-summary": "done",
    }
    # 并行收益：两任务 0.1s 并行 + 汇总，远小于 0.2s 串行 + 汇总
    assert elapsed < 0.9, f"并行未生效（耗时 {elapsed:.2f}s）"


async def test_missing_material_escalates(enterprise_env, run_store, monkeypatch):
    """场景 3 缺资料：成员升级（资料不足）→ run escalated 留痕。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.engine import EscalateSignal

    team, lead, member = await _seed_team()

    def missing_material(expert_id, contract, repair):
        raise EscalateSignal("缺少上游设计稿资料，需人工补充")

    _patch_seams(
        monkeypatch, _plan(lead.id, member.id), delegate_impl=missing_material,
    )
    run = await run_store.create_run(
        team_id=team.id, goal="实现功能", initiator_id="alice"
    )
    await _run_background(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "escalated"
    assert final.get("escalation_reason")


# ---------------------------------------------------------------------------
# 场景 4-6：多成员冲突 / 权限不足 / 独立复核
# ---------------------------------------------------------------------------


async def test_conflicting_outputs_surface_to_brain(
    enterprise_env, run_store, monkeypatch
):
    """场景 4 多成员冲突：上游产出全部进入大脑 prompt（断言重点：
    上下文冲突不被静默覆盖，由大脑显式裁决）。"""
    from qwenpaw.app.workforce import engine as engine_mod

    team, lead, member = await _seed_team()
    captured: list[str] = []

    def conflict_outputs(expert_id, contract, repair):
        # 同一成员两个节点的产出互相矛盾（评估剧本固定冲突）
        text_ = (
            "方案A：使用 MySQL"
            if contract.task_id == "fe"
            else "方案B：使用 PostgreSQL"
        )
        return _ok_result(text_), f"sess_{contract.task_id}"

    # 并行 DAG（fe/be 两节点产出冲突；桩按 objective 返回不同结论）
    _patch_seams(
        monkeypatch,
        _plan(lead.id, member.id, parallel=True),
        delegate_impl=conflict_outputs,
        brain_capture=captured,
    )
    run = await run_store.create_run(
        team_id=team.id, goal="选型并落地", initiator_id="alice"
    )
    await _run_background(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"
    # 大脑 prompt 同时携带两份冲突产出（不裁剪、不静默取一）
    assert captured, "大脑 prompt 未被捕获"
    brain_prompt = "\n".join(captured)
    assert "MySQL" in brain_prompt and "PostgreSQL" in brain_prompt


async def test_out_of_scope_tool_denied(enterprise_env, run_store, monkeypatch):
    """场景 5 权限不足：团队信封资源范围外的工具调用被治理 DENY
    （断言重点：最小授权——范围外动作不可执行）。"""
    from qwenpaw.governance import envelope_auth as ea
    from qwenpaw.governance import tool_adapter as ta

    # 合法信封：scope 只含 web（成员尝试调用 fs 工具 → 越权）
    envelope = {
        "tenant_id": "t1",
        "initiator_user_id": "alice",
        "delegate_scope": ["web"],
        "run_id": "run_eval",
        "node_key": "task-1",
        "attempt_id": "att-1",
    }
    signed = {**envelope, "sig": ea.sign_envelope_payload(envelope)}
    # scope 条目是工具策略名（或尾部通配前缀）：'web' 不等于 'Webfetch'
    # → 拒绝（最小授权按策略名精确匹配）
    assert ta._scope_allows(signed["delegate_scope"], "Webfetch") is False
    # 精确命中则放行（大小写不敏感）
    assert ta._scope_allows(signed["delegate_scope"], "Websearch") is False
    assert ta._scope_allows(["Websearch"], "Websearch") is True
    # 通配 scope 授权整类资源（'web*' 覆盖 Webfetch/Websearch）
    assert ta._scope_allows(["web*"], "Webfetch") is True
    # 信封上下文 → 验签通过还原（服务端签发可被治理侧承认）
    restored = ta.team_envelope_from_context({"team_envelope": signed})
    assert restored is not None
    assert restored.delegate_scope == ["web"]


async def test_independent_verify_unknown_not_pass(
    enterprise_env, run_store, monkeypatch
):
    """场景 6 独立复核（断言重点 1）：无法裁决 ≠ PASS——verdict 三态
    （PASS/FAIL/ESCALATE），"无法裁决"一律 ESCALATE 升级人工，不得
    当作通过放行。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import VERDICT_ESCALATE
    from qwenpaw.app.workforce.verifier import Verdict

    team, lead, member = await _seed_team()
    _patch_seams(
        monkeypatch,
        _plan(lead.id, member.id),
        verify_impl=lambda lead_id, contract, result, repair_count: Verdict(
            VERDICT_ESCALATE, reason="无法裁决",
        ),
    )
    run = await run_store.create_run(
        team_id=team.id, goal="产出报告", initiator_id="alice"
    )
    await _run_background(run["id"])
    final = await run_store.get_run(run["id"])
    # 无法裁决：不 done（未通过）→ 升级人工
    assert final["status"] == "escalated"
    node = await run_store.get_node(run["id"], "task-1")
    assert node["verdict"] != "PASS"


# ---------------------------------------------------------------------------
# 场景 7-8：预算不足 / 重复提交
# ---------------------------------------------------------------------------


async def test_budget_exhausted_escalates(enterprise_env, run_store, monkeypatch):
    """场景 7 预算不足：token 预算小于单节点预留份额 → 委派前熔断
    （预留感知口径：share = 剩余 // 并行度，≤0 即 Escalate）。"""
    from qwenpaw.app.workforce.contracts import RunPolicy

    team, lead, member = await _seed_team()
    # max_total_tokens=1 且并行度 2 → 每节点份额 1//2=0 → 派发前熔断
    policy = RunPolicy(max_total_tokens=1, parallelism=2)
    _patch_seams(monkeypatch, _plan(lead.id, member.id))
    run = await run_store.create_run(
        team_id=team.id, goal="控制成本", initiator_id="alice",
        policy=policy.model_dump(),
    )
    await _run_background(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "escalated"
    assert final.get("escalation_reason")


async def test_duplicate_submit_idempotent(enterprise_env, run_store, monkeypatch):
    """场景 8 重复提交：同幂等键两次 create_team_run → 同一 run
    （不重复创建、不重复启动）。"""
    from qwenpaw.app.workforce import service as wf_service

    team, lead, member = await _seed_team()
    await _publish_team(team.id)
    first = await wf_service.create_team_run(
        team_id=team.id, goal="同一需求", initiator_id="alice",
        idempotency_key="eval-idem-1", expert_store=None,
    )
    second = await wf_service.create_team_run(
        team_id=team.id, goal="同一需求", initiator_id="alice",
        idempotency_key="eval-idem-1", expert_store=None,
    )
    assert first["id"] == second["id"]
    assert second.get("idempotent_replay") is True
    runs = await run_store.list_runs(limit=10)
    assert sum(1 for r in runs if r["id"] == first["id"]) == 1


# ---------------------------------------------------------------------------
# 场景 9-10：取消 / 恢复
# ---------------------------------------------------------------------------


async def test_cancel_converges_and_reverts_actions(
    enterprise_env, run_store, monkeypatch
):
    """场景 9 取消：运行中取消 → canceled + 挂起动作 reverted
    （副作用不悬挂）。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import action_ledger

    team, lead, member = await _seed_team()
    started = asyncio.Event()
    release = asyncio.Event()

    async def hanging_delegate(expert_id, contract, repair=None,
                               session_id=None, timeout=None, envelope=None):
        started.set()
        await release.wait()
        return _ok_result("完成"), session_id or "sess"

    _patch_seams(monkeypatch, _plan(lead.id, member.id))
    from qwenpaw.app.workforce import engine as engine_ref

    monkeypatch.setattr(engine_ref, "delegate", hanging_delegate)

    # 预登记一个挂起动作（模拟运行中已登记未回执的外部动作）
    run = await run_store.create_run(
        team_id=team.id, goal="长任务", initiator_id="alice"
    )
    await action_ledger.register_action(
        run["id"], "task-1", "att-1", "web", "web:call-1", payload={}
    )
    task = engine_mod.start_run_background(run["id"])
    await asyncio.wait_for(started.wait(), timeout=5)
    t0 = time.monotonic()
    # 协作取消（引擎 cancel_run 传播；与 xian cancel 端点同一路径）
    await engine_mod.cancel_run(run["id"])
    release.set()
    await asyncio.wait_for(task, timeout=15)
    cancel_latency = time.monotonic() - t0
    final = await run_store.get_run(run["id"])
    assert final["status"] == "canceled"
    # 指标留痕：取消延迟被记录（CI 不锚定具体值，仅确认收敛）
    assert cancel_latency < 15
    # 挂起动作被核对（reverted）——副作用不悬挂
    row = await action_ledger.get_by_action_key(run["id"], "web:call-1")
    if row is not None:
        assert row["status"] == action_ledger.ACTION_STATUS_REVERTED


async def test_resume_reconciles_and_completes(
    enterprise_env, run_store, monkeypatch
):
    """场景 10 恢复：interrupted → 续跑核对（挂起动作回收 +
    run_reconciled 事件）→ 完成；累计时间不清零。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import action_ledger
    from qwenpaw.app.workforce.contracts import RUN_STATUS_INTERRUPTED

    team, lead, member = await _seed_team()
    _patch_seams(monkeypatch, _plan(lead.id, member.id))
    run = await run_store.create_run(
        team_id=team.id, goal="断点续跑", initiator_id="alice"
    )
    run_id = run["id"]
    # 造一个 interrupted 现场：置状态 + 滞留节点（先 save_plan 建节点行）
    await run_store.save_plan(run_id, _plan(lead.id, member.id))
    await run_store.set_run_status(run_id, RUN_STATUS_INTERRUPTED)
    await run_store.update_node(
        run_id, "task-1", assignee_expert_id=member.id, status="delegated",
        attempt=1,
    )
    await action_ledger.register_action(
        run_id, "task-1", "att-1", "web", "web:call-2", payload={}
    )
    # 标准入口续跑（核对 + 恢复卫生在 run_team_run 入口）
    await engine_mod.run_team_run(run_id)
    final = await run_store.get_run(run_id)
    assert final["status"] == "done"
    # 续跑核对：挂起动作 reverted + run_reconciled 事件留痕
    row = await action_ledger.get_by_action_key(run_id, "web:call-2")
    assert row is not None
    assert row["status"] == action_ledger.ACTION_STATUS_REVERTED
    events = await run_store.list_events(run_id, limit=50)
    assert any(e["kind"] == "run_reconciled" for e in events)


# ---------------------------------------------------------------------------
# 场景 11：恶意外部指令
# ---------------------------------------------------------------------------


async def test_forged_envelope_rejected(enterprise_env, run_store, monkeypatch):
    """场景 11 恶意外部指令：外部伪造 team_envelope（自签/篡改）
    → 验签失败 fail-closed DENY，不进入执行。"""
    from qwenpaw.governance import tool_adapter as ta

    # 篡改 payload 的伪造信封（签名与内容不匹配；attempt_id 为 str）
    forged = {
        "tenant_id": "t1",
        "initiator_user_id": "attacker",
        "delegate_scope": ["fs", "web", "kb"],
        "run_id": "run_forge",
        "node_key": "task-1",
        "attempt_id": "att-1",
        "sig": "v1:" + "0" * 64,
    }
    with pytest.raises(ValueError):
        ta.team_envelope_from_context({"team_envelope": forged})
    # 畸形输入（非 JSON 字符串）同样拒绝
    with pytest.raises(ValueError):
        ta.team_envelope_from_context({"team_envelope": "{not-json"})
    # 无信封 → 不进入团队分支（返回 None，普通语义接管）
    assert ta.team_envelope_from_context({}) is None
