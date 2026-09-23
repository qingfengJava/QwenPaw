# -*- coding: utf-8 -*-
"""Permission matching for the M4 RBAC model.

Supported grant shapes inside a role's permission list:

- ``"*"``              — everything (platform admin)
- ``"resource:*"``     — every action on one resource
- ``"resource:action"``— exactly one permission

Matching is pure string logic; empty or malformed entries never match.
"""
from __future__ import annotations

from .models import PERM_ALL


def permission_matches(grant: str, required: str) -> bool:
    """Return True when *grant* covers the *required* permission."""
    if not grant or not required:
        return False
    if grant == PERM_ALL:
        return True
    if grant == required:
        return True
    if grant.endswith(":*"):
        return required.startswith(grant[:-1])
    return False


def has_permission(grants: list[str], required: str) -> bool:
    """Return True when any grant in *grants* covers *required*."""
    return any(permission_matches(grant, required) for grant in grants)
