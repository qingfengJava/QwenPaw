# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for M4-3 agent/model grants (ACLs) and their enforcement points."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.rbac.models import GrantRecord
from qwenpaw.app.rbac.store import RbacStore
from qwenpaw.app.workspace.workspace import Workspace
from qwenpaw.exceptions import (
    AgentAccessDeniedException,
    UnauthorizedModelAccessException,
)
from qwenpaw.providers.retry_chat_model import _check_model_grant


@pytest.fixture
def store(tmp_path: Path) -> RbacStore:
    return RbacStore(tmp_path / "rbac.json")


# ---------------------------------------------------------------------------
# store ACL semantics
# ---------------------------------------------------------------------------


def test_absent_grant_is_unrestricted(store: RbacStore) -> None:
    assert store.agent_allowed("eve", "employee", "any-agent") is True
    assert store.model_allowed("eve", "employee", "p:any") is True


def test_agent_grant_by_user(store: RbacStore) -> None:
    store.set_agent_grant("bot-1", GrantRecord(users=["alice"]))
    assert store.agent_allowed("alice", "employee", "bot-1") is True
    assert store.agent_allowed("bob", "employee", "bot-1") is False
    # Other agents stay unrestricted.
    assert store.agent_allowed("bob", "employee", "bot-2") is True


def test_agent_grant_by_role(store: RbacStore) -> None:
    store.set_agent_grant("bot-1", GrantRecord(roles=["team_lead"]))
    assert store.agent_allowed("eve", "employee", "bot-1") is False
    store.grant_role("eve", "team_lead")
    assert store.agent_allowed("eve", "employee", "bot-1") is True
    # flat admin maps onto platform_admin, not team_lead — still denied.
    assert store.agent_allowed("root", "admin", "bot-1") is False


def test_agent_grant_by_team(store: RbacStore) -> None:
    store.upsert_team("core", ["alice"])
    store.set_agent_grant("bot-1", GrantRecord(teams=["core"]))
    assert store.agent_allowed("alice", "employee", "bot-1") is True
    assert store.agent_allowed("bob", "employee", "bot-1") is False


def test_model_grant_exact_and_wildcard(store: RbacStore) -> None:
    store.set_model_grant("p:premium", GrantRecord(roles=["team_lead"]))
    assert store.model_allowed("eve", "employee", "p:premium") is False
    assert store.model_allowed("eve", "employee", "p:free") is True
    # Wildcard entry gates everything without an exact entry.
    store.set_model_grant("*", GrantRecord(roles=["employee"]))
    assert store.model_allowed("eve", "employee", "p:free") is True
    # Exact entry wins over the wildcard.
    assert store.model_allowed("eve", "employee", "p:premium") is False


def test_grant_fail_closed_except_flat_admin(tmp_path: Path) -> None:
    path = tmp_path / "rbac.json"
    path.write_text("{broken", encoding="utf-8")
    broken = RbacStore(path)
    assert broken.agent_allowed("eve", "employee", "bot-1") is False
    assert broken.agent_allowed("root", "admin", "bot-1") is True
    assert broken.model_allowed("eve", "employee", "p:m") is False
    assert broken.model_allowed("root", "admin", "p:m") is True


def test_delete_grant_restores_unrestricted(store: RbacStore) -> None:
    store.set_agent_grant("bot-1", GrantRecord(users=["alice"]))
    assert store.agent_allowed("bob", "employee", "bot-1") is False
    assert store.delete_agent_grant("bot-1") is True
    assert store.agent_allowed("bob", "employee", "bot-1") is True
    assert store.delete_agent_grant("bot-1") is False


# ---------------------------------------------------------------------------
# enforcement points
# ---------------------------------------------------------------------------


def _bare_workspace() -> Workspace:
    ws = Workspace.__new__(Workspace)
    ws.agent_id = "bot-1"
    return ws


def test_agent_grant_inert_when_enforcement_off(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QWENPAW_RBAC_ENFORCE", raising=False)
    ws = _bare_workspace()
    ws._assert_agent_grant("eve")  # no raise


def test_agent_grant_enforced(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "1")
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store.get_rbac_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "qwenpaw.app.rbac.deps._resolve_flat_role",
        lambda _u: "employee",
    )
    # The workspace module imports get_rbac_store lazily from the store
    # module, so patching the store module attribute covers it.
    store.set_agent_grant("bot-1", GrantRecord(users=["alice"]))
    ws = _bare_workspace()
    with pytest.raises(AgentAccessDeniedException):
        ws._assert_agent_grant("eve")
    ws._assert_agent_grant("alice")  # granted → no raise


def test_model_grant_inert_when_enforcement_off(store: RbacStore) -> None:
    _check_model_grant("p:premium")  # no raise


def test_model_grant_enforced(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "1")
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store.get_rbac_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "qwenpaw.app.rbac.deps._resolve_flat_role",
        lambda _u: "employee",
    )
    from qwenpaw.app.agent_context import scoped_user_id

    store.set_model_grant("p:premium", GrantRecord(users=["alice"]))
    with scoped_user_id("eve"):
        with pytest.raises(UnauthorizedModelAccessException):
            _check_model_grant("p:premium")
        _check_model_grant("p:free")  # unrestricted
    with scoped_user_id("alice"):
        _check_model_grant("p:premium")  # granted


# ---------------------------------------------------------------------------
# admin grants endpoints
# ---------------------------------------------------------------------------


def test_admin_grants_endpoints(tmp_path: Path) -> None:
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    from qwenpaw.app.routers.admin import router as admin_router
    from qwenpaw.app.users.store import UserStore
    import qwenpaw.app.rbac.store as rbac_module
    import qwenpaw.app.users.store as users_module

    users_module._default_store = UserStore(tmp_path / "users.json")
    rbac_module._default_store = RbacStore(tmp_path / "rbac.json")

    app = FastAPI()

    @app.middleware("http")
    async def _fake_auth(request: Request, call_next):
        request.state.user = "root"
        return await call_next(request)

    app.include_router(admin_router, prefix="/api")
    with TestClient(app) as client:
        resp = client.put(
            "/api/admin/grants/agents/bot-1",
            json={"users": ["alice"]},
        )
        assert resp.status_code == 200
        grants = client.get("/api/admin/grants/agents").json()
        assert grants["bot-1"]["users"] == ["alice"]

        resp = client.put(
            "/api/admin/grants/models/p:premium",
            json={"roles": ["team_lead"]},
        )
        assert resp.status_code == 200
        grants = client.get("/api/admin/grants/models").json()
        assert grants["p:premium"]["roles"] == ["team_lead"]

        assert (
            client.delete("/api/admin/grants/agents/bot-1").status_code
            == 204
        )
        assert (
            client.delete("/api/admin/grants/models/p:premium").status_code
            == 204
        )
    users_module._default_store = None
    rbac_module._default_store = None
