# -*- coding: utf-8 -*-
"""T6 绑定主体端点形状单测（admin expert-teams + xian knowledge）。

打桩在 expert store / kb service / bindings 门（json manifest 态），
端点语义（404/403/201/200/204 与响应形状）由本文件锁定；RBAC 钉死
关闭态直通 require_perm 惯例。

@author qingfeng
"""

# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.kb import bindings as kb_bindings
from qwenpaw.app.kb.models import PRINCIPAL_TEAM
from qwenpaw.app.routers.admin import expert_teams as admin_teams_mod
from qwenpaw.app.routers.admin.expert_teams import (
    router as admin_teams_router,
)
from qwenpaw.app.routers.xian import knowledge as xian_knowledge_mod
from qwenpaw.app.routers.xian.knowledge import router as xian_kb_router

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _rbac_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 RBAC 关闭态（直通 require_perm）。"""
    from qwenpaw.app import rbac as rbac_pkg

    monkeypatch.setattr(rbac_pkg, "rbac_enforcement_enabled", lambda: False)


@pytest.fixture(autouse=True)
def json_bindings(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """json manifest 态 + manage 门全通（personal owner=admin）。"""
    from qwenpaw.app.kb.bindings import reset_json_store_for_tests

    monkeypatch.setattr(
        kb_bindings,
        "DEFAULT_MANIFEST_PATH",
        tmp_path / "kb_bindings.json",
    )
    monkeypatch.setattr(
        kb_bindings.write_gateway,
        "resolve_storage_backend",
        lambda: "json",
    )
    shape = kb_bindings.SpaceShape(
        scope="personal",
        owner_id="alice",
        team_id="",
        grant_roles=(),
        # admin 面 username 无中间件时为 "admin"，经 grants 命中；
        # xian 面 viewer=alice 走 personal owner 命中
        grant_users=("admin",),
        grant_teams=(),
    )

    async def _allow(space_id: str, *args, **kwargs):
        del space_id, args, kwargs
        return shape

    monkeypatch.setattr(kb_bindings, "_load_space_shape", _allow)
    reset_json_store_for_tests()
    yield
    reset_json_store_for_tests()


@pytest.fixture(autouse=True)
def _clean_cache():
    """团队解析缓存隔离。"""
    kb_bindings.invalidate_principal_cache()
    yield
    kb_bindings.invalidate_principal_cache()


@pytest.fixture()
def admin_client() -> Iterator[TestClient]:
    """挂载 admin expert-teams router（/api/admin 前缀）。"""
    application = FastAPI()
    application.include_router(admin_teams_router, prefix="/api/admin")
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def xian_client() -> Iterator[TestClient]:
    """挂载 xian knowledge router（/api/xian 前缀）。"""
    application = FastAPI()
    application.include_router(xian_kb_router, prefix="/api/xian")
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def expert_store(monkeypatch: pytest.MonkeyPatch):
    """打桩 expert store（admin 模块命名空间；团队 t1 / 专家 e1 归 alice）。"""
    team = SimpleNamespace(
        id="t1",
        name="Team A",
        members=[SimpleNamespace(expert_id="e1")],
    )
    expert = SimpleNamespace(id="e1", name="Expert A", owner_id="alice")

    class _Store:
        async def get_team(self, team_id: str):
            return team if team_id == "t1" else None

        async def get_expert(self, expert_id: str):
            return expert if expert_id == "e1" else None

        async def list_expert_cards(self, owner: str = "", **kwargs):
            del kwargs
            return [expert] if owner == "alice" else []

    store = _Store()
    # admin/expert_teams.py 是模块命名空间绑定（from ... import）
    monkeypatch.setattr(
        admin_teams_mod,
        "get_expert_store",
        lambda: store,
    )
    # xian/knowledge.py 是函数内局部 import（运行时读模块属性）
    import qwenpaw.app.experts.store as experts_store_mod

    monkeypatch.setattr(experts_store_mod, "get_expert_store", lambda: store)


# ---------------------------------------------------------------------------
# admin /expert-teams/{team_id}/kb-bindings
# ---------------------------------------------------------------------------


def test_admin_team_binding_flow(admin_client: TestClient) -> None:
    """PUT 201 → GET 含 principal_type=team → DELETE 204 → GET 空。"""
    resp = admin_client.put(
        "/api/admin/expert-teams/t1/kb-bindings",
        json={"space_id": "kb_a"},
    )
    assert resp.status_code == 201
    assert resp.json()["space_id"] == "kb_a"
    assert resp.json()["principal_type"] == PRINCIPAL_TEAM
    assert resp.json()["created"] is True

    resp = admin_client.get("/api/admin/expert-teams/t1/kb-bindings")
    assert resp.status_code == 200
    assert [r["space_id"] for r in resp.json()] == ["kb_a"]

    resp = admin_client.delete(
        "/api/admin/expert-teams/t1/kb-bindings/kb_a",
    )
    assert resp.status_code == 204
    assert admin_client.get(
        "/api/admin/expert-teams/t1/kb-bindings",
    ).json() == []


def test_admin_team_binding_idempotent_200(
    admin_client: TestClient,
) -> None:
    """重复 PUT 幂等 200（created=False，形状与首绑一致）。"""
    admin_client.put(
        "/api/admin/expert-teams/t1/kb-bindings",
        json={"space_id": "kb_a"},
    )
    resp = admin_client.put(
        "/api/admin/expert-teams/t1/kb-bindings",
        json={"space_id": "kb_a"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] is False


def test_admin_team_binding_unknown_team_404(
    admin_client: TestClient,
) -> None:
    """团队不存在 → 404（PUT/GET/DELETE 三端点一致哨兵）。"""
    assert (
        admin_client.put(
            "/api/admin/expert-teams/ghost/kb-bindings",
            json={"space_id": "kb_a"},
        ).status_code
        == 404
    )
    assert (
        admin_client.get(
            "/api/admin/expert-teams/ghost/kb-bindings",
        ).status_code
        == 404
    )
    assert (
        admin_client.delete(
            "/api/admin/expert-teams/ghost/kb-bindings/kb_a",
        ).status_code
        == 404
    )


def test_admin_team_unbind_missing_404(admin_client: TestClient) -> None:
    """解绑不存在的行 → 404。"""
    resp = admin_client.delete(
        "/api/admin/expert-teams/t1/kb-bindings/kb_ghost",
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# xian /knowledge 员工侧流
# ---------------------------------------------------------------------------


@pytest.fixture()
def kb_service(monkeypatch: pytest.MonkeyPatch):
    """打桩 kb service（kb_p1=alice 的个人库；kb_other=别人的库）。"""
    mine = SimpleNamespace(
        id="kb_p1",
        name="我的库",
        description="",
        scope="personal",
        owner_id="alice",
    )
    other = SimpleNamespace(
        id="kb_other",
        name="他人库",
        description="",
        scope="personal",
        owner_id="bob",
    )

    class _Svc:
        def get_kb(self, kb_id: str):
            return {"kb_p1": mine, "kb_other": other}.get(kb_id)

        def list_kbs(self):
            return [mine, other]

    monkeypatch.setattr(
        xian_knowledge_mod,
        "get_kb_service",
        lambda: _Svc(),
    )


@pytest.fixture()
def viewer_alice(monkeypatch: pytest.MonkeyPatch) -> None:
    """xian 面身份固定为 alice（middleware 惯例的测试等价物）。"""
    monkeypatch.setattr(
        xian_knowledge_mod,
        "_viewer",
        lambda request: "alice",
    )


# admin expert-teams 全部端点需专家团存储（统一打桩）
@pytest.fixture(autouse=True)
def _admin_expert_store(expert_store) -> None:
    yield


def test_list_my_bases_only_owned(
    xian_client: TestClient,
    kb_service,
    viewer_alice,
) -> None:
    """列我的库：仅 owner==viewer 的 personal 库。"""
    resp = xian_client.get("/api/xian/knowledge/bases")
    assert resp.status_code == 200
    assert [b["id"] for b in resp.json()] == ["kb_p1"]


def test_employee_binding_flow(
    xian_client: TestClient,
    kb_service,
    viewer_alice,
    expert_store,
) -> None:
    """绑定我的专家：PUT 201 → GET 命中 → DELETE 204。"""
    resp = xian_client.put(
        "/api/xian/knowledge/bases/kb_p1/expert-bindings",
        json={"expert_id": "e1"},
    )
    assert resp.status_code == 201
    assert resp.json()["space_id"] == "kb_p1"

    resp = xian_client.get("/api/xian/knowledge/bases/kb_p1/expert-bindings")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["expert_id"] == "e1"
    assert rows[0]["expert_name"] == "Expert A"

    resp = xian_client.delete(
        "/api/xian/knowledge/bases/kb_p1/expert-bindings/e1",
    )
    assert resp.status_code == 204
    assert (
        xian_client.get(
            "/api/xian/knowledge/bases/kb_p1/expert-bindings",
        ).json()
        == []
    )


def test_employee_binding_rejects_foreign_kb(
    xian_client: TestClient,
    kb_service,
    viewer_alice,
    expert_store,
) -> None:
    """绑他人的库 → 403（不泄露存在性差异，仅拒管理）。"""
    resp = xian_client.put(
        "/api/xian/knowledge/bases/kb_other/expert-bindings",
        json={"expert_id": "e1"},
    )
    assert resp.status_code == 403


def test_employee_binding_rejects_foreign_expert(
    xian_client: TestClient,
    kb_service,
    viewer_alice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """绑到他人的专家（expert 不在打桩返回内）→ 404 合并不泄露。"""
    import qwenpaw.app.experts.store as experts_store_mod

    class _Store:
        async def get_expert(self, expert_id: str):
            return None

    monkeypatch.setattr(
        experts_store_mod,
        "get_expert_store",
        lambda: _Store(),
    )
    resp = xian_client.put(
        "/api/xian/knowledge/bases/kb_p1/expert-bindings",
        json={"expert_id": "ghost"},
    )
    assert resp.status_code == 404


def test_admin_teams_invalidate_cache_hook(
    admin_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH 成员变更后全量失效团队解析缓存（T6 失效钩子）。"""
    team = SimpleNamespace(id="t1", name="T", members=[])

    class _Store2:
        async def update_team(self, team_id: str, **fields):
            del fields
            return team

    monkeypatch.setattr(
        admin_teams_mod,
        "get_expert_store",
        lambda: _Store2(),
    )
    kb_bindings._team_cache["expert_x"] = (0.0, ("team_t1",))
    resp = admin_client.patch("/api/admin/expert-teams/t1", json={})
    assert resp.status_code == 200
    assert "expert_x" not in kb_bindings._team_cache
