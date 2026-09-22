# -*- coding: utf-8 -*-
"""验收裁决内核：L1 专家团与 L2 数字员工共用的唯一裁决实现。

本模块是层级式 Agent Runtime「验证闭环」的单一来源：裁决常量、失败归因
三分类、验收 prompt 渲染、返工指令渲染与回执容错解析全部在此，任何一层
都不得再复制一份规则（否则规则漂移会让同一产出得出不同裁决）。

硬约束：只依赖标准库与 pydantic，禁止 import 任何引擎/模型/存储模块，
保证可被 ``loop``（低层）与 ``app.workforce``（高层）双向安全引用，
且裁决解析可脱离运行时独立单测。

@author qingfeng
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 裁决常量（L1 contracts 与 L2 gate 的唯一来源）
# ---------------------------------------------------------------------------

#: 验收裁决：通过
VERDICT_PASS = "PASS"
#: 验收裁决：不通过（需返工）
VERDICT_FAIL = "FAIL"
#: 验收裁决：熔断升级人工（超限或验收器无法裁决）
VERDICT_ESCALATE = "ESCALATE"

#: 失败归因：可返工修复（默认；进入 RepairBrief 返工循环）
FAILURE_KIND_REPAIRABLE = "repairable"
#: 失败归因：结构性失败（能力/工具/权限缺失，返工无意义 → 熔断升级）
FAILURE_KIND_STRUCTURAL = "structural"
#: 失败归因：依赖变更（上游产出与目标矛盾/缺失 → 全局 Re-plan）
FAILURE_KIND_DEPENDENCY_CHANGED = "dependency_changed"

#: 合法归因全集（裁决器输出非法值时回退 repairable）
FAILURE_KINDS = frozenset(
    {
        FAILURE_KIND_REPAIRABLE,
        FAILURE_KIND_STRUCTURAL,
        FAILURE_KIND_DEPENDENCY_CHANGED,
    },
)

# 围栏优先、裸 JSON 兜底。捕获组不可省略：解析取 group(1)，缺捕获组会让
# json.loads 收到整段文本而全部 ESCALATE（L1 真实 E2E 暴露过的缺陷）。
_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"(\{.*\})", re.DOTALL)

#: 送裁决的产出正文上限（超出则首尾保留、中段省略，裁决只需判断达标）
JUDGE_OUTPUT_LIMIT = 4000

#: 要求裁决器先推导显式要求清单再逐条裁决（L2 无预置验收标准时使用，
#: 省去「先生成标准再裁决」的第二次模型调用）
_EXTRACT_REQUIREMENTS_INSTRUCTION = (
    "裁决前请先从「任务目标」原文中逐条提取用户的显式要求（只提取明确说出的，"
    "不得发明未声明的要求），再把待验收产出逐条对照：任一条未满足即判 FAIL。"
)

_DEFAULT_ACCEPTANCE_INSTRUCTION = (
    "对照下列验收标准逐条检查待验收产出，全部满足才判 PASS。"
)


# ---------------------------------------------------------------------------
# 结构化返工指令（L1 RepairContract 继承本模型）
# ---------------------------------------------------------------------------


class RepairBrief(BaseModel):
    """验收失败后的结构化返工指令。

    返工不是"重新给一个新 Prompt"，而是明确问题、期望修改、需保留内容
    与复验标准的修复任务。
    """

    #: 被返工的原任务标识（L1 为节点 key，L2 为 turn 标识）
    original_task: str = ""
    #: 问题清单（验收裁决发现的具体问题）
    issues: List[str] = Field(default_factory=list)
    #: 期望修改（每个问题对应的期望改动）
    expected_change: List[str] = Field(default_factory=list)
    #: 需保留内容（返工时不得破坏的已有产出）
    preserve: List[str] = Field(default_factory=list)
    #: 复验标准（返工后按此重新裁决）
    acceptance: List[str] = Field(default_factory=list)
    #: 返工轮次（第 N 次返工，用于熔断计数展示）
    attempt: int = 1


@dataclass
class JudgeRequest:
    """一次验收裁决的输入（L1 节点回执与 L2 员工产出统一映射到本结构）。"""

    #: 任务目标（L1 为节点 objective，L2 为用户原始请求原文）
    objective: str
    #: 验收标准（L2 允许为空，此时由裁决器内联推导显式要求清单）
    criteria: Sequence[str] = field(default_factory=tuple)
    #: 期望产出清单（可空）
    expected_output: Sequence[str] = field(default_factory=tuple)
    #: 待验收的产出正文
    output_text: str = ""
    #: 执行方自报状态（L1 ResultContract.status；L2 通常为空）
    status: str = ""
    #: 执行方自报置信度（None 表示未采集，正文不展示该行）
    confidence: Optional[float] = None
    #: 执行方自报问题（L1 ResultContract.issues）
    issues: Sequence[str] = field(default_factory=tuple)
    #: 上轮返工指令的复验标准（复验时叠加）
    previous_acceptance: Sequence[str] = field(default_factory=tuple)
    #: 是否要求裁决器从任务目标原文推导显式要求清单并逐条对照
    #: （与 ``criteria`` 可叠加：标准为空时它是唯一尺子，非空时作补充）
    derive_requirements: bool = False
    #: 裁决所依据的上下文/标准版本（None=未采集；验收记录须绑定该版本）
    context_revision: Optional[int] = None


@dataclass
class Verdict:
    """一次验收裁决的结果（PASS / FAIL（附返工指令）/ ESCALATE）。

    FAIL 时携带结构化归因 ``failure_kind``：调用方据此分派
    返工 / 熔断 / 重规划三路处置。字段顺序是契约的一部分
    （L1 测试以位置参数构造首个字段），禁止调整。
    """

    #: 裁决值：VERDICT_PASS / VERDICT_FAIL / VERDICT_ESCALATE
    verdict: str
    #: FAIL 时必须携带的返工指令
    repair: Optional[RepairBrief] = None
    #: 裁决理由（展示给用户与留痕）
    reason: str = ""
    #: FAIL 归因：repairable / structural / dependency_changed
    failure_kind: str = FAILURE_KIND_REPAIRABLE
    #: 裁决依据的上下文/标准版本（由请求回填，供验收记录绑定）
    context_revision: Optional[int] = None
    #: 证据引用（裁决器自述的可选字段；不可替代确定性证据）
    evidence_refs: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt 渲染（L1 / L2 共用同一文本骨架，保证裁决纪律一致）
# ---------------------------------------------------------------------------


def _truncate_output(text: str) -> str:
    """按上限截断产出正文（保留首尾，中段省略）。"""
    # 未超限直接原样返回
    if len(text) <= JUDGE_OUTPUT_LIMIT:
        return text
    # 超限保留前 2000 与后 1500，中段以省略标记替代
    return text[:2000] + "\n…（中段截断）…\n" + text[-1500:]


def render_judge_prompt(request: JudgeRequest) -> str:
    """渲染验收裁决 prompt（对照标准输出结构化 verdict JSON）。

    L1 由 lead 专家人格执行、L2 由独立模型通道执行，二者共用本骨架，
    差异只体现在入参（是否有验收标准/自报回执）。
    """
    # 角色定位：验收器只判达标，不做风格偏好
    lines = ["# 任务验收裁决（你是独立验收器，负责检查产出是否达标）"]
    # 任务目标段
    lines.append("\n## 任务目标")
    lines.append(request.objective or "（未提供）")
    # 期望产出段（可空则整段省略）
    if request.expected_output:
        lines.append("\n## 期望产出")
        for item in request.expected_output:
            lines.append(f"- {item}")
    # 验收标准段：有标准按标准裁；另可在无标准时要求从任务目标推导
    if request.criteria:
        lines.append("\n## 验收标准")
        for item in request.criteria:
            lines.append(f"- {item}")
    elif request.derive_requirements:
        lines.append("\n## 验收标准（由你从任务目标推导）")
        lines.append(_EXTRACT_REQUIREMENTS_INSTRUCTION)
    else:
        lines.append("\n## 验收标准")
        lines.append(_DEFAULT_ACCEPTANCE_INSTRUCTION)
    # 已有基线标准但仍要求推导（L2 场景）：补充逐条对照指令
    if request.criteria and request.derive_requirements:
        lines.append("\n## 补充推导要求")
        lines.append(_EXTRACT_REQUIREMENTS_INSTRUCTION)
    # 复验时叠加上轮返工的复验标准
    if request.previous_acceptance:
        lines.append("\n## 上轮返工指令的复验标准")
        for item in request.previous_acceptance:
            lines.append(f"- {item}")
    # 执行方回执段（仅在有自报信息时渲染，避免噪声）
    if request.status or request.issues or request.confidence is not None:
        lines.append("\n## 执行方回执")
        if request.status:
            confidence = (
                f"（置信度 {request.confidence}）"
                if request.confidence is not None
                else ""
            )
            lines.append(f"- 自报状态：{request.status}{confidence}")
        if request.issues:
            lines.append(f"- 自报问题：{'; '.join(request.issues)}")
    # 待验收正文段（超限截断）
    lines.append("\n### 产出正文")
    lines.append(_truncate_output(request.output_text or "（无正文）"))
    # 输出格式约定（字段集与 parse_verdict 一一对应）
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
    lines.append('    structural=能力/工具/权限缺失返工无意义 |')
    lines.append('    dependency_changed=上游产出与目标矛盾或缺失需全局重新规划"')
    lines.append("}")
    lines.append("```")
    # 裁决纪律：宁 FAIL 不放过，无法判断时不得给 PASS
    lines.append(
        "\n裁决纪律：标准全部满足才 PASS；只看产出是否达标，不做风格偏好评判；"
        "无法判断时 verdict 填 FAIL 并在 issues 写明信息缺口。",
    )
    return "\n".join(lines)


def render_repair_prompt(repair: RepairBrief) -> str:
    """把返工指令渲染为注入执行的 prompt 段（L1 委派与 L2 续跑共用）。"""
    lines = [f"## 返工指令（第 {repair.attempt} 轮，前次产出未通过验收）"]
    # 问题清单（必须逐条解决）
    lines.append("### 验收发现的问题（必须逐条解决）")
    for issue in repair.issues:
        lines.append(f"- {issue}")
    # 期望修改
    if repair.expected_change:
        lines.append("### 期望修改")
        for item in repair.expected_change:
            lines.append(f"- {item}")
    # 需保留内容
    if repair.preserve:
        lines.append("### 需保留内容（不得破坏）")
        for item in repair.preserve:
            lines.append(f"- {item}")
    # 复验标准
    if repair.acceptance:
        lines.append("### 复验标准")
        for item in repair.acceptance:
            lines.append(f"- {item}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 回执容错解析（解析失败一律 ESCALATE，绝不误判 PASS）
# ---------------------------------------------------------------------------


def _extract_json_payload(text: str) -> Optional[dict[str, Any]]:
    """从裁决回复中提取 JSON 对象；取不到或非法返回 None。"""
    # 围栏优先，裸 JSON 兜底
    match = _JSON_FENCE_RE.search(text or "")
    if match is None:
        match = _BARE_JSON_RE.search(text or "")
    if match is None:
        return None
    try:
        # 仅接受对象结构（数组/标量视为非法回执）
        data = json.loads(match.group(1))
    except Exception:  # noqa: BLE001 - 非法 JSON 交由调用方升级人工
        return None
    return data if isinstance(data, dict) else None


def _normalize_failure_kind(raw: Any) -> str:
    """归一化失败归因；非法或缺省回退 repairable（保守可返工）。"""
    kind = str(raw or FAILURE_KIND_REPAIRABLE).strip().lower()
    return kind if kind in FAILURE_KINDS else FAILURE_KIND_REPAIRABLE


def parse_verdict(
    text: str,
    *,
    task_id: str,
    attempt: int,
    acceptance: Sequence[str] = (),
    repair_model: type[RepairBrief] = RepairBrief,
    context_revision: Optional[int] = None,
) -> Verdict:
    """解析裁决 JSON；任何无法裁决的情况一律 ESCALATE。

    Args:
        text: 裁决器回复原文。
        task_id: 被验收任务标识（写入返工指令）。
        attempt: 本次裁决对应的返工轮次。
        acceptance: 复验标准（默认沿用任务验收标准）。
        repair_model: 返工指令的具体类型（L1 传 RepairContract）。
        context_revision: 裁决依据的上下文/标准版本（回填 Verdict，
            供上层验收记录绑定；不参与裁决本身）。

    Returns:
        :class:`Verdict`：PASS / FAIL（附 :class:`RepairBrief`）/ ESCALATE。
    """
    # 回执完全不可解析 → 升级人工（绝不误判 PASS）
    data = _extract_json_payload(text)
    if data is None:
        return Verdict(
            VERDICT_ESCALATE,
            reason="验收器未输出结构化裁决，升级人工复核",
            context_revision=context_revision,
        )
    # 裁决器自述证据引用（可选字段；缺失不阻断，仅作留痕）
    evidence_refs = [str(e) for e in data.get("evidence_refs", []) if str(e).strip()]
    # PASS 直接通过（reason 保留裁决说明）
    if str(data.get("verdict", "")).upper() == VERDICT_PASS:
        return Verdict(
            VERDICT_PASS,
            reason=str(data.get("reason", "")),
            context_revision=context_revision,
            evidence_refs=evidence_refs,
        )
    # FAIL 必须给出具体问题，否则视为无法裁决
    issues = [str(i) for i in data.get("issues", []) if str(i).strip()]
    if not issues:
        return Verdict(
            VERDICT_ESCALATE,
            reason="验收器判定 FAIL 但未给出具体问题，升级人工复核",
            context_revision=context_revision,
        )
    # 组装结构化返工指令（复验标准一律取任务验收标准，不采信裁决器自述，
    # 避免裁决器改写复验标准导致复验口径漂移）
    repair = repair_model(
        original_task=task_id,
        issues=issues,
        expected_change=[str(c) for c in data.get("expected_change", [])],
        preserve=[str(p) for p in data.get("preserve", [])],
        acceptance=list(acceptance),
        attempt=attempt,
    )
    # 非 PASS 且问题明确 → FAIL（携带归因供调用方分派处置）
    return Verdict(
        VERDICT_FAIL,
        repair=repair,
        reason=str(data.get("reason", "")),
        failure_kind=_normalize_failure_kind(data.get("failure_kind")),
        context_revision=context_revision,
        evidence_refs=evidence_refs,
    )
