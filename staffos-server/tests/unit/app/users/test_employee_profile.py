# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""员工档案字段、默认超管 seed、按钮级权限匹配 的单元测试。

覆盖企业级 RBAC 组织权限升级的新增后端能力（无 PG 依赖，走文件后端 +
纯函数）：

- UserRecord 新增档案字段的默认值与文件 store 读写；
- ``seed_default_admin`` 幂等（无账号创建 / 有账号跳过 / 环境变量覆盖）；
- 按钮级细粒度权限码的通配匹配语义（``*`` / ``admin:*`` / 精确）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app import auth as auth_mod
from qwenpaw.app.rbac.permissions import has_permission, permission_matches
from qwenpaw.app.users.models import ROLE_ADMIN, UserRecord
from qwenpaw.app.users.store import UserStore


# ---------------------------------------------------------------------------
# 员工档案字段
# ---------------------------------------------------------------------------


def test_user_record_profile_defaults() -> None:
    """旧记录缺字段时按默认值兜底（users.json 向后兼容）。"""
    record = UserRecord(username="a", password_hash="h")
    assert record.real_name == ""
    assert record.phone == ""
    assert record.gender == 0
    assert record.position == ""
    assert record.is_superadmin is False


def test_file_store_create_user_with_profile(tmp_path: Path) -> None:
    """文件后端 create_user 落库全部员工档案字段。"""
    store = UserStore(tmp_path / "users.json")
    record = store.create_user(
        "alice",
        "pw",
        role=ROLE_ADMIN,
        real_name="爱丽丝",
        phone="13800000000",
        gender=2,
        position="工程师",
        is_superadmin=True,
    )
    assert record is not None
    loaded = store.get_user("alice")
    assert loaded is not None
    assert loaded.real_name == "爱丽丝"
    assert loaded.phone == "13800000000"
    assert loaded.gender == 2
    assert loaded.position == "工程师"
    assert loaded.is_superadmin is True


def test_file_store_set_profile_partial(tmp_path: Path) -> None:
    """set_profile 仅更新传入字段，None 字段保持不变。"""
    store = UserStore(tmp_path / "users.json")
    store.create_user("bob", "pw", real_name="鲍勃", phone="1")
    assert store.set_profile("bob", phone="2", gender=1) is True
    loaded = store.get_user("bob")
    assert loaded is not None
    assert loaded.real_name == "鲍勃"  # 未传，保持
    assert loaded.phone == "2"
    assert loaded.gender == 1


# ---------------------------------------------------------------------------
# 默认超管 seed
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_user_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> UserStore:
    """把全局用户 store 换成临时文件 store，并屏蔽 legacy 迁移副作用。"""
    store = UserStore(tmp_path / "users.json")
    monkeypatch.setattr("qwenpaw.app.users.store._default_store", store)
    monkeypatch.setattr(auth_mod, "_ensure_users_migrated", lambda: None)
    for var in (
        "QWENPAW_DEFAULT_ADMIN_USERNAME",
        "QWENPAW_DEFAULT_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    return store


def test_seed_default_admin_creates_when_empty(isolated_user_store) -> None:
    """无任何账号时创建受保护的默认超管。"""
    assert isolated_user_store.has_users() is False
    assert auth_mod.seed_default_admin() is True
    admin = isolated_user_store.get_user(auth_mod.DEFAULT_ADMIN_USERNAME)
    assert admin is not None
    assert admin.role == ROLE_ADMIN
    assert admin.is_superadmin is True
    assert admin.real_name == "超级管理员"


def test_seed_default_admin_skips_when_users_exist(
    isolated_user_store,
) -> None:
    """已有账号时不覆盖（幂等，绝不动既有运维账号）。"""
    isolated_user_store.create_user("root", "pw")
    assert auth_mod.seed_default_admin() is False
    assert isolated_user_store.get_user("admin") is None


def test_seed_default_admin_env_override(
    isolated_user_store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """环境变量覆盖用户名与口令；此时不视为内置默认口令。"""
    monkeypatch.setenv("QWENPAW_DEFAULT_ADMIN_USERNAME", "superadmin")
    monkeypatch.setenv("QWENPAW_DEFAULT_ADMIN_PASSWORD", "S3cret!x")
    assert auth_mod.seed_default_admin() is True
    assert isolated_user_store.get_user("superadmin") is not None
    # 自定义口令下 hint 应为 False（不对外暴露）。
    assert auth_mod.default_admin_password_is_default() is False


def test_default_admin_hint_true_on_builtin_password(
    isolated_user_store,
) -> None:
    """内置默认口令未改时 hint 为 True。"""
    auth_mod.seed_default_admin()
    assert auth_mod.default_admin_password_is_default() is True


# ---------------------------------------------------------------------------
# 按钮级权限匹配
# ---------------------------------------------------------------------------


def test_button_permission_wildcard_match() -> None:
    """platform_admin 的 ``*`` 与 ``admin:*`` 覆盖按钮级细码。"""
    assert permission_matches("*", "admin:usersCreate") is True
    assert permission_matches("admin:*", "admin:usersCreate") is True
    assert permission_matches("admin:usersCreate", "admin:usersCreate") is True


def test_button_permission_exact_no_prefix_leak() -> None:
    """精确码不越权：``admin:users`` 不覆盖 ``admin:usersCreate``。"""
    assert permission_matches("admin:users", "admin:usersCreate") is False
    assert has_permission(["admin:users"], "admin:usersQuery") is False
    assert has_permission(["admin:users", "admin:usersQuery"], "admin:usersQuery") is True
