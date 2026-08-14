# -*- coding: utf-8 -*-
"""Admin API routers (M4): user/role/team/audit management.

Physically separated from the employee-facing routers so the split is
visible in the tree; every route carries a ``require_perm`` dependency
that is inert until ``QWENPAW_RBAC_ENFORCE`` is switched on.
"""
from fastapi import APIRouter

from ...orgs.api import router as orgs_router
from .audit import router as audit_router
from .expert_teams import router as expert_teams_router
from .experts import router as experts_router
from .grants import router as grants_router
from .kb import router as kb_router
from .quotas import router as quotas_router
from .roles import router as roles_router
from .teams import router as teams_router
from .users import router as users_router

router = APIRouter(prefix="/admin")
router.include_router(users_router)
router.include_router(roles_router)
router.include_router(teams_router)
router.include_router(audit_router)
router.include_router(quotas_router)
router.include_router(grants_router)
router.include_router(kb_router)
router.include_router(orgs_router)
router.include_router(experts_router)
router.include_router(expert_teams_router)

__all__ = ["router"]
