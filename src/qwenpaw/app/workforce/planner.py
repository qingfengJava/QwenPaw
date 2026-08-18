# -*- coding: utf-8 -*-
"""Planning Engine：需求 → DagPlan（Plan-then-Execute 的一次性规划）。

规划路径（优先级从高到低）：

1. **orchestration 预置模板**：管理端在 expert_teams.orchestration
   配置的 DAG 模板（OrchestrationSpec 校验），不依赖 LLM 规划质量；
2. **中央大脑 LLM 生成**：lead 成员专家单次结构化输出 DagPlan
   （强模型；校验失败带错误重试一次，仍失败则报错终止——不静默
   修复非法 DAG）；需求不明时输出澄清问题清单（Clarification，
   run 置 awaiting_confirm，用户答复后重入规划）。

能力发现（Capability Discovery）：规划与契约构建时读取
``expert_skills`` 绑定（共享技能注册表为权威），把可用技能填入
TaskContract.available_skills（Skill=能力 / Tool=动作 严格分离）。

@author qingfeng
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..experts.models import (
    ExpertRecord,
    ExpertTeamRecord,
    TEAM_MEMBER_ROLE_LEAD,
    expert_agent_id,
)
from . import bundle as bundle_mod
from .contracts import (
    Clarification,
    ContextBundle,
    DagNode,
    DagPlan,
    NODE_TYPE_FINAL,
    NODE_TYPE_INTEGRATION,
    NODE_TYPE_TASK,
    OrchestrationSpec,
    TaskContract,
    validate_dag,
)

logger = logging.getLogger(__name__)

#: 围栏/裸 JSON 提取（与 delegator 相同约定；捕获组不可少：取 group(1)）
_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"(\{.*\})", re.DOTALL)

#: 默认的最终汇总节点 key（LLM 规划未给出 final 节点时自动补齐）
_DEFAULT_FINAL_KEY = "final-summary"


@dataclass
class PlanOutcome:
    """规划结果（三选一：plan 成功 / clarification 澄清 / error 失败）。"""

    #: 成功产出的任务图（与 clarification/error 互斥）
    plan: Optional[DagPlan] = None
    #: 需求不明时的澄清问题（run 将置 awaiting_confirm）
    clarification: Optional[Clarification] = None
    #: 失败原因（run 将置 failed 或提示重试）
    error: str = ""
    #: 规划来源：orchestration（模板）/ llm（中央大脑生成）
    source: str = "orchestration"


def build_task_contract(
    node: DagNode,
    expert: Optional[ExpertRecord],
    bundle: ContextBundle,
    member_skills: Optional[Dict[str, List[str]]] = None,
    run_id: str = "",
) -> TaskContract:
    """从 DAG 节点 + 上下文束构建 TaskContract（纯函数，可单测）。

    - ``global_context`` 携带版本化快照（含 context_version）；
    - ``upstream_summaries`` 仅投影本节点 deps 声明的上游摘要；
    - ``available_skills`` 来自 expert_skills 绑定（能力发现）；
    - final/integration 节点（expert 为空）由中央大脑自执行。
    """
    # 全局快照注入版本号（子员工可见其依据的事实版本）
    global_snapshot = dict(bundle.global_ctx)
    global_snapshot["context_version"] = bundle.version
    # 依赖描述：上游节点的目标与完成状态
    dependencies: Dict[str, str] = {}
    for dep in node.deps:
        summary = bundle.execution_ctx.get(dep)
        if summary:
            dependencies[dep] = f"{summary.get('label', dep)}（状态 {summary.get('status')}）"
        else:
            dependencies[dep] = "上游节点"
    # 能力发现：成员技能绑定（expert_skills 权威）
    skills: List[str] = []
    if expert and member_skills:
        skills = list(member_skills.get(expert.id, []))
    # 默认验收标准（DAG 节点未显式给出时）
    criteria = [
        "产出完整覆盖期望交付物",
        "与既定决策和上游产出一致",
    ]
    # 组装契约（objective 缺省时按节点类型给兜底文案）
    objective = node.objective or f"完成节点 {node.node_key} 的任务"
    return TaskContract(
        task_id=node.node_key,
        objective=objective,
        global_context=global_snapshot,
        parent_decision=list(bundle.global_ctx.get("decisions", [])),
        dependencies=dependencies,
        expected_output=list(node.expected_output),
        constraints=["遵守全局背景中的既定决策，不得自行偏离"],
        quality_criteria=criteria,
        available_skills=skills,
        available_tools=[],
        upstream_summaries=bundle_mod.upstream_summaries(bundle, node),
    )


def _validate_plan_members(
    plan: DagPlan,
    member_ids: set,
) -> Optional[str]:
    """校验节点指派均在团队成员内；返回错误描述（None=通过）。

    final/integration 节点由中央大脑自执行，允许 assignee 为空。
    """
    for node in plan.nodes:
        # 中央大脑自执行节点跳过成员校验
        if node.node_type in (NODE_TYPE_FINAL, NODE_TYPE_INTEGRATION) and not node.assignee_expert_id:
            continue
        # task/repair 节点必须指派给真实成员
        if node.assignee_expert_id and node.assignee_expert_id not in member_ids:
            return f"节点 {node.node_key} 指派了非成员专家 {node.assignee_expert_id}"
        if node.node_type == NODE_TYPE_TASK and not node.assignee_expert_id:
            return f"task 节点 {node.node_key} 缺少指派专家"
    return None


def _ensure_final_node(plan: DagPlan) -> DagPlan:
    """确保 plan 存在 final 汇总节点（LLM 遗漏时自动补齐）。"""
    # 已有 final 节点则原样返回
    for node in plan.nodes:
        if node.node_type == NODE_TYPE_FINAL:
            return plan
    # 以全部 task 节点为依赖补一个 final 节点（中央大脑自执行）
    task_keys = [n.node_key for n in plan.nodes if n.node_type == NODE_TYPE_TASK]
    plan.nodes.append(
        DagNode(
            node_key=_DEFAULT_FINAL_KEY,
            deps=task_keys,
            node_type=NODE_TYPE_FINAL,
            objective="汇总全部成员产出，形成最终交付结果",
            expected_output=["最终汇总报告"],
        )
    )
    return plan


def _parse_plan_json(text: str) -> Dict[str, Any]:
    """从 LLM 回复中提取规划 JSON（围栏优先，裸 JSON 兜底）。"""
    # 围栏提取
    match = _JSON_FENCE_RE.search(text)
    if match is None:
        match = _BARE_JSON_RE.search(text)
    if match is None:
        raise ValueError("回复中未找到 JSON")
    return json.loads(match.group(1))


def _plan_from_llm_payload(
    data: Dict[str, Any],
    member_ids: set,
) -> PlanOutcome:
    """把 LLM 规划 JSON 转换为校验通过的 DagPlan（或澄清/错误）。"""
    # 需求不明：优先返回澄清清单（不进入执行）
    if data.get("need_clarification"):
        clarification = Clarification(
            questions=list(data.get("questions", [])),
            options=dict(data.get("options", {})),
        )
        return PlanOutcome(clarification=clarification, source="llm")
    # 构造 DagPlan 并做图校验（重复 key / 悬空依赖 / 环）
    plan = DagPlan(
        nodes=[DagNode.model_validate(n) for n in data.get("nodes", [])],
        plan_note=str(data.get("plan_note", "")),
        source="llm",
    )
    try:
        validate_dag(plan)
    except ValueError as exc:
        return PlanOutcome(error=f"DAG 校验失败: {exc}", source="llm")
    # 成员存在性校验（防虚构成员）
    member_error = _validate_plan_members(plan, member_ids)
    if member_error:
        return PlanOutcome(error=member_error, source="llm")
    # 自动补齐 final 汇总节点（中央大脑自执行）
    plan = _ensure_final_node(plan)
    return PlanOutcome(plan=plan, source="llm")


def _render_planning_prompt(
    goal: str,
    team: ExpertTeamRecord,
    members: List[ExpertRecord],
    bundle: ContextBundle,
    retry_error: str = "",
) -> str:
    """渲染中央大脑的规划 prompt（结构化输出约定 + 成员花名册）。"""
    lines = ["# 团队任务规划（你是中央大脑，负责需求理解与任务拆解）"]
    # 原始需求与澄清历史
    lines.append("\n## 用户需求")
    lines.append(goal)
    if bundle.task_ctx.get("clarifications"):
        lines.append("\n## 历史澄清问答")
        for qa in bundle.task_ctx["clarifications"]:
            lines.append(f"- 问：{qa.get('question')}　答：{qa.get('answer')}")
    # 团队成员花名册（id 必须原样引用，禁止虚构）
    lines.append("\n## 可委派的团队成员（assignee_expert_id 必须取自下表 id）")
    for expert in members:
        binding = next(
            (m for m in team.members if m.expert_id == expert.id),
            None,
        )
        role = "主理人" if binding and binding.member_role == TEAM_MEMBER_ROLE_LEAD else "成员"
        title = f" · {expert.title}" if expert.title else ""
        lines.append(
            f"- id: `{expert.id}`　名称: {expert.name}{title}（{role}）"
            f"　专长: {expert.description or '（未填）'}"
        )
    # 输出格式约定
    lines.append("\n## 输出要求（只输出一个 ```json 代码块，不要多余内容）")
    lines.append("```json")
    lines.append("{")
    lines.append('  "need_clarification": false,')
    lines.append('  "questions": ["仅当 need_clarification 为 true 时填写，向用户确认的问题"],')
    lines.append('  "options": {"问题一": ["候选答案A", "候选答案B"]},')
    lines.append('  "nodes": [')
    lines.append('    {"node_key": "英文短标识", "deps": ["上游node_key"], "assignee_expert_id": "成员id", "node_type": "task", "objective": "该节点目标", "expected_output": ["交付物"]}')
    lines.append("  ],")
    lines.append('  "plan_note": "拆解思路（展示给用户）"')
    lines.append("}")
    lines.append("```")
    lines.append("\n规划约束：无依赖的节点会被并行执行；最后一个汇总节点可用 node_type=\"final\" 且不填 assignee（由你执行）。")
    # 重试时附带上一轮校验错误（定向修正而非盲重试）
    if retry_error:
        lines.append(f"\n## 上一次规划被驳回的原因（必须修正）\n{retry_error}")
    return "\n".join(lines)


def pick_template_nodes(
    spec: OrchestrationSpec,
    goal: str,
) -> tuple[List[DagNode], str]:
    """快慢链选择（纯函数，可单测）：按 goal 的意图规则信号挑选模板。

    - 命中复杂信号（多交付物/跨专业/编排动词）→ 标准链 ``nodes``；
    - 未命中且 ``fast_nodes`` 非空 → 快速链（小需求轻量路径）；
    - 其余（无快速链配置）→ 标准链兜底。
    返回 ``(节点集, 来源标记)``——来源标记写入 DagPlan.source 与
    PlanOutcome.source（RunDetail/事件可观察实际走了哪条链）。
    """
    # 延迟导入：intent 属 workforce 包但非契约依赖，planner 侧引用
    from .intent import INTENT_COMPLEX, classify_by_rules

    ruled = classify_by_rules(goal)
    if ruled is not None and ruled.intent == INTENT_COMPLEX:
        return spec.nodes, "orchestration"
    if spec.fast_nodes:
        return spec.fast_nodes, "orchestration_fast"
    return spec.nodes, "orchestration"


async def plan_run(
    goal: str,
    team: ExpertTeamRecord,
    members: List[ExpertRecord],
    bundle: ContextBundle,
) -> PlanOutcome:
    """执行规划：模板优先（快慢链选择）→ 中央大脑 LLM（失败重试一次）。"""
    member_ids = {expert.id for expert in members}
    # ---- 路径 1：orchestration 预置模板（不依赖 LLM） ----
    raw_orch = team.orchestration or {}
    if isinstance(raw_orch, dict) and raw_orch.get("nodes"):
        try:
            # 严格 schema 校验（读写唯一入口，拦截漂移）
            spec = OrchestrationSpec.model_validate(raw_orch)
        except Exception as exc:  # noqa: BLE001 - 模板损坏按失败处理
            return PlanOutcome(error=f"orchestration 模板非法: {exc}")
        # 模板显式关闭运行时编排 → 回退提示词级团队语义
        if not spec.runtime_enabled:
            return PlanOutcome(error="该团队未启用运行时编排（runtime_enabled=false）")
        # 快慢链选择：复杂信号→标准链；小需求→快速链（若配置）
        nodes, source = pick_template_nodes(spec, goal)
        # 图校验 + 成员校验（快速链与标准链同一套严格校验）
        plan = DagPlan(nodes=nodes, plan_note=spec.plan_note, source=source)
        try:
            validate_dag(plan)
        except ValueError as exc:
            return PlanOutcome(error=f"orchestration 模板 DAG 非法（{source}）: {exc}")
        member_error = _validate_plan_members(plan, member_ids)
        if member_error:
            return PlanOutcome(error=f"orchestration 模板错误（{source}）: {member_error}")
        # 模板路径同样保证 final 节点存在
        plan = _ensure_final_node(plan)
        return PlanOutcome(plan=plan, source=source)
    # ---- 路径 2：中央大脑 LLM 规划（lead 成员，一次生成 + 一次修正重试） ----
    # lead 成员优先；无 lead 标记时取第一名成员（团队至少一名成员）
    lead = next(
        (e for e in members if _is_lead(team, e.id)),
        members[0] if members else None,
    )
    if lead is None:
        return PlanOutcome(error="团队没有可用的成员专家")
    # 第一轮规划
    prompt = _render_planning_prompt(goal, team, members, bundle)
    outcome = await _llm_plan_once(lead, prompt, member_ids)
    # 校验失败：携带错误定向重试一次（禁止静默修复非法 DAG）
    if outcome.error and not outcome.clarification:
        retry_prompt = _render_planning_prompt(goal, team, members, bundle, retry_error=outcome.error)
        outcome = await _llm_plan_once(lead, retry_prompt, member_ids)
        # 重试仍失败 → 报错终止（run 置 failed，用户可改需求后重建）
        if outcome.error and not outcome.clarification:
            return PlanOutcome(error=f"中央大脑规划两次未通过校验: {outcome.error}", source="llm")
    return outcome


def _is_lead(team: ExpertTeamRecord, expert_id: str) -> bool:
    """判断某成员是否为团队主理人（lead）。"""
    for member in team.members:
        if member.expert_id == expert_id and member.member_role == TEAM_MEMBER_ROLE_LEAD:
            return True
    return False


async def _llm_plan_once(
    lead: ExpertRecord,
    prompt: str,
    member_ids: set,
) -> PlanOutcome:
    """单次 LLM 规划调用（通道异常按 error 返回，不抛出）。"""
    # 延迟导入避免循环依赖（delegator 不依赖 planner）
    from .delegator import call_expert_text
    try:
        # 走既有 A2A 通道调 lead 专家（每次规划独立 session，不复用）
        reply, _session = await call_expert_text(
            expert_agent_id(lead.id),
            prompt,
            session_id=None,
        )
        data = _parse_plan_json(reply)
    except Exception as exc:  # noqa: BLE001 - 通道/解析异常统一按规划失败
        return PlanOutcome(error=f"规划调用失败: {exc}", source="llm")
    # JSON 合法 → 转换并校验
    return _plan_from_llm_payload(data, member_ids)
