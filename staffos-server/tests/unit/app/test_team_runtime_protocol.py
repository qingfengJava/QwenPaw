# -*- coding: utf-8 -*-
"""T-1 Harness Runtime Specification 协议冻结测试（17 项）。

验证 17 项运行协议的数据结构、前置状态与失败/恢复语义已冻结在契约层
（``app.workforce.contracts`` / ``verification.kernel`` / ``harnesses.base``）。
测试输入全部固定，不调用真实外部系统；本文件不证明协议已端到端实现，
只证明协议边界可被机器检验（实现接线见计划第十四节映射表）。

@author qingfeng
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from qwenpaw.app.workforce.bundle import ContextBundle
from qwenpaw.app.workforce.contracts import (
    MEMORY_ORG_PROMOTION_STEPS,
    MEMORY_SCOPE_EMPLOYEE,
    MEMORY_SCOPE_ORG,
    MEMORY_SCOPE_TASK,
    MEMORY_SCOPE_WORKING,
    NODE_STATUS_SUPERSEDED,
    NODE_STATUS_WAITING,
    REACT_TRIGGERS,
    RUN_STATUSES,
    WAIT_REASON_PLAN_APPROVAL,
    WAIT_REASONS,
    Clarification,
    ContextVector,
    DagNode,
    DagPlan,
    HumanDecision,
    PlanRevision,
    PolicyDecision,
    RepairContract,
    RequirementBrief,
    ResultContract,
    RunPolicy,
    SkillSelection,
    TaskContract,
    ToolObservation,
    TraceLink,
    TrustedExecutionEnvelope,
    compose_policy_decisions,
    decision_matches,
    min_positive_limit,
    missing_required_skills,
    validate_dag,
)
from qwenpaw.harnesses.base import (
    RECEIPT_PHASE_CREATED,
    RECEIPT_PHASE_FAILED,
    RECEIPT_PHASE_STARTED,
    RECEIPT_PHASE_STOPPED,
    RECEIPT_PHASE_STREAMING,
    RECEIPT_PHASES,
    HarnessBackendCapabilities,
    HarnessLifecycleReceipt,
)
from qwenpaw.verification.kernel import (
    VERDICT_ESCALATE,
    VERDICT_FAIL,
    VERDICT_PASS,
    JudgeRequest,
    parse_verdict,
    render_judge_prompt,
)


def _fence(payload: dict) -> str:
    """构造裁决器标准输出（固定输入）。"""

    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


# ---------------------------------------------------------------------------
# 协议01 Task Lifecycle：状态机与等待语义
# ---------------------------------------------------------------------------


def test_01_task_lifecycle_status_machine():
    """run 状态含全部终态与中断恢复态；等待原因是可恢复语义非终态。"""
    # 终态齐全：done/failed/escalated/canceled 必须是终态成员
    for terminal in ("done", "failed", "escalated", "canceled"):
        assert terminal in RUN_STATUSES
    # 中断可续跑态在状态全集内
    assert "interrupted" in RUN_STATUSES
    # 等待原因全部注册（挂起 ≠ 终态）
    assert WAIT_REASON_PLAN_APPROVAL in WAIT_REASONS
    assert len(WAIT_REASONS) == 8
    # 等待原因与终态名不重叠（语义不混用）
    assert not (WAIT_REASONS & {"done", "failed", "canceled", "escalated"})
    # v2 节点扩展态已冻结
    assert NODE_STATUS_WAITING == "waiting"
    assert NODE_STATUS_SUPERSEDED == "superseded"


# ---------------------------------------------------------------------------
# 协议02 Agent Lifecycle：可信载荷与生命周期回执
# ---------------------------------------------------------------------------


def test_02_agent_lifecycle_envelope_and_receipt():
    """可信载荷必填租户；回执阶段完整且只有停止/失败是关闭阶段。"""
    # 缺租户直接拒绝（隔离硬边界不可缺省）
    with pytest.raises(ValidationError):
        TrustedExecutionEnvelope()
    # 全字段身份链：租户→发起人→团队→运行→节点→尝试→根会话→子执行
    envelope = TrustedExecutionEnvelope(
        tenant_id="t1",
        initiator_user_id="u1",
        delegate_scope=["read:kb", "write:report"],
        team_id="team-9",
        run_id="run-1",
        node_key="be-api",
        attempt_id="att-3",
        root_session_id="sess-root",
        execution_id="exec-77",
        policy_snapshot_ref="policy:v5",
        budget_reservation_id="resv-11",
    )
    assert envelope.execution_id == "exec-77"
    assert envelope.node_key == "be-api"
    # 回执阶段全集与关闭判定
    assert RECEIPT_PHASES == (
        RECEIPT_PHASE_CREATED,
        RECEIPT_PHASE_STARTED,
        RECEIPT_PHASE_STREAMING,
        RECEIPT_PHASE_STOPPED,
        RECEIPT_PHASE_FAILED,
    )
    receipt = HarnessLifecycleReceipt(execution_id="exec-77")
    assert receipt.phase == RECEIPT_PHASE_CREATED
    assert receipt.is_terminal() is False
    assert HarnessLifecycleReceipt(
        execution_id="x",
        phase=RECEIPT_PHASE_STOPPED,
    ).is_terminal() is True
    assert HarnessLifecycleReceipt(
        execution_id="x",
        phase=RECEIPT_PHASE_FAILED,
    ).is_terminal() is True


def test_02_backend_capability_declaration_not_proof():
    """能力声明默认全 False：未声明的能力不得承接任务（声明≠验证）。"""
    caps = HarnessBackendCapabilities()
    assert caps.structured_result is False
    assert caps.cancellation is False
    assert caps.reconnect is False
    assert caps.usage_reporting is False
    assert caps.tool_governance is False
    assert caps.sandboxed_actions is False


# ---------------------------------------------------------------------------
# 协议03 ReAct State Machine：认知触发与熔断边界
# ---------------------------------------------------------------------------


def test_03_react_trigger_events_are_bounded():
    """L1 仅在四类事件触发认知；普通推进不进触发集。"""
    assert REACT_TRIGGERS == frozenset(
        {
            "failure_attribution",
            "dependency_changed",
            "requirement_changed",
            "new_info_invalidates_plan",
        },
    )
    # "工具调用成功"等普通事件不属于认知触发
    assert "tool_result" not in REACT_TRIGGERS
    assert "wave_advanced" not in REACT_TRIGGERS


def test_03_budget_counters_independent():
    """返工/重规划/时限/并发上限相互独立（不互相冒充）。"""
    policy = RunPolicy(
        max_repair_per_node=3,
        max_replan=2,
        max_total_seconds=600,
        max_total_tokens=100000,
        parallelism=2,
    )
    assert policy.max_repair_per_node == 3
    assert policy.max_replan == 2
    assert policy.max_total_seconds == 600
    assert policy.max_total_tokens == 100000
    assert policy.parallelism == 2


def test_03_unparseable_verdict_escalates():
    """回执无法解析 → ESCALATE（循环有界，绝不误判 PASS）。"""
    verdict = parse_verdict("模型自由发挥，看起来没问题", task_id="n1", attempt=1)
    assert verdict.verdict == VERDICT_ESCALATE
    assert verdict.repair is None


# ---------------------------------------------------------------------------
# 协议04 Workforce Planning：需求基线与 DAG 校验
# ---------------------------------------------------------------------------


def test_04_requirement_brief_carries_hard_constraints():
    """需求基线承载范围/排除项/缺口/验收/资源授权。"""
    brief = RequirementBrief(
        revision=1,
        source_ref="chat-42",
        business_goal="比较三家供应商并给出采购建议",
        scope=["对比价格与交付周期"],
        exclusions=["不要下单", "不要联系供应商"],
        inputs=["三家供应商名录"],
        input_gaps=["预算上限未知"],
        deliverables=["比较表", "建议报告"],
        acceptance=["每个维度有来源引用"],
        deadline="2026-09-30T18:00:00+08:00",
        risks=["未证实供应商产能"],
        resource_scope=["kb:procurement"],
        unconfirmed_assumptions=["假定报价含税"],
    )
    # 排除项是可校验约束而非聊天语气
    assert "不要下单" in brief.exclusions
    assert brief.resource_scope == ["kb:procurement"]
    # 澄清依据来自缺口
    assert brief.input_gaps == ["预算上限未知"]


def test_04_dag_rejects_dangling_dep_and_cycle():
    """悬空依赖与环都被拒绝（规划产物必须可执行）。"""
    dangling = DagPlan(
        nodes=[DagNode(node_key="a", deps=["ghost"])],
    )
    with pytest.raises(ValueError, match="不存在"):
        validate_dag(dangling)
    cycle = DagPlan(
        nodes=[
            DagNode(node_key="a", deps=["b"]),
            DagNode(node_key="b", deps=["a"]),
        ],
    )
    with pytest.raises(ValueError, match="环"):
        validate_dag(cycle)


# ---------------------------------------------------------------------------
# 协议05 Task Contract：版本身份向量
# ---------------------------------------------------------------------------


def test_05_task_contract_identity_vector():
    """任务契约绑定需求/计划/指派/上下文完整版本向量。"""
    contract = TaskContract(
        task_id="fe-login",
        run_id="run-1",
        plan_revision=2,
        assignment_revision=1,
        requirement_revision=3,
        context_version=4,
        owner_display="王经理",
        risk_level="low",
        allow_subtask_split=False,
        objective="实现登录页",
    )
    assert contract.plan_revision == 2
    assert contract.assignment_revision == 1
    assert contract.requirement_revision == 3
    assert contract.context_version == 4
    assert contract.risk_level == "low"
    # 自由递归委派默认关闭
    assert contract.allow_subtask_split is False
    # 旧式最小构造仍兼容（identity 缺省不报错）
    legacy = TaskContract(task_id="n1", objective="o")
    assert legacy.plan_revision == 0
    assert legacy.risk_level == "low"


def test_05_task_contract_risk_level_validated():
    """风险等级只接受三档（非法值拒绝而非静默归低）。"""
    with pytest.raises(ValidationError):
        TaskContract(task_id="n1", objective="o", risk_level="urgent")


# ---------------------------------------------------------------------------
# 协议06 Context Protocol：五类上下文版本向量
# ---------------------------------------------------------------------------


def test_06_context_vector_five_revisions():
    """五类上下文各自独立递增，工具进度不提升全局版本。"""
    vector = ContextVector()
    assert vector.global_revision == 1
    assert vector.task_revision == 1
    assert vector.employee_revision == 1
    assert vector.execution_revision == 1
    assert vector.result_revision == 1
    # 执行进度推进不影响全局决策版本
    vector.execution_revision += 1
    assert vector.global_revision == 1


def test_06_context_bundle_is_versioned_medium():
    """上下文束是唯一传递介质且版本化（禁止聊天记录透传）。"""
    bundle = ContextBundle()
    bundle.global_ctx = {"decision": "API 口径以 OpenAPI v2 为准"}
    bundle.version = 1
    assert bundle.task_ctx == {}
    assert bundle.execution_ctx == {}
    assert bundle.version == 1


# ---------------------------------------------------------------------------
# 协议07 Skill Loading：必需技能缺失即阻塞
# ---------------------------------------------------------------------------


def test_07_missing_required_skill_blocks():
    """必需技能未选中即阻塞；非必需可跳过但必须解释。"""
    selections = [
        SkillSelection(
            skill_key="kb_search",
            required=True,
            selected=False,
            skip_reason="候选排序靠后",
        ),
        SkillSelection(
            skill_key="chart_render",
            required=False,
            selected=False,
            skip_reason="本任务无图表需求",
        ),
        SkillSelection(skill_key="doc_write", required=True, selected=True, version="v3"),
    ]
    # 排序靠后不能裁掉必需技能
    assert missing_required_skills(selections) == ["kb_search"]
    # 非必需跳过有解释
    assert selections[1].skip_reason == "本任务无图表需求"
    # 全部就绪时无阻塞
    selections[0].selected = True
    assert missing_required_skills(selections) == []


# ---------------------------------------------------------------------------
# 协议08 Tool Calling：三类成功与副作用状态
# ---------------------------------------------------------------------------


def test_08_tool_observation_distinguishes_success_layers():
    """传输/执行/业务效果三类成功分开；副作用未知不可自动重试。"""
    # 传输成功但业务效果未确认（如下游已受理但回执未达）
    observation = ToolObservation(
        tool_key="order_create",
        status="success",
        transport_ok=True,
        executed=True,
        business_effect_confirmed=False,
        side_effect_state="unknown",
        retryable=False,
        summary="订单接口返回 200 但无回执编号",
    )
    assert observation.executed is True
    assert observation.business_effect_confirmed is False
    assert observation.side_effect_state == "unknown"
    # 副作用未知时禁止声明可安全重试
    assert observation.retryable is False
    # usage_ref 为空表示消耗未知
    assert observation.usage_ref == ""


# ---------------------------------------------------------------------------
# 协议09 Result Protocol：解析降级与用量明示
# ---------------------------------------------------------------------------


def test_09_result_contract_unknown_usage_is_explicit():
    """未上报用量是"未知"而非零（账本不得按零结算）。"""
    result = ResultContract(task_id="n1")
    assert result.token_cost == 0
    assert result.usage_reported is False
    # 上报后语义切换
    result.usage_reported = True
    result.token_cost = 520
    assert result.usage_reported is True


def test_09_result_contract_needs_review_degradation():
    """自由文本降级必须带 needs_review 标记（不冒充结构化成功）。"""
    degraded = ResultContract(
        task_id="n1",
        result_text="我完成了（无 JSON 回执）",
        needs_review=True,
    )
    assert degraded.needs_review is True
    assert degraded.result_text != ""


# ---------------------------------------------------------------------------
# 协议10 Verification：UNKNOWN 不等于 PASS
# ---------------------------------------------------------------------------


def test_10_fail_without_issues_escalates():
    """FAIL 但无具体问题 = 无法裁决 → ESCALATE（团队严格语义）。"""
    verdict = parse_verdict(
        _fence({"verdict": "FAIL", "reason": "不达标"}),
        task_id="n1",
        attempt=1,
    )
    assert verdict.verdict == VERDICT_ESCALATE


def test_10_pass_requires_exact_verdict():
    """只有显式 PASS 才通过；小写归一化，模糊表述拒绝。"""
    assert parse_verdict(
        _fence({"verdict": "pass", "reason": "ok"}),
        task_id="n1",
        attempt=1,
    ).verdict == VERDICT_PASS
    assert parse_verdict(
        _fence({"verdict": "PASSED", "reason": "自认为完成"}),
        task_id="n1",
        attempt=1,
    ).verdict == VERDICT_ESCALATE


def test_10_verdict_binds_context_revision():
    """裁决结果回填上下文版本（验收记录可绑定依据版本）。"""
    verdict = parse_verdict(
        _fence({"verdict": "PASS", "reason": "覆盖全部标准"}),
        task_id="final",
        attempt=1,
        context_revision=7,
    )
    assert verdict.context_revision == 7


# ---------------------------------------------------------------------------
# 协议11 Repair：结构化返工指令
# ---------------------------------------------------------------------------


def test_11_repair_contract_requires_original_task():
    """节点级返工必须知道被返工的原节点（缺省拒绝）。"""
    with pytest.raises(ValidationError):
        RepairContract(issues=["缺定价"])
    repair = RepairContract(
        original_task="be-api",
        issues=["字段命名与前端不一致"],
        expected_change=["改用 OpenAPI v2 字段名"],
        preserve=["已通过的路由逻辑"],
        acceptance=["字段对照 OpenAPI v2 全部一致"],
        attempt=1,
    )
    assert repair.original_task == "be-api"
    # 复验标准不被执行者改写（由调用方传入任务标准）
    assert repair.acceptance == ["字段对照 OpenAPI v2 全部一致"]


def test_11_judge_prompt_declares_repair_discipline():
    """裁决 prompt 固定输出纪律：无法判断时不得给 PASS。"""
    prompt = render_judge_prompt(
        JudgeRequest(objective="实现登录页", criteria=["含表单校验"]),
    )
    assert "无法判断时 verdict 填 FAIL" in prompt


# ---------------------------------------------------------------------------
# 协议12 Re-plan：修订链与失效范围
# ---------------------------------------------------------------------------


def test_12_plan_revision_keeps_history():
    """重规划生成新修订并记录被取代版本与失效范围（不删旧图）。"""
    revision = PlanRevision(
        kind="plan",
        revision=3,
        reason="API 口径冲突导致集成节点失效",
        superseded_revision=2,
        invalid_scope=["integration", "final"],
    )
    assert revision.superseded_revision == 2
    assert revision.invalid_scope == ["integration", "final"]
    # 需求/上下文修订共用同一结构（kind 区分）
    assert PlanRevision(kind="requirement", revision=2).kind == "requirement"


# ---------------------------------------------------------------------------
# 协议13 Memory：作用域与组织经验晋级
# ---------------------------------------------------------------------------


def test_13_memory_scopes_and_org_promotion():
    """四种记忆作用域互异；组织经验晋级必须走完治理步骤。"""
    scopes = {
        MEMORY_SCOPE_WORKING,
        MEMORY_SCOPE_TASK,
        MEMORY_SCOPE_EMPLOYEE,
        MEMORY_SCOPE_ORG,
    }
    assert len(scopes) == 4
    # 晋级顺序：提案→脱敏→去重→批准→发布（缺步不得共享）
    assert MEMORY_ORG_PROMOTION_STEPS == (
        "propose",
        "sanitize",
        "dedupe",
        "approve",
        "publish",
    )


def test_13_subtask_delegation_default_off():
    """成员内部递归委派默认关闭（继承父契约需显式开启）。"""
    contract = TaskContract(task_id="n1", objective="o")
    assert contract.allow_subtask_split is False


# ---------------------------------------------------------------------------
# 协议14 Checkpoint：回执关闭才结算
# ---------------------------------------------------------------------------


def test_14_lifecycle_receipt_usage_semantics():
    """回执 usage 未知明示（usage_reported=False 不按零结算）。"""
    receipt = HarnessLifecycleReceipt(execution_id="exec-1")
    assert receipt.usage_reported is False
    receipt.usage_reported = True
    receipt.usage = {"total_tokens": 210}
    assert receipt.usage["total_tokens"] == 210


def test_14_receipt_phase_only_terminal_closes():
    """创建/启动/流式都不是关闭阶段（不能提前结算尝试）。"""
    for open_phase in (RECEIPT_PHASE_CREATED, RECEIPT_PHASE_STARTED, "streaming"):
        assert HarnessLifecycleReceipt(execution_id="e", phase=open_phase).is_terminal() is False


# ---------------------------------------------------------------------------
# 协议15 Human Escalation：决定绑定修订
# ---------------------------------------------------------------------------


def test_15_decision_binding_expected_revision():
    """批准绑定具体修订：版本一致才有效，过期批准拒绝。"""
    decision = HumanDecision(
        decision_id="dec-1",
        action="approve_plan",
        expected_revision=2,
        comment="同意第二轮计划",
    )
    assert decision_matches(decision, current_revision=2) is True
    # 计划已推进到 rev3：旧批准不可放行新内容
    assert decision_matches(decision, current_revision=3) is False


def test_15_decision_actions_frozen():
    """决定动作枚举冻结（前端不自创授权语义）。"""
    for action in (
        "confirm_requirement",
        "approve_plan",
        "approve_action",
        "resume",
        "cancel",
        "handover",
    ):
        HumanDecision(decision_id="d", action=action)
    with pytest.raises(ValidationError):
        HumanDecision(decision_id="d", action="force_pass")


# ---------------------------------------------------------------------------
# 协议16 Governance：约束合成
# ---------------------------------------------------------------------------


def test_16_policy_composition_deny_wins():
    """多层裁决合成：拒绝 > 询问 > 允许；空输入保守询问。"""
    platform = PolicyDecision(decision="allow", audit_ref="a-plat")
    tenant = PolicyDecision(decision="ask", reason="需审批", audit_ref="a-ten")
    team = PolicyDecision(decision="deny", reason="越权", audit_ref="a-team")
    # 拒绝优先
    assert compose_policy_decisions([platform, tenant, team]).decision == "deny"
    # 其次询问
    assert compose_policy_decisions([platform, tenant]).decision == "ask"
    # 全部允许 → 允许
    assert compose_policy_decisions([platform]).decision == "allow"
    # 空输入不留裸放行
    assert compose_policy_decisions([]).decision == "ask"


def test_16_limit_composition_takes_min_finite():
    """多层上限取最小有限值；0 表示未配置层而非无限。"""
    assert min_positive_limit(100, 30, 0) == 30
    assert min_positive_limit(0, 0) == 0
    assert min_positive_limit(50) == 50


# ---------------------------------------------------------------------------
# 协议17 Agent Trace：跨层关联
# ---------------------------------------------------------------------------


def test_17_trace_link_connects_layers():
    """团队运行/节点/尝试 ↔ 员工执行/会话 ↔ span 关联可建。"""
    link = TraceLink(
        team_run_id="run-1",
        node_key="be-api",
        attempt_id="att-3",
        agent_run_id="ar-88",
        session_id="sess-be",
        span_ids=["span-1", "span-2"],
    )
    assert link.team_run_id == "run-1"
    assert link.agent_run_id == "ar-88"
    assert link.span_ids == ["span-1", "span-2"]


# ---------------------------------------------------------------------------
# 技术专家案例阶段模拟（原文第二十五章：全程固定输入，无外部系统）
# ---------------------------------------------------------------------------


def test_tech_expert_case_stage_simulation():
    """L0 需求→澄清→Global Context v1→能力选择→计划/契约→局部执行
    →结构化结果→API 口径冲突→Repair→汇总→最终全局验收 的阶段模拟。

    每一步断言输入/输出对象、版本与停止条件；使用可观察对象，
    不以模型内部思维链作为协议内容。
    """
    # 阶段1 L0：需求基线（含明确排除项与缺口）
    brief = RequirementBrief(
        revision=1,
        business_goal="开发登录页并对接认证 API",
        scope=["登录表单", "错误提示"],
        exclusions=["不做注册页"],
        input_gaps=["登录失败提示文案未定"],
        acceptance=["表单校验通过", "字段对照 OpenAPI v2"],
        resource_scope=["repo:web", "kb:auth-spec"],
    )
    # 阶段2 缺口澄清：答复进入 Clarification（停止条件=缺口清空）
    clarification = Clarification(
        questions=["登录失败提示文案用哪一套？"],
        answers={},
    )
    clarification.answers["登录失败提示文案用哪一套？"] = "统一用『账号或密码错误』"
    assert len(clarification.answers) == 1
    # 澄清答复后需求修订推进 rev2
    brief.revision = 2
    brief.input_gaps = []
    assert brief.input_gaps == []

    # 阶段3 Global Context v1：版本化事实（唯一传递介质）
    bundle = ContextBundle()
    bundle.global_ctx = {"decision": "API 口径以 OpenAPI v2 为准"}
    bundle.version = 1

    # 阶段4 能力发现与选择：必需技能缺失即阻塞，就绪后放行
    selections = [
        SkillSelection(skill_key="kb_search", required=True, selected=True, version="v1"),
        SkillSelection(skill_key="doc_write", required=True, selected=True, version="v2"),
        SkillSelection(
            skill_key="chart_render",
            required=False,
            selected=False,
            skip_reason="登录页无图表",
        ),
    ]
    assert missing_required_skills(selections) == []

    # 阶段5 计划：前端/后端并行 + 集成 + 最终汇总（DAG 合法）
    plan = DagPlan(
        nodes=[
            DagNode(node_key="fe-login", objective="实现登录页"),
            DagNode(node_key="be-api", objective="对接认证 API"),
            DagNode(node_key="integration", deps=["fe-login", "be-api"], node_type="integration"),
            DagNode(node_key="final", deps=["integration"], node_type="final"),
        ],
    )
    waves = validate_dag(plan)
    assert waves[0] == ["be-api", "fe-login"]
    assert waves[-1] == ["final"]

    # 阶段6 任务契约：绑定完整版本向量
    contract = TaskContract(
        task_id="be-api",
        run_id="run-1",
        plan_revision=1,
        assignment_revision=1,
        requirement_revision=brief.revision,
        context_version=bundle.version,
        risk_level="low",
        objective="对接认证 API",
        quality_criteria=["字段对照 OpenAPI v2"],
    )
    assert contract.requirement_revision == 2
    assert contract.context_version == 1

    # 阶段7 L2 局部执行：结构化回执（工具观察区分传输/执行/效果）
    observation = ToolObservation(
        tool_key="repo_commit",
        transport_ok=True,
        executed=True,
        business_effect_confirmed=True,
        side_effect_state="committed",
        evidence_refs=["commit:abc123"],
    )
    assert observation.side_effect_state == "committed"
    result = ResultContract(
        task_id="be-api",
        status="COMPLETED",
        result_text="认证 API 已对接",
        evidence=["commit:abc123"],
        token_cost=480,
        usage_reported=True,
    )

    # 阶段8 L1 节点验收：API 口径冲突 → FAIL（可返工）
    fail_receipt = _fence(
        {
            "verdict": "FAIL",
            "reason": "字段命名与前端不一致",
            "issues": ["login_id 应为 user_id（OpenAPI v2）"],
            "expected_change": ["改用 user_id 字段名"],
            "preserve": ["已通过的路由逻辑"],
            "failure_kind": "repairable",
        },
    )
    verdict = parse_verdict(
        fail_receipt,
        task_id="be-api",
        attempt=1,
        acceptance=["字段对照 OpenAPI v2"],
        repair_model=RepairContract,
        context_revision=bundle.version,
    )
    assert verdict.verdict == VERDICT_FAIL
    assert verdict.repair is not None
    assert verdict.repair.original_task == "be-api"
    assert verdict.failure_kind == "repairable"
    # 停止条件检查：返工轮次在 RunPolicy 限额内
    policy = RunPolicy(max_repair_per_node=3)
    assert verdict.repair.attempt <= policy.max_repair_per_node

    # 阶段9 返工复验：同一标准复验通过（复验标准不被改写）
    pass_receipt = _fence(
        {"verdict": "PASS", "reason": "字段对照 OpenAPI v2 全部一致"},
    )
    recheck = parse_verdict(
        pass_receipt,
        task_id="be-api",
        attempt=2,
        acceptance=verdict.repair.acceptance,
        context_revision=bundle.version,
    )
    assert recheck.verdict == VERDICT_PASS
    assert recheck.context_revision == 1

    # 阶段10 汇总与最终全局验收：对照需求级标准（而非仅汇总文字）
    final_request = JudgeRequest(
        objective=brief.business_goal,
        criteria=brief.acceptance,
        output_text="登录页已交付；认证 API 已对接；未做注册页（按排除项）",
        context_revision=1,
    )
    final_prompt = render_judge_prompt(final_request)
    assert "表单校验通过" in final_prompt
    final_verdict = parse_verdict(
        _fence({"verdict": "PASS", "reason": "覆盖全部验收标准"}),
        task_id="final",
        attempt=1,
        acceptance=brief.acceptance,
        context_revision=1,
    )
    assert final_verdict.verdict == VERDICT_PASS

    # 阶段11 Trace 关联留痕：run/node/attempt ↔ agent 执行
    link = TraceLink(
        team_run_id="run-1",
        node_key="be-api",
        attempt_id="att-1",
        agent_run_id="ar-88",
        session_id="sess-be",
        span_ids=["span-1"],
    )
    assert link.node_key == "be-api"

    # 阶段12 修订链登记：本次未重规划（返工在原授权内），计划仍 rev1
    assert PlanRevision(kind="plan", revision=1).superseded_revision == 0
    # 结果版本向量推进：执行/结果各 +1，全局决策未变
    vector = ContextVector()
    vector.execution_revision += 1
    vector.result_revision += 1
    assert vector.global_revision == 1
