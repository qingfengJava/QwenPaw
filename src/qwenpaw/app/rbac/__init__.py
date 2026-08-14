# -*- coding: utf-8 -*-
"""Role-based access control (M4 milestone).

Public surface:

- :func:`require_perm` — FastAPI route dependency (gray-gated by
  ``QWENPAW_RBAC_ENFORCE``);
- :class:`RbacStore` / :func:`get_rbac_store` — roles, user grants,
  teams registry;
- permission/role name constants.
"""
from .deps import RBAC_ENFORCE_ENV, rbac_enforcement_enabled, require_perm
from .models import (
    PERM_ADMIN_AUDIT,
    PERM_ADMIN_EXPERTS,
    PERM_ADMIN_KB,
    PERM_ADMIN_ORGS,
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
    PERM_PROJECT_MANAGE,
    PERM_PROJECT_USE,
    ROLE_EMPLOYEE,
    ROLE_PLATFORM_ADMIN,
    ROLE_TEAM_LEAD,
    RbacFile,
    RoleRecord,
    TeamRecord,
)
from .permissions import has_permission, permission_matches
from .store import RbacStore, get_rbac_store, reset_rbac_store

__all__ = [
    "RBAC_ENFORCE_ENV",
    "PERM_ADMIN_AUDIT",
    "PERM_ADMIN_EXPERTS",
    "PERM_ADMIN_KB",
    "PERM_ADMIN_ORGS",
    "PERM_ADMIN_QUOTAS",
    "PERM_ADMIN_ROLES",
    "PERM_ADMIN_USERS",
    "PERM_AGENT_MANAGE",
    "PERM_AGENT_USE",
    "PERM_ALL",
    "PERM_KB_READ",
    "PERM_KB_WRITE",
    "PERM_MODEL_INVOKE",
    "PERM_MODEL_MANAGE",
    "PERM_PROJECT_MANAGE",
    "PERM_PROJECT_USE",
    "ROLE_EMPLOYEE",
    "ROLE_PLATFORM_ADMIN",
    "ROLE_TEAM_LEAD",
    "RbacFile",
    "RbacStore",
    "RoleRecord",
    "TeamRecord",
    "get_rbac_store",
    "has_permission",
    "permission_matches",
    "rbac_enforcement_enabled",
    "require_perm",
    "reset_rbac_store",
]
