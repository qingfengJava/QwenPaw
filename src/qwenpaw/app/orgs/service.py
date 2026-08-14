# -*- coding: utf-8 -*-
"""Org / department service: tree maintenance + RBAC team mirroring.

Data access uses the same ``engine.begin()`` + ``text()`` style as the
chats PG repo. Departments mirror onto RBAC teams (``dept:{path}``) so
grants expressed for a team immediately scope visibility by department.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional, Tuple

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from .models import DepartmentRecord, DepartmentTree, OrgRecord

logger = logging.getLogger(__name__)

#: Team name prefix reserved for department mirrors in ``rbac.json``.
DEPT_TEAM_PREFIX = "dept:"

_ORG_COLS = (
    "id, name, slug, plan, status, settings, created_at, updated_at"
)
_DEPT_COLS = "id, parent_id, name, path, description"


def _row_to_org(row) -> OrgRecord:
    return OrgRecord(
        id=row.id,
        name=row.name,
        slug=row.slug,
        plan=row.plan,
        status=row.status,
        settings=row.settings or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_dept(row, member_count: int = 0) -> DepartmentRecord:
    return DepartmentRecord(
        id=row.id,
        parent_id=row.parent_id,
        name=row.name,
        path=row.path,
        description=row.description or "",
        member_count=member_count,
    )


class OrgService:
    """Org/department operations scoped to the current tenant."""

    async def bootstrap_default_org(self) -> None:
        """Ensure the implicit ``default`` org row exists (idempotent).

        Runs during startup bootstrap before the schema-ready flag flips,
        so it must not go through ``require_enterprise_engine`` (which
        would 503 on the not-yet-ready state it is helping to establish).
        """
        from ..enterprise import enterprise_engine

        engine = enterprise_engine()
        if engine is None:
            return
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO orgs (tenant_id, id, name, slug) "
                    "VALUES (:tid, 'default', 'Default Org', 'default') "
                    "ON CONFLICT (tenant_id, id) DO NOTHING"
                ),
                {"tid": "default"},
            )

    # ------------------------------------------------------------------
    # orgs
    # ------------------------------------------------------------------

    async def create_org(
        self,
        name: str,
        slug: str,
        plan: str = "standard",
        settings: Optional[dict] = None,
    ) -> OrgRecord:
        org_id = new_id("org")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO orgs (tenant_id, id, name, slug, plan, "
                    "settings) VALUES (:tid, :id, :name, :slug, :plan, "
                    "CAST(:settings AS JSONB)) RETURNING " + _ORG_COLS
                ),
                {
                    "tid": org_id,
                    "id": org_id,
                    "name": name,
                    "slug": slug,
                    "plan": plan,
                    "settings": json.dumps(settings or {}),
                },
            )
            return _row_to_org(result.one())

    async def list_orgs(self) -> List[OrgRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            # Org management is a platform-admin surface: list across
            # tenants explicitly (the org plane is not per-tenant data).
            result = await conn.execute(
                text(f"SELECT {_ORG_COLS} FROM orgs ORDER BY created_at"),
            )
            return [_row_to_org(r) for r in result]

    async def get_org(self, org_id: str) -> Optional[OrgRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT {_ORG_COLS} FROM orgs "
                    "WHERE tenant_id = :tid AND id = :oid"
                ),
                {"tid": org_id, "oid": org_id},
            )
            row = result.first()
            return _row_to_org(row) if row else None

    # ------------------------------------------------------------------
    # departments
    # ------------------------------------------------------------------

    async def create_department(
        self,
        name: str,
        parent_id: Optional[str] = None,
        description: str = "",
    ) -> DepartmentRecord:
        tid = current_tenant_id()
        dept_id = new_id("dept")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            if parent_id:
                parent = await conn.execute(
                    text(
                        "SELECT path FROM departments "
                        "WHERE tenant_id = :tid AND id = :pid"
                    ),
                    {"tid": tid, "pid": parent_id},
                )
                row = parent.first()
                if row is None:
                    raise ValueError(f"parent department {parent_id} not found")
                path = f"{row.path}/{dept_id}"
            else:
                path = dept_id
            result = await conn.execute(
                text(
                    "INSERT INTO departments (tenant_id, id, parent_id, "
                    "name, path, description) VALUES (:tid, :id, :pid, "
                    ":name, :path, :desc) RETURNING " + _DEPT_COLS
                ),
                {
                    "tid": tid,
                    "id": dept_id,
                    "pid": parent_id,
                    "name": name,
                    "path": path,
                    "desc": description,
                },
            )
            record = _row_to_dept(result.one())
        await self._sync_department_team(record)
        return record

    async def update_department(
        self,
        dept_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> DepartmentRecord:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE departments SET "
                    "name = coalesce(:name, name), "
                    "description = coalesce(:desc, description), "
                    "updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id "
                    "RETURNING " + _DEPT_COLS
                ),
                {"name": name, "desc": description, "tid": tid, "id": dept_id},
            )
            row = result.first()
            if row is None:
                return None
            record = _row_to_dept(row)
        await self._sync_department_team(record)
        return record

    async def delete_department(self, dept_id: str) -> bool:
        """Delete a department; refuses when children or members exist."""
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        dept_path: Optional[str] = None
        async with engine.begin() as conn:
            current = await conn.execute(
                text(
                    "SELECT path FROM departments "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": tid, "id": dept_id},
            )
            row = current.first()
            if row is None:
                return False
            dept_path = row.path
            children = await conn.execute(
                text(
                    "SELECT 1 FROM departments "
                    "WHERE tenant_id = :tid AND parent_id = :id LIMIT 1"
                ),
                {"tid": tid, "id": dept_id},
            )
            if children.first() is not None:
                raise ValueError("department has child departments")
            members = await conn.execute(
                text(
                    "SELECT username FROM department_members "
                    "WHERE tenant_id = :tid AND department_id = :id"
                ),
                {"tid": tid, "id": dept_id},
            )
            member_names = [r.username for r in members]
            if member_names:
                raise ValueError("department still has members")
            result = await conn.execute(
                text(
                    "DELETE FROM departments "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": tid, "id": dept_id},
            )
            deleted = result.rowcount > 0
        if deleted and dept_path:
            try:
                from ..rbac.store import get_rbac_store

                get_rbac_store().delete_team(DEPT_TEAM_PREFIX + dept_path)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "dept team cleanup failed for %s", dept_id, exc_info=True
                )
        return deleted

    async def list_departments(self) -> List[DepartmentRecord]:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT {_DEPT_COLS} FROM departments "
                    "WHERE tenant_id = :tid ORDER BY path"
                ),
                {"tid": tid},
            )
            counts = await self._member_counts(conn, tid)
            return [_row_to_dept(r, counts.get(r.id, 0)) for r in result]

    async def department_tree(self) -> List[DepartmentTree]:
        records = await self.list_departments()
        nodes = {
            r.id: DepartmentTree(
                id=r.id,
                parent_id=r.parent_id,
                name=r.name,
                path=r.path,
                description=r.description,
            )
            for r in records
        }
        roots: List[DepartmentTree] = []
        for record in records:
            node = nodes[record.id]
            if record.parent_id and record.parent_id in nodes:
                nodes[record.parent_id].children.append(node)
            else:
                roots.append(node)
        return roots

    # ------------------------------------------------------------------
    # membership (users live in users.json; membership is a PG mapping so
    # it can be filtered/joined like the rest of the enterprise plane)
    # ------------------------------------------------------------------

    async def assign_member(self, dept_id: str, username: str) -> bool:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            exists = await conn.execute(
                text(
                    "SELECT 1 FROM departments "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": tid, "id": dept_id},
            )
            if exists.first() is None:
                return False
            await conn.execute(
                text(
                    "INSERT INTO department_members (tenant_id, "
                    "department_id, username) VALUES (:tid, :did, :user) "
                    "ON CONFLICT (tenant_id, department_id, username) "
                    "DO NOTHING"
                ),
                {"tid": tid, "did": dept_id, "user": username},
            )
        await self._sync_department_team_by_id(dept_id)
        return True

    async def remove_member(self, dept_id: str, username: str) -> bool:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM department_members "
                    "WHERE tenant_id = :tid AND department_id = :did "
                    "AND username = :user"
                ),
                {"tid": tid, "did": dept_id, "user": username},
            )
            removed = result.rowcount > 0
        if removed:
            await self._sync_department_team_by_id(dept_id)
        return removed

    async def department_members(self, dept_id: str) -> List[str]:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT username FROM department_members "
                    "WHERE tenant_id = :tid AND department_id = :did "
                    "ORDER BY username"
                ),
                {"tid": tid, "did": dept_id},
            )
            return [r.username for r in result]

    async def resolve_user_scope(
        self,
        username: str,
    ) -> Tuple[str, Optional[str]]:
        """Return ``(org_id, department_path)`` for one user."""
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT d.path FROM department_members m "
                    "JOIN departments d "
                    "ON d.tenant_id = m.tenant_id "
                    "AND d.id = m.department_id "
                    "WHERE m.tenant_id = :tid AND m.username = :user "
                    "LIMIT 1"
                ),
                {"tid": tid, "user": username},
            )
            row = result.first()
            return (tid, row.path if row else None)

    # ------------------------------------------------------------------
    # RBAC team mirroring
    # ------------------------------------------------------------------

    async def _member_counts(self, conn, tid: str) -> dict:
        result = await conn.execute(
            text(
                "SELECT department_id, count(*) AS n "
                "FROM department_members WHERE tenant_id = :tid "
                "GROUP BY department_id"
            ),
            {"tid": tid},
        )
        return {r.department_id: r.n for r in result}

    async def _sync_department_team_by_id(self, dept_id: str) -> None:
        records = await self.list_departments()
        match = next((r for r in records if r.id == dept_id), None)
        if match:
            await self._sync_department_team(match)

    async def _sync_department_team(self, record: DepartmentRecord) -> None:
        """Mirror one department onto its RBAC team (``dept:{path}``)."""
        try:
            from ..rbac.store import get_rbac_store

            members = await self.department_members(record.id)
            get_rbac_store().upsert_team(
                DEPT_TEAM_PREFIX + record.path,
                members,
                description=f"department mirror: {record.name}",
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "dept team sync failed for %s", record.id, exc_info=True
            )


_service: Optional[OrgService] = None


def get_org_service() -> OrgService:
    """Process-wide singleton (stateless; engine is shared per DSN)."""
    global _service  # pylint: disable=global-statement
    if _service is None:
        _service = OrgService()
    return _service
