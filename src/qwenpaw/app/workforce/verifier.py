# -*- coding: utf-8 -*-
"""Verification Engine：L1 中央大脑的结构化裁决。

裁决规则本身（prompt 骨架、JSON 容错解析、失败归因三分类、返工指令
字段集）以 :mod:`qwenpaw.verification.kernel` 为**单一来源**，L2 数字员工
的独立验收门复用同一内核；本模块只承载专家团专属语义：

1. **规则预检**：子员工自报 FAILED → 直接 FAIL（无需 LLM），并按结构性
   关键词判定 ``structural``（成员权限/工具缺失时反复返工只烧预算）；
2. **熔断双保险**：``repair_count`` 超上限 → 直接 ESCALATE（引擎层同样
   检查，本层兜底防绕过）；
3. **裁决通道**：走 lead 专家的 A2A（:func:`call_expert_text`），与委派
   同一套基础设施，不新建通道。

@author qingfeng
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from ...verification.kernel import (
    FAILURE_KIND_DEPENDENCY_CHANGED,
    FAILURE_KIND_REPAIRABLE,
    FAILURE_KIND_STRUCTURAL,
    JudgeRequest,
    Verdict,
    VERDICT_ESCALATE,
    VERDICT_FAIL,
    parse_verdict,
    render_judge_prompt,
)
from ..experts.models import expert_agent_id
from .contracts import (
    RESULT_STATUS_FAILED,
    RepairContract,
    ResultContract,
    RunPolicy,
    TaskContract,
)
from .delegator import call_expert_text

logger = logging.getLogger(__name__)

#: 自报 FAILED 的结构性关键词（命中即判 structural，fast-fail 省返工轮）：
#: 成员因工具缺失/权限不足/能力不具备失败时，反复返工只会烧预算
_STRUCTURAL_ISSUE_RE = re.compile(
    r"没有权限|无权限|未授权|权限不足|缺少工具|没有.{0,8}工具|缺.{0,4}工具"
    r"|无法调用工具|无法访问|不支持|不具备|无此能力|无法执行该任务"
    r"|no tool|not authorized|forbidden|permission denied|not available",
    re.IGNORECASE,
)


def _structural_failure(issues: list[str]) -> bool:
    """判断自报失败原因是否属于返工无意义的结构性失败。"""
    # 任一问题命中结构性关键词即视为能力/权限缺口
    return any(_STRUCTURAL_ISSUE_RE.search(item) for item in issues)


async def verify(
    verifier_expert_id: str,
    contract: TaskContract,
    result: ResultContract,
    policy: RunPolicy,
    repair_count: int = 0,
    previous_repair: Optional[RepairContract] = None,
) -> Verdict:
    """执行一次节点验收：规则预检 → LLM 裁决 → 结构化 Verdict。

    Args:
        verifier_expert_id: 裁决人格所属专家 ID（通常为团队 lead，即
            中央大脑人格）。
        contract: 被验收节点的任务契约。
        result: 子员工回传的结果契约。
        policy: run 级熔断策略。
        repair_count: 该节点已发生的返工次数。
        previous_repair: 上轮返工指令（复验时叠加其复验标准）。

    Returns:
        :class:`Verdict`：PASS / FAIL（附 RepairContract）/ ESCALATE。
    """
    # 熔断双保险：已超返工上限不再消耗 LLM（引擎层同样拦截）。
    # 边界对齐 engine：==max 时本轮结果仍须验收（FAIL 后由引擎计数超限熔断）
    if repair_count > policy.max_repair_per_node:
        limit = policy.max_repair_per_node
        return Verdict(
            VERDICT_ESCALATE,
            reason=f"返工次数超上限（{repair_count}/{limit}），升级人工",
        )
    # 规则预检：子员工自报失败 → 直接 FAIL（省一次 LLM），归因决定处置路径
    if result.status == RESULT_STATUS_FAILED:
        # 自报问题缺省时给占位文案，保证 RepairContract.issues 非空
        issues = [str(i) for i in result.issues or ["未说明原因"]]
        return Verdict(
            VERDICT_FAIL,
            repair=RepairContract(
                original_task=contract.task_id,
                issues=["子员工自报执行失败：" + "; ".join(issues)],
                expected_change=["分析失败原因并重新完成任务"],
                preserve=[],
                acceptance=list(contract.quality_criteria),
                attempt=repair_count + 1,
            ),
            reason="子员工自报 FAILED",
            failure_kind=(
                FAILURE_KIND_STRUCTURAL
                if _structural_failure(issues)
                else FAILURE_KIND_REPAIRABLE
            ),
        )
    # LLM 裁决（内核渲染 prompt；通道异常升级人工）。
    # call_expert_text 返回三元组 (回复, session_id, total_tokens)——
    # 二元组解包会让验收通道 100% 抛 ValueError 全部 ESCALATE
    # （真实 E2E 暴露：monkeypatch 桩用错签名互相掩盖的典型）
    prompt = render_judge_prompt(
        JudgeRequest(
            objective=contract.objective,
            criteria=list(contract.quality_criteria),
            expected_output=list(contract.expected_output),
            output_text=result.result_text or str(result.result),
            status=result.status,
            confidence=result.confidence,
            issues=list(result.issues),
            previous_acceptance=list(
                previous_repair.acceptance if previous_repair else [],
            ),
        ),
    )
    try:
        reply, _session, _tokens = await call_expert_text(
            expert_agent_id(verifier_expert_id),
            prompt,
            session_id=None,
        )
    except Exception as exc:  # noqa: BLE001 - 验收通道异常升级人工
        logger.warning("验收通道异常 task=%s: %s", contract.task_id, exc)
        return Verdict(VERDICT_ESCALATE, reason=f"验收通道异常: {exc}")
    # 解析裁决（L1 用 RepairContract 承载返工指令，复验口径取节点契约标准）
    return parse_verdict(
        reply,
        task_id=contract.task_id,
        attempt=repair_count + 1,
        acceptance=contract.quality_criteria,
        repair_model=RepairContract,
    )


# 兼容既有 import 路径（engine 与集成测试从本模块取归因常量与 Verdict）
__all__ = [
    "FAILURE_KIND_DEPENDENCY_CHANGED",
    "FAILURE_KIND_REPAIRABLE",
    "FAILURE_KIND_STRUCTURAL",
    "Verdict",
    "verify",
]
