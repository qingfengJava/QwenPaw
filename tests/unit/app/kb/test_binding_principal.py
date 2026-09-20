# -*- coding: utf-8 -*-
"""T6 绑定主体泛化（principal_type agent|team）单元测试。

覆盖：json 面 principal 行类型隔离 / ``bind_principal`` team 形态转换 /
``list_bound_space_ids`` 团队解析矩阵（supervisor/成员/双属/解除/
fail-soft）+ 60s TTL 缓存与失效 / 迁移三轨守护。

@author qingfeng
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from qwenpaw.app.kb import bindings as kb_bindings
from qwenpaw.app.kb.models import KbBinding, PRINCIPAL_AGENT, PRINCIPAL_TEAM

_REPO_ROOT = Path(__file__).resolve().parents[4]
_STAMP = "2026-09-20T00:00:00+00:00"


@pytest.fixture()
def json_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """json manifest 态（tmp 路径 + 单例重置）。"""
    from qwenpaw.app.kb.bindings import reset_json_store_for_tests

    manifest = tmp_path / "kb_bindings.json"
    monkeypatch.setattr(kb_bindings, "DEFAULT_MANIFEST_PATH", manifest)
    reset_json_store_for_tests()
    yield manifest
    reset_json_store_for_tests()


@pytest.fixture()
def no_pg(monkeypatch: pytest.MonkeyPatch):
    """钉 json 后端（绑定不走 pg 面）。"""
    monkeypatch.setattr(
        kb_bindings.write_gateway,
        "resolve_storage_backend",
        lambda: "json",
    )


@pytest.fixture()
def space_ok(monkeypatch: pytest.MonkeyPatch):
    """manage 门全通（personal + owner=admin，调用方 granted_by 均为 admin）。"""
    from qwenpaw.app.kb.bindings import SpaceShape

    shape = SpaceShape(
        scope="personal",
        owner_id="admin",
        team_id="",
        grant_roles=(),
        grant_users=(),
        grant_teams=(),
    )

    async def _allow(space_id: str, *args, **kwargs):
        return shape

    monkeypatch.setattr(
        kb_bindings,
        "_load_space_shape",
        _allow,
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个用例前后清空团队解析缓存（用例隔离）。"""
    kb_bindings.invalidate_principal_cache()
    yield
    kb_bindings.invalidate_principal_cache()


# ---------------------------------------------------------------------------
# json 面：principal 行类型隔离
# ---------------------------------------------------------------------------


async def test_json_rows_keep_principal_type(json_store, no_pg) -> None:
    """json manifest 行写入/读回保留 principal_type（默认 agent）。"""
    store = kb_bindings.get_json_binding_store()
    assert store.insert("agent_a", "kb_x") is True
    assert store.insert("team_t1", "kb_t", principal_type=PRINCIPAL_TEAM)
    rows = store.list_for_agent("team_t1")
    assert [r.principal_type for r in rows] == [PRINCIPAL_TEAM]
    assert [r.principal_type for r in store.list_for_agent("agent_a")] == [
        PRINCIPAL_AGENT,
    ]


async def test_same_id_agent_and_team_rows_are_isolated(
    json_store,
    no_pg,
    space_ok,
) -> None:
    """同形 ``team_{tid}`` 上 agent 直绑行与团队行互不误伤。"""
    stored = kb_bindings.team_principal_agent_id("t1")
    assert kb_bindings.team_principal_agent_id("t1") == "team_t1"
    assert await kb_bindings.bind_agent_kb(
        agent_id=stored,
        space_id="kb_direct",
        granted_by="admin",
        principal_type=PRINCIPAL_AGENT,
    )
    assert await kb_bindings.bind_agent_kb(
        agent_id=stored,
        space_id="kb_team",
        granted_by="admin",
        principal_type=PRINCIPAL_TEAM,
    )
    # 按 agent 类型解绑只回收直绑行，团队行仍在
    assert await kb_bindings.unbind_agent_kb(
        stored,
        "kb_direct",
        principal_type=PRINCIPAL_AGENT,
    )
    remaining = kb_bindings.get_json_binding_store().list_for_agent(stored)
    assert [(r.space_id, r.principal_type) for r in remaining] == [
        ("kb_team", PRINCIPAL_TEAM),
    ]
    # 反向：按 team 类型解绑团队行
    assert await kb_bindings.unbind_agent_kb(
        stored,
        "kb_team",
        principal_type=PRINCIPAL_TEAM,
    )
    assert kb_bindings.get_json_binding_store().list_for_agent(stored) == []


async def test_bind_principal_team_converts_bare_id(
    json_store,
    no_pg,
    space_ok,
) -> None:
    """``bind_principal(team)`` 存储行自动转 ``team_{tid}`` 形态。"""
    ok = await kb_bindings.bind_principal(
        principal_type=PRINCIPAL_TEAM,
        principal_id="t9",
        space_id="kb_t",
        granted_by="admin",
    )
    assert ok is True
    row = kb_bindings.get_json_binding_store().list_for_agent("team_t9")[0]
    assert row.space_id == "kb_t"
    assert row.principal_type == PRINCIPAL_TEAM


async def test_bind_principal_rejects_unknown_type(json_store, no_pg) -> None:
    """非法 principal_type 直接 ``ValueError``（不落任何行）。"""
    with pytest.raises(ValueError):
        await kb_bindings.bind_principal(
            principal_type="user",
            principal_id="u1",
            space_id="kb_x",
            granted_by="admin",
        )
    assert kb_bindings.get_json_binding_store().list_all() == []


# ---------------------------------------------------------------------------
# 团队解析矩阵（打桩 expert store，钉 TTL 缓存）
# ---------------------------------------------------------------------------


class _FakeTeam:
    def __init__(self, team_id: str, member_ids: List[str]) -> None:
        self.id = team_id
        self.members = [
            type("M", (), {"expert_id": eid})() for eid in member_ids
        ]


class _FakeExpertStore:
    def __init__(self, teams: List[_FakeTeam]) -> None:
        self.teams = teams
        self.calls = 0

    async def list_teams(self, *args, **kwargs):
        self.calls += 1
        return self.teams


@pytest.fixture()
def expert_teams(monkeypatch: pytest.MonkeyPatch):
    """打桩 ``get_expert_store``（成员归属反查数据源）。"""
    import qwenpaw.app.experts.store as experts_store_mod

    fake = _FakeExpertStore(
        [
            _FakeTeam("t1", ["e1"]),
            _FakeTeam("t2", ["e1", "e2"]),
        ],
    )
    monkeypatch.setattr(
        experts_store_mod,
        "get_expert_store",
        lambda: fake,
    )
    return fake


async def test_team_bound_space_ids_reach_supervisor(
    json_store,
    no_pg,
    space_ok,
) -> None:
    """supervisor 归属：团队绑行对 ``team_{tid}`` 运行态 id 直接生效。"""
    assert await kb_bindings.bind_principal(
        principal_type=PRINCIPAL_TEAM,
        principal_id="t1",
        space_id="kb_team1",
        granted_by="admin",
    )
    assert await kb_bindings.list_bound_space_ids("team_t1") == ["kb_team1"]


async def test_member_reaches_team_bindings(
    json_store,
    no_pg,
    space_ok,
    expert_teams,
) -> None:
    """成员归属：expert 成员经成员表反查命中所在团队的绑行。"""
    assert await kb_bindings.bind_principal(
        principal_type=PRINCIPAL_TEAM,
        principal_id="t1",
        space_id="kb_t1",
        granted_by="admin",
    )
    # e1 双属 t1+t2；t2 无绑行
    assert await kb_bindings.bind_principal(
        principal_type=PRINCIPAL_TEAM,
        principal_id="t2",
        space_id="kb_t2",
        granted_by="admin",
    )
    assert await kb_bindings.list_bound_space_ids("expert_e1") == [
        "kb_t1",
        "kb_t2",
    ]
    # e2 只属 t2
    assert await kb_bindings.list_bound_space_ids("expert_e2") == ["kb_t2"]


async def test_member_agent_direct_plus_team_union(
    json_store,
    no_pg,
    space_ok,
    expert_teams,
) -> None:
    """直绑 ∪ 团队绑合并去重（双属 + 直绑重叠场景）。"""
    assert await kb_bindings.bind_principal(
        principal_type=PRINCIPAL_TEAM,
        principal_id="t1",
        space_id="kb_shared",
        granted_by="admin",
    )
    assert await kb_bindings.bind_principal(
        principal_type=PRINCIPAL_TEAM,
        principal_id="t2",
        space_id="kb_shared",
        granted_by="admin",
    )
    assert await kb_bindings.bind_agent_kb(
        agent_id="expert_e1",
        space_id="kb_own",
        granted_by="admin",
    )
    assert await kb_bindings.list_bound_space_ids("expert_e1") == [
        "kb_own",
        "kb_shared",
    ]


async def test_team_unbinding_stops_member_access(
    json_store,
    no_pg,
    space_ok,
    expert_teams,
) -> None:
    """解除：团队绑行删除后成员不再收敛到该库。"""
    assert await kb_bindings.bind_principal(
        principal_type=PRINCIPAL_TEAM,
        principal_id="t1",
        space_id="kb_t1",
        granted_by="admin",
    )
    assert await kb_bindings.list_bound_space_ids("expert_e1") == ["kb_t1"]
    assert await kb_bindings.unbind_agent_kb(
        kb_bindings.team_principal_agent_id("t1"),
        "kb_t1",
        principal_type=PRINCIPAL_TEAM,
    )
    assert await kb_bindings.list_bound_space_ids("expert_e1") == []


async def test_team_resolution_fail_soft(
    json_store,
    no_pg,
    space_ok,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """专家团存储不可用（json 部署）fail-soft：只保留直绑。"""
    import qwenpaw.app.experts.store as experts_store_mod

    def _boom():
        raise RuntimeError("enterprise engine unavailable")

    monkeypatch.setattr(experts_store_mod, "get_expert_store", _boom)
    assert await kb_bindings.bind_agent_kb(
        agent_id="expert_e1",
        space_id="kb_own",
        granted_by="admin",
    )
    assert await kb_bindings.list_bound_space_ids("expert_e1") == ["kb_own"]


async def test_ttl_cache_and_invalidation(
    json_store,
    no_pg,
    space_ok,
    expert_teams,
) -> None:
    """团队解析 60s TTL 缓存：命中不重查；失效后重查。"""
    assert await kb_bindings.bind_principal(
        principal_type=PRINCIPAL_TEAM,
        principal_id="t1",
        space_id="kb_t1",
        granted_by="admin",
    )
    assert await kb_bindings.list_bound_space_ids("expert_e1") == ["kb_t1"]
    calls_after_first = expert_teams.calls
    # 第二次解析走缓存，成员表零调用
    assert await kb_bindings.list_bound_space_ids("expert_e1") == ["kb_t1"]
    assert expert_teams.calls == calls_after_first
    # 显式失效后重新解析（缓存重建，成员表再次被读）
    kb_bindings.invalidate_principal_cache()
    assert await kb_bindings.list_bound_space_ids("expert_e1") == ["kb_t1"]
    assert expert_teams.calls == calls_after_first + 1


# ---------------------------------------------------------------------------
# 迁移三轨守护
# ---------------------------------------------------------------------------


def test_migration_triple_track_covers_principal_type() -> None:
    """0048 四文件（alembic/changelog/test/prod）均含 principal_type。"""
    files = [
        _REPO_ROOT
        / "src/qwenpaw/db/alembic/versions/0048_binding_principal.py",
        _REPO_ROOT
        / "db/feature/agent_run_logs_20260908/changelog/20260920"
        / "06_binding_principal.sql",
        _REPO_ROOT / "db/feature/agent_run_logs_20260908/test.sql",
        _REPO_ROOT / "db/feature/agent_run_logs_20260908/prod.sql",
    ]
    for path in files:
        assert path.is_file(), f"missing migration artifact: {path}"
        text = path.read_text(encoding="utf-8")
        assert "principal_type" in text, f"missing column in {path.name}"
        assert "DEFAULT 'agent'" in text, f"missing default in {path.name}"


def test_binding_row_defaults_agent_type() -> None:
    """KbBinding 缺省 principal_type=agent（存量 manifest 兼容读回）。"""
    row = KbBinding(agent_id="a", space_id="s")
    assert row.principal_type == PRINCIPAL_AGENT
    # 旧 manifest JSON（无 principal_type 键）读回自动补默认
    legacy = KbBinding.model_validate(
        {"agent_id": "a", "space_id": "s", "granted_by": "x"},
    )
    assert legacy.principal_type == PRINCIPAL_AGENT
