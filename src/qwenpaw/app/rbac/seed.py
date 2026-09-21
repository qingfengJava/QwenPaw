# -*- coding: utf-8 -*-
"""RBAC 内置数据 Seed（M5+）。

启动时幂等写入 PG：权限注册表 + 内置角色 + 角色权限绑定 +
初始菜单 + 角色菜单绑定 + 用户角色绑定（flat role 映射补齐）。
所有写操作使用 ``INSERT ... ON CONFLICT`` 保证重复执行不报错、
不产生重复数据。

挂载点：``qwenpaw.app._app.lifespan`` 的 ``_background_startup``，
紧跟 ``bootstrap_enterprise()`` 之后（enterprise schema 就绪后）。

PG 不可用时静默跳过（单机/文件后端部署零影响）。
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from .models import (
    FLAT_ROLE_TO_RBAC,
    PERM_ADMIN_AUDIT,
    PERM_ADMIN_EXPERTS,
    PERM_ADMIN_KB,
    PERM_ADMIN_ORGS,
    PERM_ADMIN_PLATFORM,
    PERM_ADMIN_QUOTAS,
    PERM_ADMIN_ROLES,
    PERM_ADMIN_USERS,
    PERM_AGENT_MANAGE,
    PERM_AGENT_USE,
    PERM_ALL,
    PERM_KB_READ,
    PERM_KB_WRITE,
    PERM_MODEL_INVOKE,
    PERM_MODEL_MANAGE,
    PERM_ONTOLOGY_MANAGE,
    PERM_PROJECT_MANAGE,
    PERM_PROJECT_USE,
    ROLE_EMPLOYEE,
    ROLE_PLATFORM_ADMIN,
    ROLE_TEAM_LEAD,
)

logger = logging.getLogger(__name__)

_TENANT = "default"

# models.py 未定义但 seed 需要的菜单类权限码（与前端 admin:menus /
# admin:permissions 路由保持一致）
PERM_ADMIN_MENUS = "admin:menus"
PERM_ADMIN_PERMISSIONS = "admin:permissions"


# ---------------------------------------------------------------------------
# 按钮级细粒度权限码（企业后台"角色-功能权限"勾选到操作粒度）。
# 命名沿用 resource:action 二级格式，action 用 camelCase 区分操作；
# platform_admin 持 "*" 自动覆盖，自定义角色按需勾选。
# ---------------------------------------------------------------------------
_BUTTON_PERM_SPECS = [
    # 用户管理
    ("admin:usersQuery", "用户-查询", "users", "query"),
    ("admin:usersCreate", "用户-新建", "users", "create"),
    ("admin:usersUpdate", "用户-编辑", "users", "update"),
    ("admin:usersDelete", "用户-删除", "users", "delete"),
    ("admin:usersResetPwd", "用户-重置密码", "users", "resetPwd"),
    ("admin:usersAssignRole", "用户-分配角色", "users", "assignRole"),
    # 角色管理
    ("admin:rolesQuery", "角色-查询", "roles", "query"),
    ("admin:rolesCreate", "角色-新建", "roles", "create"),
    ("admin:rolesUpdate", "角色-编辑", "roles", "update"),
    ("admin:rolesDelete", "角色-删除", "roles", "delete"),
    ("admin:rolesAssign", "角色-分配权限", "roles", "assign"),
    # 组织/部门管理
    ("admin:orgsQuery", "组织-查询", "orgs", "query"),
    ("admin:orgsCreate", "组织-新建", "orgs", "create"),
    ("admin:orgsUpdate", "组织-编辑", "orgs", "update"),
    ("admin:orgsDelete", "组织-删除", "orgs", "delete"),
    ("admin:orgsAssignMember", "组织-分配成员", "orgs", "assignMember"),
    # 菜单管理
    ("admin:menusQuery", "菜单-查询", "menus", "query"),
    ("admin:menusCreate", "菜单-新建", "menus", "create"),
    ("admin:menusUpdate", "菜单-编辑", "menus", "update"),
    ("admin:menusDelete", "菜单-删除", "menus", "delete"),
    # 权限管理
    ("admin:permissionsQuery", "权限-查询", "permissions", "query"),
    ("admin:permissionsCreate", "权限-新建", "permissions", "create"),
    ("admin:permissionsUpdate", "权限-编辑", "permissions", "update"),
    ("admin:permissionsDelete", "权限-删除", "permissions", "delete"),
]

# 按钮码 → 所属页面菜单 id（用于生成 button 型菜单条目并挂到对应页面下）。
_BUTTON_PERM_MENU = {
    "users": "menu_admin_users",
    "roles": "menu_admin_roles",
    "orgs": "menu_admin_orgs",
    "menus": "menu_admin_menus",
    "permissions": "menu_admin_permissions",
}


# ---------------------------------------------------------------------------
# C.1 权限注册表：(code, name, resource, action, perm_type)
# ---------------------------------------------------------------------------

_PERMISSION_SEED: List[Tuple[str, str, str, str, str]] = [
    (PERM_ALL, "全部权限", "*", "*", "api"),
    # agent
    (PERM_AGENT_USE, "使用数字员工", "agent", "use", "api"),
    (PERM_AGENT_MANAGE, "管理数字员工", "agent", "manage", "api"),
    # kb
    (PERM_KB_READ, "查看知识库", "kb", "read", "api"),
    (PERM_KB_WRITE, "编辑知识库", "kb", "write", "api"),
    # model
    (PERM_MODEL_INVOKE, "调用模型", "model", "invoke", "api"),
    (PERM_MODEL_MANAGE, "管理模型", "model", "manage", "api"),
    # project
    (PERM_PROJECT_USE, "使用项目", "project", "use", "api"),
    (PERM_PROJECT_MANAGE, "管理项目", "project", "manage", "api"),
    # admin (menu 类)
    (PERM_ADMIN_USERS, "用户管理", "admin", "users", "menu"),
    (PERM_ADMIN_ROLES, "角色管理", "admin", "roles", "menu"),
    (PERM_ADMIN_AUDIT, "审计日志", "admin", "audit", "menu"),
    (PERM_ADMIN_QUOTAS, "配额管理", "admin", "quotas", "menu"),
    (PERM_ADMIN_KB, "知识库管理", "admin", "kb", "menu"),
    (PERM_ONTOLOGY_MANAGE, "本体管理", "admin", "ontology", "menu"),
    (PERM_ADMIN_ORGS, "组织管理", "admin", "orgs", "menu"),
    (PERM_ADMIN_EXPERTS, "数字员工管理", "admin", "experts", "menu"),
    (PERM_ADMIN_PLATFORM, "平台管理", "admin", "platform", "menu"),
    (PERM_ADMIN_MENUS, "菜单管理", "admin", "menus", "menu"),
    (PERM_ADMIN_PERMISSIONS, "权限管理", "admin", "permissions", "menu"),
]

# 按钮级权限码追加到注册表（perm_type=button，resource 统一 admin）。
_PERMISSION_SEED += [
    (code, name, "admin", code.split(":", 1)[1], "button")
    for (code, name, _mod, _action) in _BUTTON_PERM_SPECS
]


# ---------------------------------------------------------------------------
# C.2 内置角色：(name, display_name, description, data_scope, permissions)
# ---------------------------------------------------------------------------

_BUILTIN_ROLES_SEED: List[Tuple[str, str, str, str, List[str]]] = [
    (
        ROLE_PLATFORM_ADMIN, "平台管理员",
        "系统最高权限，管理所有资源与配置",
        "all", [PERM_ALL],
    ),
    (
        ROLE_TEAM_LEAD, "团队负责人",
        "管理本部门及子部门的资源，可配置数字员工",
        "dept_and_child",
        [
            PERM_AGENT_USE, PERM_AGENT_MANAGE,
            PERM_KB_READ, PERM_KB_WRITE,
            PERM_MODEL_INVOKE,
            PERM_PROJECT_USE, PERM_PROJECT_MANAGE,
        ],
    ),
    (
        ROLE_EMPLOYEE, "普通员工",
        "使用平台资源，仅查看本人相关数据",
        "self",
        [
            PERM_AGENT_USE, PERM_KB_READ,
            PERM_MODEL_INVOKE, PERM_PROJECT_USE,
        ],
    ),
]


# ---------------------------------------------------------------------------
# C.3 初始菜单（动态菜单唯一数据源；结构精确镜像
#      console/src/layouts/registry/builtinMenu.ts + builtinRoutes.tsx）
# (id, parent_id, name, menu_type, path, component, icon,
#  perm_code, sort_order)
#
# 约束（防导航漂移）：
#   - path 必须是 builtinRoutes.tsx 里真实注册的路由；
#   - component 必须是可被 lazyImportWithRetry 解析的 pages 相对路径串
#     （约定 "Admin/Users" → pages/Admin/Users.tsx）；
#   - icon 必须是前端 iconRegistry 注册过的名字。
# menu_type: directory=分组 / menu=页面 / button=权限点(不进导航)。
# ---------------------------------------------------------------------------

_MENU_SEED: List[
    Tuple[str, Optional[str], str, str, str, str, str, str, int]
] = [
    # 工作台（所有登录用户）
    ("menu_workbench", None, "工作台", "menu",
     "/workbench", "Workbench/index", "LayoutDashboard", "", 10),

    # 员工与通道（目录）
    ("menu_staff_channels", None, "员工与通道", "directory",
     "", "", "UsersRound", "", 20),
    ("menu_agents", "menu_staff_channels", "数字员工", "menu",
     "/agents", "Agents/AgentsConsolePage", "SparkAgentLine",
     PERM_AGENT_USE, 21),
    ("menu_channels", "menu_staff_channels", "渠道接入", "menu",
     "/channels", "Control/Channels/ChannelsPlatformPage",
     "SparkWifiLine", "", 22),
    ("menu_inbox", "menu_staff_channels", "收件箱", "menu",
     "/inbox", "Inbox/index", "SparkEmailLine", "", 23),

    # 能力与扩展（目录）
    ("menu_capability", None, "能力与扩展", "directory",
     "", "", "Layers", "", 30),
    ("menu_models", "menu_capability", "模型配置", "menu",
     "/models", "Settings/Models/index", "SparkModePlazaLine",
     PERM_MODEL_INVOKE, 31),
    ("menu_skill_pool", "menu_capability", "技能池", "menu",
     "/skill-pool", "Settings/SkillPool/index", "SparkOtherLine", "", 32),
    ("menu_marketplace", "menu_capability", "扩展市场", "menu",
     "/market", "Market/index", "SparkMyApplicationLine", "", 33),

    # 设置（目录）
    ("menu_settings", None, "设置", "directory",
     "", "", "Settings2", "", 40),
    ("menu_voice", "menu_settings", "语音转写", "menu",
     "/voice-transcription", "Settings/VoiceTranscription/index",
     "SparkMicLine", "", 41),

    # 数据与安全（目录）
    ("menu_data", None, "数据与安全", "directory",
     "", "", "Database", "", 50),
    ("menu_environments", "menu_data", "环境", "menu",
     "/environments", "Settings/Environments/index",
     "SparkInternetLine", "", 51),
    ("menu_offload", "menu_data", "工具卸载", "menu",
     "/offload-policy", "Settings/OffloadPolicy/index",
     "SparkDateLine", "", 52),
    ("menu_security", "menu_data", "安全", "menu",
     "/security", "Settings/Security/index", "SparkBrowseLine", "", 53),
    ("menu_token_usage", "menu_data", "Token 用量", "menu",
     "/token-usage", "Settings/TokenUsage/index", "SparkDataLine", "", 54),
    ("menu_backups", "menu_data", "备份", "menu",
     "/backups", "Settings/Backups/index", "SparkSaveLine", "", 55),

    # 高级（目录）
    ("menu_advanced", None, "高级", "directory",
     "", "", "SlidersHorizontal", "", 60),
    ("menu_debug", "menu_advanced", "调试", "menu",
     "/debug", "Settings/Debug/index", "SparkDebugLine", "", 61),

    # 平台管理（目录，admin-only；含菜单管理/权限管理入口）
    ("menu_admin", None, "平台管理", "directory",
     "", "", "Building2", "", 90),
    ("menu_admin_pending", "menu_admin", "待审收件箱", "menu",
     "/admin/pending", "Admin/Pending", "ListTodo",
     PERM_ADMIN_AUDIT, 905),
    ("menu_admin_attribution", "menu_admin", "归因热力", "menu",
     "/admin/attribution", "Admin/Attribution", "Flame",
     PERM_ADMIN_AUDIT, 907),
    ("menu_admin_users", "menu_admin", "用户管理", "menu",
     "/admin/users", "Admin/Users", "Users",
     PERM_ADMIN_USERS, 910),
    ("menu_admin_roles", "menu_admin", "角色管理", "menu",
     "/admin/roles", "Admin/Roles", "ShieldCheck",
     PERM_ADMIN_ROLES, 920),
    ("menu_admin_teams", "menu_admin", "团队管理", "menu",
     "/admin/teams", "Admin/Teams", "UsersRound",
     PERM_ADMIN_ROLES, 930),
    ("menu_admin_agent_grants", "menu_admin", "员工授权", "menu",
     "/admin/agent-grants", "Admin/AgentGrants", "Bot",
     PERM_ADMIN_EXPERTS, 940),
    ("menu_admin_model_grants", "menu_admin", "模型授权", "menu",
     "/admin/model-grants", "Admin/ModelGrants", "KeyRound",
     PERM_ADMIN_ROLES, 950),
    ("menu_admin_quotas", "menu_admin", "配额管理", "menu",
     "/admin/quotas", "Admin/Quotas", "Gauge",
     PERM_ADMIN_QUOTAS, 960),
    ("menu_admin_audit", "menu_admin", "审计日志", "menu",
     "/admin/audit", "Admin/Audit", "ScrollText",
     PERM_ADMIN_AUDIT, 970),
    ("menu_admin_kb", "menu_admin", "知识库管理", "menu",
     "/admin/knowledge", "Admin/Knowledge", "BookOpen",
     PERM_ADMIN_KB, 980),
    ("menu_admin_ontology", "menu_admin", "本体管理", "menu",
     "/admin/ontology", "Admin/Ontology", "BookOpen",
     PERM_ONTOLOGY_MANAGE, 985),
    ("menu_admin_orgs", "menu_admin", "组织管理", "menu",
     "/admin/organization", "Admin/Organization", "UsersRound",
     PERM_ADMIN_ORGS, 990),
    ("menu_admin_menus", "menu_admin", "菜单管理", "menu",
     "/admin/menus", "Admin/MenuManagement", "ListTodo",
     PERM_ADMIN_MENUS, 1000),
    ("menu_admin_permissions", "menu_admin", "权限管理", "menu",
     "/admin/permissions", "Admin/Permissions", "KeyRound",
     PERM_ADMIN_PERMISSIONS, 1010),
]

# 按钮型菜单条目：挂在对应页面菜单下，仅作为"角色-功能权限"树的叶子
# 元数据（映射到按钮权限码），不参与导航渲染、也不绑定给内置角色。
_MENU_SEED += [
    (
        f"menu_btn_{mod}_{action}",
        _BUTTON_PERM_MENU[mod],
        name,
        "button",
        "", "", "", code,
        1000 + idx,
    )
    for idx, (code, name, mod, action) in enumerate(_BUTTON_PERM_SPECS)
]

# 绑定计算一律排除 button 型（menu_type 位于元组索引 3），避免按钮
# 条目泄漏到用户导航菜单。
_ALL_MENU_IDS: List[str] = [
    m[0] for m in _MENU_SEED if m[3] != "button"
]
_NON_ADMIN_MENU_IDS: List[str] = [
    m[0] for m in _MENU_SEED
    if m[3] != "button" and not m[0].startswith("menu_admin")
]
_ALL_ADMIN_MENU_IDS: List[str] = [
    m[0] for m in _MENU_SEED
    if m[3] != "button" and m[0].startswith("menu_admin")
]
# 仅平台管理员可见的系统配置菜单（菜单管理/权限管理）。
_ADMIN_CONFIG_MENU_IDS: List[str] = [
    "menu_admin_menus", "menu_admin_permissions",
]
# 旧版 seed 存在、新版已删的内置菜单 id。reseed 时一并清理，避免管理树
# 残留孤儿行（它们已不绑定任何角色，不会进导航，但会干扰管理员理解）。
_RETIRED_MENU_IDS: List[str] = [
    "menu_kb", "menu_admin_experts", "menu_admin_platform",
]


# ---------------------------------------------------------------------------
# C.4 角色-菜单绑定
# ---------------------------------------------------------------------------

_ROLE_MENU_BINDINGS = {
    ROLE_PLATFORM_ADMIN: _ALL_MENU_IDS,
    ROLE_TEAM_LEAD: (
        _NON_ADMIN_MENU_IDS
        + [m for m in _ALL_ADMIN_MENU_IDS if m not in _ADMIN_CONFIG_MENU_IDS]
    ),
    ROLE_EMPLOYEE: _NON_ADMIN_MENU_IDS,
}


# ===========================================================================
# Public entry
# ===========================================================================


def seed_rbac_pg() -> bool:
    """幂等 seed PG RBAC 数据。应用启动时调用。

    Returns:
        ``True`` 表示 seed 已执行（PG 可用且成功）；
        ``False`` 表示 PG 不可用或异常已记录（调用方无需处理）。
    """
    try:
        from .store_pg import get_pg_rbac_store

        pg_store = get_pg_rbac_store()
    except Exception:  # pylint: disable=broad-except
        logger.debug("rbac seed: store_pg import failed", exc_info=True)
        return False
    if pg_store is None:
        logger.debug("rbac seed skipped: PG store unavailable")
        return False
    try:
        _seed_permissions(pg_store)
        _seed_builtin_roles(pg_store)
        _seed_menus(pg_store)
        _seed_role_menus(pg_store)
        user_role_count = _seed_user_roles(pg_store)
        # 清缓存，让后续 has_permission / get_user_menus 立刻读到新数据
        try:
            pg_store._invalidate()  # noqa: SLF001 - same package
        except Exception:  # pylint: disable=broad-except
            pass
        logger.info(
            "rbac seed completed: %d permissions, %d builtin roles, "
            "%d menus, %d user-role bindings",
            len(_PERMISSION_SEED), len(_BUILTIN_ROLES_SEED),
            len(_MENU_SEED), user_role_count,
        )
        return True
    except Exception:  # pylint: disable=broad-except
        logger.warning("rbac seed failed", exc_info=True)
        return False


# ===========================================================================
# Internal seed steps
# ===========================================================================


def _seed_permissions(pg_store) -> None:
    """注册所有权限码到 ``rbac_permissions`` 表（幂等 upsert）。"""
    import shortuuid
    from sqlalchemy import text

    async def _run() -> None:
        async with pg_store._get_engine().begin() as conn:  # noqa: SLF001
            for code, name, resource, action, perm_type in _PERMISSION_SEED:
                pid = shortuuid.uuid()
                await conn.execute(
                    text(
                        "INSERT INTO rbac_permissions "
                        "(id, code, name, resource, action, perm_type) "
                        "VALUES (:id, :code, :name, :res, :act, :pt) "
                        "ON CONFLICT (tenant_id, code) DO UPDATE SET "
                        "name = EXCLUDED.name, "
                        "resource = EXCLUDED.resource, "
                        "action = EXCLUDED.action, "
                        "perm_type = EXCLUDED.perm_type",
                    ),
                    {"id": pid, "code": code, "name": name,
                     "res": resource, "act": action, "pt": perm_type},
                )

    pg_store._run(_run())  # noqa: SLF001


def _seed_builtin_roles(pg_store) -> None:
    """幂等创建/更新 3 个内置角色 + 权限绑定 + data_scope。"""
    import shortuuid
    from sqlalchemy import text

    async def _run() -> None:
        async with pg_store._get_engine().begin() as conn:  # noqa: SLF001
            for (name, display_name, description,
                 data_scope, permissions) in _BUILTIN_ROLES_SEED:
                rid = shortuuid.uuid()
                await conn.execute(
                    text(
                        "INSERT INTO rbac_roles "
                        "(id, name, display_name, description, "
                        "is_builtin, data_scope) "
                        "VALUES (:id, :name, :dn, :desc, TRUE, :ds) "
                        "ON CONFLICT (tenant_id, name) DO UPDATE SET "
                        "display_name = EXCLUDED.display_name, "
                        "description = EXCLUDED.description, "
                        "is_builtin = TRUE, "
                        "data_scope = EXCLUDED.data_scope, "
                        "is_enabled = TRUE",
                    ),
                    {"id": rid, "name": name, "dn": display_name,
                     "desc": description, "ds": data_scope},
                )
                # 取实际 role_id（可能是之前已存在的）
                row = (
                    await conn.execute(
                        text(
                            "SELECT id FROM rbac_roles "
                            "WHERE tenant_id = :tid AND name = :name",
                        ),
                        {"tid": _TENANT, "name": name},
                    )
                ).fetchone()
                actual_rid = str(row[0]) if row else rid

                # 重建权限绑定（先清后写，保证与 seed 声明一致）
                await conn.execute(
                    text(
                        "DELETE FROM rbac_role_permissions "
                        "WHERE tenant_id = :tid AND role_id = :rid",
                    ),
                    {"tid": _TENANT, "rid": actual_rid},
                )
                for code in permissions:
                    prow = (
                        await conn.execute(
                            text(
                                "SELECT id FROM rbac_permissions "
                                "WHERE tenant_id = :tid AND code = :code",
                            ),
                            {"tid": _TENANT, "code": code},
                        )
                    ).fetchone()
                    if prow is None:
                        logger.warning(
                            "rbac seed: permission %r missing, "
                            "skip binding to role %r", code, name,
                        )
                        continue
                    await conn.execute(
                        text(
                            "INSERT INTO rbac_role_permissions "
                            "(role_id, permission_id) "
                            "VALUES (:rid, :pid) "
                            "ON CONFLICT DO NOTHING",
                        ),
                        {"rid": actual_rid, "pid": str(prow[0])},
                    )

                # 泛化 data_scope 行（resource='*' 覆盖所有资源）
                sid = shortuuid.uuid()
                await conn.execute(
                    text(
                        "INSERT INTO rbac_data_scopes "
                        "(id, role_id, resource, scope_type, "
                        "custom_dept_ids) "
                        "VALUES (:id, :rid, '*', :st, '[]'::jsonb) "
                        "ON CONFLICT (tenant_id, role_id, resource) "
                        "DO UPDATE SET "
                        "scope_type = EXCLUDED.scope_type, "
                        "custom_dept_ids = EXCLUDED.custom_dept_ids",
                    ),
                    {"id": sid, "rid": actual_rid, "st": data_scope},
                )

    pg_store._run(_run())  # noqa: SLF001


def _write_menus(pg_store, force: bool) -> None:
    """写入初始菜单（固定 ID，镜像 builtinMenu.ts 结构）。

    force=False（启动 seed）：``ON CONFLICT DO NOTHING`` —— 仅补齐缺失
    菜单，绝不覆盖管理员在菜单管理里做过的改名/隐藏/删除等编辑。
    force=True（显式 reseed）：``ON CONFLICT DO UPDATE`` —— 用 seed 结构
    强制覆盖全部菜单行（供“重置为默认菜单”运维入口使用）。
    """
    from sqlalchemy import text

    conflict_tail = (
        "DO UPDATE SET parent_id = EXCLUDED.parent_id, "
        "name = EXCLUDED.name, menu_type = EXCLUDED.menu_type, "
        "path = EXCLUDED.path, component = EXCLUDED.component, "
        "icon = EXCLUDED.icon, perm_code = EXCLUDED.perm_code, "
        "sort_order = EXCLUDED.sort_order, is_visible = TRUE, "
        "is_enabled = TRUE"
        if force
        else "DO NOTHING"
    )

    async def _run() -> None:
        async with pg_store._get_engine().begin() as conn:  # noqa: SLF001
            for (mid, parent_id, name, menu_type, path, component,
                 icon, perm_code, sort_order) in _MENU_SEED:
                await conn.execute(
                    text(
                        "INSERT INTO rbac_menus "
                        "(id, parent_id, name, menu_type, path, "
                        "component, icon, perm_code, sort_order, "
                        "is_visible, is_enabled, is_external, redirect) "
                        "VALUES (:id, :pid, :name, :mt, :path, :comp, "
                        ":icon, :pc, :so, TRUE, TRUE, FALSE, '') "
                        "ON CONFLICT (tenant_id, id) " + conflict_tail,
                    ),
                    {"id": mid, "pid": parent_id, "name": name,
                     "mt": menu_type, "path": path, "comp": component,
                     "icon": icon, "pc": perm_code, "so": sort_order},
                )

    pg_store._run(_run())  # noqa: SLF001


def _seed_menus(pg_store) -> None:
    """启动 seed：仅补齐缺失菜单（不覆盖运营编辑）。"""
    _write_menus(pg_store, force=False)


def _write_role_menus(pg_store, force: bool) -> None:
    """写入角色-菜单默认绑定。

    force=False（启动 seed）：**差集增量补齐**——先查“已被任意角色绑定
    过的菜单 id”，仅对从未分发过的内置菜单（版本升级新增场景，如本体
    管理）按角色期望集补写绑定（INSERT ... ON CONFLICT DO NOTHING）。
    运营已配置的绑定一律不碰：既不会重启抹掉自定义授权，也不会让新增
    菜单因“角色已有历史绑定”而永远不可见。约定：永久隐藏菜单应使用
    is_visible/is_enabled 开关，而非删除全部角色的绑定行——后者会让
    该菜单被视为未分发新菜单而在下次启动时补回默认角色。
    force=True（显式 reseed）：先删后建，用 seed 声明重建绑定。
    """
    from sqlalchemy import text

    async def _run() -> None:
        async with pg_store._get_engine().begin() as conn:  # noqa: SLF001
            # 差集基准：已被任意角色绑定过的菜单视为“存量已分发”，
            # 启动路径一律不触碰（含运营的增删与隐藏配置）。
            bound_ids: set = set()
            if not force:
                bound_rows = (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT menu_id FROM rbac_role_menus "
                            "WHERE tenant_id = :tid",
                        ),
                        {"tid": _TENANT},
                    )
                ).fetchall()
                bound_ids = {str(r[0]) for r in bound_rows}
            for role_name, menu_ids in _ROLE_MENU_BINDINGS.items():
                row = (
                    await conn.execute(
                        text(
                            "SELECT id FROM rbac_roles "
                            "WHERE tenant_id = :tid AND name = :name",
                        ),
                        {"tid": _TENANT, "name": role_name},
                    )
                ).fetchone()
                if row is None:
                    logger.warning(
                        "rbac seed: role %r missing, skip menu binding",
                        role_name,
                    )
                    continue
                rid = str(row[0])
                if force:
                    await conn.execute(
                        text(
                            "DELETE FROM rbac_role_menus "
                            "WHERE tenant_id = :tid AND role_id = :rid",
                        ),
                        {"tid": _TENANT, "rid": rid},
                    )
                for mid in menu_ids:
                    if not force and mid in bound_ids:
                        # 存量菜单：绑定权已交给运营，启动时不复活。
                        continue
                    await conn.execute(
                        text(
                            "INSERT INTO rbac_role_menus "
                            "(role_id, menu_id) "
                            "VALUES (:rid, :mid) "
                            "ON CONFLICT DO NOTHING",
                        ),
                        {"rid": rid, "mid": mid},
                    )

    pg_store._run(_run())  # noqa: SLF001


def _seed_role_menus(pg_store) -> None:
    """启动 seed：仅为未绑定菜单的角色写默认绑定（不覆盖自定义）。"""
    _write_role_menus(pg_store, force=False)


def _seed_user_roles(pg_store) -> int:
    """启动 seed：为“零绑定”用户按 flat role 映射补齐 RBAC 角色绑定。

    仅补齐 ``rbac_user_roles`` 中零绑定的用户（不覆盖已有绑定，保护运营
    的显式授权/降级）；映射表见 :data:`models.FLAT_ROLE_TO_RBAC`
    （admin→platform_admin、employee→employee）。与 changelog 20260920/01
    的回填 SQL 同构（``INSERT ... ON CONFLICT DO NOTHING``，幂等）。

    Returns:
        本次补齐到至少一个角色绑定的用户数。
    """
    from sqlalchemy import text

    async def _run() -> int:
        processed = 0
        async with pg_store._get_engine().begin() as conn:  # noqa: SLF001
            rows = (
                await conn.execute(
                    text(
                        "SELECT u.username, u.role FROM qwenpaw_users u "
                        "WHERE NOT EXISTS ("
                        "  SELECT 1 FROM rbac_user_roles ur "
                        "  WHERE ur.tenant_id = u.tenant_id "
                        "    AND ur.username = u.username"
                        ")",
                    ),
                )
            ).fetchall()
            for username, flat_role in rows:
                role_names = FLAT_ROLE_TO_RBAC.get(str(flat_role), [])
                ensured = False
                for role_name in role_names:
                    row = (
                        await conn.execute(
                            text(
                                "SELECT id FROM rbac_roles "
                                "WHERE tenant_id = :tid AND name = :n",
                            ),
                            {"tid": _TENANT, "n": role_name},
                        )
                    ).fetchone()
                    if row is None:
                        continue
                    await conn.execute(
                        text(
                            "INSERT INTO rbac_user_roles "
                            "(username, role_id) VALUES (:u, :rid) "
                            "ON CONFLICT DO NOTHING",
                        ),
                        {"u": str(username), "rid": str(row[0])},
                    )
                    ensured = True
                if ensured:
                    processed += 1
        return processed

    return pg_store._run(_run())  # noqa: SLF001


def _delete_menus_by_ids(pg_store, menu_ids: List[str]) -> None:
    """删除指定菜单及其角色绑定（reseed 清理退役内置菜单专用）。

    先删 rbac_role_menus 引用再删 rbac_menus，避免外键残留。
    """
    if not menu_ids:
        return
    from sqlalchemy import text

    async def _run() -> None:
        async with pg_store._get_engine().begin() as conn:  # noqa: SLF001
            for mid in menu_ids:
                await conn.execute(
                    text(
                        "DELETE FROM rbac_role_menus "
                        "WHERE tenant_id = :tid AND menu_id = :mid",
                    ),
                    {"tid": _TENANT, "mid": mid},
                )
                await conn.execute(
                    text(
                        "DELETE FROM rbac_menus "
                        "WHERE tenant_id = :tid AND id = :mid",
                    ),
                    {"tid": _TENANT, "mid": mid},
                )

    pg_store._run(_run())  # noqa: SLF001


def reseed_menus() -> bool:
    """强制用 seed 结构重置 rbac_menus 与角色菜单绑定。

    供“重置为默认菜单”运维入口（``POST /admin/menus/reseed``）调用；
    与启动 seed 不同，这里会覆盖管理员对菜单的编辑。

    Returns:
        ``True`` 重置成功；``False`` PG 不可用或异常（已记录日志）。
    """
    try:
        from .store_pg import get_pg_rbac_store

        pg_store = get_pg_rbac_store()
    except Exception:  # pylint: disable=broad-except
        logger.debug("menu reseed: store_pg import failed", exc_info=True)
        return False
    if pg_store is None:
        logger.warning("menu reseed skipped: PG store unavailable")
        return False
    try:
        _write_menus(pg_store, force=True)
        _delete_menus_by_ids(pg_store, _RETIRED_MENU_IDS)
        _write_role_menus(pg_store, force=True)
        try:
            pg_store._invalidate()  # noqa: SLF001
        except Exception:  # pylint: disable=broad-except
            pass
        logger.info(
            "menu reseed completed: %d menus reset to builtin",
            len(_MENU_SEED),
        )
        return True
    except Exception:  # pylint: disable=broad-except
        logger.warning("menu reseed failed", exc_info=True)
        return False
