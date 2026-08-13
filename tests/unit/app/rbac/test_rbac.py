# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the M4 RBAC store, matching rules and FastAPI deps."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.rbac import (
    PERM_ADMIN_USERS,
    PERM_ALL,
    PERM_KB_READ,
    ROLE_EMPLOYEE,
    ROLE_PLATFORM_ADMIN,
    ROLE_TEAM_LEAD,
    has_permission,
    permission_matches,
    require_perm,
)
from qwenpaw.app.rbac.models import (
    FLAT_ROLE_TO_RBAC,
    RbacFile,
    RoleRecord,
)
from qwenpaw.app.rbac.store import RbacStore


# ---------------------------------------------------------------------------
# permission matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grant", "required", "expected"),
    [
        ("*", "admin:users", True),
        ("agent:*", "agent:use", True),
        ("agent:*", "agent:manage", True),
        ("agent:*", "kb:read", False),
        ("kb:read", "kb:read", True),
        ("kb:read", "kb:write", False),
        ("kb:read", "admin:users", False),
        ("", "kb:read", False),
        ("kb:read", "", False),
        ("agent", "agent:use", False),  # no bare-resource shorthand
    ],
)
def test_permission_matches(
    grant: str,
    required: str,
    expected: bool,
) -> None:
    assert permission_matches(grant, required) is expected


def test_has_permission_any_grant() -> None:
    grants = ["kb:read", "agent:*"]
    assert has_permission(grants, "agent:manage") is True
    assert has_permission(grants, "admin:users") is False


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> RbacStore:
    return RbacStore(tmp_path / "rbac.json")


def test_builtin_roles_seeded(store: RbacStore) -> None:
    roles = {role.name: role for role in store.list_roles()}
    assert roles[ROLE_PLATFORM_ADMIN].permissions == [PERM_ALL]
    assert roles[ROLE_PLATFORM_ADMIN].builtin is True
    assert PERM_KB_READ in roles[ROLE_EMPLOYEE].permissions
    assert PERM_ADMIN_USERS not in roles[ROLE_TEAM_LEAD].permissions


def test_builtin_roles_cannot_be_weakened_by_file(
    store: RbacStore,
) -> None:
    # A hand-edited rbac.json trying to strip the admin role is re-seeded.
    data = RbacFile(
        roles={
            ROLE_PLATFORM_ADMIN: RoleRecord(
                name=ROLE_PLATFORM_ADMIN,
                permissions=[],
                builtin=True,
            ),
        },
    )
    store.path.write_text(
        json.dumps(data.model_dump(mode="json")),
        encoding="utf-8",
    )
    role = store.get_role(ROLE_PLATFORM_ADMIN)
    assert role is not None and role.permissions == [PERM_ALL]


def test_flat_role_mapping_is_bootstrap(store: RbacStore) -> None:
    assert store.roles_for_user("root", flat_role="admin") == [
        ROLE_PLATFORM_ADMIN,
    ]
    assert store.roles_for_user("eve", flat_role="employee") == [
        ROLE_EMPLOYEE,
    ]
    assert store.roles_for_user("anon", flat_role="") == []


def test_user_has_permission_via_flat_role(store: RbacStore) -> None:
    assert store.user_has_permission("root", PERM_ADMIN_USERS, "admin")
    assert not store.user_has_permission("eve", PERM_ADMIN_USERS, "employee")
    assert store.user_has_permission("eve", PERM_KB_READ, "employee")


def test_grant_and_revoke_role(store: RbacStore) -> None:
    assert store.grant_role("eve", ROLE_TEAM_LEAD) is True
    assert ROLE_TEAM_LEAD in store.roles_for_user("eve", "employee")
    # team_lead grant is additive over the employee flat role.
    assert store.user_has_permission("eve", "kb:write", "employee")
    assert store.revoke_role("eve", ROLE_TEAM_LEAD) is True
    assert not store.user_has_permission("eve", "kb:write", "employee")
    assert store.revoke_role("eve", ROLE_TEAM_LEAD) is False


def test_grant_unknown_role_rejected(store: RbacStore) -> None:
    assert store.grant_role("eve", "no_such_role") is False


def test_custom_role_crud(store: RbacStore) -> None:
    role = store.upsert_role(
        "auditor",
        ["admin:audit", "kb:read"],
        description="read-only auditor",
    )
    assert role is not None and role.builtin is False
    assert store.grant_role("carol", "auditor") is True
    assert store.user_has_permission("carol", "admin:audit", "employee")
    assert not store.user_has_permission("carol", PERM_ADMIN_USERS, "employee")

    # Deleting the role strips it from grants.
    assert store.delete_role("auditor") is True
    assert store.get_role("auditor") is None
    assert "auditor" not in store.roles_for_user("carol", "employee")


def test_builtin_role_immutable_and_undeletable(store: RbacStore) -> None:
    assert store.upsert_role(ROLE_EMPLOYEE, ["*"]) is None
    assert store.delete_role(ROLE_EMPLOYEE) is False


def test_store_fail_closed_except_flat_admin(tmp_path: Path) -> None:
    path = tmp_path / "rbac.json"
    path.write_text("{not json", encoding="utf-8")
    broken = RbacStore(path)
    assert not broken.user_has_permission("eve", PERM_KB_READ, "employee")
    # Bootstrap guarantee: a flat admin is never locked out.
    assert broken.user_has_permission("root", PERM_ADMIN_USERS, "admin")


def test_teams_crud(store: RbacStore) -> None:
    team = store.upsert_team("core", ["alice", "bob"], description="d")
    assert team is not None
    assert store.teams_for_user("alice") == ["core"]
    assert store.teams_for_user("carol") == []
    assert store.get_team("core") is not None
    assert store.delete_team("core") is True
    assert store.teams_for_user("alice") == []


# ---------------------------------------------------------------------------
# require_perm dependency
# ---------------------------------------------------------------------------


def _request(user: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(user=user),
        url=SimpleNamespace(path="/api/admin/users"),
    )


async def test_require_perm_disabled_passes_without_identity() -> None:
    dep = require_perm(PERM_ADMIN_USERS)
    await dep(_request(None))  # no raise


async def test_require_perm_enforced_allows_admin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "1")
    monkeypatch.setattr(
        "qwenpaw.app.rbac.deps.get_rbac_store",
        lambda: RbacStore(tmp_path / "rbac.json"),
    )
    monkeypatch.setattr(
        "qwenpaw.app.rbac.deps._resolve_flat_role",
        lambda _u: "admin",
    )
    await require_perm(PERM_ADMIN_USERS)(_request("root"))


async def test_require_perm_enforced_denies_employee(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "1")
    monkeypatch.setattr(
        "qwenpaw.app.rbac.deps.get_rbac_store",
        lambda: RbacStore(tmp_path / "rbac.json"),
    )
    monkeypatch.setattr(
        "qwenpaw.app.rbac.deps._resolve_flat_role",
        lambda _u: "employee",
    )
    with pytest.raises(HTTPException) as exc_info:
        await require_perm(PERM_ADMIN_USERS)(_request("eve"))
    assert exc_info.value.status_code == 403
    # An employee permission passes.
    await require_perm(PERM_KB_READ)(_request("eve"))


async def test_require_perm_enforced_rejects_anonymous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "1")
    with pytest.raises(HTTPException) as exc_info:
        await require_perm(PERM_KB_READ)(_request(None))
    assert exc_info.value.status_code == 403


def test_flat_role_mapping_covers_m1_roles() -> None:
    assert FLAT_ROLE_TO_RBAC["admin"] == [ROLE_PLATFORM_ADMIN]
    assert FLAT_ROLE_TO_RBAC["employee"] == [ROLE_EMPLOYEE]
