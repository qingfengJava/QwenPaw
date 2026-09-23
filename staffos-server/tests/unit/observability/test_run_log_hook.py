# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for qwenpaw.hooks.observability.run_log_hook.

Real file IO through monkeypatched store directories. Covers: the start
hook (trace + index row + extras handoff), the finish hook (success /
failure finalization, token aggregation), and the two pure helpers.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app import inbox_trace_store as trace_store
from qwenpaw.app import run_log_store as log_store
from qwenpaw.hooks.observability.run_log_hook import (
    RunLogFinishHook,
    RunLogStartHook,
    _resolve_environment,
    _sum_delta_tokens,
)
from qwenpaw.runtime.hooks import HookContext
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


class _FakeSession:
    """Minimal session store holding a mutable AgentState context."""

    def __init__(self, messages: list[dict]):
        self.messages = messages

    async def get_session_state_dict(self, *args, **kwargs):
        return {"agent": {"state": {"context": self.messages}}}


def _assistant_msg(tokens: int = 55) -> dict:
    return {
        "role": "assistant",
        "content": "done",
        "created_at": "2026-09-08T12:00:00",
        "metadata": {
            "qwenpaw_turn_usage": {"usage": {"total_tokens": tokens}},
        },
    }


def _make_ctx(
    *,
    agent_id: str = "agent-a",
    session_messages: list[dict] | None = None,
    error: BaseException | None = None,
    agent_config: object | None = None,
) -> HookContext:
    """Build a minimal HookContext for hook unit tests."""
    if agent_config is None:
        agent_config = SimpleNamespace(
            version="1.2.3",
            active_model=SimpleNamespace(model="qwen-max"),
        )
    return HookContext(
        request=SimpleNamespace(
            user_id="u-1",
            channel="feishim",
            chat_id="chat-9",
        ),
        session_id="s-1",
        agent_id=agent_id,
        root_session_id="s-root",
        root_agent_id=agent_id,
        workspace_dir=None,
        workspace=SimpleNamespace(session=_FakeSession(session_messages or [])),
        app_services=None,
        input_msgs=[],
        error=error,
        agent_config=agent_config,
    )


@pytest.fixture
def store_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect both stores to tmp and keep the retention sweep idle."""
    monkeypatch.setattr(trace_store, "_TRACE_DIR", tmp_path / "inbox_traces")
    monkeypatch.setattr(log_store, "_INDEX_DIR", tmp_path / "run_logs")
    monkeypatch.setattr(log_store, "_last_purge_at", time.time())
    # Keep cross-test leakage out of the staged usage table.
    TokenRecordingModelWrapper._usage_by_session.pop("s-1", None)
    return tmp_path


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_resolve_environment_maps_draft_suffix():
    assert _resolve_environment("expert_x__draft") == "debug"
    assert _resolve_environment("expert_x") == "online"
    assert _resolve_environment(None) == "online"


def test_sum_delta_tokens_only_counts_assistant_usage():
    delta = [
        {"role": "user", "content": "hi"},
        _assistant_msg(tokens=40),
        {"role": "assistant", "content": "no meta"},
        _assistant_msg(tokens=15),
    ]
    assert _sum_delta_tokens(delta) == 55
    assert _sum_delta_tokens([]) == 0


# ---------------------------------------------------------------------------
# start hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_hook_writes_trace_and_index_row(store_dirs: Path):
    ctx = _make_ctx(session_messages=[_assistant_msg()])

    result = await RunLogStartHook().run(ctx)

    assert result.action.value == "continue"
    handoff = ctx.extras["_qp_runlog_ctx"]
    run_id = handoff["run_id"]
    assert (trace_store._TRACE_DIR / f"{run_id}.json").exists()
    assert handoff["baseline_count"] == 1

    shard = next((log_store._INDEX_DIR).glob("index-*.jsonl"))
    row = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
    assert row["run_id"] == run_id
    assert row["status"] == "running"
    assert row["source"] == "chat"
    assert row["channel"] == "feishim"
    # Agent labels advertised by the config land in both stores.
    assert row["version"] == "1.2.3"
    assert row["model"] == "qwen-max"
    assert row["app_version"]
    trace = await trace_store.get_trace(run_id)
    assert trace["meta"]["model"] == "qwen-max"
    assert trace["meta"]["version"] == "1.2.3"


@pytest.mark.asyncio
async def test_start_hook_swallows_store_failures(store_dirs: Path):
    # Point the store at a path that cannot exist (a file as a directory)
    # so the append blows up; the hook must still return cleanly.
    import qwenpaw.app.run_log_store as store_mod

    blocked = store_dirs / "blocked"
    blocked.write_text("not a dir", encoding="utf-8")
    store_mod._INDEX_DIR = blocked  # type: ignore[assignment]

    ctx = _make_ctx()
    result = await RunLogStartHook().run(ctx)

    assert result.action.value == "continue"
    assert "_qp_runlog_ctx" not in ctx.extras


# ---------------------------------------------------------------------------
# finish hook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finish_hook_finalizes_success_with_tokens(store_dirs: Path):
    ctx = _make_ctx(session_messages=[_assistant_msg(tokens=0)])
    await RunLogStartHook().run(ctx)
    handoff = ctx.extras["_qp_runlog_ctx"]
    # Simulate work time so duration_ms is a positive number.
    handoff["started_at"] = time.time() - 2
    # The run appends one assistant message to the session during work.
    ctx.workspace.session.messages.append(_assistant_msg(tokens=55))

    await RunLogFinishHook().run(ctx)

    trace = await trace_store.get_trace(handoff["run_id"])
    assert trace is not None
    assert trace["status"] == "success"
    assert len(trace["events"]) == 1
    assert trace["events"][0]["event"]["role"] == "assistant"

    shard = next((log_store._INDEX_DIR).glob("index-*.jsonl"))
    row = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "success"
    assert row["total_tokens"] == 55
    assert row["duration_ms"] >= 1000


@pytest.mark.asyncio
async def test_finish_hook_marks_failures(store_dirs: Path):
    ctx = _make_ctx(error=RuntimeError("model exploded"))
    await RunLogStartHook().run(ctx)
    run_id = ctx.extras["_qp_runlog_ctx"]["run_id"]

    await RunLogFinishHook().run(ctx)

    trace = await trace_store.get_trace(run_id)
    assert trace["status"] == "failed"
    assert "model exploded" in trace["error"]

    shard = next((log_store._INDEX_DIR).glob("index-*.jsonl"))
    row = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "failed"


@pytest.mark.asyncio
async def test_finish_hook_noop_without_start(store_dirs: Path):
    ctx = _make_ctx()
    result = await RunLogFinishHook().run(ctx)
    assert result.action.value == "continue"


@pytest.mark.asyncio
async def test_finish_hook_prefers_staged_usage(store_dirs: Path):
    """Staged usage (written pre-channel-commit) wins over the delta scan."""
    ctx = _make_ctx(session_messages=[_assistant_msg(tokens=0)])
    await RunLogStartHook().run(ctx)
    run_id = ctx.extras["_qp_runlog_ctx"]["run_id"]
    TokenRecordingModelWrapper._usage_by_session["s-1"] = {
        "model_name": "qwen-plus",
        "total_tokens": 4321,
    }

    await RunLogFinishHook().run(ctx)

    shard = next((log_store._INDEX_DIR).glob("index-*.jsonl"))
    row = json.loads(shard.read_text(encoding="utf-8").splitlines()[0])
    assert row["total_tokens"] == 4321
    # Actually-used model overrides the config prediction.
    assert row["model"] == "qwen-plus"
    # Peek must not pop: the channel layer still owns the record.
    assert "s-1" in TokenRecordingModelWrapper._usage_by_session
