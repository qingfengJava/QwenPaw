# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for registry viewer scoping (list visibility == runtime ACL).

Non-admins must never see an employee they cannot talk to, and admins must
see everything without paying for a per-row RBAC lookup. Both rules live in
``registry._apply_viewer_scope`` and reuse ``RbacStore.grant_allows`` so the
list shares one judgement with the runtime guard.
"""
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app.employees import registry as registry_mod
from qwenpaw.app.employees.models import DigitalEmployeeVO
from qwenpaw.app.rbac.models import GrantRecord
from qwenpaw.app.rbac.store import RbacStore


class _FakeRbac:
    """Preloaded RBAC snapshot; the real judgement method is reused."""

    # Reuse the production judgement verbatim (staticmethod keeps the
    # 4-argument signature when borrowed onto a fake class).
    grant_allows = staticmethod(RbacStore.grant_allows)

    def __init__(self, grants=None, roles=(), teams=(), *, load_error=False):
        self.grants = dict(grants or {})
        self.roles = list(roles)
        self.teams = list(teams)
        # Mirrors RbacStore.load_error: True simulates an unreadable file.
        self.load_error = load_error
        self.calls: list[str] = []

    def list_agent_grants(self):
        self.calls.append("list_agent_grants")
        return dict(self.grants)

    def roles_for_user(self, username, flat_role=""):
        self.calls.append("roles_for_user")
        return list(self.roles)

    def teams_for_user(self, username):
        self.calls.append("teams_for_user")
        return list(self.teams)


def _row(agent_id: str, **kwargs) -> DigitalEmployeeVO:
    payload = {"agent_id": agent_id, "name": agent_id}
    payload.update(kwargs)
    return DigitalEmployeeVO(**payload)


def _request(user: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=user))


def _rows() -> list:
    return [
        # Org-wide: no grant row at all.
        _row("default"),
        # Department scoped: ACL points at the mirrored department teams.
        _row(
            "expert_sales",
            visibility="department",
            department_id="d_sales",
        ),
        # Owner only.
        _row("expert_bob", visibility="private"),
        # Department scoped to a team the viewer is not part of.
        _row("expert_finance", visibility="department"),
        # Department hit, but never materialized into a runtime agent.
        _row("expert_draft", visibility="department", usable=False),
    ]


def _grants() -> dict:
    return {
        "expert_sales": GrantRecord(teams=["dept:sales"], users=["alice"]),
        "expert_bob": GrantRecord(users=["bob"]),
        "expert_finance": GrantRecord(teams=["dept:finance"]),
        "expert_draft": GrantRecord(teams=["dept:sales"], users=["alice"]),
    }


def _patch_viewer(monkeypatch, *, flat_role, rbac, auth_enabled=True):
    monkeypatch.setattr(
        registry_mod,
        "_resolve_flat_role",
        lambda user: flat_role,
    )
    monkeypatch.setattr(registry_mod, "get_rbac_store", lambda: rbac)
    import qwenpaw.app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "is_auth_enabled", lambda: auth_enabled)


# ---------------------------------------------------------------------------
# privileged viewers
# ---------------------------------------------------------------------------


def test_admin_sees_everything_and_skips_rbac(monkeypatch):
    rbac = _FakeRbac(_grants())
    _patch_viewer(monkeypatch, flat_role="admin", rbac=rbac)

    visible = registry_mod._apply_viewer_scope(_request("root"), _rows())

    assert [row.agent_id for row in visible] == [
        "default",
        "expert_sales",
        "expert_bob",
        "expert_finance",
        "expert_draft",
    ]
    # One snapshot for the whole list: no per-row RBAC access at all.
    assert rbac.calls == []


def test_admin_keeps_unmaterialized_row_unusable(monkeypatch):
    rbac = _FakeRbac(_grants())
    _patch_viewer(monkeypatch, flat_role="admin", rbac=rbac)

    visible = registry_mod._apply_viewer_scope(_request("root"), _rows())

    draft = next(row for row in visible if row.agent_id == "expert_draft")
    # Admin clears the ACL, but a draft has no workbench to open.
    assert draft.usable is False


def test_single_user_deployment_without_auth_is_privileged(monkeypatch):
    rbac = _FakeRbac({"expert_finance": GrantRecord(teams=["dept:finance"])})
    _patch_viewer(
        monkeypatch,
        flat_role="user",
        rbac=rbac,
        auth_enabled=False,
    )

    visible = registry_mod._apply_viewer_scope(_request("local"), _rows())

    assert len(visible) == len(_rows())
    assert rbac.calls == []


# ---------------------------------------------------------------------------
# regular viewers
# ---------------------------------------------------------------------------


def test_member_only_sees_org_plus_own_departments(monkeypatch):
    rbac = _FakeRbac(_grants(), teams=["dept:sales"])
    _patch_viewer(monkeypatch, flat_role="user", rbac=rbac)

    visible = registry_mod._apply_viewer_scope(_request("alice"), _rows())

    assert [row.agent_id for row in visible] == [
        "default",
        "expert_sales",
        "expert_draft",
    ]
    # Snapshot fetched exactly once for the whole list.
    assert rbac.calls == [
        "list_agent_grants",
        "roles_for_user",
        "teams_for_user",
    ]


def test_visible_row_stays_unusable_when_not_materialized(monkeypatch):
    rbac = _FakeRbac(_grants(), teams=["dept:sales"])
    _patch_viewer(monkeypatch, flat_role="user", rbac=rbac)

    visible = registry_mod._apply_viewer_scope(_request("alice"), _rows())

    draft = next(row for row in visible if row.agent_id == "expert_draft")
    assert draft.usable is False


def test_role_grant_opens_employee_for_role_holder(monkeypatch):
    grants = _grants()
    grants["expert_finance"] = GrantRecord(roles=["finance"])
    rbac = _FakeRbac(grants, roles=["finance"])
    _patch_viewer(monkeypatch, flat_role="user", rbac=rbac)

    visible = registry_mod._apply_viewer_scope(_request("carol"), _rows())

    assert "expert_finance" in [row.agent_id for row in visible]


def test_owner_sees_private_employee(monkeypatch):
    rbac = _FakeRbac(_grants())
    _patch_viewer(monkeypatch, flat_role="user", rbac=rbac)

    visible = registry_mod._apply_viewer_scope(_request("bob"), _rows())

    assert [row.agent_id for row in visible] == ["default", "expert_bob"]


def test_request_without_state_falls_back_to_local(monkeypatch):
    rbac = _FakeRbac(_grants())
    _patch_viewer(monkeypatch, flat_role="user", rbac=rbac)

    # No auth middleware injected a user: treated as the local account.
    assert registry_mod._viewer_of(object()) == "local"
    visible = registry_mod._apply_viewer_scope(object(), _rows())
    assert [row.agent_id for row in visible] == ["default"]


# ---------------------------------------------------------------------------
# unreadable rbac file: fail closed (same semantics as agent_allowed)
# ---------------------------------------------------------------------------


def test_unreadable_rbac_fails_closed_for_regular_viewer(monkeypatch):
    # Empty grants on a broken file would otherwise mean "unrestricted"
    # and leak every private/department employee to non-admins.
    rbac = _FakeRbac(_grants(), teams=["dept:sales"], load_error=True)
    _patch_viewer(monkeypatch, flat_role="user", rbac=rbac)

    visible = registry_mod._apply_viewer_scope(_request("alice"), _rows())

    assert visible == []
    # Fail fast before reading any snapshot from the broken store.
    assert rbac.calls == []


def test_unreadable_rbac_still_lets_admin_see_everything(monkeypatch):
    rbac = _FakeRbac(load_error=True)
    _patch_viewer(monkeypatch, flat_role="admin", rbac=rbac)

    visible = registry_mod._apply_viewer_scope(_request("root"), _rows())

    # Admin is the repair path, exactly like runtime agent_allowed.
    assert len(visible) == len(_rows())
