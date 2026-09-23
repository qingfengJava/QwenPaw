# -*- coding: utf-8 -*-
"""Tests for the BOOTSTRAP.md first-interaction guidance hook.

Regression guard: the guidance must be appended to the agent's
transient system prompt and must NEVER mutate the user's input
message — any in-place edit of ``ctx.input_msgs`` is deep-copied into
``state.context`` by agentscope and persists into the session
snapshot, echoing back as a polluted user message after refresh.
"""

import asyncio
from types import SimpleNamespace

from qwenpaw.hooks.bootstrap.bootstrap_hook import BootstrapHook
from qwenpaw.runtime.hooks import HookContext


def _make_ctx(tmp_path, *, agent=None, msgs=None, is_cron=False):
    """Build a minimal HookContext for the bootstrap hook."""
    return HookContext(
        request=SimpleNamespace(),
        session_id="s1",
        agent_id="default",
        root_session_id="",
        root_agent_id="",
        workspace_dir=tmp_path,
        workspace=None,
        app_services=None,
        input_msgs=msgs if msgs is not None else [],
        agent=agent,
        extras={"is_cron": True} if is_cron else {},
    )


def _run(coro):
    return asyncio.run(coro)


def test_guidance_goes_to_system_prompt_not_user_message(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("bootstrap me", encoding="utf-8")
    agent = SimpleNamespace(_system_prompt="You are QwenPaw.")
    original_content = [{"type": "text", "text": "能告诉我你有哪些技能吗？"}]
    msgs = [SimpleNamespace(role="user", content=original_content)]
    ctx = _make_ctx(tmp_path, agent=agent, msgs=msgs)

    _run(BootstrapHook().run(ctx))

    # Guidance landed on the transient system prompt.
    assert "# 引导模式" in agent._system_prompt
    assert agent._system_prompt.startswith("You are QwenPaw.")

    # The user's message content is untouched — this is the regression
    # that used to pollute the persisted session history.
    assert msgs[0].content == original_content

    # Completion flag prevents repeat injection.
    assert (tmp_path / ".bootstrap_completed").exists()


def test_skips_when_flag_already_exists(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("bootstrap me", encoding="utf-8")
    (tmp_path / ".bootstrap_completed").touch()
    agent = SimpleNamespace(_system_prompt="base")
    msgs = [SimpleNamespace(role="user", content=[{"type": "text", "text": "hi"}])]
    ctx = _make_ctx(tmp_path, agent=agent, msgs=msgs)

    _run(BootstrapHook().run(ctx))

    assert agent._system_prompt == "base"


def test_skips_without_bootstrap_md(tmp_path):
    agent = SimpleNamespace(_system_prompt="base")
    msgs = [SimpleNamespace(role="user", content=[{"type": "text", "text": "hi"}])]
    ctx = _make_ctx(tmp_path, agent=agent, msgs=msgs)

    _run(BootstrapHook().run(ctx))

    assert agent._system_prompt == "base"
    assert not (tmp_path / ".bootstrap_completed").exists()


def test_skips_for_cron_runs(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("bootstrap me", encoding="utf-8")
    agent = SimpleNamespace(_system_prompt="base")
    ctx = _make_ctx(tmp_path, agent=agent, is_cron=True)

    _run(BootstrapHook().run(ctx))

    assert agent._system_prompt == "base"
    assert not (tmp_path / ".bootstrap_completed").exists()


def test_skips_safely_without_agent(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("bootstrap me", encoding="utf-8")
    ctx = _make_ctx(tmp_path, agent=None)

    _run(BootstrapHook().run(ctx))

    assert not (tmp_path / ".bootstrap_completed").exists()
