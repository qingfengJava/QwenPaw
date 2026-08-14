# -*- coding: utf-8 -*-
"""Admin organization/department management API (XianWork Phase 1).

Mounted under ``/api/admin`` next to the M4 admin routers. Every route
carries ``require_perm("admin:orgs")`` — inert until enforcement is on.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..rbac import PERM_ADMIN_ORGS, require_perm
from .models import (
    DepartmentCreateBody,
    DepartmentTree,
    DepartmentUpdateBody,
    OrgCreateBody,
    OrgRecord,
)
from .service import get_org_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/orgs",
    tags=["admin-orgs"],
    dependencies=[Depends(require_perm(PERM_ADMIN_ORGS))],
)


@router.get("", response_model=list[OrgRecord])
async def list_orgs() -> list[OrgRecord]:
    """List every organization (platform-admin surface)."""
    return await get_org_service().list_orgs()


@router.post("", status_code=201, response_model=OrgRecord)
async def create_org(body: OrgCreateBody) -> OrgRecord:
    """Create an organization (its id becomes the tenant id)."""
    return await get_org_service().create_org(
        name=body.name,
        slug=body.slug,
        plan=body.plan,
        settings=body.settings,
    )


@router.get("/departments", response_model=list[DepartmentTree])
async def department_tree() -> list[DepartmentTree]:
    """The department tree of the current tenant."""
    return await get_org_service().department_tree()


@router.post("/departments", status_code=201)
async def create_department(body: DepartmentCreateBody) -> dict:
    """Create a department under ``parent_id`` (root when omitted)."""
    try:
        record = await get_org_service().create_department(
            name=body.name,
            parent_id=body.parent_id,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": record.id, "path": record.path}


@router.patch("/departments/{dept_id}")
async def update_department(
    dept_id: str,
    body: DepartmentUpdateBody,
) -> dict:
    """Rename a department or update its description."""
    record = await get_org_service().update_department(
        dept_id,
        name=body.name,
        description=body.description,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Department not found")
    return {"ok": True}


@router.delete("/departments/{dept_id}", status_code=204)
async def delete_department(dept_id: str) -> None:
    """Delete an empty department (no children, no members)."""
    try:
        if not await get_org_service().delete_department(dept_id):
            raise HTTPException(
                status_code=404,
                detail="Department not found",
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/departments/{dept_id}/members")
async def department_members(dept_id: str) -> dict:
    """Usernames assigned to one department."""
    return {
        "department_id": dept_id,
        "members": await get_org_service().department_members(dept_id),
    }


@router.post("/departments/{dept_id}/members", status_code=204)
async def assign_member(dept_id: str, body: dict) -> None:
    """Assign a user to a department (mirrors onto the RBAC team)."""
    username = (body or {}).get("username", "")
    if not username:
        raise HTTPException(status_code=400, detail="username required")
    if not await get_org_service().assign_member(dept_id, username):
        raise HTTPException(status_code=404, detail="Department not found")


@router.delete(
    "/departments/{dept_id}/members/{username}",
    status_code=204,
)
async def remove_member(dept_id: str, username: str) -> None:
    """Remove a user from a department."""
    await get_org_service().remove_member(dept_id, username)
