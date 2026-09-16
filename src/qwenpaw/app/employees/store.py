# -*- coding: utf-8 -*-
"""PG persistence for the digital-employee governance plane.

``employee_governance`` 是「归属部门 + 可见范围」的唯一权威表，按运行时
``agent_id`` 主键治理，覆盖 agent / expert / team / workflow 四种形态。
写路径只有本 Store（经 :mod:`.projection` 同步投影到 RBAC），其余模块
一律只读，保证不存在第二份治理副本。

@author qingfeng
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, require_enterprise_engine
from .models import (
    EMPLOYEE_KIND_AGENT,
    VISIBILITY_ORG,
    GovernanceRecord,
)

logger = logging.getLogger(__name__)

_COLS = (
    "agent_id, entity_kind, entity_id, department_id, visibility, "
    "granted_departments, owner_id, updated_by, created_at, updated_at"
)


def _row_to_governance(row) -> GovernanceRecord:
    """Map one ``employee_governance`` row to :class:`GovernanceRecord`."""
    return GovernanceRecord(
        agent_id=row.agent_id,
        entity_kind=row.entity_kind or EMPLOYEE_KIND_AGENT,
        entity_id=row.entity_id or "",
        department_id=row.department_id,
        visibility=row.visibility or VISIBILITY_ORG,
        granted_departments=list(row.granted_departments or []),
        owner_id=row.owner_id,
        updated_by=row.updated_by or "",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class EmployeeGovernanceStore:
    """CRUD over ``employee_governance``, tenant-scoped."""

    async def get(self, agent_id: str) -> Optional[GovernanceRecord]:
        """读取一个员工的治理行（无行 = 未归属 + 全员共享）。"""
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT {_COLS} FROM employee_governance "
                    "WHERE tenant_id = :tid AND agent_id = :agent"
                ),
                {"tid": current_tenant_id(), "agent": agent_id},
            )
            row = result.first()
            return _row_to_governance(row) if row else None

    async def list_all(self) -> List[GovernanceRecord]:
        """全量治理行（单租户一页拿完，注册表侧内存建索引）。"""
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT {_COLS} FROM employee_governance "
                    "WHERE tenant_id = :tid ORDER BY agent_id"
                ),
                {"tid": current_tenant_id()},
            )
            return [_row_to_governance(row) for row in result]

    async def batch_upsert(
        self,
        rows: List[Dict[str, Any]],
    ) -> List[GovernanceRecord]:
        """一条语句批量 upsert 治理行（禁止逐条写）。

        ``rows`` 每项键：``agent_id`` / ``entity_kind`` / ``entity_id`` /
        ``department_id`` / ``visibility`` / ``granted_departments`` /
        ``owner_id`` / ``updated_by``。
        """
        if not rows:
            return []
        payload = [
            {
                "agent_id": row["agent_id"],
                "entity_kind": row.get("entity_kind") or EMPLOYEE_KIND_AGENT,
                "entity_id": row.get("entity_id") or "",
                "department_id": row.get("department_id"),
                "visibility": row.get("visibility") or VISIBILITY_ORG,
                "granted_departments": list(
                    row.get("granted_departments") or [],
                ),
                "owner_id": row.get("owner_id"),
                "updated_by": row.get("updated_by") or "",
            }
            for row in rows
        ]
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO employee_governance ("
                    "tenant_id, agent_id, entity_kind, entity_id, "
                    "department_id, visibility, granted_departments, "
                    "owner_id, updated_by) "
                    "SELECT :tid, x.agent_id, x.entity_kind, x.entity_id, "
                    "x.department_id, x.visibility, x.granted_departments, "
                    "x.owner_id, x.updated_by "
                    "FROM jsonb_to_recordset(CAST(:rows AS JSONB)) AS x("
                    "agent_id text, entity_kind text, entity_id text, "
                    "department_id text, visibility text, "
                    "granted_departments jsonb, owner_id text, "
                    "updated_by text) "
                    "ON CONFLICT (tenant_id, agent_id) DO UPDATE SET "
                    "entity_kind = EXCLUDED.entity_kind, "
                    "entity_id = EXCLUDED.entity_id, "
                    "department_id = EXCLUDED.department_id, "
                    "visibility = EXCLUDED.visibility, "
                    "granted_departments = EXCLUDED.granted_departments, "
                    "owner_id = EXCLUDED.owner_id, "
                    "updated_by = EXCLUDED.updated_by, "
                    "updated_at = now() "
                    "RETURNING " + _COLS
                ),
                {"tid": current_tenant_id(), "rows": json.dumps(payload)},
            )
            return [_row_to_governance(row) for row in result]

    async def upsert(
        self,
        agent_id: str,
        entity_kind: str,
        entity_id: str,
        department_id: Optional[str],
        visibility: str,
        granted_departments: List[str],
        owner_id: Optional[str],
        updated_by: str,
    ) -> GovernanceRecord:
        """写入（或覆盖）单个员工的治理行。"""
        records = await self.batch_upsert(
            [
                {
                    "agent_id": agent_id,
                    "entity_kind": entity_kind,
                    "entity_id": entity_id,
                    "department_id": department_id,
                    "visibility": visibility,
                    "granted_departments": granted_departments,
                    "owner_id": owner_id,
                    "updated_by": updated_by,
                },
            ],
        )
        return records[0]


_STORE: Optional[EmployeeGovernanceStore] = None


def get_employee_governance_store() -> EmployeeGovernanceStore:
    """Shared store instance (stateless; engine resolved per call)."""
    global _STORE  # pylint: disable=global-statement
    if _STORE is None:
        _STORE = EmployeeGovernanceStore()
    return _STORE
