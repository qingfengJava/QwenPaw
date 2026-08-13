# -*- coding: utf-8 -*-
"""User domain models for multi-user support (M1 milestone)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from pydantic import BaseModel, Field

# Password hashing algorithms recognised by the user store.
PASSWORD_ALGO_SHA256 = "sha256"  # legacy single-user format
PASSWORD_ALGO_ARGON2 = "argon2"  # current default for all new hashes

# Built-in roles. The M4 milestone replaces this flat role field with the
# full RBAC model (roles/permissions/user_roles tables).
ROLE_ADMIN = "admin"
ROLE_EMPLOYEE = "employee"
VALID_ROLES = frozenset({ROLE_ADMIN, ROLE_EMPLOYEE})


class UserRecord(BaseModel):
    """One registered user account.

    ``username`` is the immutable identity anchor: sessions, chats, memory
    and history rows are owner-tagged with it, so it can never be renamed
    once other users exist.
    """

    username: str
    password_hash: str
    password_salt: str = ""  # legacy sha256 salt; empty for argon2 records
    password_algo: str = PASSWORD_ALGO_ARGON2
    role: str = ROLE_EMPLOYEE
    display_name: str = ""
    disabled: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class UsersFile(BaseModel):
    """``users.json`` root document.

    ``identity_bindings`` maps ``"{channel}:{external_user_id}"`` onto a
    registered ``username`` so channel-reported identities (e.g. a DingTalk
    sender id) resolve to exactly one enterprise account.
    """

    version: int = 1
    users: List[UserRecord] = Field(default_factory=list)
    identity_bindings: Dict[str, str] = Field(default_factory=dict)
