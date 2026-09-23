# -*- coding: utf-8 -*-
"""FastAPI dependencies for RBAC enforcement (M4).

``require_perm("resource:action")`` returns a dependency that rejects the
request with 403 unless the authenticated user holds the permission.
Enforcement is gated by ``QWENPAW_RBAC_ENFORCE``:

- **off** (default): every check passes — zero behavior change, routes
  can be annotated incrementally without risk;
- **on**: annotated routes enforce; unannotated routes stay open
  (per the M4 plan's gray-rollout semantics).

The identity comes from ``request.state.user`` (populated by
``AuthMiddleware`` after token verification) and the flat M1 role from
the user store, which keeps the bootstrap guarantee: a flat ``admin``
always passes, so RBAC can never lock operators out.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from fastapi import Depends, HTTPException, Request

from ...constant import EnvVarLoader
from .store import get_rbac_store

logger = logging.getLogger(__name__)

RBAC_ENFORCE_ENV = "QWENPAW_RBAC_ENFORCE"


def _get_pg_store() -> Optional[Any]:
    """延迟导入 PG store 单例（PG 不可用/未安装时返回 ``None``）。

    ``require_perm`` / ``require_data_scope`` / ``get_user_menus_dep``
    统一走此入口，避免顶层导入在 SQLAlchemy 缺失时炸掉整个 rbac 包。
    """
    try:
        from .store_pg import get_pg_rbac_store

        return get_pg_rbac_store()
    except Exception:  # pylint: disable=broad-except
        return None


def _resolve_username(request: Request) -> str:
    """统一解析当前请求的身份名。

    兼容两种中间件约定：``request.state.user``（现有 AuthMiddleware）
    与 ``request.state.username``（部分企业平面路由）。两者均空时返回
    空串，由调用方决定 fail-closed 行为。
    """
    username = getattr(request.state, "user", None)
    if not username:
        username = getattr(request.state, "username", None)
    return str(username or "")


def rbac_enforcement_enabled() -> bool:
    """Whether ``require_perm`` actually rejects.

    默认值跟随认证开关（Governance Engine 的存在前提）：

    - ``QWENPAW_RBAC_ENFORCE`` 显式配置时以其为准（灰度微调仍可用）；
    - 未配置时：认证开启（多用户/企业部署）→ **默认强制**；认证关闭
      （本机单机桌面模式）→ 默认关闭。企业平面在多用户部署下不再
      依赖运维记得手动打开开关。
    """
    # 显式配置优先（true/on/1 开；false/off/0 关）
    explicit = EnvVarLoader.get_str(RBAC_ENFORCE_ENV, "").strip().lower()
    if explicit in ("1", "true", "on", "yes"):
        return True
    if explicit in ("0", "false", "off", "no"):
        return False
    # 未显式配置：跟随认证开关（延迟导入防循环依赖）
    try:
        from ..auth import is_auth_enabled

        return is_auth_enabled()
    except Exception:  # pylint: disable=broad-except
        return False


def _resolve_flat_role(username: str) -> str:
    """Look up the M1 flat role for *username* ("" when unknown)."""
    try:
        from ..users.store import get_user_store

        user = get_user_store().get_user(username)
        return user.role if user is not None else ""
    except Exception:  # pylint: disable=broad-except
        logger.debug("rbac: flat-role lookup failed", exc_info=True)
        return ""


def _resolve_request_agent_id(request: Request) -> str:
    """解析本次请求针对的员工 id（与 ``get_agent_for_request`` 同源）。

    优先级：``request.state.agent_id``（agent-scoped 路由
    ``/api/agents/{id}/...`` 注入）→ ``X-Agent-Id`` 头（控制台顶层路径
    写请求的常规形态，``buildAuthHeaders`` 全局注入）→ config 活动员工
    兜底。闸门必须解析出与端点**将要写入的同一个** agent_id：否则头域
    写请求会因 ``state.agent_id`` 为空被 fail-closed 误拒（打断全部正常
    控制台配置写入），或对着错误的员工判权。伪造头不构成绕过——攻击者
    仍需对伪造目标持有管理授权，且端点写入的正是同一目标。
    """
    agent_id = str(getattr(request.state, "agent_id", "") or "")
    if agent_id:
        return agent_id
    agent_id = str(request.headers.get("X-Agent-Id") or "")
    if agent_id:
        return agent_id
    try:
        from ...config import load_config

        return str(load_config().agents.active_agent or "default")
    except Exception:  # pylint: disable=broad-except
        logger.debug("rbac: active-agent fallback failed", exc_info=True)
        return ""


def require_perm(permission: str) -> Callable:
    """Build a FastAPI dependency enforcing *permission* on this route.

    Usage::

        @router.get("/admin/users",
                    dependencies=[Depends(require_perm("admin:users"))])

    判定顺序（M5+ PG 优先）：

    1. RBAC 关闭（单机免认证部署）→ 直通，零行为变化；
    2. 无身份 → 403（fail-closed）；
    3. **PG store 可用** → ``pg_store.has_permission(username, permission)``
       决定放行/拒绝（PG 为权威源，拒绝时不再 fallback 文件后端）；
    4. PG store 不可用（``None`` 或抛异常）→ fallback 到现有文件 store
       逻辑（``get_rbac_store().user_has_permission``），保持原有代码路径不变。
    """

    async def _dependency(request: Request) -> None:
        if not rbac_enforcement_enabled():
            return
        username = _resolve_username(request)
        if not username:
            # AuthMiddleware normally guarantees an identity; without one
            # (e.g. loopback whitelist bypass) fail closed under enforce.
            raise HTTPException(
                status_code=403,
                detail="RBAC: no authenticated identity",
            )

        # ---- PG-first path (M5+) ----
        pg_store = _get_pg_store()
        if pg_store is not None:
            try:
                if pg_store.has_permission(username, permission):
                    return
                # bootstrap 不变量：扁平 admin 恒通过（与文件后端
                # user_has_permission(flat_role) 及 /auth/permissions
                # 的 "*" 注入对称），避免 PG 绑定数据未就绪时锁死运维。
                if _resolve_flat_role(username) == "admin":
                    logger.debug(
                        "rbac: flat-admin bootstrap bypass (pg denial "
                        "ignored) user=%r permission=%r",
                        username,
                        permission,
                    )
                    return
                logger.warning(
                    "rbac deny (pg): user=%r permission=%r path=%s",
                    username,
                    permission,
                    request.url.path,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Missing permission: {permission}",
                )
            except HTTPException:
                raise
            except Exception:  # pylint: disable=broad-except
                # PG 路径异常（连接抖动 / SQL 错误）→ fallback 文件后端，
                # 避免因 PG 临时故障导致全站 403。
                logger.debug(
                    "rbac: PG has_permission failed, falling back "
                    "to file store",
                    exc_info=True,
                )

        # ---- File store fallback (原有代码路径，不改动) ----
        flat_role = _resolve_flat_role(username)
        if get_rbac_store().user_has_permission(
            username,
            permission,
            flat_role=flat_role,
        ):
            return
        logger.warning(
            "rbac deny: user=%r permission=%r path=%s",
            username,
            permission,
            request.url.path,
        )
        raise HTTPException(
            status_code=403,
            detail=f"Missing permission: {permission}",
        )

    return _dependency


# ---------------------------------------------------------------------------
# 后台配置域闸门：员工级管理授权（双平面模型的 manage 平面）
# ---------------------------------------------------------------------------


async def _fallback_manage_owner(agent_id: str) -> str:
    """无 manage grant 行时的兜底 owner 解析（仅创建者可配）。

    优先治理行 owner_id；无治理行时 expert 形态回退 experts.owner_id
    （创建者）；原生 agent 无 owner 概念返回空串（仅 admin/team_lead
    可配）。任何存储抖动返回空串（fail-closed 由调用方统一兜底）。
    """
    try:
        from ..employees.store import get_employee_governance_store

        record = await get_employee_governance_store().get(agent_id)
        if record is not None and record.owner_id:
            return str(record.owner_id)
    except Exception:  # pylint: disable=broad-except
        logger.debug(
            "rbac: governance lookup failed for %s", agent_id, exc_info=True
        )
    if agent_id.startswith("expert_"):
        try:
            from ..experts.store import get_expert_store

            expert = await get_expert_store().get_expert(
                agent_id.removeprefix("expert_")
            )
            if expert is not None and expert.owner_id:
                return str(expert.owner_id)
        except Exception:  # pylint: disable=broad-except
            logger.debug(
                "rbac: expert owner lookup failed for %s",
                agent_id,
                exc_info=True,
            )
    return ""


async def manage_allowed(username: str, agent_id: str) -> bool:
    """判定 ``username`` 是否可配置 ``agent_id``（后台配置域 manage 平面）。

    与 :func:`require_agent_manage` 闸门同源同序，抽成布尔函数供闸门与
    统计口径（``scope=agent`` 需管理权）等复用，避免判定逻辑分叉：
    flat admin → ``agent:manage`` 角色（team_lead）→ manage grant 行 →
    无行兜底创建者（治理行 owner / experts owner）。不含 RBAC 开关与
    身份存在性检查（由调用方前置）。
    """
    flat_role = _resolve_flat_role(username)
    if flat_role == "admin":
        return True
    store = get_rbac_store()
    if store.user_has_permission(
        username,
        "agent:manage",
        flat_role=flat_role,
    ):
        return True
    grant = store.get_agent_manage_grant(agent_id)
    if grant is not None:
        # 有 grant 行即以其为准（不回落 owner 兜底，与“有行即限”一致）
        return store.grant_allows(
            grant,
            username,
            store.roles_for_user(username, flat_role),
            store.teams_for_user(username),
        )
    owner = await _fallback_manage_owner(agent_id)
    return bool(owner) and owner == username


def is_platform_admin(username: str) -> bool:
    """平台管理员判定（扁平 admin 或持有 ``admin:platform`` 权限）。

    个人资产（S2 用户个人平面，如个人定时任务/技能/草稿）的可见性与
    写权为「owner 本人 + 平台管理员审计」，与员工级管理授权
    （:func:`manage_allowed`，含 team_lead / grant）刻意区分：team_lead 管员工
    **共享面**，但不介入用户个人资产的隐私边界。无身份时返回 False。
    """
    if not username:
        return False
    flat_role = _resolve_flat_role(username)
    if flat_role == "admin":
        return True
    from .models import PERM_ADMIN_PLATFORM

    return get_rbac_store().user_has_permission(
        username,
        PERM_ADMIN_PLATFORM,
        flat_role=flat_role,
    )


def require_agent_manage() -> Callable:
    """后台配置域闸门：登录 + 对该员工的管理授权。

    判定顺序（任一命中即放行）：

    1. RBAC 关闭（单机免认证部署）→ 直通，零行为变化；
    2. flat admin → 直通（bootstrap 修复路径）；
    3. 持有 ``agent:manage`` 角色权限（team_lead）→ 全员工直通；
    4. ``agent_manage_grants`` 有行 → 按 grant 的 users/roles/teams 判定
       （治理面 manage_visibility/manage_granted_* 的投影）；
    5. 无 grant 行 → 兜底 private 语义：仅创建者（治理行/experts owner）。

    与使用域 ``agent_grants`` 的关键差异：manage 平面「无行 ≠ 不限制」，
    出厂默认最严（private），避免新员工被全员可改。
    """

    async def _dependency(request: Request) -> None:
        if not rbac_enforcement_enabled():
            return
        username = str(getattr(request.state, "user", None) or "")
        if not username:
            raise HTTPException(
                status_code=403,
                detail="RBAC: no authenticated identity",
            )
        agent_id = _resolve_request_agent_id(request)
        if not agent_id:
            # 无法解析目标员工（既无 agent 域路由也无头/活动员工）：
            # fail closed 暴露装配错误，绝不对"未知员工"放行写权限
            raise HTTPException(
                status_code=403,
                detail="RBAC: agent scope missing for manage gate",
            )
        # 判定与统计口径复用同一 manage_allowed（同源同序，禁逻辑分叉；
        # flat admin / team_lead 角色 / grant 行 / owner 兜底均含其中）
        if await manage_allowed(username, agent_id):
            return
        _deny_manage(username, agent_id)

    return _dependency


def _deny_manage(username: str, agent_id: str) -> None:
    """统一 403 出口（日志 + 中文可读 detail，前端 toast 直接展示）。"""
    logger.warning(
        "rbac deny: user=%r lacks manage grant on agent=%s",
        username,
        agent_id,
    )
    raise HTTPException(
        status_code=403,
        detail="无该员工配置权限（请联系管理员授予管理授权）",
    )


def require_agent_manage_audited(audit_action: str) -> Callable:
    """管理闸门 + 治理审计留痕：过闸后写一条 ALLOW 到 audit_events。

    S1 共享配置写端点统一用本依赖：闸判与留痕同处完成，路由不再各自
    散写审计。审计绝不抛异常（失败仅告警），不阻塞业务主流程。
    """
    inner = require_agent_manage()

    async def _dependency(request: Request) -> None:
        # 先过权限闸：未过闸由 require_agent_manage 直接抛 403
        await inner(request)
        # 过闸后补治理审计留痕（谁在何时操作了哪个员工的哪个配置面）
        _record_gate_audit(request, audit_action)

    return _dependency


def _agent_use_allowed(username: str, agent_id: str) -> bool:
    """使用授权判定（usage plane）：复用运行期 agent_grants 链。

    与注册表「列表可见」同源：无 grant 行 = 不限制（fail-closed 由
    ``load_error`` 处理）；文件不可读时不放行。
    """
    flat_role = _resolve_flat_role(username)
    if flat_role == "admin":
        return True
    try:
        return get_rbac_store().agent_allowed(username, flat_role, agent_id)
    except Exception:  # pylint: disable=broad-except
        logger.debug("rbac: use-plane lookup failed", exc_info=True)
        return False


async def resolve_agent_doc_write_plane(
    request: Request,
    *,
    allow_personal: bool,
    audit_action: str = "",
) -> str:
    """档案文档写平面分流：返回 ``"shared"`` / ``"personal"``（无权 403）。

    T11 个人档案草稿：写端点按调用者身份分平面，管理员写共享行、
    普通使用者写本人草稿行（不触共享行）：

    1. RBAC 关闭（单机免认证部署）→ ``shared``（零行为变化）；
    2. 有管理权（flat admin / agent:manage / manage grant / owner 兜底，
       同 :func:`manage_allowed`）→ ``shared``；``audit_action`` 非空时
       补治理审计留痕（与 require_agent_manage_audited 同源）；
    3. 无管理权但持该员工使用授权 → ``personal``（仅 ``allow_personal``
       端点允许；非白名单文件的写仍拒绝）；
    4. 以上均无 → 403（统一 deny 出口，文案与 manage 闸门一致）。

    本函数不是 FastAPI 依赖而是端点内显式调用的判定入口：调用方需先
    知道目标文件名是否在档案白名单内（决定 allow_personal），再据此
    决定落哪个平面。
    """
    if not rbac_enforcement_enabled():
        return "shared"
    username = str(getattr(request.state, "user", None) or "")
    if not username:
        raise HTTPException(
            status_code=403,
            detail="RBAC: no authenticated identity",
        )
    agent_id = _resolve_request_agent_id(request)
    if not agent_id:
        raise HTTPException(
            status_code=403,
            detail="RBAC: agent scope missing for manage gate",
        )
    # 判定与统计口径复用同一 manage_allowed（同源同序，禁逻辑分叉）
    if await manage_allowed(username, agent_id):
        if audit_action:
            _record_gate_audit(request, audit_action)
        return "shared"
    if allow_personal and _agent_use_allowed(username, agent_id):
        return "personal"
    _deny_manage(username, agent_id)
    # _deny_manage 恒抛 403；此行为不可达（显式 raise 满足类型检查）
    raise AssertionError("unreachable: _deny_manage always raises")


def _record_gate_audit(request: Request, audit_action: str) -> None:
    """为闸门通过写一条 ALLOW 审计（吞掉所有异常，绝不影响业务）。"""
    try:
        from ...config import load_config
        from ...governance.audit import AuditLog
        from ...governance.policy import (
            GovernanceAction,
            GovernanceDecision,
            ToolCallSpec,
        )

        agent_id = _resolve_request_agent_id(request)
        workspace_dir = ""
        if agent_id:
            profile = load_config().agents.profiles.get(agent_id)
            workspace_dir = str(getattr(profile, "workspace_dir", "") or "")
        spec = ToolCallSpec(
            tool_name=audit_action,
            target=request.url.path,
            agent_id=agent_id,
            session_id="",
            raw_params={"method": request.method},
            user_id=str(getattr(request.state, "user", "") or ""),
        )
        AuditLog.get_instance().record(
            workspace_dir,
            spec,
            GovernanceDecision(
                action=GovernanceAction.ALLOW,
                reason="agent manage gate passed",
            ),
        )
    except Exception:  # noqa: BLE001 - audit must never raise
        logger.warning(
            "audit write failed for manage gate %s (%s)",
            audit_action,
            request.url.path,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# 数据范围与菜单依赖（M5+ PG 平面）
# ---------------------------------------------------------------------------


def require_data_scope(resource: str):
    """FastAPI 依赖工厂：注入当前用户对指定资源的数据范围。

    Usage::

        @router.get("/projects")
        async def list_projects(
            scope: DataScopeRecord = Depends(require_data_scope("project")),
        ):
            ...

    PG 可用时委托 ``PgRbacStore.resolve_user_scope``；PG 不可用时
    fallback 到最宽松的 ``all`` 范围（单机/文件后端部署零阻断）。
    """
    from .models import DataScopeRecord

    async def _dep(request: Request) -> DataScopeRecord:
        username = _resolve_username(request)
        pg_store = _get_pg_store()
        if pg_store is not None and username:
            try:
                return pg_store.resolve_user_scope(username, resource)
            except Exception:  # pylint: disable=broad-except
                logger.debug(
                    "rbac: resolve_user_scope failed for %r/%s",
                    username, resource, exc_info=True,
                )
        # fallback: 返回最宽松的 all 范围
        return DataScopeRecord(
            id="", role_id="", resource=resource,
            scope_type="all", custom_dept_ids=[],
        )

    return _dep


async def get_user_menus_dep(request: Request) -> List[Any]:
    """FastAPI 依赖：获取当前用户可见菜单树。

    Usage::

        @router.get("/menus")
        async def my_menus(
            menus: list = Depends(get_user_menus_dep),
        ):
            return menus

    PG 可用时委托 ``PgRbacStore.get_user_menus``（已含角色聚合 +
    树形构造）；PG 不可用或无身份时返回空列表。
    """
    username = _resolve_username(request)
    if not username:
        return []
    pg_store = _get_pg_store()
    if pg_store is None:
        return []
    try:
        return pg_store.get_user_menus(username)
    except Exception:  # pylint: disable=broad-except
        logger.debug(
            "rbac: get_user_menus failed for %r", username, exc_info=True,
        )
        return []
