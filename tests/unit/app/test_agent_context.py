# -*- coding: utf-8 -*-
"""Unit tests for trusted user identity resolution (M1 shadow mode)."""

from __future__ import annotations

import pytest

from qwenpaw.app.agent_context import (
    resolve_trusted_user_id,
    set_current_user_id,
)
from qwenpaw.runtime.runtime import Runtime


@pytest.fixture(autouse=True)
def _clear_user_context():
    """Ensure the request-scoped user context never leaks between tests."""
    set_current_user_id(None)
    yield
    set_current_user_id(None)


class TestResolveTrustedUserId:
    def test_no_auth_user_claimed_wins(self) -> None:
        assert resolve_trusted_user_id("bob", fallback="s1") == "bob"

    def test_no_auth_user_falls_back(self) -> None:
        assert resolve_trusted_user_id(None, fallback="s1") == "s1"
        assert resolve_trusted_user_id("", fallback="s1") == "s1"

    def test_auth_user_overrides_claim(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        set_current_user_id("alice")
        with caplog.at_level("WARNING"):
            assert resolve_trusted_user_id("bob", fallback="s1") == "alice"
        assert "bob" in caplog.text

    def test_auth_user_matching_claim_stays_silent(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        set_current_user_id("alice")
        with caplog.at_level("WARNING"):
            assert resolve_trusted_user_id("alice", fallback="s1") == "alice"
        assert caplog.text == ""

    def test_auth_user_claim_equals_fallback_stays_silent(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # A claim equal to the session fallback is the legacy default,
        # not an identity spoof attempt.
        set_current_user_id("alice")
        with caplog.at_level("WARNING"):
            assert resolve_trusted_user_id("s1", fallback="s1") == "alice"
        assert caplog.text == ""


class TestRuntimeNormalize:
    def test_legacy_fallback_without_auth(self) -> None:
        req = Runtime._normalize({"session_id": "s1"})
        assert req.user_id == "s1"

    def test_session_id_generated_when_missing(self) -> None:
        req = Runtime._normalize({})
        assert req.session_id
        assert req.user_id == req.session_id

    def test_auth_user_overrides_body_claim(self) -> None:
        set_current_user_id("alice")
        req = Runtime._normalize({"session_id": "s1", "user_id": "mallory"})
        assert req.user_id == "alice"

    def test_claimed_user_kept_without_auth(self) -> None:
        req = Runtime._normalize({"session_id": "s1", "user_id": "bob"})
        assert req.user_id == "bob"
