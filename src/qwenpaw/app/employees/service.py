# -*- coding: utf-8 -*-
"""数字员工治理服务：校验 → 写权威表 → 投影鉴权面。

治理写入的唯一入口（Controller 只做路由与异常翻译，业务判断集中在此）：

1. 校验目标存在、部门引用有效、部门专属必须有生效部门；
2. 与既有治理行合并（``None`` = 该维度不修改，空串 = 清空归属部门）；
3. 一次批量 upsert 写 ``employee_governance``（权威）；
4. 逐条投影到 RBAC ``agent_grants`` 并镜像 experts 兼容列。

@author qingfeng
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import (
    VISIBILITY_DEPARTMENT,
    VISIBILITY_ORG,
    GovernanceBatchUpdateBody,
    GovernanceRecord,
    GovernanceUpdateBody,
)
from .projection import project, selected_department_ids
from .registry import load_sources, target_of
from .store import get_employee_governance_store

logger = logging.getLogger(__name__)


class EmployeeNotFoundError(Exception):
    """目标员工在任何权威源都不存在（接口层转 404）。"""


class GovernanceValidationError(Exception):
    """治理入参不满足业务规则（接口层转 400）。"""


def _merged_department_id(
    body_department_id: Optional[str],
    current: Optional[GovernanceRecord],
) -> Optional[str]:
    """归属部门合并：``None`` 保持原值，空串表示清空归属。"""
    if body_department_id is None:
        return current.department_id if current else None
    cleaned = body_department_id.strip()
    return cleaned or None


def _merged_granted(
    body_granted: Optional[List[str]],
    current: Optional[GovernanceRecord],
) -> List[str]:
    """授权部门合并：``None`` 保持原值，传 list（含空 list）整体替换。"""
    if body_granted is None:
        return list(current.granted_departments) if current else []
    ordered: List[str] = []
    for item in body_granted:
        cleaned = (item or "").strip()
        if cleaned and cleaned not in ordered:
            ordered.append(cleaned)
    return ordered


class EmployeeGovernanceService:
    """Governance writes, tenant-scoped."""

    async def apply_batch(
        self,
        agent_ids: List[str],
        body: GovernanceUpdateBody,
        actor: str,
        request: Any = None,
    ) -> List[GovernanceRecord]:
        """把同一套治理态套用到多个员工（单条读快照 + 单条批量写）。"""
        sources = await load_sources(request)
        known_departments = {
            item.id for item in sources.departments
        }
        payload: List[Dict[str, Any]] = []

        for agent_id in agent_ids:
            target = target_of(agent_id, sources)
            if not target.get("exists"):
                raise EmployeeNotFoundError(f"数字员工不存在: {agent_id}")
            current = sources.governance.get(agent_id)
            department_id = _merged_department_id(body.department_id, current)
            granted = _merged_granted(body.granted_departments, current)
            # 归属部门与可见范围是两个独立维度：只设归属时可见性保持默认全员共享
            visibility = body.visibility or (
                current.visibility if current else VISIBILITY_ORG
            )
            record = GovernanceRecord(
                agent_id=agent_id,
                entity_kind=target["entity_kind"],
                entity_id=target["entity_id"],
                department_id=department_id,
                visibility=visibility,
                granted_departments=granted,
                owner_id=target.get("owner_id")
                or (current.owner_id if current else None),
                updated_by=actor,
            )
            self._validate(record, known_departments)
            payload.append(
                {
                    "agent_id": record.agent_id,
                    "entity_kind": record.entity_kind,
                    "entity_id": record.entity_id,
                    "department_id": record.department_id,
                    "visibility": record.visibility,
                    "granted_departments": record.granted_departments,
                    "owner_id": record.owner_id,
                    "updated_by": record.updated_by,
                },
            )

        # 先整体校验再落库：任一员工非法即全单拒绝，避免半套治理态
        written = await get_employee_governance_store().batch_upsert(payload)
        # 部门快照一次取回，全循环复用（禁止逐条回查，N+1）
        from ..orgs.service import get_org_service

        departments = await get_org_service().list_departments()
        for record in written:
            # 投影失败必须显式暴露（GrantProjectionError → 503）：
            # 鉴权面与治理面不一致比写入失败更危险
            await project(record, departments=departments)
        return written

    async def apply(
        self,
        agent_id: str,
        body: GovernanceUpdateBody,
        actor: str,
        request: Any = None,
    ) -> GovernanceRecord:
        """写入单个员工的治理态。"""
        records = await self.apply_batch([agent_id], body, actor, request)
        return records[0]

    async def apply_batch_body(
        self,
        body: GovernanceBatchUpdateBody,
        actor: str,
        request: Any = None,
    ) -> List[GovernanceRecord]:
        """批量治理入口（载荷自带员工清单）。"""
        return await self.apply_batch(
            body.agent_ids,
            GovernanceUpdateBody(
                department_id=body.department_id,
                visibility=body.visibility,
                granted_departments=body.granted_departments,
            ),
            actor,
            request,
        )

    @staticmethod
    def _validate(
        record: GovernanceRecord,
        known_departments: set,
    ) -> None:
        """业务规则校验：部门引用必须存在，部门专属必须有生效部门。"""
        referenced = [
            item
            for item in [record.department_id, *record.granted_departments]
            if item
        ]
        unknown = [
            item for item in referenced if item not in known_departments
        ]
        if unknown:
            raise GovernanceValidationError(
                f"部门不存在或已删除: {', '.join(unknown)}",
            )
        if (
            record.visibility == VISIBILITY_DEPARTMENT
            and not selected_department_ids(record)
        ):
            raise GovernanceValidationError(
                "部门专属必须至少指定一个归属部门或授权部门",
            )


_SERVICE: Optional[EmployeeGovernanceService] = None


def get_employee_governance_service() -> EmployeeGovernanceService:
    """Shared governance service instance."""
    global _SERVICE  # pylint: disable=global-statement
    if _SERVICE is None:
        _SERVICE = EmployeeGovernanceService()
    return _SERVICE


__all__ = [
    "EmployeeGovernanceService",
    "EmployeeNotFoundError",
    "GovernanceValidationError",
    "get_employee_governance_service",
]
