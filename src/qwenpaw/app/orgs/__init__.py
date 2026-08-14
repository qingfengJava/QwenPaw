# -*- coding: utf-8 -*-
"""Organization / department domain (XianWork Phase 1).

The org is the tenant boundary; departments form a tree via a
materialized path and are mirrored onto RBAC teams so existing
``agent_grants`` / ``model_grants`` (roles/users/teams) immediately
express department-scoped visibility without a new permission engine.
"""
from .models import DepartmentRecord, DepartmentTree, OrgRecord
from .service import OrgService, get_org_service

__all__ = [
    "DepartmentRecord",
    "DepartmentTree",
    "OrgRecord",
    "OrgService",
    "get_org_service",
]
