# -*- coding: utf-8 -*-
"""动态菜单 seed 结构一致性测试（纯 Python，无需 PG）。

守护"菜单管理驱动侧栏 + 动态路由"的数据契约：seed 里每条页面菜单都必须
带真实 path 与可解析 component，目录不带 path，button 不进导航，且所有被
引用到的菜单 id（按钮挂载、角色绑定）都真实存在——防止导航漂移/死链。
"""
from __future__ import annotations

from qwenpaw.app.rbac import seed


def _menu_by_id():
    return {m[0]: m for m in seed._MENU_SEED}


def test_page_menus_have_path_and_component():
    """menu 型必须同时具备 path 与 component（动态路由依赖二者）。"""
    for mid, _parent, _name, mtype, path, component, _icon, _pc, _so in seed._MENU_SEED:
        if mtype == "menu":
            assert path, f"menu {mid} 缺少 path"
            assert component, f"menu {mid} 缺少 component"


def test_directories_have_no_path():
    """directory 型是分组，不应带 path。"""
    for mid, _parent, _name, mtype, path, *_rest in seed._MENU_SEED:
        if mtype == "directory":
            assert not path, f"directory {mid} 不应带 path"


def test_button_menus_excluded_from_nav_ids():
    """_ALL_MENU_IDS（角色可绑定的导航菜单）不得含任何 button。"""
    by_id = _menu_by_id()
    button_ids = {m[0] for m in seed._MENU_SEED if m[3] == "button"}
    assert button_ids, "seed 应包含 button 型权限点"
    assert button_ids.isdisjoint(set(seed._ALL_MENU_IDS))
    for mid in seed._ALL_MENU_IDS:
        assert by_id[mid][3] != "button"


def test_button_perm_menu_targets_exist():
    """按钮挂载的页面菜单 id 必须真实存在。"""
    by_id = _menu_by_id()
    for module, target_id in seed._BUTTON_PERM_MENU.items():
        assert target_id in by_id, f"按钮模块 {module} 挂载目标 {target_id} 不存在"


def test_role_menu_bindings_reference_real_menus():
    """角色-菜单绑定里的每个 id 都必须在 seed 中存在。"""
    by_id = _menu_by_id()
    for role, menu_ids in seed._ROLE_MENU_BINDINGS.items():
        for mid in menu_ids:
            assert mid in by_id, f"角色 {role} 绑定了不存在的菜单 {mid}"


def test_admin_config_menus_present():
    """菜单管理/权限管理入口必须存在于导航（用户可进入配置页）。"""
    by_id = _menu_by_id()
    assert "menu_admin_menus" in by_id
    assert "menu_admin_permissions" in by_id
    assert set(seed._ADMIN_CONFIG_MENU_IDS).issubset(by_id)
