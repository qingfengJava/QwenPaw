# -*- coding: utf-8 -*-
"""RBAC store (``rbac.json`` in ``SECRET_DIR``).

File-backed to match the M1 user store: the management-plane dataset is
tiny (a handful of roles and grants), so the JSON document with an
mtime-keyed read cache is sufficient and keeps RBAC available on the
default (json) storage backend.

Consistency model mirrors :class:`qwenpaw.app.users.store.UserStore`:
single-process writer, ``threading.Lock`` around read-modify-write, and
fail-closed semantics — an unreadable ``rbac.json`` resolves every
permission check to *deny* (except the bootstrap flat-admin mapping,
which is always honored so operators can never lock themselves out).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import List, Optional

from ...constant import SECRET_DIR
from .models import (
    BUILTIN_ROLE_PERMISSIONS,
    FLAT_ROLE_TO_RBAC,
    RbacFile,
    RoleRecord,
    TeamRecord,
)
from .permissions import has_permission

logger = logging.getLogger(__name__)

RBAC_FILE = SECRET_DIR / "rbac.json"


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _prepare_secret_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(path.parent, 0o700)


class RbacStore:
    """File-backed RBAC registry: roles, user role grants, teams."""

    def __init__(self, path: Path | str = RBAC_FILE) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._load_error = False
        self._cache_valid = False
        self._cache_key: Optional[int] = None
        self._cache_data: Optional[RbacFile] = None

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self) -> RbacFile:
        """Load ``rbac.json``; fail closed on read/parse errors.

        Cached by ``st_mtime_ns`` like the user store; built-in roles are
        merged into the returned document so custom files cannot remove
        or weaken them.
        """
        try:
            cache_key: Optional[int] = self._path.stat().st_mtime_ns
        except OSError:
            cache_key = None
        if self._cache_valid and cache_key == self._cache_key:
            return self._cache_data  # type: ignore[return-value]

        data = RbacFile()
        if self._path.is_file():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    data = RbacFile.model_validate(json.load(fh))
                self._load_error = False
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.error(
                    "Failed to load rbac file %s: %s",
                    self._path,
                    exc,
                )
                self._load_error = True
                # Do not cache failures; the next call retries the read.
                return RbacFile()
        else:
            self._load_error = False

        self._seed_builtin_roles(data)
        self._cache_valid = True
        self._cache_key, self._cache_data = cache_key, data
        return data

    @staticmethod
    def _seed_builtin_roles(data: RbacFile) -> None:
        """Force built-in roles to their canonical permission sets."""
        for name, permissions in BUILTIN_ROLE_PERMISSIONS.items():
            data.roles[name] = RoleRecord(
                name=name,
                permissions=list(permissions),
                builtin=True,
                description="built-in role",
            )

    def _save(self, data: RbacFile) -> None:
        """Write ``rbac.json`` with restrictive permissions."""
        _prepare_secret_parent(self._path)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(
                data.model_dump(mode="json"),
                fh,
                indent=2,
                ensure_ascii=False,
            )
        _chmod_best_effort(self._path, 0o600)
        try:
            self._cache_key = self._path.stat().st_mtime_ns
        except OSError:
            self._cache_key = None
        self._cache_data = data
        self._cache_valid = True

    # ------------------------------------------------------------------
    # role queries
    # ------------------------------------------------------------------

    def list_roles(self) -> List[RoleRecord]:
        return list(self._load().roles.values())

    def get_role(self, name: str) -> Optional[RoleRecord]:
        return self._load().roles.get(name)

    def roles_for_user(self, username: str, flat_role: str = "") -> List[str]:
        """Resolve one user's RBAC role names.

        The flat M1 role mapping is always applied (bootstrap guarantee);
        explicit grants in ``user_roles`` extend it.  Unknown role names
        are dropped.
        """
        data = self._load()
        names: list[str] = list(FLAT_ROLE_TO_RBAC.get(flat_role, ()))
        for name in data.user_roles.get(username, ()):
            if name in data.roles and name not in names:
                names.append(name)
        return names

    def permissions_for_user(
        self,
        username: str,
        flat_role: str = "",
    ) -> List[str]:
        """Resolve the union of one user's role permissions."""
        data = self._load()
        grants: list[str] = []
        for role_name in self.roles_for_user(username, flat_role):
            role = data.roles.get(role_name)
            if role is None:
                continue
            for permission in role.permissions:
                if permission not in grants:
                    grants.append(permission)
        return grants

    def user_has_permission(
        self,
        username: str,
        required: str,
        flat_role: str = "",
    ) -> bool:
        """Permission check; fail closed when the store is unreadable."""
        if self._load_error:
            # Fail closed except for the bootstrap guarantee: a flat admin
            # keeps full access so a corrupt rbac.json cannot lock
            # operators out of the admin API that would repair it.
            return flat_role == "admin"
        grants = self.permissions_for_user(username, flat_role)
        return has_permission(grants, required)

    # ------------------------------------------------------------------
    # role management (admin API surface)
    # ------------------------------------------------------------------

    def upsert_role(
        self,
        name: str,
        permissions: List[str],
        description: str = "",
    ) -> Optional[RoleRecord]:
        """Create or replace a custom role. Built-in roles are immutable."""
        name = name.strip()
        if not name:
            return None
        with self._lock:
            data = self._load()
            if self._load_error:
                return None
            existing = data.roles.get(name)
            if existing is not None and existing.builtin:
                logger.warning("Refusing to modify built-in role '%s'", name)
                return None
            record = RoleRecord(
                name=name,
                permissions=list(dict.fromkeys(permissions)),
                builtin=False,
                description=description.strip(),
            )
            data.roles[name] = record
            self._save(data)
        return record

    def delete_role(self, name: str) -> bool:
        """Delete a custom role and strip it from all user grants."""
        with self._lock:
            data = self._load()
            if self._load_error:
                return False
            role = data.roles.get(name)
            if role is None or role.builtin:
                return False
            del data.roles[name]
            for username, names in list(data.user_roles.items()):
                if name in names:
                    data.user_roles[username] = [
                        n for n in names if n != name
                    ]
            self._save(data)
        return True

    def grant_role(self, username: str, role_name: str) -> bool:
        """Additively grant *role_name* to *username*."""
        if not username or not role_name:
            return False
        with self._lock:
            data = self._load()
            if self._load_error:
                return False
            if role_name not in data.roles:
                return False
            names = data.user_roles.setdefault(username, [])
            if role_name not in names:
                names.append(role_name)
            self._save(data)
        return True

    def revoke_role(self, username: str, role_name: str) -> bool:
        """Remove one explicit grant. Returns True when it existed."""
        with self._lock:
            data = self._load()
            if self._load_error:
                return False
            names = data.user_roles.get(username)
            if not names or role_name not in names:
                return False
            names.remove(role_name)
            if not names:
                del data.user_roles[username]
            self._save(data)
        return True

    # ------------------------------------------------------------------
    # teams
    # ------------------------------------------------------------------

    def upsert_team(
        self,
        name: str,
        members: List[str],
        description: str = "",
    ) -> Optional[TeamRecord]:
        name = name.strip()
        if not name:
            return None
        with self._lock:
            data = self._load()
            if self._load_error:
                return None
            record = TeamRecord(
                name=name,
                members=list(dict.fromkeys(members)),
                description=description.strip(),
            )
            data.teams[name] = record
            self._save(data)
        return record

    def get_team(self, name: str) -> Optional[TeamRecord]:
        return self._load().teams.get(name)

    def list_teams(self) -> List[TeamRecord]:
        return list(self._load().teams.values())

    def delete_team(self, name: str) -> bool:
        with self._lock:
            data = self._load()
            if self._load_error or name not in data.teams:
                return False
            del data.teams[name]
            self._save(data)
        return True

    def teams_for_user(self, username: str) -> List[str]:
        """Names of teams that include *username*."""
        data = self._load()
        return [
            name
            for name, team in data.teams.items()
            if username in team.members
        ]


_default_store: Optional[RbacStore] = None


def get_rbac_store() -> RbacStore:
    """Return the process-wide default RBAC store (lazy singleton)."""
    global _default_store  # noqa: PLW0603
    if _default_store is None:
        _default_store = RbacStore()
    return _default_store


def reset_rbac_store() -> None:
    """Drop the singleton (tests)."""
    global _default_store  # noqa: PLW0603
    _default_store = None
