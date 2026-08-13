# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the M3 per-user LLM quota (user-dimension rate limiter)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, AsyncGenerator

import pytest

from qwenpaw.app.agent_context import scoped_user_id
from qwenpaw.providers import rate_limiter as rl
from qwenpaw.providers.rate_limiter import (
    _limiters,
    get_user_rate_limiter,
)
from qwenpaw.providers.retry_chat_model import (
    RateLimitConfig,
    RetryChatModel,
    RetryConfig,
)


@pytest.fixture(autouse=True)
def _clear_limiters():
    _limiters.clear()
    yield
    _limiters.clear()


def _enable_user_quota(
    monkeypatch: pytest.MonkeyPatch,
    *,
    concurrent: int = 0,
    qpm: int = 0,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.constant.LLM_USER_MAX_CONCURRENT",
        concurrent,
    )
    monkeypatch.setattr(
        "qwenpaw.constant.LLM_USER_MAX_QPM",
        qpm,
    )


async def test_user_limiter_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_user_quota(monkeypatch, concurrent=0, qpm=0)
    assert await get_user_rate_limiter("alice") is None
    assert not _limiters


async def test_user_limiter_keyed_per_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_user_quota(monkeypatch, concurrent=2)
    alice = await get_user_rate_limiter("alice")
    bob = await get_user_rate_limiter("bob")
    assert alice is not None and bob is not None
    assert alice is not bob
    assert await get_user_rate_limiter("alice") is alice
    assert alice.stats()["max_concurrent"] == 2


async def test_user_limiter_empty_user_maps_to_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_user_quota(monkeypatch, concurrent=1)
    anon = await get_user_rate_limiter("")
    system = await get_user_rate_limiter("system")
    assert anon is system
    assert "user:system" in _limiters


async def test_user_limiter_qpm_only_does_not_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QPM-only configuration must not create a Semaphore(0)."""
    _enable_user_quota(monkeypatch, concurrent=0, qpm=5)
    limiter = await get_user_rate_limiter("alice")
    assert limiter is not None
    # Acquire/release twice: the semaphore ceiling never binds.
    await limiter.acquire()
    limiter.release()
    await limiter.acquire()
    limiter.release()
    assert limiter.stats()["max_qpm"] == 5


class _SlowModel:
    """Inner model recording its peak in-flight concurrency."""

    model = "user-quota-test"
    stream = False
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.in_flight = 0
        self.peak_in_flight = 0

    async def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return SimpleNamespace(content="ok")
        finally:
            self.in_flight -= 1


class _StreamModel:
    model = "user-quota-stream-test"
    stream = True
    context_size = 32768
    parameters = None
    _provider_id = "unit"

    async def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        async def _gen() -> AsyncGenerator[Any, None]:
            yield SimpleNamespace(content="chunk")

        return _gen()


def _wrap(inner: Any) -> RetryChatModel:
    return RetryChatModel(
        inner,
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(acquire_timeout=10.0),
    )


async def test_retry_chat_model_serializes_same_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent calls from one user never overlap when the
    per-user cap is 1."""
    _enable_user_quota(monkeypatch, concurrent=1)
    inner = _SlowModel()
    model = _wrap(inner)
    with scoped_user_id("alice"):
        await asyncio.gather(model(), model())
    assert inner.peak_in_flight == 1
    # The user slot was released: the limiter is idle again.
    assert _limiters["user:alice"].stats()["current_in_flight"] == 0


async def test_retry_chat_model_users_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different users hold independent quota buckets."""
    _enable_user_quota(monkeypatch, concurrent=1)
    inner = _SlowModel()
    model = _wrap(inner)

    async def _call_as(user: str) -> None:
        with scoped_user_id(user):
            await model()

    await asyncio.gather(_call_as("alice"), _call_as("bob"))
    assert inner.peak_in_flight == 2


async def test_retry_chat_model_stream_releases_user_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming success releases the user slot on the first chunk."""
    _enable_user_quota(monkeypatch, concurrent=1)
    inner = _StreamModel()
    model = _wrap(inner)
    with scoped_user_id("alice"):
        stream = await model()
        async for _ in stream:
            pass
    assert _limiters["user:alice"].stats()["current_in_flight"] == 0


async def test_retry_chat_model_disabled_quota_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default config (quota disabled) creates no user limiters."""
    _enable_user_quota(monkeypatch, concurrent=0, qpm=0)
    inner = _SlowModel()
    model = _wrap(inner)
    with scoped_user_id("alice"):
        await model()
    assert not any(k.startswith("user:") for k in _limiters)


# ---------------------------------------------------------------------------
# ToolCallSpec user context (M3 governor subject injection)
# ---------------------------------------------------------------------------


def test_tool_call_spec_user_id_defaults_empty() -> None:
    from qwenpaw.governance.policy import ToolCallSpec

    spec = ToolCallSpec(
        tool_name="Bash",
        target="ls",
        agent_id="a1",
        session_id="s1",
    )
    assert spec.user_id == ""


def test_build_tc_spec_prefers_request_context_user() -> None:
    from qwenpaw.governance.tool_adapter import _build_tc_spec

    tool = SimpleNamespace(
        _qp_governor=None,
        _qp_raw_params={},
        _qp_request_context={
            "agent_id": "a1",
            "session_id": "s1",
            "user_id": "alice",
        },
        name="execute_shell_command",
    )
    spec = _build_tc_spec(tool)
    assert spec.user_id == "alice"


def test_build_tc_spec_falls_back_to_context_var() -> None:
    from qwenpaw.governance.tool_adapter import _build_tc_spec

    tool = SimpleNamespace(
        _qp_governor=None,
        _qp_raw_params={},
        _qp_request_context={"agent_id": "a1", "session_id": "s1"},
        name="execute_shell_command",
    )
    with scoped_user_id("bob"):
        spec = _build_tc_spec(tool)
    assert spec.user_id == "bob"


def test_build_tc_spec_without_identity_is_empty() -> None:
    from qwenpaw.governance.tool_adapter import _build_tc_spec

    tool = SimpleNamespace(
        _qp_governor=None,
        _qp_raw_params={},
        _qp_request_context={},
        name="execute_shell_command",
    )
    spec = _build_tc_spec(tool)
    assert spec.user_id == ""
