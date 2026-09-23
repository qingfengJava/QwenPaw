# -*- coding: utf-8 -*-
"""``/auth/menus`` 回归测试：认证关闭返回全量菜单树（2026-09-20 修复）。

守护：单机（认证关闭）时 ``/auth/menus`` 必须与 ``/auth/permissions`` 的
``["*"]`` 注入对称——返回 PG 全量菜单树而非空数组，动态菜单在单机部署
同样可用；PG 不可用时保持 ``[]``（前端回退内置菜单）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import qwenpaw.app.auth as auth
import qwenpaw.app.users.store as users_store
from qwenpaw.app.rbac.models import MenuRecord
from qwenpaw.app.routers.auth import router as auth_router
from qwenpaw.app.users.store import UserStore


class _FakePgRbac:
    """伪 PG RBAC store：菜单两入口 + 调用记录。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_menu_tree(self) -> list[MenuRecord]:
        self.calls.append("tree")
        return [
            MenuRecord(
                id="m1",
                name="系统",
                menu_type="directory",
                children=[
                    MenuRecord(id="m2", name="用户管理", path="/admin/users"),
                ],
            ),
        ]

    def get_user_menus(self, username: str) -> list[MenuRecord]:
        self.calls.append(f"user:{username}")
        return [MenuRecord(id="u1", name=f"{username}-menu", path="/x")]


@pytest.fixture
def menus_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """auth router + 伪 PG store（认证与用户文件隔离到 tmp_path）。"""
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "secret" / "auth.json")
    store = UserStore(tmp_path / "secret" / "users.json")
    monkeypatch.setattr(users_store, "_default_store", store)
    fake_pg = _FakePgRbac()
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store_pg.get_pg_rbac_store",
        lambda: fake_pg,
    )
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    with TestClient(app) as client:
        yield client, fake_pg


def test_menus_auth_disabled_returns_full_tree(
    menus_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """认证关闭：返回全量菜单树（与 ["*"] 对称），含 children 序列化。"""
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "0")
    client, fake_pg = menus_client
    resp = client.get("/api/auth/menus")
    assert resp.status_code == 200
    body = resp.json()
    assert [m["id"] for m in body] == ["m1"]
    assert body[0]["children"][0]["path"] == "/admin/users"
    assert fake_pg.calls == ["tree"]


def test_menus_auth_disabled_pg_unavailable_returns_empty(
    menus_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """认证关闭 + PG 不可用：返回 []（前端回退内置菜单）。"""
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "0")
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store_pg.get_pg_rbac_store",
        lambda: None,
    )
    client, _ = menus_client
    resp = client.get("/api/auth/menus")
    assert resp.status_code == 200
    assert resp.json() == []


def test_menus_authed_user_gets_own_tree(
    menus_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """认证开启：带有效 token 返回该用户菜单（get_user_menus）。"""
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "1")
    client, fake_pg = menus_client
    token = auth.register_user("alice", "pw-1")
    assert token
    resp = client.get(
        "/api/auth/menus",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["name"] == "alice-menu"
    assert fake_pg.calls == ["user:alice"]


def test_menus_authed_requires_token(
    menus_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """认证开启但无 token：401（不放行全量树）。"""
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "1")
    client, _ = menus_client
    assert client.get("/api/auth/menus").status_code == 401