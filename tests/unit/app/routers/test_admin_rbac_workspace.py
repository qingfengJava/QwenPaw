# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""部门员工 / 角色工作台 admin API 的单元路由测试。

覆盖企业级 RBAC 升级新增/增强的端点（文件后端，无 PG 依赖）：

- ``POST /admin/users`` 落员工档案字段；
- ``GET /admin/users`` 关键字 / 状态筛选；
- 超管保护：is_superadmin 账号禁止被禁用 / 降级；
- ``GET /admin/roles/{name}/users`` 角色成员列表（文件回退路径）。

强制 ``QWENPAW_RBAC_ENFORCE=0`` 使断言与宿主机 .env 的认证开关解耦。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app.rbac.store import RbacStore
from qwenpaw.app.routers.admin import router as admin_router
from qwenpaw.app.users.store import UserStore


@pytest.fixture
def workspace_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, UserStore, RbacStore]]:
    user_store = UserStore(tmp_path / "users.json")
    rbac_store = RbacStore(tmp_path / "rbac.json")
    monkeypatch.setattr("qwenpaw.app.users.store._default_store", user_store)
    monkeypatch.setattr("qwenpaw.app.rbac.store._default_store", rbac_store)
    # 与 .env 解耦：显式关闭 RBAC 强制，路由对无身份请求放行。
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "0")
    # 强制无 PG：角色成员查询走文件回退路径，不依赖真实数据库。
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store_pg.get_pg_rbac_store", lambda: None
    )

    app = FastAPI()

    @app.middleware("http")
    async def _fake_auth(request: Request, call_next):
        request.state.user = request.headers.get("x-test-user") or None
        return await call_next(request)

    app.include_router(admin_router, prefix="/api")
    with TestClient(app) as client:
        yield client, user_store, rbac_store


def test_create_user_persists_profile(workspace_client) -> None:
    client, _, _ = workspace_client
    resp = client.post(
        "/api/admin/users",
        json={
            "username": "eve",
            "password": "pw2",
            "real_name": "伊芙",
            "phone": "13900000000",
            "gender": 2,
            "position": "产品经理",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["real_name"] == "伊芙"
    assert body["phone"] == "13900000000"
    assert body["gender"] == 2
    assert body["position"] == "产品经理"
    assert body["department_names"] == []


def test_list_users_keyword_and_status_filter(workspace_client) -> None:
    client, _, _ = workspace_client
    client.post(
        "/api/admin/users",
        json={"username": "alice", "password": "pw", "real_name": "爱丽丝"},
    )
    client.post(
        "/api/admin/users",
        json={"username": "bob", "password": "pw", "real_name": "鲍勃"},
    )
    # 关键字命中姓名。
    hit = client.get("/api/admin/users", params={"keyword": "鲍勃"}).json()
    assert [u["username"] for u in hit] == ["bob"]
    # 状态筛选：全部启用。
    enabled = client.get(
        "/api/admin/users", params={"disabled": False}
    ).json()
    assert {u["username"] for u in enabled} == {"alice", "bob"}


def test_superadmin_cannot_be_disabled_or_demoted(workspace_client) -> None:
    client, users, _ = workspace_client
    users.create_user("root", "pw", is_superadmin=True)
    disabled = client.patch(
        "/api/admin/users/root", json={"disabled": True}
    )
    assert disabled.status_code == 400
    demoted = client.patch("/api/admin/users/root", json={"role": "employee"})
    assert demoted.status_code == 400
    # 普通档案更新仍允许。
    renamed = client.patch(
        "/api/admin/users/root", json={"real_name": "超级管理员"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["real_name"] == "超级管理员"


def test_role_users_endpoint_lists_members(workspace_client) -> None:
    client, users, rbac = workspace_client
    rbac.upsert_role("support_lead", ["kb:read"], description="客服")
    users.create_user("eve", "pw", real_name="伊芙")
    rbac.grant_role("eve", "support_lead")
    members = client.get("/api/admin/roles/support_lead/users").json()
    assert isinstance(members, list)
    assert [m["username"] for m in members] == ["eve"]
    assert members[0]["real_name"] == "伊芙"
