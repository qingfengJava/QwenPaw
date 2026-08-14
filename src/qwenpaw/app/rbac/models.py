# -*- coding: utf-8 -*-
"""RBAC domain models (M4 milestone).

Permission model (deliberately small): ``permission = resource:action``
(e.g. ``agent:use``, ``kb:write``, ``admin:users``).  A *role* is a named
permission set; a user resolves to roles via the built-in mapping from
``UserRecord.role`` plus explicit entries in ``user_roles`` (grants
managed by platform admins).

Storage follows the same file-backed pattern as ``users.json`` so RBAC
works on the default (json) storage backend; a PostgreSQL implementation
can later slide behind the same store interface.
"""
from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Built-in permissions (resource:action)
# ---------------------------------------------------------------------------

PERM_AGENT_USE = "agent:use"
PERM_AGENT_MANAGE = "agent:manage"
PERM_KB_READ = "kb:read"
PERM_KB_WRITE = "kb:write"
PERM_MODEL_INVOKE = "model:invoke"
PERM_MODEL_MANAGE = "model:manage"
PERM_ADMIN_USERS = "admin:users"
PERM_ADMIN_ROLES = "admin:roles"
PERM_ADMIN_AUDIT = "admin:audit"
PERM_ADMIN_QUOTAS = "admin:quotas"
PERM_ADMIN_KB = "admin:kb"

# XianWork enterprise permissions (org / project / expert publishing).
PERM_ADMIN_ORGS = "admin:orgs"
PERM_ADMIN_EXPERTS = "admin:experts"
PERM_PROJECT_USE = "project:use"
PERM_PROJECT_MANAGE = "project:manage"

#: Wildcard permission held by platform admins.
PERM_ALL = "*"

# ---------------------------------------------------------------------------
# Built-in roles
# ---------------------------------------------------------------------------

ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_TEAM_LEAD = "team_lead"
ROLE_EMPLOYEE = "employee"

#: Mapping from the M1 flat ``UserRecord.role`` onto RBAC roles.  The flat
#: role remains the bootstrap source of truth; explicit ``user_roles``
#: entries in ``rbac.json`` extend (never reduce) it.
FLAT_ROLE_TO_RBAC: Dict[str, List[str]] = {
    "admin": [ROLE_PLATFORM_ADMIN],
    "employee": [ROLE_EMPLOYEE],
}

BUILTIN_ROLE_PERMISSIONS: Dict[str, List[str]] = {
    ROLE_PLATFORM_ADMIN: [PERM_ALL],
    ROLE_TEAM_LEAD: [
        PERM_AGENT_USE,
        PERM_AGENT_MANAGE,
        PERM_KB_READ,
        PERM_KB_WRITE,
        PERM_MODEL_INVOKE,
        PERM_PROJECT_USE,
        PERM_PROJECT_MANAGE,
    ],
    ROLE_EMPLOYEE: [
        PERM_AGENT_USE,
        PERM_KB_READ,
        PERM_MODEL_INVOKE,
        PERM_PROJECT_USE,
    ],
}


class RoleRecord(BaseModel):
    """One named role: a permission set plus metadata."""

    name: str
    permissions: List[str] = Field(default_factory=list)
    builtin: bool = False
    description: str = ""


class TeamRecord(BaseModel):
    """One team: a named group of usernames (M4 management scope)."""

    name: str
    members: List[str] = Field(default_factory=list)
    description: str = ""


class GrantRecord(BaseModel):
    """ACL grant for one resource (agent or model).

    A resource *absent* from the grants table is unrestricted (pre-M4
    behavior); a resource present is restricted to the listed
    roles/users/teams.
    """

    roles: List[str] = Field(default_factory=list)
    users: List[str] = Field(default_factory=list)
    teams: List[str] = Field(default_factory=list)
    description: str = ""


class RbacFile(BaseModel):
    """``rbac.json`` root document.

    ``roles`` holds custom roles; built-in roles are seeded from
    ``BUILTIN_ROLE_PERMISSIONS`` on load and their ``builtin`` flag makes
    them immutable through the admin API.  ``user_roles`` maps a username
    onto extra role names (additive over the flat-role mapping).
    ``agent_grants`` (key: agent_id) and ``model_grants`` (key:
    ``provider:model``) gate access to digital employees and models.
    """

    version: int = 1
    roles: Dict[str, RoleRecord] = Field(default_factory=dict)
    user_roles: Dict[str, List[str]] = Field(default_factory=dict)
    teams: Dict[str, TeamRecord] = Field(default_factory=dict)
    agent_grants: Dict[str, GrantRecord] = Field(default_factory=dict)
    model_grants: Dict[str, GrantRecord] = Field(default_factory=dict)
