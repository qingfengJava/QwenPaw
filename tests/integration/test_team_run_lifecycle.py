# -*- coding: utf-8 -*-
"""run 生命周期集成测试（专家团 T5）。

覆盖（PG + LLM 接缝桩）：

1. **完成驱动有界调度**：无依赖慢节点不阻塞已完成节点的下游派发
   （协议8.5：某节点验收完成后立即释放其下游）；
2. **取消恢复**：取消传播后 run 收敛 canceled；在途外部动作被核对
   （registered → reverted，副作用不悬挂）；
3. **续跑核对**：interrupted run 重入时挂起动作被回收并留事件；
4. **版本漂移**：钉住成员版本与实例不一致 → run 暂停待显式处理；
5. **累计活跃时间**：run 行 active_seconds 段末累加（恢复不清零）。

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


@pytest.fixture
def run_store():
    from qwenpaw.app.workforce.run_store import get_run_store

    return get_run_store()


async def _seed_team(name: str = "生命周期测试团"):
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore

    expert_store = ExpertStore()
    lead = await expert_store.create_expert(
        name="周期负责人", icon="🧭", description="lead"
    )
    member = await expert_store.create_expert(
        name="周期成员", icon="🎨", description="member"
    )
    team = await expert_store.create_team(
        name=name,
        description="T5 生命周期测试团队",
        mode="router",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, seq=1),
        ],
    )
    return team, lead, member


def _ok_result(text_value: str = "已完成"):
    from qwenpaw.app.workforce.contracts import (
        RESULT_STATUS_COMPLETED,
        ResultContract,
    )

    return ResultContract(
        status=RESULT_STATUS_COMPLETED,
        result={"text": text_value},
        result_text=text_value,
        token_cost=7,
        usage_reported=True,
    )


def _patch_llm_seams(monkeypatch, plan, delegate_impl, verify_impl=None):
    """LLM 接缝桩（planner/delegator/verifier/大脑）。"""
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
        return await delegate_impl(expert_id, contract, session_id)

    async def fake_verify(
        lead_id, contract, result, policy, repair_count=0, previous_repair=None
    ):
        if verify_impl is not None:
            return verify_impl(lead_id, contract, result)
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


# ---------------------------------------------------------------------------
# 1. 完成驱动有界调度（协议8.5）
# ---------------------------------------------------------------------------


async def test_scheduler_releases_downstream_without_wave_barrier(
    enterprise_env, run_store, monkeypatch
):
    """无依赖慢节点不阻塞已完成节点的下游：task-3 在 task-2 结束前派发。"""
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan

    team, lead, member = await _seed_team()

    # DAG：task-1(快) → task-3；task-2(慢, 无依赖)。旧波次调度会让
    # task-3 等 task-2 整波结束才开始；完成驱动下 task-3 立即派发
    plan = DagPlan(
        nodes=[
            DagNode(
                node_key="task-1",
                deps=[],
                assignee_expert_id=member.id,
                node_type="task",
                objective="快任务",
                expected_output=["o"],
            ),
            DagNode(
                node_key="task-2",
                deps=[],
                assignee_expert_id=member.id,
                node_type="task",
                objective="慢任务",
                expected_output=["o"],
            ),
            DagNode(
                node_key="task-3",
                deps=["task-1"],
                assignee_expert_id=member.id,
                node_type="task",
                objective="下游任务",
                expected_output=["o"],
            ),
            DagNode(
                node_key="final-summary",
                deps=["task-2", "task-3"],
                node_type="final",
                objective="汇总",
            ),
        ],
        source="orchestration",
    )

    timeline: dict = {}

    async def seq_delegate(expert_id, contract, session_id):
        key = contract.task_id
        timeline[f"{key}:start"] = time.monotonic()
        if key == "task-2":
            await asyncio.sleep(1.0)
        else:
            await asyncio.sleep(0.05)
        timeline[f"{key}:end"] = time.monotonic()
        return _ok_result(f"{key} 完成"), session_id or "sess"

    _patch_llm_seams(monkeypatch, plan, seq_delegate)

    run = await run_store.create_run(
        team_id=team.id, goal="G", initiator_id="alice"
    )
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"

    # 核心断言：下游 task-3 的开始时间早于慢节点 task-2 的结束时间
    assert timeline["task-3:start"] < timeline["task-2:end"]
    # 全部节点仍按依赖约束完成（task-3 在 task-1 之后才开始）
    assert timeline["task-3:start"] > timeline["task-1:end"]
    # 并发约束（parallelism 默认 2）：task-2 与 task-3 同期重叠在途
    assert timeline["task-2:start"] < timeline["task-3:end"]


# ---------------------------------------------------------------------------
# 2/3. 取消与续跑核对（协议8.4）
# ---------------------------------------------------------------------------


async def test_cancel_reconciles_pending_actions(
    enterprise_env, run_store, monkeypatch
):
    """取消传播：run 收敛 canceled，挂起外部动作被核对（reverted）。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import action_ledger as ledger
    from qwenpaw.app.workforce.contracts import RUN_STATUS_CANCELED, DagNode, DagPlan

    team, lead, member = await _seed_team()
    plan = DagPlan(
        nodes=[
            DagNode(
                node_key="task-1",
                deps=[],
                assignee_expert_id=member.id,
                node_type="task",
                objective="慢任务",
                expected_output=["o"],
            ),
            DagNode(
                node_key="final-summary",
                deps=["task-1"],
                node_type="final",
                objective="汇总",
            ),
        ],
        source="orchestration",
    )
    started = asyncio.Event()

    async def blocking_delegate(expert_id, contract, session_id):
        started.set()
        await asyncio.sleep(30)

    _patch_llm_seams(monkeypatch, plan, blocking_delegate)
    run = await run_store.create_run(
        team_id=team.id, goal="G", initiator_id="alice"
    )
    run_id = run["id"]
    # 预置一个挂起的 registered 外部动作（模拟中断前的在途副作用）
    await ledger.register_action(
        run_id=run_id,
        node_key="task-1",
        attempt_id="att-x",
        action_type="external_email",
        action_key="email.send:1",
        payload={"to": "ops@example.com"},
    )
    task = engine_mod.start_run_background(run_id)
    await asyncio.wait_for(started.wait(), timeout=5)
    assert await engine_mod.cancel_run(run_id) is True
    await asyncio.wait_for(task, timeout=15)

    final = await run_store.get_run(run_id)
    assert final["status"] == RUN_STATUS_CANCELED
    # 在途动作被核对：registered → reverted（不悬挂、不重复执行）
    action = await ledger.get_by_action_key(run_id, "email.send:1")
    assert action["status"] == "reverted"


async def test_resume_reconciles_and_records_event(
    enterprise_env, run_store, monkeypatch
):
    """interrupted run 重入：挂起动作回收 + run_reconciled 事件留痕。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce import action_ledger as ledger
    from qwenpaw.app.workforce.contracts import RUN_STATUS_DONE, DagNode, DagPlan
    from qwenpaw.app.workforce.lifecycle import reconcile_resumed_run

    team, lead, member = await _seed_team()
    plan = DagPlan(
        nodes=[
            DagNode(
                node_key="task-1",
                deps=[],
                assignee_expert_id=member.id,
                node_type="task",
                objective="任务",
                expected_output=["o"],
            ),
            DagNode(
                node_key="final-summary",
                deps=["task-1"],
                node_type="final",
                objective="汇总",
            ),
        ],
        source="orchestration",
    )
    async def fast_delegate(expert_id, contract, session_id):
        return _ok_result("完成"), session_id or "sess"

    _patch_llm_seams(monkeypatch, plan, fast_delegate)
    run = await run_store.create_run(
        team_id=team.id, goal="G", initiator_id="alice"
    )
    run_id = run["id"]
    await run_store.save_plan(run_id, plan)
    # 模拟中断现场：挂起动作 + run 置 interrupted
    await ledger.register_action(
        run_id=run_id,
        node_key="task-1",
        attempt_id="att-y",
        action_type="external_email",
        action_key="email.send:2",
        payload={},
    )
    await run_store.set_run_status(run_id, "interrupted", error="x")

    # 直接核对入口（引擎重入同路径）
    swept = await reconcile_resumed_run(run_store, run_id)
    assert swept == 1
    action = await ledger.get_by_action_key(run_id, "email.send:2")
    assert action["status"] == "reverted"
    events = await run_store.list_events(run_id)
    assert any(e["kind"] == "run_reconciled" for e in events)

    # 续跑至完成（恢复卫生：无滞留中间态）
    await engine_mod.run_team_run(run_id)
    final = await run_store.get_run(run_id)
    assert final["status"] == RUN_STATUS_DONE


# ---------------------------------------------------------------------------
# 4. 版本漂移（协议8.1）
# ---------------------------------------------------------------------------


async def test_version_drift_pauses_run(
    enterprise_env, run_store, monkeypatch
):
    """钉住成员版本与实例不一致 → run 暂停 + 事件，不静默切换执行。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan, RequirementBrief

    team, lead, member = await _seed_team()
    plan = DagPlan(
        nodes=[
            DagNode(
                node_key="task-1",
                deps=[],
                assignee_expert_id=member.id,
                node_type="task",
                objective="任务",
                expected_output=["o"],
            ),
            DagNode(
                node_key="final-summary",
                deps=["task-1"],
                node_type="final",
                objective="汇总",
            ),
        ],
        source="orchestration",
    )
    dispatched: list = []

    async def must_not_run(expert_id, contract, session_id):
        dispatched.append(contract.task_id)
        return _ok_result("不应执行"), session_id

    _patch_llm_seams(monkeypatch, plan, must_not_run)

    run = await run_store.create_run(
        team_id=team.id, goal="G", initiator_id="alice"
    )
    run_id = run["id"]
    # 钉一个过期版本（模拟 run 创建后专家实例升级）
    stale_roster = [
        {
            "expert_id": member.id,
            "name": member.name,
            "version": int(member.version or 1) + 99,
        }
    ]
    await run_store.update_run(
        run_id,
        context_bundle={
            "global_ctx": {},
            "task_ctx": {
                "goal": "G",
                "roster": stale_roster,
                "requirement_brief": RequirementBrief(
                    source_ref="", business_goal="G"
                ).model_dump(),
            },
            "execution_ctx": {},
            "version": 1,
        },
    )
    await engine_mod.run_team_run(run_id)
    final = await run_store.get_run(run_id)
    # 漂移 → 暂停（非终态、不执行、不静默切换）
    assert final["status"] == "paused"
    assert dispatched == []
    events = await run_store.list_events(run_id)
    drift_events = [e for e in events if e["kind"] == "version_drift_detected"]
    assert len(drift_events) == 1
    assert drift_events[0]["payload"]["members"][0]["expert_id"] == member.id


# ---------------------------------------------------------------------------
# 5. 累计活跃时间（协议8.5）
# ---------------------------------------------------------------------------


async def test_active_seconds_accumulates(enterprise_env, run_store, monkeypatch):
    """段末累计 active_seconds：本段耗时入账，恢复不清零。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import DagNode, DagPlan

    team, lead, member = await _seed_team()
    plan = DagPlan(
        nodes=[
            DagNode(
                node_key="task-1",
                deps=[],
                assignee_expert_id=member.id,
                node_type="task",
                objective="任务",
                expected_output=["o"],
            ),
            DagNode(
                node_key="final-summary",
                deps=["task-1"],
                node_type="final",
                objective="汇总",
            ),
        ],
        source="orchestration",
    )

    async def timed_delegate(expert_id, contract, session_id):
        # 1.5s 委派耗时（int() 截断后仍 >= 1，覆盖段计时精度）
        await asyncio.sleep(1.5)
        return _ok_result("完成"), session_id

    _patch_llm_seams(monkeypatch, plan, timed_delegate)
    run = await run_store.create_run(
        team_id=team.id, goal="G", initiator_id="alice"
    )
    run_id = run["id"]
    # 走标准入口（_guarded_run 收尾负责本段累计）
    await engine_mod._guarded_run(run_id)
    final = await run_store.get_run(run_id)
    assert final["status"] == "done"
    # 1.5s 委派 + 汇总开销 → 累计活跃秒数 >= 1（宽松下界防抖动）
    assert int(final.get("active_seconds") or 0) >= 1
