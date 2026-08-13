# -*- coding: utf-8 -*-
"""Unit tests for the multi-user account store (M1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.users.models import (
    PASSWORD_ALGO_ARGON2,
    PASSWORD_ALGO_SHA256,
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
)
from qwenpaw.app.users.store import UserStore


@pytest.fixture
def store(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path / "users.json")


# ----------------------------------------------------------------------
# account creation
# ----------------------------------------------------------------------


def test_first_user_becomes_admin(store: UserStore) -> None:
    record = store.create_user("alice", "pw-1")
    assert record is not None
    assert record.role == ROLE_ADMIN
    assert record.password_algo == PASSWORD_ALGO_ARGON2
    assert record.password_salt == ""


def test_second_user_defaults_to_employee(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    second = store.create_user("bob", "pw-2")
    assert second is not None
    assert second.role == ROLE_EMPLOYEE


def test_duplicate_username_rejected(store: UserStore) -> None:
    assert store.create_user("alice", "pw-1") is not None
    assert store.create_user("alice", "pw-2") is None


def test_blank_credentials_rejected(store: UserStore) -> None:
    assert store.create_user("", "pw") is None
    assert store.create_user("alice", "") is None


# ----------------------------------------------------------------------
# verification
# ----------------------------------------------------------------------


def test_verify_password_round_trip(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    record = store.verify_password("alice", "pw-1")
    assert record is not None
    assert record.username == "alice"


def test_verify_wrong_password_denied(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    assert store.verify_password("alice", "wrong") is None


def test_verify_unknown_user_denied(store: UserStore) -> None:
    assert store.verify_password("ghost", "pw") is None


def test_disabled_user_denied(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    assert store.set_disabled("alice", True) is True
    assert store.verify_password("alice", "pw-1") is None
    assert store.is_active("alice") is False
    assert store.set_disabled("alice", False) is True
    assert store.verify_password("alice", "pw-1") is not None


def test_update_password(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    assert store.update_password("alice", "pw-2") is True
    assert store.verify_password("alice", "pw-1") is None
    assert store.verify_password("alice", "pw-2") is not None
    record = store.get_user("alice")
    assert record is not None
    assert record.password_algo == PASSWORD_ALGO_ARGON2


def test_update_password_unknown_user(store: UserStore) -> None:
    assert store.update_password("ghost", "pw") is False


# ----------------------------------------------------------------------
# legacy migration & transparent hash upgrade
# ----------------------------------------------------------------------


def _legacy_record(username: str, password: str) -> dict:
    import hashlib
    import secrets

    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return {
        "username": username,
        "password_hash": digest,
        "password_salt": salt,
    }


def test_import_legacy_user_verifies_then_upgrades(store: UserStore) -> None:
    imported = store.import_legacy_user(_legacy_record("alice", "pw-1"))
    assert imported is not None
    assert imported.role == ROLE_ADMIN
    assert imported.password_algo == PASSWORD_ALGO_SHA256

    # First successful login against the legacy hash upgrades to argon2id.
    record = store.verify_password("alice", "pw-1")
    assert record is not None
    assert record.password_algo == PASSWORD_ALGO_ARGON2
    assert record.password_salt == ""

    # The upgraded hash keeps working.
    assert store.verify_password("alice", "pw-1") is not None
    assert store.verify_password("alice", "wrong") is None


def test_import_legacy_incomplete_record_rejected(store: UserStore) -> None:
    assert store.import_legacy_user({"username": "alice"}) is None
    assert store.has_users() is False


def test_import_legacy_idempotent(store: UserStore) -> None:
    legacy = _legacy_record("alice", "pw-1")
    assert store.import_legacy_user(legacy) is not None
    assert store.import_legacy_user(legacy) is not None
    assert len(store.list_users()) == 1


# ----------------------------------------------------------------------
# identity bindings
# ----------------------------------------------------------------------


def test_identity_binding_round_trip(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    assert store.bind_identity("dingtalk", "dt-uid-1", "alice") is True
    assert store.resolve_identity("dingtalk", "dt-uid-1") == "alice"
    assert store.resolve_identity("dingtalk", "other") is None
    assert store.resolve_identity("discord", "dt-uid-1") is None
    assert store.unbind_identity("dingtalk", "dt-uid-1") is True
    assert store.resolve_identity("dingtalk", "dt-uid-1") is None


def test_bind_identity_to_unknown_user_rejected(store: UserStore) -> None:
    assert store.bind_identity("dingtalk", "dt-uid-1", "ghost") is False


def test_bind_identity_requires_all_parts(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    assert store.bind_identity("", "x", "alice") is False
    assert store.bind_identity("dingtalk", "", "alice") is False
    assert store.bind_identity("dingtalk", "x", "") is False


# ----------------------------------------------------------------------
# fail-closed behaviour
# ----------------------------------------------------------------------


def test_corrupt_users_file_fails_closed(store: UserStore) -> None:
    store.create_user("alice", "pw-1")
    store.path.write_text("{ not json", encoding="utf-8")

    assert store.verify_password("alice", "pw-1") is None
    assert store.is_active("alice") is False
    assert store.create_user("bob", "pw-2") is None
