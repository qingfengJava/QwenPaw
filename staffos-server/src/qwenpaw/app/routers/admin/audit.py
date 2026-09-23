# -*- coding: utf-8 -*-
"""Admin audit query API (M4)."""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ....governance.audit import AuditLog
from ...rbac import PERM_ADMIN_AUDIT, is_platform_admin, require_perm
from ...rbac.deps import _resolve_username

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/audit",
    tags=["admin-audit"],
    dependencies=[Depends(require_perm(PERM_ADMIN_AUDIT))],
)


class AuditEventView(BaseModel):
    ts: int
    workspace_dir: str
    agent_id: str
    session_id: str
    tool_name: str
    target: str
    decision: str
    reason: str = ""
    actor_id: str = ""


class AuditPage(BaseModel):
    events: List[AuditEventView] = Field(default_factory=list)
    total: int = 0


@router.get("", response_model=AuditPage)
async def query_audit(
    request: Request,
    workspace_dir: Optional[str] = None,
    agent_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    decision: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
) -> AuditPage:
    """Query the governance audit log (newest first, paginated).

    数据权限（M5+，resource=``audit``）：平台管理员查看全部审计日志；其他
    角色仅能查看与自己相关的条目（``actor_id`` 匹配当前用户名），避免越权
    窥探他人操作轨迹。审计后端不支持按 actor 下推 WHERE，故在分页结果上做
    内存收敛；任何异常都优雅降级回未过滤结果，绝不阻断查询。
    """
    rows, total = AuditLog.get_instance().query(
        workspace_dir=workspace_dir,
        agent_id=agent_id,
        tool_name=tool_name,
        decision=decision,
        since=since,
        until=until,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
    events = [
        AuditEventView(
            ts=row.ts,
            workspace_dir=row.workspace_dir,
            agent_id=row.agent_id,
            session_id=row.session_id,
            tool_name=row.tool_name,
            target=row.target,
            decision=row.decision,
            reason=row.reason,
            actor_id=row.actor_id,
        )
        for row in rows
    ]
    events, total = _apply_audit_data_scope(request, events, total)
    return AuditPage(events=events, total=total)


def _apply_audit_data_scope(
    request: Request,
    events: List[AuditEventView],
    total: int,
):
    """审计日志数据范围收敛：平台管理员全量，其余仅本人相关。

    非平台管理员按 ``actor_id == username`` 过滤（``self`` 语义，owner 字段
    即 ``actor_id``）；因过滤发生在分页之后，返回的 ``total`` 收敛为当前页
    命中数，避免向非管理员泄露全局审计条数。异常时回落未过滤结果。
    """
    try:
        username = _resolve_username(request)
        if not username or is_platform_admin(username):
            return events, total
        from ...rbac.data_scope import SCOPE_SELF, DataScopeFilter
        from ...rbac.models import DataScopeRecord

        # 非平台管理员统一收敛为「仅本人」：即便角色被误配了更宽的 audit
        # 数据范围，也不放开他人审计（审计面越权风险高于可用性）。
        scope = DataScopeFilter.resolve_scope(username, "audit")
        if getattr(scope, "scope_type", "") != SCOPE_SELF:
            scope = DataScopeRecord(
                id="", role_id="", resource="audit", scope_type=SCOPE_SELF,
            )
        filtered = DataScopeFilter.apply_to_list(
            events,
            scope,
            username,
            user_dept_id=None,
            dept_id_field="actor_id",
            owner_field="actor_id",
        )
        return filtered, len(filtered)
    except Exception:  # pylint: disable=broad-except
        logger.debug("audit data-scope filter skipped", exc_info=True)
        return events, total
