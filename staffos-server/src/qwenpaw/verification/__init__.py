# -*- coding: utf-8 -*-
"""Verification kernel package: 层级式 Agent Runtime 的验收闭环入口。

对外只暴露裁决内核（纯解析/纯渲染）与 LLM 裁决通道两类能力：
- :mod:`.kernel` 裁决常量、Verdict/RepairBrief、prompt 渲染与容错解析；
- :mod:`.judge`  一次性模型裁决调用（复用 model_factory 与额度链路）。

L1 专家团（``app/workforce``）与 L2 数字员工（``loop/gates``）都必须复用
本包，禁止再实现第二套裁决规则。

@author qingfeng
"""

from .kernel import (
    FAILURE_KIND_DEPENDENCY_CHANGED,
    FAILURE_KIND_REPAIRABLE,
    FAILURE_KIND_STRUCTURAL,
    FAILURE_KINDS,
    VERDICT_ESCALATE,
    VERDICT_FAIL,
    VERDICT_PASS,
    JudgeRequest,
    RepairBrief,
    Verdict,
    parse_verdict,
    render_judge_prompt,
    render_repair_prompt,
)

__all__ = [
    "FAILURE_KINDS",
    "FAILURE_KIND_DEPENDENCY_CHANGED",
    "FAILURE_KIND_REPAIRABLE",
    "FAILURE_KIND_STRUCTURAL",
    "JudgeRequest",
    "RepairBrief",
    "VERDICT_ESCALATE",
    "VERDICT_FAIL",
    "VERDICT_PASS",
    "Verdict",
    "parse_verdict",
    "render_judge_prompt",
    "render_repair_prompt",
]
