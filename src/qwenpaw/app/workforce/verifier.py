# -*- coding: utf-8 -*-
"""Verification Engine：中央大脑对照验收标准的结构化裁决。

裁决策略（规则优先，节省 token）：

1. **规则预检**：子员工自报 FAILED → 直接 FAIL（无需 LLM）；
2. **LLM 裁决**：对照 TaskContract.quality_criteria（复验时叠加
   RepairContract.acceptance）输出结构化 verdict JSON；解析失败或
   无法裁决 → ESCALATE（升级人工，绝不误判 PASS）；
3. **熔断双保险**：repair_count 超上限 → 直接 ESCALATE（引擎层
   同样检查，本层兜底防绕过）。

FAIL 时产出 RepairContract（issues / expected_change / preserve /
acceptance），返工不是"重新给一个新 Prompt"而是结构化修复指令。

@author qingfeng
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from ..experts.models import expert_agent_id
from .contracts import (
    RESULT_STATUS_FAILED,
    RepairContract,
    ResultContract,
    RunPolicy,
    TaskContract,
    VERDICT_ESCALATE,
    VERDICT_FAIL,
    VERDICT_PASS,
)
from .delegator import call_expert_text

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

#: 失败归因：可返工修复（默认；进入 RepairContract 返工循环）
FAILURE_KIND_REPAIRABLE = "repairable"
#: 失败归因：结构性失败（成员能力/工具/权限缺失，返工无意义 → 熔断升级）
FAILURE_KIND_STRUCTURAL = "structural"
#: 失败归因：依赖变更（上游产出与目标矛盾/缺失 → 全局 Re-plan）
FAILURE_KIND_DEPENDENCY_CHANGED = "dependency_changed"

#: 自报 FAILED 的结构性关键词（命中即判 structural，fast-fail 省返工轮）：
#: 成员因工具缺失/权限不足/能力不具备失败时，反复返工只会烧预算
_STRUCTURAL_ISSUE_RE = re.compile(
    r"没有权限|无权限|未授权|权限不足|缺少工具|没有.{0,8}工具|缺.{0,4}工具"
    r"|无法调用工具|无法访问|不支持|不具备|无此能力|无法执行该任务"
    r"|no tool|not authorized|forbidden|permission denied|not available",
    re.IGNORECASE,
)


@dataclass
class Verdict:
    """一次验收裁决的结果（PASS / FAIL（附 RepairContract）/ ESCALATE）。

    FAIL 时携带结构化归因 ``failure_kind``（Failure Analyzer 的
    裁决输入）：引擎据此分派 返工 / 熔断 / Re-plan 三路处置。
    """

    #: 裁决值：VERDICT_PASS / VERDICT_FAIL / VERDICT_ESCALATE
    verdict: str
    #: FAIL 时必须携带的返工契约
    repair: Optional[RepairContract] = None
    #: 裁决理由（展示给用户与留痕）
    reason: str = ""
    #: FAIL 归因：repairable / structural / dependency_changed
    failure_kind: str = FAILURE_KIND_REPAIRABLE


def _render_verify_prompt(
    contract: TaskContract,
    result: ResultContract,
    previous_repair: Optional[RepairContract] = None,
) -> str:
    """渲染中央大脑的验收裁决 prompt（对照标准输出结构化 verdict）。"""
    lines = ["# 任务验收裁决（你是中央大脑，负责检查子员工产出质量）"]
    # 委派事实回放（契约核心字段）
    lines.append("\n## 当初的委派")
    lines.append(f"- 目标：{contract.objective}")
    for item in contract.expected_output:
        lines.append(f"- 期望产出：{item}")
    for item in contract.quality_criteria:
        lines.append(f"- 验收标准：{item}")
    # 复验时叠加上轮返工的复验标准
    if previous_repair is not None:
        lines.append("\n## 上轮返工指令的复验标准")
        for item in previous_repair.acceptance:
            lines.append(f"- {item}")
    # 子员工回执（完整结果契约）
    lines.append("\n## 子员工回执（ResultContract）")
    lines.append(f"- 自报状态：{result.status}（置信度 {result.confidence}）")
    if result.issues:
        lines.append(f"- 自报问题：{'; '.join(result.issues)}")
    digest = result.result_text or str(result.result)
    # 回执正文截断（验收只需判断，超长部分截断）
    if len(digest) > 4000:
        digest = digest[:2000] + "\n…（中段截断）…\n" + digest[-1500:]
    lines.append(f"\n### 产出正文\n{digest}")
    # 输出格式约定
    lines.append("\n## 输出要求（只输出一个 ```json 代码块）")
    lines.append("```json")
    lines.append("{")
    lines.append('  "verdict": "PASS 或 FAIL",')
    lines.append('  "reason": "裁决理由（一句话）",')
    lines.append('  "issues": ["FAIL 时：具体问题"],')
    lines.append('  "expected_change": ["FAIL 时：每个问题对应的期望修改"],')
    lines.append('  "preserve": ["FAIL 时：不得破坏的已有内容"],')
    lines.append('  "failure_kind": "FAIL 时必填，三选一：')
    lines.append('    repairable=产出质量缺陷可返工修复 |')
    lines.append('    structural=成员能力/工具/权限缺失返工无意义 |')
    lines.append('    dependency_changed=上游产出与目标矛盾或缺失需全局重新规划"')
    lines.append("}")
    lines.append("```")
    lines.append("\n裁决纪律：标准全部满足才 PASS；只看产出是否达标，不做风格偏好评判；无法判断时 verdict 填 FAIL 并在 issues 写明信息缺口。")
    return "\n".join(lines)


def _parse_verdict(
    text: str,
    contract: TaskContract,
    attempt: int,
) -> Verdict:
    """解析裁决 JSON；解析失败一律 ESCALATE（绝不误判 PASS）。"""
    # 围栏优先，裸 JSON 兜底
    match = _JSON_FENCE_RE.search(text)
    if match is None:
        match = _BARE_JSON_RE.search(text)
    if match is None:
        return Verdict(
            VERDICT_ESCALATE,
            reason="验收器未输出结构化裁决，升级人工复核",
        )
    try:
        data = json.loads(match.group(1))
    except Exception:  # noqa: BLE001 - 解析失败升级人工
        return Verdict(
            VERDICT_ESCALATE,
            reason="验收器输出 JSON 非法，升级人工复核",
        )
    # PASS 直接通过（reason 保留裁决说明）
    if str(data.get("verdict", "")).upper() == VERDICT_PASS:
        return Verdict(VERDICT_PASS, reason=str(data.get("reason", "")))
    # FAIL 必须产出 RepairContract（issues 缺失则视为无法裁决）
    issues = [str(i) for i in data.get("issues", []) if str(i).strip()]
    if not issues:
        return Verdict(
            VERDICT_ESCALATE,
            reason="验收器判定 FAIL 但未给出具体问题，升级人工复核",
        )
    # 结构化归因（Failure Analyzer 的分派依据；非法值/缺省回退可返工）
    kind = str(data.get("failure_kind", FAILURE_KIND_REPAIRABLE)).strip().lower()
    if kind not in (
        FAILURE_KIND_REPAIRABLE,
        FAILURE_KIND_STRUCTURAL,
        FAILURE_KIND_DEPENDENCY_CHANGED,
    ):
        kind = FAILURE_KIND_REPAIRABLE
    # 组装返工契约（attempt 记录返工轮次）
    repair = RepairContract(
        original_task=contract.task_id,
        issues=issues,
        expected_change=[str(c) for c in data.get("expected_change", [])],
        preserve=[str(p) for p in data.get("preserve", [])],
        acceptance=list(contract.quality_criteria),
        attempt=attempt,
    )
    return Verdict(VERDICT_FAIL, repair=repair, reason=str(data.get("reason", "")), failure_kind=kind)


async def verify(
    verifier_expert_id: str,
    contract: TaskContract,
    result: ResultContract,
    policy: RunPolicy,
    repair_count: int = 0,
    previous_repair: Optional[RepairContract] = None,
) -> Verdict:
    """执行一次验收：规则预检 → LLM 裁决 → 结构化 Verdict。

    verifier_expert_id 通常是团队 lead 成员（中央大脑人格）；
    repair_count 超上限直接 ESCALATE（熔断双保险）。
    """
    # 熔断双保险：已超返工上限不再消耗 LLM（引擎层同样拦截）。
    # 边界对齐 engine：==max 时本轮结果仍须验收（FAIL 后由引擎计数超限熔断）
    if repair_count > policy.max_repair_per_node:
        return Verdict(
            VERDICT_ESCALATE,
            reason=f"返工次数超上限（{repair_count}/{policy.max_repair_per_node}），升级人工",
        )
    # 规则预检：子员工自报失败 → 直接 FAIL（省一次 LLM）。
    # 归因：issues 命中结构性关键词（权限/工具/能力缺失）→ structural
    # （引擎 fast-fail 熔断，不再烧满返工轮）；其余默认可返工修复。
    if result.status == RESULT_STATUS_FAILED:
        issues = [str(i) for i in result.issues or ["未说明原因"]]
        kind = (
            FAILURE_KIND_STRUCTURAL
            if any(_STRUCTURAL_ISSUE_RE.search(i) for i in issues)
            else FAILURE_KIND_REPAIRABLE
        )
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
            failure_kind=kind,
        )
    # LLM 裁决（lead 专家人格执行；通道异常升级人工）
    prompt = _render_verify_prompt(contract, result, previous_repair)
    try:
        reply, _session = await call_expert_text(
            expert_agent_id(verifier_expert_id),
            prompt,
            session_id=None,
        )
    except Exception as exc:  # noqa: BLE001 - 验收通道异常升级人工
        logger.warning("验收通道异常 task=%s: %s", contract.task_id, exc)
        return Verdict(VERDICT_ESCALATE, reason=f"验收通道异常: {exc}")
    # 解析裁决（失败一律 ESCALATE）
    return _parse_verdict(reply, contract, repair_count + 1)
