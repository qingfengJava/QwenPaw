# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for SpanRecorderMiddleware.

A fake sink records emissions; the middleware must capture kind/name/
parent/tokens for system, llm, tool and reply spans while passing the
underlying calls through unchanged — including when the handler raises.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from qwenpaw.agents.middlewares import SpanRecorderMiddleware
from qwenpaw.observability.span_sink import (
    clear_run_context,
    set_run_context,
)


class _FakeSink:
    def __init__(self):
        self.spans: list[dict] = []

    def emit_span(self, **kwargs):
        self.spans.append(kwargs)
        return f"span-{len(self.spans)}"

    def start_run(self, meta):
        pass

    def finish_run(self, **kwargs):
        pass


@pytest.fixture(autouse=True)
def _ctx():
    set_run_context("run-1")
    yield
    clear_run_context()


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> _FakeSink:
    fake = _FakeSink()
    monkeypatch.setattr(
        "qwenpaw.observability.span_sink.get_span_sink",
        lambda: fake,
    )
    return fake


def _llm_msg(output_tokens: int = 42):
    return SimpleNamespace(
        name="qwen-max",
        usage=SimpleNamespace(output_tokens=output_tokens),
        content=[{"type": "text", "text": "答案"}],
    )


async def test_on_model_call_records_llm_span(sink: _FakeSink):
    async def handler(**kwargs):
        return _llm_msg()

    mw = SpanRecorderMiddleware()
    result = await mw.on_model_call(
        SimpleNamespace(),
        {"messages": [{"role": "user", "content": "hi"}]},
        handler,
    )
    assert result.usage.output_tokens == 42
    assert len(sink.spans) == 1
    span = sink.spans[0]
    assert span["kind"] == "llm"
    assert span["name"] == "qwen-max"
    assert span["tokens"] == 42
    assert span["input"]["message_count"] == 1
    assert span["input"]["last_message"]["role"] == "user"


async def test_on_model_call_failure_still_records(sink: _FakeSink):
    async def handler(**kwargs):
        raise RuntimeError("model down")

    mw = SpanRecorderMiddleware()
    with pytest.raises(RuntimeError):
        await mw.on_model_call(SimpleNamespace(), {"messages": []}, handler)
    assert len(sink.spans) == 1
    assert sink.spans[0]["status"] == "failed"
    assert "model down" in sink.spans[0]["error"]


async def test_on_acting_pairs_tool_under_llm(sink: _FakeSink):
    from qwenpaw.observability.span_sink import set_current_llm_span

    set_current_llm_span("llm-parent")
    response = ToolResponse(
        content=[TextBlock(type="text", text="done")],
        id="tc-1",
    )

    async def handler():
        yield response

    mw = SpanRecorderMiddleware()
    collected = [
        event
        async for event in mw.on_acting(
            SimpleNamespace(),
            {
                "tool_call": SimpleNamespace(
                    name="bash",
                    input={"command": "ls"},
                    id="tc-1",
                ),
            },
            handler,
        )
    ]
    assert collected == [response]
    assert len(sink.spans) == 1
    span = sink.spans[0]
    assert span["kind"] == "tool"
    assert span["name"] == "bash"
    assert span["parent_span_id"] == "llm-parent"
    assert span["input"] == {"command": "ls"}
    assert span["output"] == {"content": ["done"]}


async def test_on_acting_failure_records_failed_span(sink: _FakeSink):
    async def handler():
        raise RuntimeError("tool exploded")
        yield  # pragma: no cover

    mw = SpanRecorderMiddleware()
    with pytest.raises(RuntimeError):
        async for _ in mw.on_acting(
            SimpleNamespace(),
            {"tool_call": SimpleNamespace(name="bash", input={}, id="t")},
            handler,
        ):
            pass
    assert sink.spans[0]["status"] == "failed"
    assert "tool exploded" in sink.spans[0]["error"]


async def test_on_reply_records_reply_span(sink: _FakeSink):
    async def handler():
        yield SimpleNamespace(
            content=[SimpleNamespace(type="text", text="逻辑结束文本")],
        )

    mw = SpanRecorderMiddleware()
    collected = [
        item
        async for item in mw.on_reply(SimpleNamespace(), {}, handler)
    ]
    assert len(collected) == 1
    assert len(sink.spans) == 1
    span = sink.spans[0]
    assert span["kind"] == "reply"
    assert span["output"] == "逻辑结束文本"


async def test_on_system_prompt_records_system_span(sink: _FakeSink):
    mw = SpanRecorderMiddleware()
    prompt = await mw.on_system_prompt(SimpleNamespace(), "系统提示词")
    assert prompt == "系统提示词"
    assert len(sink.spans) == 1
    span = sink.spans[0]
    assert span["kind"] == "system"
    assert span["input"] == {"prompt_chars": 5}


async def test_sink_failure_never_breaks_handler(
    monkeypatch: pytest.MonkeyPatch,
):
    def _boom():
        raise RuntimeError("sink down")

    monkeypatch.setattr(
        "qwenpaw.observability.span_sink.get_span_sink",
        _boom,
    )

    async def handler(**kwargs):
        return "untouched"

    mw = SpanRecorderMiddleware()
    result = await mw.on_model_call(
        SimpleNamespace(),
        {"messages": []},
        handler,
    )
    assert result == "untouched"
