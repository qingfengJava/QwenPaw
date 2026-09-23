# -*- coding: utf-8 -*-
"""admin users 角色授予写路径单测：PG 优先 + 文件回退（平面对齐守护）。

守护 2026-09-20 修复：grant/revoke 必须写 PG 权威平面（rbac_user_roles），
否则 UI"绑定成功"但读路径（PG JOIN rbac_user_roles）永远为空。
"""
from __future__ import annotations

from pathlib import Path

from qwenpaw.app.rbac.store import RbacStore
from qwenpaw.app.routers.admin import users as users_module


class _FakePgRbac:
    """伪 PG RBAC store：记录调用并可控返回。"""

    def __init__(self, ok: bool = True):
        self.ok = ok
        self.calls = []

    def assign_user_role(self, username: str, role: str) -> bool:
        self.calls.append(("assign", username, role))
        return self.ok

    def revoke_user_role(self, username: str, role: str) -> bool:
        self.calls.append(("revoke", username, role))
        return self.ok


def test_grant_role_prefers_pg_plane(monkeypatch) -> None:
    fake = _FakePgRbac()
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store_pg.get_pg_rbac_store",
        lambda: fake,
    )
    assert users_module._grant_role_pg_first("eve", "team_lead") is True
    assert fake.calls == [("assign", "eve", "team_lead")]


def test_revoke_role_prefers_pg_plane(monkeypatch) -> None:
    fake = _FakePgRbac()
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store_pg.get_pg_rbac_store",
        lambda: fake,
    )
    assert users_module._revoke_role_pg_first("eve", "team_lead") is True
    assert fake.calls == [("revoke", "eve", "team_lead")]


def test_grant_role_falls_back_to_file_store(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store_pg.get_pg_rbac_store",
        lambda: None,
    )
    file_store = RbacStore(tmp_path / "rbac.json")
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store.get_rbac_store",
        lambda: file_store,
    )
    assert users_module._grant_role_pg_first("eve", "team_lead") is True
    assert "team_lead" in file_store.roles_for_user("eve", "employee")
    # 未知角色在文件平面同样拒绝（保持 400 语义）。
    assert users_module._grant_role_pg_first("eve", "no_such_role") is False
