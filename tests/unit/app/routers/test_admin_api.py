# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the M4 admin API (users/roles/teams/audit)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app.rbac.store import RbacStore
from qwenpaw.app.routers.admin import router as admin_router
from qwenpaw.app.users.store import UserStore
from qwenpaw.governance.audit import AuditLog


@pytest.fixture
def admin_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """A minimal app mounting the admin router with a header-driven
    fake identity (AuthMiddleware is out of scope for these tests)."""
    user_store = UserStore(tmp_path / "users.json")
    rbac_store = RbacStore(tmp_path / "rbac.json")
    monkeypatch.setattr(
        "qwenpaw.app.users.store._default_store",
        user_store,
    )
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store._default_store",
        rbac_store,
    )
    # Close any live singleton before rebinding: monkeypatching
    # ``_instance`` would resurrect the closed instance on undo (its
    # writer thread is dead, and a second close() then blocks forever
    # on the queue join).
    existing = AuditLog._instance
    if existing is not None:
        existing.close()
    audit_log = AuditLog.get_instance(tmp_path / "auditdir")

    app = FastAPI()

    @app.middleware("http")
    async def _fake_auth(request: Request, call_next):
        request.state.user = request.headers.get("x-test-user") or None
        return await call_next(request)

    app.include_router(admin_router, prefix="/api")
    # TestClient must be closed explicitly: its anyio portal thread keeps
    # the pytest process alive otherwise.
    with TestClient(app) as client:
        yield client, user_store, rbac_store
    audit_log.close()


def _enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "1")


# ---------------------------------------------------------------------------
# enforcement gate
# ---------------------------------------------------------------------------


def test_open_when_enforcement_off(admin_app) -> None:
    client, _, _ = admin_app
    # No identity at all: enforcement off means routes stay reachable.
    resp = client.get("/api/admin/users")
    assert resp.status_code == 200


def test_forbidden_without_identity_when_enforced(
    admin_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enforced(monkeypatch)
    client, _, _ = admin_app
    assert client.get("/api/admin/users").status_code == 403


def test_forbidden_for_employee_when_enforced(
    admin_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enforced(monkeypatch)
    client, users, _ = admin_app
    users.create_user("root", "pw")  # first user becomes admin
    users.create_user("eve", "pw")
    resp = client.get("/api/admin/users", headers={"x-test-user": "eve"})
    assert resp.status_code == 403


def test_allowed_for_admin_when_enforced(
    admin_app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enforced(monkeypatch)
    client, users, _ = admin_app
    users.create_user("root", "pw")
    resp = client.get("/api/admin/users", headers={"x-test-user": "root"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


def test_user_crud_flow(admin_app) -> None:
    client, users, _ = admin_app
    users.create_user("root", "pw")

    created = client.post(
        "/api/admin/users",
        json={"username": "eve", "password": "pw2", "display_name": "Eve"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["username"] == "eve"
    assert body["role"] == "employee"
    assert "password" not in body and "password_hash" not in body

    duplicate = client.post(
        "/api/admin/users",
        json={"username": "eve", "password": "pw2"},
    )
    assert duplicate.status_code == 409

    assert (
        client.post(
            "/api/admin/users/eve/password",
            json={"password": "newpw"},
        ).status_code
        == 204
    )
    assert users.verify_password("eve", "newpw") is not None

    # Disable last: a disabled account fails verify_password by design.
    patched = client.patch(
        "/api/admin/users/eve",
        json={"display_name": "Eve S.", "disabled": True},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "Eve S."
    assert patched.json()["disabled"] is True
    assert users.get_user("eve").disabled is True


def test_self_lockout_guard(admin_app) -> None:
    client, users, _ = admin_app
    users.create_user("root", "pw")
    resp = client.patch(
        "/api/admin/users/root",
        json={"disabled": True},
        headers={"x-test-user": "root"},
    )
    assert resp.status_code == 400
    resp = client.patch(
        "/api/admin/users/root",
        json={"role": "employee"},
        headers={"x-test-user": "root"},
    )
    assert resp.status_code == 400
    assert users.get_user("root").role == "admin"


def test_role_grant_flow(admin_app) -> None:
    client, users, rbac = admin_app
    users.create_user("root", "pw")
    users.create_user("eve", "pw")

    assert (
        client.post(
            "/api/admin/users/eve/roles",
            json={"role": "team_lead"},
        ).status_code
        == 204
    )
    assert "team_lead" in rbac.roles_for_user("eve", "employee")

    got = client.get("/api/admin/users/eve")
    assert got.json()["rbac_roles"] == ["employee", "team_lead"]

    assert (
        client.delete("/api/admin/users/eve/roles/team_lead").status_code
        == 204
    )
    assert "team_lead" not in rbac.roles_for_user("eve", "employee")

    assert (
        client.post(
            "/api/admin/users/eve/roles",
            json={"role": "nope"},
        ).status_code
        == 400
    )


# ---------------------------------------------------------------------------
# roles / teams
# ---------------------------------------------------------------------------


def test_roles_crud_and_builtin_protection(admin_app) -> None:
    client, _, _ = admin_app
    roles = client.get("/api/admin/roles").json()
    names = {r["name"] for r in roles}
    assert {"platform_admin", "team_lead", "employee"} <= names

    created = client.put(
        "/api/admin/roles/auditor",
        json={"permissions": ["admin:audit"], "description": "d"},
    )
    assert created.status_code == 200
    assert created.json()["builtin"] is False

    builtin = client.put(
        "/api/admin/roles/employee",
        json={"permissions": ["*"]},
    )
    assert builtin.status_code == 400

    assert client.delete("/api/admin/roles/auditor").status_code == 204
    assert client.delete("/api/admin/roles/employee").status_code == 404


def test_teams_crud(admin_app) -> None:
    client, _, _ = admin_app
    resp = client.put(
        "/api/admin/teams/core",
        json={"members": ["alice", "bob"]},
    )
    assert resp.status_code == 200
    teams = client.get("/api/admin/teams").json()
    assert teams[0]["members"] == ["alice", "bob"]
    assert client.delete("/api/admin/teams/core").status_code == 204


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def test_audit_query_shape(admin_app) -> None:
    client, _, _ = admin_app
    from qwenpaw.governance.policy import (
        GovernanceAction,
        GovernanceDecision,
        ToolCallSpec,
    )

    AuditLog.get_instance().record(
        "/ws",
        ToolCallSpec(
            tool_name="Bash",
            target="ls",
            agent_id="a1",
            session_id="s1",
            user_id="alice",
        ),
        GovernanceDecision(action=GovernanceAction.ALLOW, reason="ok"),
    )
    AuditLog.get_instance().flush()

    resp = client.get("/api/admin/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    event = body["events"][0]
    assert event["actor_id"] == "alice"
    assert event["tool_name"] == "Bash"
