# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the digital-employee registry aggregation.

Covers kind resolution (authority sources first, agent-id prefix as the
fallback), VO field assembly, the draft-preview exclusion, filter semantics
and the "at most one query per table" rule that keeps the list endpoint
free of N+1 access.
"""
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app.employees import registry as registry_mod
from qwenpaw.app.employees.models import (
    EMPLOYEE_KIND_AGENT,
    EMPLOYEE_KIND_EXPERT,
    EMPLOYEE_KIND_TEAM,
    GovernanceRecord,
)
from qwenpaw.app.employees.registry import (
    EmployeeSources,
    apply_filters,
    build_row,
    is_draft_preview_agent,
    load_sources,
    target_of,
)
from qwenpaw.app.experts.models import (
    ExpertRecord,
    ExpertTeamRecord,
    TeamMember,
)
from qwenpaw.app.orgs.models import DepartmentRecord
from qwenpaw.app.routers.agents import AgentSummary

# ---------------------------------------------------------------------------
# fixtures / fakes
# ---------------------------------------------------------------------------


def _summary(
    agent_id: str,
    *,
    name: str = "",
    enabled: bool = True,
    startup: str = "running",
    backend: str = "qwenpaw",
    model: str = "",
) -> AgentSummary:
    return AgentSummary(
        id=agent_id,
        name=name or agent_id,
        description=f"desc-{agent_id}",
        workspace_dir=f"/ws/{agent_id}",
        enabled=enabled,
        pinned=False,
        startup_status=startup,
        backend=backend,
        backend_model=model or None,
    )


def _expert(expert_id: str, **kwargs) -> ExpertRecord:
    payload = {
        "id": expert_id,
        "name": kwargs.pop("name", f"expert-{expert_id}"),
        "title": "Solution architect",
        "icon": "dicebear://bottts/seed",
        "description": "expert description",
        "status": "published",
        "usage_count": 7,
        "tags": ["crm", "sales"],
    }
    payload.update(kwargs)
    return ExpertRecord(**payload)


def _team(team_id: str, **kwargs) -> ExpertTeamRecord:
    payload = {
        "id": team_id,
        "name": kwargs.pop("name", f"team-{team_id}"),
        "description": "team description",
        "mode": "pipeline",
        "status": "published",
        "members": [
            TeamMember(expert_id="sales"),
            TeamMember(expert_id="support"),
        ],
    }
    payload.update(kwargs)
    return ExpertTeamRecord(**payload)


def _department(
    department_id: str,
    *,
    name: str = "",
    path: str = "",
) -> DepartmentRecord:
    return DepartmentRecord(
        id=department_id,
        name=name or department_id,
        path=path or department_id,
    )


class _CountingExpertStore:
    def __init__(self, experts=(), teams=()):
        self._experts = list(experts)
        self._teams = list(teams)
        self.calls: list[str] = []

    async def list_expert_cards(self):
        self.calls.append("list_expert_cards")
        return list(self._experts)

    async def list_teams(self):
        self.calls.append("list_teams")
        return list(self._teams)


class _CountingGovernanceStore:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.calls: list[str] = []

    async def list_all(self):
        self.calls.append("list_all")
        return list(self._rows)


class _CountingOrgService:
    def __init__(self, departments=()):
        self._departments = list(departments)
        self.calls: list[str] = []

    async def list_departments(self):
        self.calls.append("list_departments")
        return list(self._departments)


def _patch_sources(
    monkeypatch,
    *,
    summaries,
    experts=(),
    teams=(),
    governance=(),
    departments=(),
):
    """Wire counting fakes into every source ``load_sources`` touches."""

    async def _list_agents(request=None):
        return SimpleNamespace(agents=list(summaries))

    expert_store = _CountingExpertStore(experts, teams)
    governance_store = _CountingGovernanceStore(governance)
    org_service = _CountingOrgService(departments)

    monkeypatch.setattr(
        "qwenpaw.app.routers.agents.list_agents",
        _list_agents,
    )
    monkeypatch.setattr(
        registry_mod,
        "get_expert_store",
        lambda: expert_store,
    )
    monkeypatch.setattr(
        registry_mod,
        "get_employee_governance_store",
        lambda: governance_store,
    )
    monkeypatch.setattr(
        registry_mod,
        "get_org_service",
        lambda: org_service,
    )
    return expert_store, governance_store, org_service


# ---------------------------------------------------------------------------
# kind resolution
# ---------------------------------------------------------------------------


def _sources_with_all() -> EmployeeSources:
    sources = EmployeeSources()
    for agent_id in ("default", "expert_sales", "team_support"):
        sources.agents[agent_id] = _summary(agent_id)
        sources.agent_order.append(agent_id)
    sources.experts["expert_sales"] = _expert("sales")
    sources.teams["team_support"] = _team("support")
    return sources


def test_kind_prefers_authority_over_prefix():
    sources = _sources_with_all()
    assert registry_mod._resolve_kind("expert_sales", sources) == (
        EMPLOYEE_KIND_EXPERT
    )
    assert registry_mod._resolve_kind("team_support", sources) == (
        EMPLOYEE_KIND_TEAM
    )
    assert registry_mod._resolve_kind("default", sources) == (
        EMPLOYEE_KIND_AGENT
    )


def test_kind_falls_back_to_agent_id_prefix():
    sources = EmployeeSources()
    # No expert/team rows at all: the id prefix is the only signal left.
    assert registry_mod._resolve_kind("expert_ghost", sources) == (
        EMPLOYEE_KIND_EXPERT
    )
    assert registry_mod._resolve_kind("team_ghost", sources) == (
        EMPLOYEE_KIND_TEAM
    )
    assert registry_mod._resolve_kind("default", sources) == (
        EMPLOYEE_KIND_AGENT
    )


def test_target_of_demotes_stale_prefix_to_agent():
    sources = EmployeeSources()
    sources.agents["expert_ghost"] = _summary("expert_ghost")
    sources.agent_order.append("expert_ghost")
    target = target_of("expert_ghost", sources)
    # Prefix says expert, but the experts table has no row -> plain agent.
    assert target["entity_kind"] == EMPLOYEE_KIND_AGENT
    assert target["entity_id"] == "expert_ghost"
    assert target["exists"] is True


def test_target_of_rejects_draft_preview_and_unknown():
    sources = _sources_with_all()
    assert target_of("expert_sales__draft", sources) == {"exists": False}
    assert target_of("nope", sources)["exists"] is False


def test_is_draft_preview_agent():
    assert is_draft_preview_agent("expert_x__draft") is True
    assert is_draft_preview_agent("expert_x") is False


# ---------------------------------------------------------------------------
# VO assembly
# ---------------------------------------------------------------------------


def test_build_row_expert_fields():
    sources = _sources_with_all()
    sources.governance["expert_sales"] = GovernanceRecord(
        agent_id="expert_sales",
        entity_kind="expert",
        entity_id="sales",
        department_id="d_sales",
        visibility="department",
        granted_departments=["d_support"],
        owner_id="alice",
    )
    names = {"d_sales": "Sales", "d_support": "Support"}
    row = build_row("expert_sales", sources, names)

    assert row.entity_kind == "expert"
    assert row.entity_id == "sales"
    assert row.name == "expert-sales"
    assert row.title == "Solution architect"
    assert row.description == "expert description"
    # The avatar seed must be the stripped id, never the runtime agent id.
    assert row.icon == "dicebear://bottts/seed"
    assert row.department_id == "d_sales"
    assert row.department_name == "Sales"
    assert row.granted_department_names == ["Support"]
    assert row.visibility == "department"
    assert row.governed is True
    assert row.usage_count == 7
    assert row.tags == ["crm", "sales"]
    assert row.startup_status == "running"
    assert row.workspace_dir == "/ws/expert_sales"
    assert row.usable is True


def test_build_row_team_members_and_mode():
    sources = _sources_with_all()
    # Member names resolve from the already-loaded experts map (no re-query).
    sources.experts["expert_sales"] = _expert("sales", name="Seller")
    row = build_row("team_support", sources, {})
    assert row.entity_kind == "team"
    assert row.mode == "pipeline"
    assert row.member_count == 2
    assert [member.name for member in row.members] == ["Seller", "support"]
    assert [member.expert_id for member in row.members] == [
        "sales",
        "support",
    ]


def test_build_row_unmaterialized_draft_is_unusable():
    sources = _sources_with_all()
    del sources.agents["expert_sales"]
    row = build_row("expert_sales", sources, {})
    assert row.usable is False
    assert row.available_in_chat is False
    assert row.startup_status == ""
    # Name still resolves from the domain record (authoritative source).
    assert row.name == "expert-sales"


def test_build_row_ungoverned_defaults():
    sources = _sources_with_all()
    row = build_row("default", sources, {})
    assert row.visibility == "org"
    assert row.governed is False
    assert row.department_id is None
    assert row.granted_departments == []


def test_build_row_keeps_falsey_summary_flags():
    sources = _sources_with_all()
    sources.agents["default"] = _summary("default", enabled=False)
    sources.agents["default"].available_in_chat = False
    row = build_row("default", sources, {})
    # ``or``-style fallbacks would silently flip these to True.
    assert row.enabled is False
    assert row.available_in_chat is False


def test_model_label_prefers_active_model():
    sources = _sources_with_all()
    summary = _summary("default", model="backend-model")
    summary.active_model = SimpleNamespace(model="active-model")
    sources.agents["default"] = summary
    assert build_row("default", sources, {}).model_label == "active-model"
    assert registry_mod._model_label_of(None) == ""


# ---------------------------------------------------------------------------
# load_sources: ordering, draft exclusion, one query per table
# ---------------------------------------------------------------------------


async def test_load_sources_queries_each_table_once(monkeypatch):
    stores = _patch_sources(
        monkeypatch,
        summaries=[
            _summary("default"),
            _summary("expert_sales"),
            _summary("expert_x__draft"),
            _summary("team_support"),
        ],
        experts=[_expert("sales")],
        teams=[_team("support")],
        governance=[
            GovernanceRecord(agent_id="expert_sales", visibility="private"),
        ],
        departments=[_department("d_sales")],
    )
    expert_store, governance_store, org_service = stores

    sources = await load_sources(object())

    assert expert_store.calls == ["list_expert_cards", "list_teams"]
    assert governance_store.calls == ["list_all"]
    assert org_service.calls == ["list_departments"]
    # Draft debug instances never reach the registry.
    assert "expert_x__draft" not in sources.agents
    assert sources.agent_order == ["default", "expert_sales", "team_support"]
    assert sources.governance["expert_sales"].visibility == "private"


async def test_load_sources_degrades_without_enterprise_plane(monkeypatch):
    async def _list_agents(request=None):
        return SimpleNamespace(agents=[_summary("default")])

    def _boom():
        raise RuntimeError("PG not configured")

    monkeypatch.setattr(
        "qwenpaw.app.routers.agents.list_agents",
        _list_agents,
    )
    monkeypatch.setattr(registry_mod, "get_expert_store", _boom)

    sources = await load_sources(object())

    assert list(sources.agents) == ["default"]
    assert sources.experts == {}
    assert sources.departments == []


async def test_build_registry_appends_unmaterialized_rows(monkeypatch):
    # The team exists in the domain plane but was never materialized.
    _patch_sources(
        monkeypatch,
        summaries=[_summary("default")],
        experts=[],
        teams=[_team("support")],
    )
    rows = await registry_mod.build_registry(object())

    assert [row.agent_id for row in rows] == ["default", "team_support"]
    assert rows[1].usable is False


# ---------------------------------------------------------------------------
# filters
# ---------------------------------------------------------------------------


def _rows_for_filters():
    sources = _sources_with_all()
    sources.governance["expert_sales"] = GovernanceRecord(
        agent_id="expert_sales",
        entity_kind="expert",
        entity_id="sales",
        department_id="d_sales",
        visibility="department",
    )
    names = {"d_sales": "Sales"}
    return [build_row(agent_id, sources, names) for agent_id in (
        "default",
        "expert_sales",
        "team_support",
    )]


def test_apply_filters_kind_tab():
    rows = _rows_for_filters()
    assert [r.agent_id for r in apply_filters(rows, kind="agents")] == [
        "default",
        "expert_sales",
    ]
    assert [r.agent_id for r in apply_filters(rows, kind="team")] == [
        "team_support",
    ]
    assert [r.agent_id for r in apply_filters(rows, kind="all")] == [
        "default",
        "expert_sales",
        "team_support",
    ]


def test_apply_filters_governance_dimensions():
    rows = _rows_for_filters()
    assert [
        r.agent_id for r in apply_filters(rows, department_id="d_sales")
    ] == ["expert_sales"]
    assert [
        r.agent_id for r in apply_filters(rows, unassigned=True)
    ] == ["default", "team_support"]
    assert [
        r.agent_id for r in apply_filters(rows, visibility="department")
    ] == ["expert_sales"]
    assert [r.agent_id for r in apply_filters(rows, status="published")] == [
        "expert_sales",
        "team_support",
    ]


def test_apply_filters_keyword_matches_tags():
    rows = _rows_for_filters()
    assert [r.agent_id for r in apply_filters(rows, q="CRM")] == [
        "expert_sales",
    ]
    assert apply_filters(rows, q="nothing-matches") == []
