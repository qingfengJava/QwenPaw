# -*- coding: utf-8 -*-
"""Unit tests for trusted user identity resolution (M1 shadow mode)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.agent_context import (
    _enforce_expert_acl,
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


class _StubUserStore:
    """Minimal ``users.store`` stand-in: one known admin, no one else."""

    def get_user(self, username: str):
        if username == "alice":
            return SimpleNamespace(role="admin")
        return None


class TestEnforceExpertAcl:
    """Lock the expert ACL gate semantics.

    Regression guard: ``HTTPException`` was undefined inside
    ``_enforce_expert_acl``, so every enforce-mode rejection raised
    ``NameError`` instead, was swallowed by the broad except and
    degraded the fail-closed gate into a logged fail-open.
    """

    @staticmethod
    def _request(username):
        return SimpleNamespace(state=SimpleNamespace(user=username))

    def test_non_expert_agent_short_circuits(self) -> None:
        # Plain agents (no expert_/team_ prefix) never touch RBAC.
        _enforce_expert_acl(self._request(None), "default")

    def test_enforce_off_allows_expert_agents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "qwenpaw.app.rbac.deps.rbac_enforcement_enabled",
            lambda: False,
        )
        _enforce_expert_acl(self._request(None), "expert_builtin_researcher")

    def test_enforce_on_without_identity_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "qwenpaw.app.rbac.deps.rbac_enforcement_enabled",
            lambda: True,
        )
        with pytest.raises(HTTPException) as exc_info:
            _enforce_expert_acl(
                self._request(None), "expert_builtin_researcher"
            )
        assert exc_info.value.status_code == 403

    def test_enforce_on_denied_agent_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "qwenpaw.app.rbac.deps.rbac_enforcement_enabled",
            lambda: True,
        )
        monkeypatch.setattr(
            "qwenpaw.app.users.store.get_user_store",
            lambda: _StubUserStore(),
        )
        monkeypatch.setattr(
            "qwenpaw.app.rbac.store.get_rbac_store",
            # stub 形参序与真实 RbacStore.agent_allowed 严格一致，
            # 调用方参数错序会在此 TypeError 而非静默通过
            lambda: SimpleNamespace(
                agent_allowed=lambda username, flat_role="", agent_id="": False
            ),
        )
        with pytest.raises(HTTPException) as exc_info:
            _enforce_expert_acl(
                self._request("alice"), "expert_builtin_researcher"
            )
        assert exc_info.value.status_code == 403

    def test_enforce_on_allowed_agent_passes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "qwenpaw.app.rbac.deps.rbac_enforcement_enabled",
            lambda: True,
        )
        monkeypatch.setattr(
            "qwenpaw.app.users.store.get_user_store",
            lambda: _StubUserStore(),
        )
        monkeypatch.setattr(
            "qwenpaw.app.rbac.store.get_rbac_store",
            lambda: SimpleNamespace(
                agent_allowed=lambda username, flat_role="", agent_id="": True
            ),
        )
        # Must not raise: granted access resolves to a no-op.
        _enforce_expert_acl(self._request("alice"), "expert_builtin_researcher")

    def test_acl_infrastructure_failure_fails_open_with_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Gray-rollout design: ACL infra errors log a warning and allow,
        # so a broken store never takes down agent resolution.
        monkeypatch.setattr(
            "qwenpaw.app.rbac.deps.rbac_enforcement_enabled",
            lambda: True,
        )
        monkeypatch.setattr(
            "qwenpaw.app.users.store.get_user_store",
            lambda: _StubUserStore(),
        )

        def _broken_store():
            raise RuntimeError("rbac store unreadable")

        monkeypatch.setattr(
            "qwenpaw.app.rbac.store.get_rbac_store", _broken_store
        )
        with caplog.at_level("WARNING"):
            _enforce_expert_acl(
                self._request("alice"), "expert_builtin_researcher"
            )
        assert "expert ACL check errored" in caplog.text
