# -*- coding: utf-8 -*-
"""Tests for the ``/auth/verify`` role metadata (M5)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import qwenpaw.app.auth as auth
import qwenpaw.app.rbac.store as rbac_store_module
import qwenpaw.app.users.store as users_store
from qwenpaw.app.rbac.store import RbacStore
from qwenpaw.app.routers.auth import router as auth_router
from qwenpaw.app.users.store import UserStore


@pytest.fixture
def verify_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Auth router against isolated auth.json / users.json / rbac.json."""
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "secret" / "auth.json")
    store = UserStore(tmp_path / "secret" / "users.json")
    rbac = RbacStore(tmp_path / "rbac.json")
    monkeypatch.setattr(users_store, "_default_store", store)
    monkeypatch.setattr(rbac_store_module, "_default_store", rbac)
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    with TestClient(app) as client:
        yield client, store, rbac


def test_verify_auth_disabled_reports_admin(verify_client) -> None:
    client, _, _ = verify_client
    resp = client.get("/api/auth/verify")
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["role"] == "admin"
    assert "platform_admin" in body["roles"]


def test_verify_returns_admin_roles(
    verify_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "1")
    client, store, _ = verify_client
    token = auth.register_user("alice", "pw-1")
    assert token
    assert store.get_user("alice").role == "admin"

    resp = client.get(
        "/api/auth/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice"
    assert body["role"] == "admin"
    assert "platform_admin" in body["roles"]


def test_verify_returns_employee_and_granted_roles(
    verify_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "1")
    client, store, rbac = verify_client
    assert auth.register_user("alice", "pw-1")  # first user -> admin
    store.create_user("bob", "pw-2")
    assert rbac.grant_role("bob", "team_lead") is True

    token = auth.authenticate("bob", "pw-2")
    assert token
    resp = client.get(
        "/api/auth/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "bob"
    assert body["role"] == "employee"
    assert "employee" in body["roles"]
    assert "team_lead" in body["roles"]


def test_verify_rejects_missing_or_bad_token(
    verify_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "1")
    client, _, _ = verify_client
    assert client.get("/api/auth/verify").status_code == 401
    resp = client.get(
        "/api/auth/verify",
        headers={"Authorization": "Bearer not-a-token"},
    )
    assert resp.status_code == 401


def test_verify_role_lookup_failure_degrades(
    verify_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken rbac store must not fail the token check itself."""
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "1")
    client, _, rbac = verify_client
    token = auth.register_user("alice", "pw-1")
    assert token

    def _boom(*_args, **_kwargs):
        raise RuntimeError("rbac.json corrupted")

    monkeypatch.setattr(rbac, "roles_for_user", _boom)
    resp = client.get(
        "/api/auth/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["username"] == "alice"
    assert body["roles"] == []
