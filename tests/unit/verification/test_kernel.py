# -*- coding: utf-8 -*-
"""Tests for the shared verification kernel (L1/L2 single source)."""

from __future__ import annotations

import json

import pytest

from qwenpaw.verification.kernel import (
    FAILURE_KIND_DEPENDENCY_CHANGED,
    FAILURE_KIND_REPAIRABLE,
    FAILURE_KIND_STRUCTURAL,
    JudgeRequest,
    RepairBrief,
    VERDICT_ESCALATE,
    VERDICT_FAIL,
    VERDICT_PASS,
    parse_verdict,
    render_judge_prompt,
    render_repair_prompt,
)


def _fence(payload: dict) -> str:
    """Wrap a payload in the ```json fence the judge prompt asks for."""
    fenced = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
    return "前置说明\n" + fenced


# ---------------------------------------------------------------------------
# parse_verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "看起来还不错，应该没问题",
        "```json\nnot-json\n```",
        "[1, 2, 3]",
    ],
)
def test_unparseable_receipt_escalates(text: str):
    """回执无法解析时必须 ESCALATE，绝不给 PASS。"""
    verdict = parse_verdict(text, task_id="node-1", attempt=1)
    assert verdict.verdict == VERDICT_ESCALATE
    assert verdict.repair is None


def test_pass_from_fenced_json_keeps_reason():
    """围栏 PASS：裁决通过并保留理由。"""
    verdict = parse_verdict(
        _fence({"verdict": "pass", "reason": "符合验收标准"}),
        task_id="node-1",
        attempt=1,
    )
    assert verdict.verdict == VERDICT_PASS
    assert verdict.reason == "符合验收标准"


def test_bare_json_is_accepted_as_fallback():
    """无围栏时裸 JSON 兜底（捕获组缺失曾导致全量 ESCALATE）。"""
    verdict = parse_verdict(
        '前言 {"verdict":"PASS","reason":"ok"} 结语',
        task_id="node-1",
        attempt=1,
    )
    assert verdict.verdict == VERDICT_PASS


def test_fail_without_issues_escalates():
    """判 FAIL 但没给出具体问题等于无法裁决，必须升级人工。"""
    verdict = parse_verdict(
        _fence({"verdict": "FAIL", "reason": "不行"}),
        task_id="node-1",
        attempt=2,
    )
    assert verdict.verdict == VERDICT_ESCALATE


def test_fail_builds_repair_brief_with_attempt_and_acceptance():
    """FAIL 组装结构化返工指令：轮次与复验标准按入参传递。"""
    verdict = parse_verdict(
        _fence(
            {
                "verdict": "FAIL",
                "reason": "缺少定价建议",
                "issues": ["未覆盖定价"],
                "expected_change": ["补充定价区间"],
                "preserve": ["保留竞品表"],
            },
        ),
        task_id="node-1",
        attempt=3,
        acceptance=["覆盖定价"],
    )
    assert verdict.verdict == VERDICT_FAIL
    assert isinstance(verdict.repair, RepairBrief)
    assert verdict.repair.original_task == "node-1"
    assert verdict.repair.attempt == 3
    # 复验标准一律取任务标准，不采信裁决器自述的 acceptance
    assert verdict.repair.acceptance == ["覆盖定价"]
    assert verdict.repair.preserve == ["保留竞品表"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (FAILURE_KIND_STRUCTURAL, FAILURE_KIND_STRUCTURAL),
        (FAILURE_KIND_DEPENDENCY_CHANGED, FAILURE_KIND_DEPENDENCY_CHANGED),
        ("  Repairable ", FAILURE_KIND_REPAIRABLE),
        ("nonsense", FAILURE_KIND_REPAIRABLE),
        (None, FAILURE_KIND_REPAIRABLE),
    ],
)
def test_failure_kind_normalisation(raw, expected: str):
    """归因非法或缺省回退 repairable，合法值原样保留。"""
    verdict = parse_verdict(
        _fence({"verdict": "FAIL", "issues": ["a"], "failure_kind": raw}),
        task_id="node-1",
        attempt=1,
    )
    assert verdict.failure_kind == expected


def test_repair_model_override_is_used():
    """repair_model 让 L1 用自身契约类型承载返工指令。"""

    class _Sub(RepairBrief):
        marker: str = "sub"

    verdict = parse_verdict(
        _fence({"verdict": "FAIL", "issues": ["a"]}),
        task_id="node-1",
        attempt=1,
        repair_model=_Sub,
    )
    assert isinstance(verdict.repair, _Sub)
    assert verdict.repair.marker == "sub"


# ---------------------------------------------------------------------------
# prompt rendering
# ---------------------------------------------------------------------------


def test_judge_prompt_renders_criteria_and_output():
    """有验收标准时按标准渲染，并带上待验收正文。"""
    prompt = render_judge_prompt(
        JudgeRequest(
            objective="产出调研报告",
            criteria=["含定价建议"],
            expected_output=["报告文档"],
            output_text="正文内容",
            status="COMPLETED",
            confidence=0.9,
            issues=["数据缺口"],
        ),
    )
    assert "## 任务目标" in prompt
    assert "含定价建议" in prompt
    assert "报告文档" in prompt
    assert "正文内容" in prompt
    assert "COMPLETED" in prompt
    assert '"verdict": "PASS 或 FAIL"' in prompt


def test_judge_prompt_derives_requirements_when_criteria_missing():
    """无标准时要求裁决器从任务目标推导显式要求清单。"""
    prompt = render_judge_prompt(
        JudgeRequest(objective="给我报告和方案", derive_requirements=True),
    )
    assert "由你从任务目标推导" in prompt
    assert "逐条提取用户的显式要求" in prompt


def test_judge_prompt_appends_derivation_to_baseline_criteria():
    """基线标准与推导要求可叠加（L2 场景）。"""
    prompt = render_judge_prompt(
        JudgeRequest(
            objective="o",
            criteria=["覆盖全部显式要求"],
            derive_requirements=True,
        ),
    )
    assert "## 验收标准" in prompt
    assert "## 补充推导要求" in prompt


def test_judge_prompt_includes_previous_acceptance():
    """复验轮叠加上一轮返工的复验标准。"""
    prompt = render_judge_prompt(
        JudgeRequest(
            objective="o",
            criteria=["c"],
            previous_acceptance=["细节完整"],
        ),
    )
    assert "## 上轮返工指令的复验标准" in prompt
    assert "细节完整" in prompt


def test_judge_prompt_truncates_long_output():
    """超长正文按首尾保留截断，避免裁决 prompt 膨胀。"""
    long_text = "A" * 3000 + "B" * 3000
    prompt = render_judge_prompt(
        JudgeRequest(objective="o", output_text=long_text),
    )
    assert "（中段截断）" in prompt
    assert len(prompt) < len(long_text)


def test_repair_prompt_sections():
    """返工指令段完整渲染四类信息。"""
    text = render_repair_prompt(
        RepairBrief(
            original_task="node-1",
            issues=["缺定价"],
            expected_change=["补定价区间"],
            preserve=["保留竞品表"],
            acceptance=["覆盖定价"],
            attempt=2,
        ),
    )
    assert "第 2 轮" in text
    assert "缺定价" in text
    assert "补定价区间" in text
    assert "保留竞品表" in text
    assert "覆盖定价" in text
