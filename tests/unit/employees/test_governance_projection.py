# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the governance -> RBAC grant projection.

The governance table is the authority; the runtime ACL surface is derived
from it. These tests pin the translation rules (org clears the grant,
department expands the subtree into ``dept:{path}`` teams, private pins the
owner) plus the experts mirror columns and the department lifecycle hooks.
"""
from __future__ import annotations

from qwenpaw.app.employees import projection as projection_mod
from qwenpaw.app.employees.models import (
    EMPLOYEE_KIND_AGENT,
    EMPLOYEE_KIND_EXPERT,
    EMPLOYEE_KIND_TEAM,
    VISIBILITY_DEPARTMENT,
    VISIBILITY_ORG,
    VISIBILITY_PRIVATE,
    GovernanceRecord,
)
from qwenpaw.app.employees.projection import (
    clear_department_reference,
    expand_department_subtree,
    grant_for_record,
    project,
    refresh_for_new_department,
    refresh_for_removed_department,
    selected_department_ids,
    write_grant,
)
from qwenpaw.app.orgs.models import DepartmentRecord


def _department(department_id: str, *, name: str = "", path: str = ""):
    return DepartmentRecord(
        id=department_id,
        name=name or department_id,
        path=path or department_id,
    )


def _record(**kwargs) -> GovernanceRecord:
    payload = {
        "agent_id": "expert_sales",
        "entity_kind": EMPLOYEE_KIND_EXPERT,
        "entity_id": "sales",
        "visibility": VISIBILITY_ORG,
        "owner_id": "alice",
    }
    payload.update(kwargs)
    return GovernanceRecord(**payload)


DEPARTMENTS = [
    _department("d_sales", name="Sales", path="sales"),
    _department("d_sales_bj", name="Sales BJ", path="sales/beijing"),
    _department("d_sales_bjjr", name="JR", path="sales/beijing_jr"),
    # Sibling whose path merely starts with the same string: must stay out.
    _department("d_salesmate", name="Salesmate", path="salesmate"),
    _department("d_support", name="Support", path="support"),
]


class _FakeRbac:
    def __init__(self):
        self.set_calls: list[tuple[str, object]] = []
        self.deleted: list[str] = []

    def set_agent_grant(self, agent_id, grant):
        self.set_calls.append((agent_id, grant))

    def delete_agent_grant(self, agent_id):
        self.deleted.append(agent_id)


class _FakeExpertStore:
    def __init__(self, error: Exception | None = None):
        self.updates: list[dict] = []
        self._error = error

    async def update_expert(self, expert_id, **fields):
        if self._error:
            raise self._error
        self.updates.append({"id": expert_id, **fields})


class _FakeGovernanceStore:
    def __init__(self, rows):
        self._rows = list(rows)
        self.upserts: list[dict] = []

    async def list_all(self):
        return list(self._rows)

    async def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        return GovernanceRecord(**kwargs)


class _FakeOrgService:
    def __init__(self, departments):
        self._departments = list(departments)

    async def list_departments(self):
        return list(self._departments)


def _patch(monkeypatch, *, rbac, experts=None, departments=DEPARTMENTS):
    monkeypatch.setattr(projection_mod, "get_rbac_store", lambda: rbac)
    monkeypatch.setattr(
        projection_mod,
        "get_expert_store",
        lambda: experts or _FakeExpertStore(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.orgs.service.get_org_service",
        lambda: _FakeOrgService(departments),
    )


# ---------------------------------------------------------------------------
# department set expansion
# ---------------------------------------------------------------------------


def test_selected_department_ids_dedupe_and_order():
    record = _record(
        department_id="d_sales",
        granted_departments=["d_support", "d_sales", ""],
    )
    assert selected_department_ids(record) == ["d_sales", "d_support"]


def test_expand_subtree_uses_path_segments_not_raw_prefix():
    path_by_id = {item.id: item.path for item in DEPARTMENTS}
    expanded = expand_department_subtree(["d_sales"], path_by_id)
    # Children are joined by "/"; "salesmate" only shares a string prefix.
    assert set(expanded) == {"d_sales", "d_sales_bj", "d_sales_bjjr"}
    assert "d_salesmate" not in expanded


def test_expand_subtree_skips_unknown_departments():
    path_by_id = {item.id: item.path for item in DEPARTMENTS}
    assert expand_department_subtree(["gone"], path_by_id) == []


# ---------------------------------------------------------------------------
# grant translation
# ---------------------------------------------------------------------------


def test_org_visibility_clears_grant():
    grant = grant_for_record(_record(visibility=VISIBILITY_ORG), DEPARTMENTS)
    assert grant is None


def test_private_visibility_grants_owner_only():
    grant = grant_for_record(
        _record(visibility=VISIBILITY_PRIVATE, owner_id="bob"),
        DEPARTMENTS,
    )
    assert grant.users == ["bob"]
    assert grant.teams == []
    assert grant.roles == []


def test_private_without_owner_leaves_acl_empty():
    grant = grant_for_record(
        _record(visibility=VISIBILITY_PRIVATE, owner_id=None),
        DEPARTMENTS,
    )
    # An empty grant list means "restricted to nobody": honest reflection of
    # a broken configuration rather than silently opening it to everyone.
    assert grant.users == []


def test_department_visibility_expands_subtree_into_dept_teams():
    grant = grant_for_record(
        _record(
            visibility=VISIBILITY_DEPARTMENT,
            department_id="d_sales",
            granted_departments=["d_support"],
            owner_id="alice",
        ),
        DEPARTMENTS,
    )
    assert set(grant.teams) == {
        "dept:sales",
        "dept:sales/beijing",
        "dept:sales/beijing_jr",
        "dept:support",
    }
    assert "dept:salesmate" not in grant.teams
    assert grant.users == ["alice"]


def test_write_grant_deletes_when_projection_says_unrestricted(monkeypatch):
    rbac = _FakeRbac()
    _patch(monkeypatch, rbac=rbac)
    write_grant(_record(visibility=VISIBILITY_ORG), None)
    assert rbac.deleted == ["expert_sales"]


def test_write_grant_sets_translated_grant(monkeypatch):
    rbac = _FakeRbac()
    _patch(monkeypatch, rbac=rbac)
    record = _record(visibility=VISIBILITY_PRIVATE)
    write_grant(record, grant_for_record(record, DEPARTMENTS))
    assert len(rbac.set_calls) == 1
    assert rbac.set_calls[0][0] == "expert_sales"
    assert rbac.set_calls[0][1].users == ["alice"]


# ---------------------------------------------------------------------------
# project(): grant + experts mirror
# ---------------------------------------------------------------------------


async def test_project_mirrors_expert_columns(monkeypatch):
    rbac, experts = _FakeRbac(), _FakeExpertStore()
    _patch(monkeypatch, rbac=rbac, experts=experts)

    await project(
        _record(
            visibility=VISIBILITY_DEPARTMENT,
            department_id="d_sales",
        ),
    )

    assert experts.updates == [
        {"id": "sales", "visibility": "department", "department": "Sales"},
    ]
    assert len(rbac.set_calls) == 1


async def test_project_skips_mirror_for_non_expert_kinds(monkeypatch):
    for kind, agent_id in (
        (EMPLOYEE_KIND_AGENT, "default"),
        (EMPLOYEE_KIND_TEAM, "team_support"),
    ):
        rbac, experts = _FakeRbac(), _FakeExpertStore()
        _patch(monkeypatch, rbac=rbac, experts=experts)
        await project(
            _record(
                agent_id=agent_id,
                entity_kind=kind,
                entity_id="support" if kind == EMPLOYEE_KIND_TEAM else "",
                visibility=VISIBILITY_PRIVATE,
            ),
        )
        assert experts.updates == []
        assert len(rbac.set_calls) == 1


async def test_project_swallows_mirror_failure(monkeypatch):
    # The authority table is already written; a broken mirror must not
    # rollback the governance save, while the ACL projection still lands.
    rbac = _FakeRbac()
    _patch(
        monkeypatch,
        rbac=rbac,
        experts=_FakeExpertStore(error=RuntimeError("db down")),
    )
    await project(_record(visibility=VISIBILITY_PRIVATE))
    assert len(rbac.set_calls) == 1


# ---------------------------------------------------------------------------
# department lifecycle hooks
# ---------------------------------------------------------------------------


async def test_refresh_only_reprojects_ancestor_grants(monkeypatch):
    rbac = _FakeRbac()
    _patch(monkeypatch, rbac=rbac)
    monkeypatch.setattr(
        projection_mod,
        "get_employee_governance_store",
        lambda: _FakeGovernanceStore(
            [
                # Granted the parent of the new department -> needs refresh.
                _record(
                    agent_id="a",
                    visibility=VISIBILITY_DEPARTMENT,
                    department_id="d_sales",
                ),
                # Granted the new department itself -> already projected.
                _record(
                    agent_id="b",
                    visibility=VISIBILITY_DEPARTMENT,
                    department_id="d_new",
                ),
                # Unrelated department -> untouched.
                _record(
                    agent_id="c",
                    visibility=VISIBILITY_DEPARTMENT,
                    department_id="d_support",
                ),
                # Org-wide -> never projected.
                _record(agent_id="d", visibility=VISIBILITY_ORG),
            ],
        ),
    )
    refreshed = await refresh_for_new_department(
        _department("d_new", name="New", path="sales/new"),
    )
    assert refreshed == 1


async def test_refresh_purges_removed_subtree_team_from_ancestor_grants(
    monkeypatch,
):
    """Deleting a child must clean the parent-scoped grants that inlined it."""
    rbac = _FakeRbac()
    survivors = [item for item in DEPARTMENTS if item.id != "d_sales_bj"]
    _patch(monkeypatch, rbac=rbac, departments=survivors)
    monkeypatch.setattr(
        projection_mod,
        "get_employee_governance_store",
        lambda: _FakeGovernanceStore(
            [
                # Granted the ancestor -> its grant still names the child.
                _record(
                    agent_id="a",
                    visibility=VISIBILITY_DEPARTMENT,
                    department_id="d_sales",
                ),
                # Unrelated branch -> untouched.
                _record(
                    agent_id="b",
                    visibility=VISIBILITY_DEPARTMENT,
                    department_id="d_support",
                ),
            ],
        ),
    )

    refreshed = await refresh_for_removed_department("sales/beijing")

    assert refreshed == 1
    assert [agent for agent, _grant in rbac.set_calls] == ["a"]
    assert rbac.set_calls[0][1].teams == [
        "dept:sales",
        "dept:sales/beijing_jr",
    ]


async def test_refresh_for_removed_department_edge_cases(monkeypatch):
    rbac = _FakeRbac()
    _patch(monkeypatch, rbac=rbac)
    store = _FakeGovernanceStore(
        [_record(agent_id="a", visibility=VISIBILITY_DEPARTMENT)],
    )
    monkeypatch.setattr(
        projection_mod,
        "get_employee_governance_store",
        lambda: store,
    )

    # Root departments have no ancestor whose grant could have inlined them.
    assert await refresh_for_removed_department("sales") == 0
    assert await refresh_for_removed_department("") == 0
    assert rbac.set_calls == []


def test_ancestor_paths_helper():
    from qwenpaw.app.employees.projection import _ancestor_paths

    assert _ancestor_paths("a/b/c") == ["a", "a/b", "a/b/c"]
    assert _ancestor_paths("") == []


async def test_clear_department_reference_falls_back_to_org(monkeypatch):
    rbac = _FakeRbac()
    _patch(monkeypatch, rbac=rbac)
    store = _FakeGovernanceStore(
        [
            _record(
                agent_id="a",
                visibility=VISIBILITY_DEPARTMENT,
                department_id="d_gone",
                granted_departments=["d_gone"],
            ),
            _record(
                agent_id="b",
                visibility=VISIBILITY_DEPARTMENT,
                department_id="d_sales",
                granted_departments=["d_gone", "d_support"],
            ),
            _record(agent_id="c", visibility=VISIBILITY_ORG),
        ],
    )
    monkeypatch.setattr(
        projection_mod,
        "get_employee_governance_store",
        lambda: store,
    )

    cleared = await clear_department_reference("d_gone")

    assert cleared == 2
    by_agent = {item["agent_id"]: item for item in store.upserts}
    # Losing the last effective department would lock everyone out.
    assert by_agent["a"]["visibility"] == VISIBILITY_ORG
    assert by_agent["a"]["department_id"] is None
    assert by_agent["a"]["granted_departments"] == []
    # Still scoped to the surviving department, reference removed.
    assert by_agent["b"]["visibility"] == VISIBILITY_DEPARTMENT
    assert by_agent["b"]["department_id"] == "d_sales"
    assert by_agent["b"]["granted_departments"] == ["d_support"]
    assert by_agent["b"]["updated_by"] == "department_cleanup"
    # Org-wide rows are never rewritten by cleanup.
    assert "c" not in by_agent
