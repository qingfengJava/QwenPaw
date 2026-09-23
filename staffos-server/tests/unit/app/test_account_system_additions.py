# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the account-system backend additions.

Covers:
- run_logs router data-permission helpers (employee scope + ownership gate);
- file UserStore new methods: ``set_profile`` and ``list_identity_bindings``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.routers import run_logs
from qwenpaw.app.users.store import UserStore
from qwenpaw.app.users.models import ROLE_ADMIN, ROLE_EMPLOYEE


# ---------------------------------------------------------------------------
# run_logs data-permission helpers
# ---------------------------------------------------------------------------


def _request(user=None):
    """Minimal FastAPI Request stand-in carrying request.state.user."""
    return SimpleNamespace(state=SimpleNamespace(user=user))


def test_scope_viewer_no_auth_passes_claim_through():
    # 认证关闭（无 request.state.user）：客户端 user 参数原样透传。
    assert run_logs._scope_user_for_viewer(_request(None), "alice") == "alice"
    assert run_logs._scope_user_for_viewer(_request(None), None) is None


def test_scope_viewer_employee_is_forced_to_self(monkeypatch: pytest.MonkeyPatch):
    # employee 一律收窄到自己，忽略客户端传入的他人 user。
    monkeypatch.setattr(
        run_logs,
        "_viewer_role",
        lambda _username: ROLE_EMPLOYEE,
    )
    assert run_logs._scope_user_for_viewer(_request("bob"), "alice") == "bob"


def test_scope_viewer_admin_keeps_claim(monkeypatch: pytest.MonkeyPatch):
    # admin 保留任意筛选能力。
    monkeypatch.setattr(
        run_logs,
        "_viewer_role",
        lambda _username: ROLE_ADMIN,
    )
    assert run_logs._scope_user_for_viewer(_request("root"), "alice") == "alice"


def test_can_view_run_employee_ownership_gate(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        run_logs,
        "_viewer_role",
        lambda _username: ROLE_EMPLOYEE,
    )
    # 自己的运行可看，他人的拒绝（详情端点据此返回 404）。
    assert run_logs._can_view_run(_request("alice"), "alice") is True
    assert run_logs._can_view_run(_request("alice"), "bob") is False
    # 空归属（历史/匿名行）对 employee 不放开，避免越权读取。
    assert run_logs._can_view_run(_request("alice"), None) is False


def test_can_view_run_admin_and_anonymous(monkeypatch: pytest.MonkeyPatch):
    # 认证关闭：任何人可看。
    assert run_logs._can_view_run(_request(None), "anyone") is True
    monkeypatch.setattr(
        run_logs,
        "_viewer_role",
        lambda _username: ROLE_ADMIN,
    )
    # admin：全量可看。
    assert run_logs._can_view_run(_request("root"), "someone") is True


# ---------------------------------------------------------------------------
# file UserStore additions
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path / "users.json")


def test_set_profile_updates_display_name_and_avatar(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    assert store.set_profile("alice", display_name="Alice Zhang") is True
    assert store.get_user("alice").display_name == "Alice Zhang"

    assert store.set_profile("alice", avatar="https://cdn/a.png") is True
    rec = store.get_user("alice")
    # 仅改头像时昵称保持不变（None 字段不触碰）。
    assert rec.display_name == "Alice Zhang"
    assert rec.avatar == "https://cdn/a.png"


def test_set_profile_unknown_user_returns_false(store: UserStore) -> None:
    assert store.set_profile("ghost", display_name="x") is False


def test_list_identity_bindings_shape(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    assert store.bind_identity("dingtalk", "dt-1", "alice") is True
    rows = store.list_identity_bindings()
    assert rows == [
        {
            "channel": "dingtalk",
            "external_user_id": "dt-1",
            "username": "alice",
        },
    ]
