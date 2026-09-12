#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the channel intent-dispatch gate (no PG / LLM needed).

Tests cover:
  - last_user_text: user-message extraction, assistant skip, multi-part
    join, empty input safety
  - gate pass-through: unconfigured channel / no text / <2 candidates
  - dispatch hit: forwards through the target workspace stream and does
    NOT call the owning process
  - dispatch miss: owning process used as-is
  - sticky semantics: non-empty session_id → sticky=True
  - degradation: classifier raising → owning process still serves
  - forward failure: target stream raising falls back to owning process
"""

from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, List

import pytest

import qwenpaw.app.channels.intent_dispatch_gate as gate_mod
from qwenpaw.app.channels.intent_dispatch_gate import (
    last_user_text,
    wrap_process_with_dispatch,
)
from qwenpaw.schemas import AgentRequest, Message, Role, TextContent


def _request(text: str = "", channel: str = "dingtalk", session_id: str = "") -> AgentRequest:
    """Build one channel-shaped AgentRequest."""
    input_msgs = (
        [Message(role=Role.USER, content=[TextContent(text=text)])] if text else []
    )
    request = AgentRequest(
        session_id=session_id,
        user_id="u1",
        input=input_msgs,
    )
    request.channel = channel
    return request


async def _record_process(calls: List[Any], tag: str = "own"):
    async def process(request: Any) -> AsyncGenerator[str, None]:
        calls.append((tag, request))
        yield f"event-from-{tag}"

    return process


def _ws(manager: Any = None, agent_id: str = "default"):
    return SimpleNamespace(agent_id=agent_id, _manager=manager)


class _FakeManager:
    def __init__(self, target_ws: Any) -> None:
        self.target_ws = target_ws
        self.requested: List[str] = []

    async def get_agent(self, agent_id: str):
        self.requested.append(agent_id)
        return self.target_ws


def _target_ws(calls: List[Any]):
    async def stream_query(request: Any) -> AsyncGenerator[str, None]:
        calls.append(("target", request))
        yield "event-from-target"

    return SimpleNamespace(stream_query=stream_query)


def _fake_choice(expert_id: str) -> Dict[str, Any]:
    return {"expert_id": expert_id, "confidence": 0.95, "reason": "r", "stay": False}


def _fake_candidates(monkeypatch, ids: List[str]) -> None:
    """Published-candidate projection without touching ExpertStore."""
    async def fake_load(expert_ids, cache):
        return [
            SimpleNamespace(expert_id=eid, name=eid, title="", description="")
            for eid in expert_ids
        ]

    monkeypatch.setattr(gate_mod, "_load_candidates", fake_load)


# ---------------------------------------------------------------------------
# last_user_text
# ---------------------------------------------------------------------------


def test_last_user_text_extracts_user_message():
    request = AgentRequest(
        input=[
            Message(role=Role.USER, content=[TextContent(text="你好")]),
        ],
    )
    assert last_user_text(request) == "你好"


def test_last_user_text_skips_assistant_and_uses_last_user():
    request = AgentRequest(
        input=[
            Message(role=Role.USER, content=[TextContent(text="第一条")]),
            Message(role=Role.ASSISTANT, content=[TextContent(text="回复")]),
            Message(role=Role.USER, content=[TextContent(text="最"), TextContent(text="新")]),
        ],
    )
    assert last_user_text(request) == "最新"


def test_last_user_text_empty_input():
    assert last_user_text(AgentRequest(input=[])) == ""
    assert last_user_text(SimpleNamespace(input=None)) == ""


# ---------------------------------------------------------------------------
# gate 行为
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured_channel_passes_through(monkeypatch):
    calls: List[Any] = []
    process = await _record_process(calls)
    wrapped = wrap_process_with_dispatch(
        process,
        _ws(),
        {"dingtalk": ["e1", "e2"]},
    )
    events = [item async for item in wrapped(_request("hi", channel="qq"))]
    assert events == ["event-from-own"]
    assert [tag for tag, _ in calls] == ["own"]


@pytest.mark.asyncio
async def test_no_text_passes_through(monkeypatch):
    calls: List[Any] = []
    process = await _record_process(calls)
    _fake_candidates(monkeypatch, ["e1", "e2"])
    wrapped = wrap_process_with_dispatch(
        process,
        _ws(),
        {"dingtalk": ["e1", "e2"]},
    )
    events = [item async for item in wrapped(_request("", channel="dingtalk"))]
    assert events == ["event-from-own"]


@pytest.mark.asyncio
async def test_single_candidate_passes_through(monkeypatch):
    calls: List[Any] = []
    process = await _record_process(calls)
    _fake_candidates(monkeypatch, ["e1"])
    wrapped = wrap_process_with_dispatch(
        process,
        _ws(),
        {"dingtalk": ["e1"]},
    )
    events = [item async for item in wrapped(_request("hi"))]
    assert events == ["event-from-own"]


@pytest.mark.asyncio
async def test_dispatch_hit_forwards_to_target(monkeypatch):
    calls: List[Any] = []
    target_calls: List[Any] = []
    process = await _record_process(calls)
    target_ws = _target_ws(target_calls)
    manager = _FakeManager(target_ws)
    _fake_candidates(monkeypatch, ["e1", "e2"])

    async def fake_dispatch(text, candidates, current_expert_id="", sticky=False):
        return _fake_choice("e2")

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch.dispatch_expert_intent",
        fake_dispatch,
    )

    wrapped = wrap_process_with_dispatch(
        process,
        _ws(manager=manager),
        {"dingtalk": ["e1", "e2"]},
    )
    events = [item async for item in wrapped(_request("帮我写周报"))]
    # 目标员工事件透传；本员工 process 未被调用
    assert events == ["event-from-target"]
    assert calls == []
    assert manager.requested == ["expert_e2"]
    assert [tag for tag, _ in target_calls] == ["target"]


@pytest.mark.asyncio
async def test_dispatch_miss_uses_own_process(monkeypatch):
    calls: List[Any] = []
    process = await _record_process(calls)
    _fake_candidates(monkeypatch, ["e1", "e2"])

    async def fake_dispatch(text, candidates, current_expert_id="", sticky=False):
        return None

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch.dispatch_expert_intent",
        fake_dispatch,
    )
    wrapped = wrap_process_with_dispatch(
        process,
        _ws(),
        {"dingtalk": ["e1", "e2"]},
    )
    events = [item async for item in wrapped(_request("hi"))]
    assert events == ["event-from-own"]


@pytest.mark.asyncio
async def test_sticky_flag_follows_session(monkeypatch):
    """非空 session_id（进行中会话）→ sticky=True 传给分类器."""
    calls: List[Any] = []
    process = await _record_process(calls)
    _fake_candidates(monkeypatch, ["e1", "e2"])
    seen: Dict[str, Any] = {}

    async def fake_dispatch(text, candidates, current_expert_id="", sticky=False):
        seen["sticky"] = sticky
        seen["current"] = current_expert_id
        return None

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch.dispatch_expert_intent",
        fake_dispatch,
    )
    wrapped = wrap_process_with_dispatch(
        process,
        _ws(agent_id="default"),
        {"dingtalk": ["e1", "e2"]},
    )
    async for _ in wrapped(_request("hi", session_id="s-1")):
        pass
    assert seen == {"sticky": True, "current": "default"}


@pytest.mark.asyncio
async def test_classifier_exception_degrades(monkeypatch):
    calls: List[Any] = []
    process = await _record_process(calls)
    _fake_candidates(monkeypatch, ["e1", "e2"])

    async def boom(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch.dispatch_expert_intent",
        boom,
    )
    wrapped = wrap_process_with_dispatch(
        process,
        _ws(),
        {"dingtalk": ["e1", "e2"]},
    )
    events = [item async for item in wrapped(_request("hi"))]
    assert events == ["event-from-own"]


@pytest.mark.asyncio
async def test_forward_failure_falls_back(monkeypatch):
    """目标 workspace 流抛异常 → 回落本员工（不丢消息）."""
    calls: List[Any] = []
    process = await _record_process(calls)

    async def broken_stream(request: Any) -> AsyncGenerator[str, None]:
        raise RuntimeError("target crashed")
        yield  # pragma: no cover - makes this an async generator

    manager = _FakeManager(SimpleNamespace(stream_query=broken_stream))
    _fake_candidates(monkeypatch, ["e1", "e2"])

    async def fake_dispatch(text, candidates, current_expert_id="", sticky=False):
        return _fake_choice("e1")

    monkeypatch.setattr(
        "qwenpaw.app.experts.intent_dispatch.dispatch_expert_intent",
        fake_dispatch,
    )
    wrapped = wrap_process_with_dispatch(
        process,
        _ws(manager=manager),
        {"dingtalk": ["e1", "e2"]},
    )
    events = [item async for item in wrapped(_request("hi"))]
    assert events == ["event-from-own"]
