# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for IndependentVerifierGate (L2 independent verification loop)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from agentscope.message import Msg, TextBlock

from qwenpaw.constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
    VERIFY_REPAIR_MESSAGE_TAG,
)
from qwenpaw.loop.gates.base import StopAction
from qwenpaw.loop.gates.independent_verify import IndependentVerifierGate
from qwenpaw.verification.kernel import (
    FAILURE_KIND_REPAIRABLE,
    FAILURE_KIND_STRUCTURAL,
    RepairBrief,
    Verdict,
    VERDICT_ESCALATE,
    VERDICT_FAIL,
    VERDICT_PASS,
)

# 命中 workforce 多交付物规则（报告 + 和 + 方案）且长度超过 min_objective_chars
COMPLEX_REQUEST = (
    "帮我做一份市场调研报告和一份产品方案，需要覆盖竞品分析、定价建议与上线节奏"
)
SIMPLE_REQUEST = "这个函数是干什么用的？"


@pytest.fixture(autouse=True)
def _force_session_id():
    with patch(
        "qwenpaw.loop.gates.loop_gate._session_id",
        return_value="verify-session",
    ):
        yield


def _user_msg(text: str) -> Msg:
    """Build a message tagged as a real external user request."""
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
        metadata={QWENPAW_MESSAGE_TAG_KEY: EXTERNAL_USER_QUERY_MESSAGE_TAG},
    )


def _candidate(text: str) -> Msg:
    """Build the assistant draft the loop is about to stop on."""
    return Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(type="text", text=text)],
    )


def _agent(request_text: str) -> SimpleNamespace:
    """Build the minimal agent surface the gate reads."""
    return SimpleNamespace(
        state=SimpleNamespace(context=[_user_msg(request_text)]),
        _request_context={"agent_id": "expert_x"},
        _agent_config=SimpleNamespace(id="expert_x", verifier_model=None),
    )


def _ctx(request_text: str, draft: Msg) -> dict:
    """Build the gate context exactly as ``run_stop_handlers`` does."""
    return {
        "final_msg": draft,
        "agent": _agent(request_text),
        "iteration": 1,
        "has_tool_calls": False,
    }


def _patch_judge(monkeypatch, verdict: Verdict, calls: list) -> None:
    """Replace the verification model channel with a canned verdict."""

    async def _fake_judge(prompt, **kwargs):
        calls.append({"prompt": prompt, "kwargs": kwargs})
        return verdict

    monkeypatch.setattr("qwenpaw.verification.judge.judge", _fake_judge)


def _fail(kind: str = FAILURE_KIND_REPAIRABLE) -> Verdict:
    """FAIL verdict carrying one repairable defect."""
    return Verdict(
        VERDICT_FAIL,
        repair=RepairBrief(
            original_task="turn",
            issues=["缺少定价建议"],
            expected_change=["补充定价区间"],
            acceptance=["覆盖定价"],
        ),
        reason="未覆盖全部要求",
        failure_kind=kind,
    )


@pytest.mark.asyncio
async def test_tool_call_iteration_never_verifies(monkeypatch):
    """工具轮不裁决：验收只看最终产出。"""
    calls: list = []
    _patch_judge(monkeypatch, Verdict(VERDICT_PASS), calls)
    gate = IndependentVerifierGate()

    ctx = _ctx(COMPLEX_REQUEST, _candidate("draft"))
    ctx["has_tool_calls"] = True
    result = await gate.check(ctx)

    assert result.action == StopAction.BYPASS
    assert calls == []


@pytest.mark.asyncio
async def test_simple_request_skips_verification_entirely(monkeypatch):
    """复杂度分级未命中 complex 时整轮零模型调用。"""
    calls: list = []
    _patch_judge(monkeypatch, Verdict(VERDICT_PASS), calls)
    gate = IndependentVerifierGate()

    result = await gate.check(_ctx(SIMPLE_REQUEST, _candidate("答")))

    assert result.action == StopAction.BYPASS
    assert calls == []


@pytest.mark.asyncio
async def test_short_request_is_not_armed_even_if_rules_match(monkeypatch):
    """短于 min_objective_chars 的请求不启用验收（保护追问成本）。"""
    calls: list = []
    _patch_judge(monkeypatch, Verdict(VERDICT_PASS), calls)
    gate = IndependentVerifierGate(min_objective_chars=200)

    result = await gate.check(_ctx(COMPLEX_REQUEST, _candidate("答")))

    assert result.action == StopAction.BYPASS
    assert calls == []


@pytest.mark.asyncio
async def test_pass_terminates_normally(monkeypatch):
    """独立验收通过则正常收尾，产出原文不被改写。"""
    calls: list = []
    _patch_judge(monkeypatch, Verdict(VERDICT_PASS, reason="达标"), calls)
    gate = IndependentVerifierGate()
    draft = _candidate("完整产出")

    result = await gate.check(_ctx(COMPLEX_REQUEST, draft))

    assert result.action == StopAction.TERMINATE
    assert "独立验收通过" in result.reason
    assert len(calls) == 1
    assert "市场调研报告" in calls[0]["prompt"]
    assert calls[0]["kwargs"]["agent_id"] == "expert_x"


@pytest.mark.asyncio
async def test_repairable_fail_injects_repair_instruction(monkeypatch):
    """可返工缺陷：注入结构化返工指令并继续循环。"""
    _patch_judge(monkeypatch, _fail(), [])
    gate = IndependentVerifierGate(max_repairs=2)

    result = await gate.check(_ctx(COMPLEX_REQUEST, _candidate("v1")))

    assert result.action == StopAction.INTERRUPT_AND_CONTINUE
    assert result.reset_peers is True
    # 返工指令是合成消息，必须打专属 tag 防止被当成新请求
    assert result.continuation_metadata == {
        QWENPAW_MESSAGE_TAG_KEY: VERIFY_REPAIR_MESSAGE_TAG,
    }
    continuation = gate.build_continuation()
    assert "缺少定价建议" in continuation
    assert "补充定价区间" in continuation
    assert gate._state().repairs == 1


@pytest.mark.asyncio
async def test_second_candidate_pass_after_repair(monkeypatch):
    """返工后的新产出复验通过即收尾。"""
    verdicts = [_fail(), Verdict(VERDICT_PASS, reason="已补齐")]
    calls: list = []

    async def _fake_judge(prompt, **kwargs):
        calls.append(prompt)
        return verdicts[len(calls) - 1]

    monkeypatch.setattr("qwenpaw.verification.judge.judge", _fake_judge)
    gate = IndependentVerifierGate(max_repairs=1)
    request_ctx = _ctx(COMPLEX_REQUEST, _candidate("v1"))

    first = await gate.check(request_ctx)
    second = await gate.check(_ctx(COMPLEX_REQUEST, _candidate("v2")))

    assert first.action == StopAction.INTERRUPT_AND_CONTINUE
    assert second.action == StopAction.TERMINATE
    # 复验 prompt 必须带上上一轮返工的复验标准
    assert "上轮返工指令的复验标准" in calls[1]
    assert "覆盖定价" in calls[1]


@pytest.mark.asyncio
async def test_same_candidate_is_not_graded_twice(monkeypatch):
    """同一条产出只裁决一次，避免重复烧预算与死循环。"""
    calls: list = []
    _patch_judge(monkeypatch, _fail(), calls)
    gate = IndependentVerifierGate(max_repairs=3)
    draft = _candidate("v1")
    ctx = _ctx(COMPLEX_REQUEST, draft)

    assert (await gate.check(ctx)).action == StopAction.INTERRUPT_AND_CONTINUE
    assert (await gate.check(ctx)).action == StopAction.BYPASS
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_repair_budget_exhaustion_escalates_with_notice(monkeypatch):
    """返工超限：熔断收尾并把缺口追加到回复，绝不静默放行。"""
    gate = IndependentVerifierGate(max_repairs=0)
    _patch_judge(monkeypatch, _fail(), [])
    draft = _candidate("半成品")

    result = await gate.check(_ctx(COMPLEX_REQUEST, draft))

    assert result.action == StopAction.TERMINATE
    assert "熔断" in result.reason
    tail = "".join(
        block.text for block in draft.content if block.type == "text"
    )
    assert "独立验收未通过" in tail
    assert "缺少定价建议" in tail


@pytest.mark.asyncio
async def test_structural_failure_escalates_without_rework(monkeypatch):
    """结构性缺陷返工无意义，直接熔断到用户。"""
    calls: list = []
    _patch_judge(monkeypatch, _fail(FAILURE_KIND_STRUCTURAL), calls)
    gate = IndependentVerifierGate(max_repairs=3)

    result = await gate.check(_ctx(COMPLEX_REQUEST, _candidate("v1")))

    assert result.action == StopAction.TERMINATE
    assert gate._state() is None


@pytest.mark.asyncio
async def test_ungradable_verdict_never_blocks_the_chat(monkeypatch):
    """验收器无法裁决时放行产出，不阻塞主链路。"""
    _patch_judge(monkeypatch, Verdict(VERDICT_ESCALATE, reason="超时"), [])
    gate = IndependentVerifierGate()

    result = await gate.check(_ctx(COMPLEX_REQUEST, _candidate("v1")))

    assert result.action == StopAction.TERMINATE
    assert "放行" in result.reason


@pytest.mark.asyncio
async def test_judge_crash_is_swallowed(monkeypatch):
    """裁决通道抛异常必须被吞掉并放行。"""

    async def _boom(_prompt, **_kwargs):
        raise RuntimeError("channel exploded")

    monkeypatch.setattr("qwenpaw.verification.judge.judge", _boom)
    gate = IndependentVerifierGate()

    result = await gate.check(_ctx(COMPLEX_REQUEST, _candidate("v1")))

    assert result.action == StopAction.BYPASS


@pytest.mark.asyncio
async def test_new_user_turn_resets_repair_budget(monkeypatch):
    """新来一条真实用户请求即重置返工预算并重新分级。"""
    _patch_judge(monkeypatch, _fail(), [])
    gate = IndependentVerifierGate(max_repairs=1)

    await gate.check(_ctx(COMPLEX_REQUEST, _candidate("v1")))
    state = gate._state()
    assert state is not None and state.repairs == 1

    second_request = COMPLEX_REQUEST + "，另外再补一份上线风险清单"
    await gate.check(_ctx(second_request, _candidate("v2")))

    refreshed = gate._state()
    assert refreshed.objective == second_request
    # 上一轮已用掉 1 次返工，新 turn 预算重新计数后再返工一次
    assert refreshed.repairs == 1


@pytest.mark.asyncio
async def test_missing_agent_context_bypasses(monkeypatch):
    """取不到本轮用户请求（如后台任务）时不参与验收。"""
    calls: list = []
    _patch_judge(monkeypatch, Verdict(VERDICT_PASS), calls)
    gate = IndependentVerifierGate()

    result = await gate.check(
        {
            "final_msg": _candidate("v"),
            "agent": SimpleNamespace(
                state=SimpleNamespace(context=[]),
                _request_context={},
                _agent_config=None,
            ),
            "iteration": 1,
            "has_tool_calls": False,
        },
    )

    assert result.action == StopAction.BYPASS
    assert calls == []
