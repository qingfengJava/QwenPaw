# -*- coding: utf-8 -*-
"""团队动作能力投影：根据 RBAC 权限与团队归属计算当前用户可执行操作。

本模块是 ``TeamActionCapabilities`` 的唯一计算入口，供 admin/xian
路由在团队详情接口中调用。权限判定规则：

- ``manageable``：用户持有 ``admin:experts`` 权限（管理员/配置员）；
- ``can_edit_draft``：manageable 或团队 owner（草稿编辑面）；
- ``can_publish``：manageable（发布是管理操作，owner 不足以单独发布）；
- ``can_execute``：任何能看到已发布团队的用户均可执行（执行走的是
  已发布快照，不影响草稿）；
- ``can_view_published``：始终 True（公开面数据，无需额外权限）。

@author qingfeng
"""

from __future__ import annotations

import logging

from .models import TeamActionCapabilities
from .store import get_expert_store

logger = logging.getLogger(__name__)

#: 管理端专家模块权限（与 rbac.models.PERM_ADMIN_EXPERTS 同值，
#: 此处本地声明避免循环导入）。
_PERM_ADMIN_EXPERTS = "admin:experts"


def _check_permission(username: str, perm: str) -> bool:
    """判定 *username* 是否持有 *perm*（PG-first + flat-admin bypass）。

    与 ``rbac.deps.require_perm`` 同口径，但不抛 HTTPException，
    返回 bool 供能力矩阵消费。RBAC 关闭时直通 True（与 require_perm
    零行为变化对齐）。
    """
    # 延迟导入避免顶层循环依赖
    from ..rbac.deps import _get_pg_store, rbac_enforcement_enabled

    if not rbac_enforcement_enabled():
        return True

    pg_store = _get_pg_store()
    if pg_store is not None:
        try:
            if pg_store.has_permission(username, perm):
                return True
            # flat admin bypass（与 require_perm 对称）
            from ..rbac.deps import _resolve_flat_role

            if _resolve_flat_role(username) == "admin":
                return True
        except Exception:  # noqa: BLE001 - PG 异常回退文件后端
            logger.debug("team_access: PG check failed, fallback", exc_info=True)

    # 文件后端 fallback
    from ..rbac.store import get_rbac_store

    return get_rbac_store().user_has_permission(username, perm)


async def resolve_team_capabilities(
    username: str,
    team_id: str,
) -> TeamActionCapabilities:
    """计算 *username* 对团队 *team_id* 的动作能力矩阵。

    纯读操作：先查团队记录，再查 RBAC 权限，最后组装返回。
    团队不存在时仍返回默认能力（全 False），路由层自行判断 404。
    """
    store = get_expert_store()
    team = await store.get_team(team_id)

    # 团队不存在：返回空能力（路由层根据 needs_404 自行处理）
    if team is None:
        return TeamActionCapabilities(team_id=team_id)

    # 管理员权限判定（PG-first + flat-admin bypass，与 require_perm 同口径）
    manageable = _check_permission(username, _PERM_ADMIN_EXPERTS)

    # owner 判定：团队创建者拥有草稿编辑权
    is_owner = team.owner_id == username

    # 执行能力：仅已发布团队可执行（执行走已发布快照；草稿/归档
    # 团队返回 False，与 create_team_run 的准入拦截同口径，避免
    # 下游调用方直接信任投影时绕过发布门）
    published = team.status == "published"

    return TeamActionCapabilities(
        team_id=team_id,
        can_view_published=True,
        can_edit_draft=manageable or is_owner,
        can_publish=manageable,
        can_execute=published,
        manageable=manageable,
    )


__all__ = [
    "resolve_team_capabilities",
]
