# -*- coding: utf-8 -*-
"""Unit tests for the auth module's multi-user bridge (M1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import qwenpaw.app.auth as auth
import qwenpaw.app.users.store as users_store
from qwenpaw.app.users.models import (
    PASSWORD_ALGO_ARGON2,
    PASSWORD_ALGO_SHA256,
    ROLE_ADMIN,
)
from qwenpaw.app.users.store import UserStore


@pytest.fixture
def isolated_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> UserStore:
    """Point ``auth.json`` and the user store at a temp directory."""
    auth_file = tmp_path / "secret" / "auth.json"
    store = UserStore(tmp_path / "secret" / "users.json")
    monkeypatch.setattr(auth, "AUTH_FILE", auth_file)
    monkeypatch.setattr(users_store, "_default_store", store)
    return store


def test_register_first_user_returns_token_and_admin(
    isolated_auth: UserStore,
) -> None:
    token = auth.register_user("alice", "pw-1")
    assert token
    assert auth.verify_token(token) == "alice"
    record = isolated_auth.get_user("alice")
    assert record is not None
    assert record.role == ROLE_ADMIN


def test_register_second_user_rejected(isolated_auth: UserStore) -> None:
    assert auth.register_user("alice", "pw-1")
    assert auth.register_user("bob", "pw-2") is None


def test_authenticate_success_and_failure(isolated_auth: UserStore) -> None:
    auth.register_user("alice", "pw-1")
    assert auth.authenticate("alice", "pw-1")
    assert auth.authenticate("alice", "wrong") is None
    assert auth.authenticate("ghost", "pw-1") is None


def test_legacy_auth_json_user_auto_migrates(isolated_auth: UserStore) -> None:
    # Build a legacy single-user auth.json (salted SHA-256 era).
    legacy_hash, legacy_salt = auth._hash_password("pw-1")
    auth.AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    auth.AUTH_FILE.write_text(
        json.dumps(
            {
                "jwt_secret": "legacy-secret",
                "user": {
                    "username": "alice",
                    "password_hash": legacy_hash,
                    "password_salt": legacy_salt,
                },
            },
        ),
        encoding="utf-8",
    )

    # Any entry point triggers the one-shot migration.
    assert auth.has_registered_users() is True
    record = isolated_auth.get_user("alice")
    assert record is not None
    assert record.role == ROLE_ADMIN
    assert record.password_algo == PASSWORD_ALGO_SHA256

    # Login against the legacy hash succeeds and upgrades to argon2id.
    token = auth.authenticate("alice", "pw-1")
    assert token
    record = isolated_auth.get_user("alice")
    assert record is not None
    assert record.password_algo == PASSWORD_ALGO_ARGON2


def test_disabled_user_token_rejected(isolated_auth: UserStore) -> None:
    token = auth.register_user("alice", "pw-1")
    assert auth.verify_token(token) == "alice"

    isolated_auth.set_disabled("alice", True)
    assert auth.verify_token(token) is None


def test_update_credentials_rejects_rename(isolated_auth: UserStore) -> None:
    auth.register_user("alice", "pw-1")
    assert (
        auth.update_credentials(
            username="alice",
            current_password="pw-1",
            new_username="alice2",
        )
        is None
    )


def test_update_credentials_requires_current_password(
    isolated_auth: UserStore,
) -> None:
    auth.register_user("alice", "pw-1")
    assert (
        auth.update_credentials(
            username="alice",
            current_password="wrong",
            new_password="pw-2",
        )
        is None
    )


def test_update_credentials_password_change(isolated_auth: UserStore) -> None:
    auth.register_user("alice", "pw-1")
    token = auth.update_credentials(
        username="alice",
        current_password="pw-1",
        new_password="pw-2",
    )
    assert token
    assert auth.authenticate("alice", "pw-1") is None
    assert auth.authenticate("alice", "pw-2")
