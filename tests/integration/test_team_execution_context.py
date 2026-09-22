# -*- coding: utf-8 -*-
"""TrustedExecutionEnvelope 执行上下文测试（专家团 T4）。

覆盖三层：

1. **信封构建纯函数**（无 PG）：全部字段取自服务端持久状态，
   范围未配置即空（最小授权）；execution_id 每次新生成；
2. **签名与治理强制**（无 PG）：HMAC 往返/篡改必败；tool_adapter
   信封分支范围内 ALLOW / 范围外 DENY / 畸形 fail-closed，且先于
   approval_level=off 短路（团队硬约束不可被开发模式旁路）；
3. **引擎接线**（PG + LLM 接缝桩）：委派携带信封（绑尝试/预留/范围），
   预算结算闭环；不限预算时无预留（budget_reservation_id 为空）。

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


def _run_row(**overrides):
    """构造信封构建用的 run 行（与 get_run 返回的列键一致）。"""
    run = {
        "id": "run-1",
        "tenant_id": "default",
        "team_id": "team-1",
        "initiator_id": "alice",
        "source_chat_id": "chat-9",
        "context_bundle": {},
    }
    run.update(overrides)
    return run


def _brief_bundle(resource_scope):
    """需求基线注入 context_bundle（信封范围来源）。"""
    from qwenpaw.app.workforce.contracts import RequirementBrief

    brief = RequirementBrief(
        source_ref="chat-9",
        business_goal="G",
        resource_scope=resource_scope,
    )
    return {"task_ctx": {"requirement_brief": brief.model_dump()}}


# ---------------------------------------------------------------------------
# 1. 信封构建纯函数（无 PG）
# ---------------------------------------------------------------------------


def test_envelope_built_from_server_state():
    """信封字段全部来自服务端持久状态；范围未配置即空（最小授权）。"""
    from qwenpaw.app.workforce.action_ledger import build_execution_envelope

    # 显式范围：来自需求基线 resource_scope
    run = _run_row(context_bundle=_brief_bundle(["WebSearch", "execute*"]))
    env = build_execution_envelope(
        run, "task-1", "att-1", budget_reservation_id="resv-1"
    )
    assert env.tenant_id == "default"
    assert env.initiator_user_id == "alice"
    assert env.delegate_scope == ["WebSearch", "execute*"]
    assert env.team_id == "team-1"
    assert env.run_id == "run-1"
    assert env.node_key == "task-1"
    assert env.attempt_id == "att-1"
    assert env.root_session_id == "chat-9"
    assert env.execution_id
    assert env.policy_snapshot_ref == "run_policy:run-1"
    assert env.budget_reservation_id == "resv-1"
    # execution_id 每次构建新生成（一次子执行一个标识）
    env2 = build_execution_envelope(run, "task-1", "att-1")
    assert env2.execution_id != env.execution_id

    # 范围未配置：空列表（治理面拒绝全部越界工具，最小授权兜底）
    empty = build_execution_envelope(_run_row(), "task-1", "att-1")
    assert empty.delegate_scope == []
    assert empty.budget_reservation_id == ""


def test_envelope_signature_roundtrip_and_tamper():
    """HMAC 往返一致；载荷任一字段篡改或签名缺失/伪造必败。"""
    from qwenpaw.governance.envelope_auth import (
        sign_envelope_payload,
        verify_envelope_payload,
    )

    payload = {"run_id": "run-1", "delegate_scope": ["WebSearch"]}
    sig = sign_envelope_payload(payload)
    assert sig.startswith("v1:")
    # 往返一致
    assert verify_envelope_payload(payload, sig) is True
    # 重新序列化（不同键序）不影响确定性签名
    reordered = {"delegate_scope": ["WebSearch"], "run_id": "run-1"}
    assert verify_envelope_payload(reordered, sig) is True
    # 载荷篡改必败（授权边界不可伪造）
    tampered = dict(payload, delegate_scope=["*"])
    assert verify_envelope_payload(tampered, sig) is False
    # 签名缺失/格式错误/伪造必败
    assert verify_envelope_payload(payload, "") is False
    assert verify_envelope_payload(payload, "deadbeef") is False
    assert verify_envelope_payload(payload, "v1:" + "0" * 64) is False


def test_envelope_from_context_parse_and_tamper():
    """request_context 解析：缺失 → None；有效签名 → 信封；篡改 → 异常。"""
    from qwenpaw.governance.envelope_auth import sign_envelope_payload
    from qwenpaw.governance.tool_adapter import (
        team_envelope_from_context,
        TEAM_ENVELOPE_CONTEXT_KEY,
    )

    # 无信封：None（既有非团队路径不受影响）
    assert team_envelope_from_context({}) is None
    assert team_envelope_from_context(None) is None

    payload = {
        "tenant_id": "default",
        "delegate_scope": ["WebSearch"],
        "run_id": "run-1",
        "node_key": "task-1",
        "attempt_id": "att-1",
        "execution_id": "exec-1",
    }
    signed = {**payload, "sig": sign_envelope_payload(payload)}
    env = team_envelope_from_context({TEAM_ENVELOPE_CONTEXT_KEY: signed})
    assert env is not None
    assert env.run_id == "run-1"
    assert env.delegate_scope == ["WebSearch"]

    # 字符串形态（存储往返序列化）同样可解析
    import json

    env2 = team_envelope_from_context(
        {TEAM_ENVELOPE_CONTEXT_KEY: json.dumps(signed)}
    )
    assert env2 is not None and env2.run_id == "run-1"

    # 签名缺失 → ValueError（fail-closed）
    with pytest.raises(ValueError):
        team_envelope_from_context({TEAM_ENVELOPE_CONTEXT_KEY: payload})
    # 载荷篡改 → ValueError
    tampered = dict(payload, sig=signed["sig"], delegate_scope=["*"])
    with pytest.raises(ValueError):
        team_envelope_from_context({TEAM_ENVELOPE_CONTEXT_KEY: tampered})
    # 畸形 JSON 字符串 → ValueError
    with pytest.raises(ValueError):
        team_envelope_from_context({TEAM_ENVELOPE_CONTEXT_KEY: "{not-json"})


# ---------------------------------------------------------------------------
# 2. 治理强制（无 PG：直接驱动 tool_adapter 的检查函数）
# ---------------------------------------------------------------------------


def _stub_tool(name: str, request_context: dict):
    """构造 check_permissions 所需的最小 self 桩（不依赖动态类）。"""
    return SimpleNamespace(
        name=name,
        _qp_request_context=request_context,
        _qp_governor=None,
        _qp_raw_params={},
    )


def _signed_context(payload_overrides=None, tamper=False):
    """构造带签名信封的 request_context（off 旁路回归共用）。"""
    from qwenpaw.governance.envelope_auth import sign_envelope_payload
    from qwenpaw.governance.tool_adapter import TEAM_ENVELOPE_CONTEXT_KEY

    payload = {
        "tenant_id": "default",
        "delegate_scope": ["WebSearch", "execute*"],
        "run_id": "run-1",
        "node_key": "task-1",
        "attempt_id": "att-1",
        "execution_id": "exec-1",
    }
    payload.update(payload_overrides or {})
    sig = sign_envelope_payload(payload)
    if tamper:
        # 签名后改载荷（伪造范围放大的典型攻击形态）
        payload = dict(payload, delegate_scope=["*"])
    return {TEAM_ENVELOPE_CONTEXT_KEY: {**payload, "sig": sig}}


async def test_governance_envelope_allows_in_scope_denies_out():
    """范围内 ALLOW（含尾部通配）；范围外 DENY（无 ask 后门）。"""
    from agentscope.permission import PermissionBehavior

    from qwenpaw.governance.tool_adapter import _policy_tool_check_permissions

    ctx = _signed_context()
    # 范围内精确命中
    decision = await _policy_tool_check_permissions(_stub_tool("WebSearch", ctx))
    assert decision.behavior == PermissionBehavior.ALLOW
    # 范围内尾部通配命中（WebSearch → execute* 前缀不匹配；
    # execute_bash 命中 execute*）
    decision = await _policy_tool_check_permissions(
        _stub_tool("execute_bash", ctx)
    )
    assert decision.behavior == PermissionBehavior.ALLOW
    # 范围外：DENY 且为最终拒绝
    decision = await _policy_tool_check_permissions(_stub_tool("Bash", ctx))
    assert decision.behavior == PermissionBehavior.DENY
    assert "outside the team delegate scope" in decision.message


async def test_governance_envelope_not_shortcircuited_by_off():
    """approval_level=off 不得短路团队信封：范围外仍 DENY（核心回归）。"""
    from agentscope.permission import PermissionBehavior

    from qwenpaw.governance.tool_adapter import _policy_tool_check_permissions

    # off + 范围外工具：信封分支先于 off 短路 → DENY
    ctx = _signed_context()
    ctx["approval_level"] = "off"
    decision = await _policy_tool_check_permissions(_stub_tool("Bash", ctx))
    assert decision.behavior == PermissionBehavior.DENY
    # off + 范围内工具：信封范围放行
    decision = await _policy_tool_check_permissions(_stub_tool("WebSearch", ctx))
    assert decision.behavior == PermissionBehavior.ALLOW


async def test_governance_tampered_envelope_fail_closed():
    """畸形/篡改信封一律 DENY（外部请求自填无效）。"""
    from agentscope.permission import PermissionBehavior

    from qwenpaw.governance.tool_adapter import _policy_tool_check_permissions

    # 篡改载荷（签名不匹配）
    decision = await _policy_tool_check_permissions(
        _stub_tool("WebSearch", _signed_context(tamper=True))
    )
    assert decision.behavior == PermissionBehavior.DENY
    assert "invalid team envelope" in decision.message
    # 无签名自填（外部伪造）
    from qwenpaw.governance.tool_adapter import TEAM_ENVELOPE_CONTEXT_KEY

    decision = await _policy_tool_check_permissions(
        _stub_tool(
            "WebSearch",
            {TEAM_ENVELOPE_CONTEXT_KEY: {"run_id": "run-1"}},
        )
    )
    assert decision.behavior == PermissionBehavior.DENY


# ---------------------------------------------------------------------------
# 3. 引擎接线（PG + LLM 接缝桩）
# ---------------------------------------------------------------------------


async def _seed_team(name: str = "信封测试团"):
    from qwenpaw.app.experts.models import TeamMember
    from qwenpaw.app.experts.store import ExpertStore

    expert_store = ExpertStore()
    lead = await expert_store.create_expert(
        name="信封负责人", icon="🧭", description="lead"
    )
    member = await expert_store.create_expert(
        name="信封成员", icon="🎨", description="member"
    )
    team = await expert_store.create_team(
        name=name,
        description="T4 信封测试团队",
        mode="router",
        members=[
            TeamMember(expert_id=lead.id, member_role="lead", seq=0),
            TeamMember(expert_id=member.id, seq=1),
        ],
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
                objective="产出方案",
                expected_output=["结构化方案"],
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


def _patch_llm_seams(monkeypatch, plan, delegate_impl):
    """LLM 接缝桩；委派桩捕获信封（engine 接线断言依据）。"""
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
        return await delegate_impl(
            expert_id, contract, session_id, envelope
        )

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


async def test_engine_delegation_carries_envelope_and_settles_budget(
    enterprise_env, run_store, monkeypatch
):
    """有限预算：委派携带信封（绑尝试/预留/范围），预留结算闭环。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import RunPolicy, TrustedExecutionEnvelope

    team, lead, member = await _seed_team()
    plan = _two_node_plan(lead.id, member.id)
    captured: dict = {}

    async def cap_delegate(expert_id, contract, session_id, envelope):
        captured[expert_id] = envelope
        return _ok_result(f"{expert_id} 完成"), session_id or "sess_1"

    _patch_llm_seams(monkeypatch, plan, cap_delegate)

    run = await run_store.create_run(
        team_id=team.id, goal="G", initiator_id="alice"
    )
    run_id = run["id"]
    # 注入需求基线范围 + 有限预算策略（引擎从 DB 重读，必须持久化）
    await run_store.update_run(
        run_id,
        context_bundle=_brief_bundle(["WebSearch", "execute*"]),
        policy=RunPolicy(max_total_tokens=1000, parallelism=2).model_dump(),
    )
    await engine_mod.run_team_run(run_id)
    final = await run_store.get_run(run_id)
    assert final["status"] == "done"

    # 成员委派携带签名信封（控制面字段完整）
    env = captured.get(member.id)
    assert isinstance(env, TrustedExecutionEnvelope)
    assert env.run_id == run_id
    assert env.node_key == "task-1"
    assert env.attempt_id
    assert env.delegate_scope == ["WebSearch", "execute*"]
    assert env.initiator_user_id == "alice"
    assert env.budget_reservation_id
    # 中央大脑自执行节点不产生信封（无委派）
    assert lead.id not in captured

    # 预留结算闭环：成员节点预留 = 剩余按并发均分（1000//2=500），
    # 结算按回执实际用量落账（7）；大脑自执行节点同样先预留（LLM
    # 调用同样消耗预算），其回执 0 token → 按零结算
    from qwenpaw.db import engine as engine_db

    db = engine_db.create_pg_engine(DSN)
    async with db.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT status, reserved_tokens, used_tokens, node_key "
                    "FROM team_run_budget_reservations WHERE run_id = :run "
                    "ORDER BY node_key"
                ),
                {"run": run_id},
            )
        ).mappings().all()
    assert len(rows) == 2
    by_node = {r["node_key"]: r for r in rows}
    assert by_node["task-1"]["status"] == "settled"
    assert by_node["task-1"]["reserved_tokens"] == 500
    assert by_node["task-1"]["used_tokens"] == 7
    # 大脑节点：task-1 结算后用量 7 → 剩余 993，预留 993//2=496
    assert by_node["final-summary"]["status"] == "settled"
    assert by_node["final-summary"]["reserved_tokens"] == 496
    assert by_node["final-summary"]["used_tokens"] == 0
    await engine_db.dispose_engines()


async def test_engine_no_budget_skips_reservation(
    enterprise_env, run_store, monkeypatch
):
    """不限预算：无预留面，信封 budget_reservation_id 为空。"""
    from qwenpaw.app.workforce import engine as engine_mod

    team, lead, member = await _seed_team()
    plan = _two_node_plan(lead.id, member.id)
    captured: dict = {}

    async def cap_delegate(expert_id, contract, session_id, envelope):
        captured[expert_id] = envelope
        return _ok_result(f"{expert_id} 完成"), session_id or "sess_1"

    _patch_llm_seams(monkeypatch, plan, cap_delegate)

    run = await run_store.create_run(
        team_id=team.id, goal="G", initiator_id="alice"
    )
    run_id = run["id"]
    # 默认策略 max_total_tokens=0（不限）：不预留
    await run_store.update_run(
        run_id, context_bundle=_brief_bundle(["WebSearch"])
    )
    await engine_mod.run_team_run(run_id)
    final = await run_store.get_run(run_id)
    assert final["status"] == "done"
    assert captured[member.id].budget_reservation_id == ""

    from qwenpaw.db import engine as engine_db

    db = engine_db.create_pg_engine(DSN)
    async with db.begin() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM team_run_budget_reservations "
                    "WHERE run_id = :run"
                ),
                {"run": run_id},
            )
        ).scalar_one()
    assert count == 0
    await engine_db.dispose_engines()
