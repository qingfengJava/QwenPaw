# -*- coding: utf-8 -*-
"""Org directory for XianWork (read-only user/department lookup).

Backing the project "invite" drawer: employees pick collaborators across
departments, so the plane needs a searchable user directory and the
department tree. No PII beyond username / display name / department.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Request

from ...enterprise import current_tenant_id, require_enterprise_engine
from ...users.store import get_user_store
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/directory", tags=["xian-directory"])


def _viewer(request: Request) -> str:
    return getattr(request.state, "user", None) or "local"


@router.get("/users")
async def list_directory_users(
    request: Request,
    q: str = "",
    department: Optional[str] = None,
    limit: int = 50,
) -> List[dict]:
    """Searchable org member directory (username/display/department).

    ``q`` matches username or display name (case-insensitive substring);
    ``department`` filters by department id. PG carries the department
    relation; the flat account store supplies display names.
    """
    engine = require_enterprise_engine()
    tid = current_tenant_id()
    keyword = (q or "").strip().lower()
    limit = min(max(limit, 1), 200)

    # Department membership per user for this tenant (one query).
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT dm.username, dm.department_id, d.name AS dept_name "
                "FROM department_members dm "
                "LEFT JOIN departments d "
                "ON d.tenant_id = dm.tenant_id AND d.id = dm.department_id "
                "WHERE dm.tenant_id = :tid"
            ),
            {"tid": tid},
        )
        membership: dict[str, dict] = {}
        for row in result:
            membership[row.username] = {
                "department_id": row.department_id,
                "department_name": row.dept_name or "",
            }

    viewer = _viewer(request)
    directory: List[dict] = []
    for user in get_user_store().list_users():
        if user.disabled:
            continue
        info = membership.get(user.username, {})
        if department and info.get("department_id") != department:
            continue
        if keyword and keyword not in (
            f"{user.username} {user.display_name}".lower()
        ):
            continue
        directory.append(
            {
                "username": user.username,
                "display_name": user.display_name or user.username,
                "department_id": info.get("department_id"),
                "department_name": info.get("department_name", ""),
                "role": user.role,
                "is_self": user.username == viewer,
            }
        )
        if len(directory) >= limit:
            break
    directory.sort(key=lambda item: item["username"])
    return directory


@router.get("/departments")
async def list_directory_departments(request: Request) -> List[dict]:
    """Department tree (id/name/parent/member count) for filter picks."""
    from ...orgs.service import get_org_service

    require_enterprise_engine()
    tree = await get_org_service().department_tree()
    return [node.model_dump() for node in tree]
