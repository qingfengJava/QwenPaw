# -*- coding: utf-8 -*-
"""Unit tests: 多员工意图分发内核（P5）——粘性/阈值/降级纯逻辑。

LLM 通道（_classify）以 monkeypatch 打桩；验证路由判定纪律：
stay/低置信/未知候选 → 不切换；粘性保护需要更高置信度。
"""

from __future__ import annotations

import pytest

from qwenpaw.app.experts.intent_dispatch import (
    DispatchCandidate,
    dispatch_expert_intent,
)


def _candidates() -> list:
    return [
        DispatchCandidate("exp_a", "法务", "合规审查官", "合同审查与条款风险"),
        DispatchCandidate("exp_b", "财务", "报销管家", "报销流程与发票"),
        DispatchCandidate("exp_c", "行政", "事务管家", "会议室与差旅"),
    ]


@pytest.mark.asyncio
async def test_dispatch_routes_to_best_fit(monkeypatch):
    """高置信命中 → 切换到目标员工。"""

    async def fake_classify(prompt):
        return {"expert_id": "exp_b", "confidence": 0.9, "reason": "报销问题"}

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch._classify",
        fake_classify,
    )
    result = await dispatch_expert_intent("帮我报销这张发票", _candidates())
    assert result is not None
    assert result["expert_id"] == "exp_b"
    assert result["confidence"] >= 0.75


@pytest.mark.asyncio
async def test_dispatch_low_confidence_stays(monkeypatch):
    """低置信度 → None（调用方保持默认路由，绝不瞎切）。"""

    async def fake_classify(prompt):
        return {"expert_id": "exp_a", "confidence": 0.4, "reason": "不确定"}

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch._classify",
        fake_classify,
    )
    assert await dispatch_expert_intent("今天天气不错", _candidates()) is None


@pytest.mark.asyncio
async def test_dispatch_sticky_guard(monkeypatch):
    """粘性场景：从当前员工切走需要 ≥ sticky 阈值。"""

    async def fake_classify(prompt):
        return {"expert_id": "exp_b", "confidence": 0.8, "reason": "可能财务"}

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch._classify",
        fake_classify,
    )
    # 0.8 ≥ 普通阈值但 < 粘性阈值 → 不切
    result = await dispatch_expert_intent(
        "这个合同条款怎么处理",
        _candidates(),
        current_expert_id="exp_a",
        sticky=True,
    )
    assert result is None

    # 0.95 ≥ 粘性阈值 → 切走
    async def fake_classify_high(prompt):
        return {"expert_id": "exp_b", "confidence": 0.95, "reason": "明确报销"}

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch._classify",
        fake_classify_high,
    )
    result = await dispatch_expert_intent(
        "帮我报销这张发票",
        _candidates(),
        current_expert_id="exp_a",
        sticky=True,
    )
    assert result is not None and result["expert_id"] == "exp_b"


@pytest.mark.asyncio
async def test_dispatch_degrades_on_channel_error(monkeypatch):
    """LLM 通道异常 → None（分发故障绝不阻塞消息主链路）。"""

    async def broken_classify(prompt):
        raise RuntimeError("channel down")

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch._classify",
        broken_classify,
    )
    assert await dispatch_expert_intent("你好", _candidates()) is None
    # 候选 <2 也直接不分发
    assert await dispatch_expert_intent("你好", _candidates()[:1]) is None
