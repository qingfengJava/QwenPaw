# -*- coding: utf-8 -*-
"""Multi-user account store (``users.json`` in ``SECRET_DIR``).

M1 milestone: file-backed user registry replacing the single-user record in
``auth.json``. The store stays file-backed to match the M1 "isolate first,
database later" staging; the M2 milestone migrates it to PostgreSQL behind
this same class interface.

Security properties preserved from the legacy auth module:

- fail closed: an unreadable/corrupt ``users.json`` makes every
  verification return ``None`` instead of silently bypassing auth;
- the file is written with ``0o600`` permissions under ``SECRET_DIR``;
- legacy salted-SHA256 hashes keep working and are transparently re-hashed
  to argon2id on the next successful login.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerificationError

from ...constant import SECRET_DIR
from .models import (
    PASSWORD_ALGO_ARGON2,
    PASSWORD_ALGO_SHA256,
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    VALID_ROLES,
    UserRecord,
    UsersFile,
)

logger = logging.getLogger(__name__)

USERS_FILE = SECRET_DIR / "users.json"

# Argon2id hasher with library-default parameters (OWASP-recommended).
_password_hasher = PasswordHasher()


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _prepare_secret_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(path.parent, 0o700)


def _hash_password_argon2(password: str) -> str:
    """Hash *password* with argon2id (salt embedded in the encoded hash)."""
    return _password_hasher.hash(password)


def _verify_argon2(password: str, encoded: str) -> bool:
    try:
        return _password_hasher.verify(encoded, password)
    except (VerificationError, Argon2Error):
        # Wrong password, malformed hash, or backend failure — all deny.
        return False


def _verify_sha256(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a legacy salted-SHA256 password from the single-user era."""
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, stored_hash)


class UserStore:
    """File-backed multi-user registry with argon2id password hashing."""

    def __init__(self, path: Path | str = USERS_FILE) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        # Flipped when the file exists but cannot be read/parsed: every
        # verification then fails closed.
        self._load_error = False

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self) -> UsersFile:
        """Load ``users.json``; fail closed on read/parse errors."""
        if not self._path.is_file():
            self._load_error = False
            return UsersFile()
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = UsersFile.model_validate(json.load(fh))
            self._load_error = False
            return data
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.error("Failed to load users file %s: %s", self._path, exc)
            self._load_error = True
            return UsersFile()

    def _save(self, data: UsersFile) -> None:
        """Write ``users.json`` with restrictive permissions."""
        _prepare_secret_parent(self._path)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(
                data.model_dump(mode="json"),
                fh,
                indent=2,
                ensure_ascii=False,
            )
        _chmod_best_effort(self._path, 0o600)

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def has_users(self) -> bool:
        return bool(self._load().users)

    def get_user(self, username: str) -> Optional[UserRecord]:
        for user in self._load().users:
            if user.username == username:
                return user
        return None

    def list_users(self) -> list[UserRecord]:
        return list(self._load().users)

    def is_active(self, username: str) -> bool:
        """True when the user exists and is not disabled.

        Returns False when the store is in fail-closed state.
        """
        if self._load_error:
            return False
        user = self.get_user(username)
        return user is not None and not user.disabled

    # ------------------------------------------------------------------
    # account management
    # ------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password: str,
        *,
        role: str = ROLE_EMPLOYEE,
        display_name: str = "",
    ) -> Optional[UserRecord]:
        """Create a user. The very first account is always an admin."""
        username = username.strip()
        if not username or not password:
            return None
        with self._lock:
            data = self._load()
            if self._load_error:
                return None
            if any(u.username == username for u in data.users):
                logger.warning("Refusing to create duplicate user '%s'", username)
                return None
            effective_role = (
                ROLE_ADMIN if not data.users else (role or ROLE_EMPLOYEE)
            )
            if effective_role not in VALID_ROLES:
                effective_role = ROLE_EMPLOYEE
            record = UserRecord(
                username=username,
                password_hash=_hash_password_argon2(password),
                password_algo=PASSWORD_ALGO_ARGON2,
                role=effective_role,
                display_name=display_name.strip(),
            )
            data.users.append(record)
            self._save(data)
        logger.info("User '%s' created with role '%s'", username, effective_role)
        return record

    def import_legacy_user(self, legacy: dict) -> Optional[UserRecord]:
        """Import the single-user record from legacy ``auth.json``.

        The legacy salted-SHA256 hash is preserved as-is; it is upgraded to
        argon2id on the user's next successful login (see
        :meth:`verify_password`). The imported account becomes the first
        admin.
        """
        username = str(legacy.get("username", "")).strip()
        password_hash = str(legacy.get("password_hash", ""))
        password_salt = str(legacy.get("password_salt", ""))
        if not username or not password_hash or not password_salt:
            logger.error("Legacy auth user record is incomplete; not migrated")
            return None
        with self._lock:
            data = self._load()
            if self._load_error:
                return None
            if any(u.username == username for u in data.users):
                return self.get_user(username)
            record = UserRecord(
                username=username,
                password_hash=password_hash,
                password_salt=password_salt,
                password_algo=PASSWORD_ALGO_SHA256,
                role=ROLE_ADMIN,
            )
            data.users.append(record)
            self._save(data)
        logger.info(
            "Imported legacy auth.json user '%s' as admin (sha256 pending "
            "upgrade on next login)",
            username,
        )
        return record

    def verify_password(
        self,
        username: str,
        password: str,
    ) -> Optional[UserRecord]:
        """Verify credentials; upgrade legacy hashes transparently.

        Returns the user record on success, ``None`` on any failure
        (unknown user, wrong password, disabled account, store error).
        """
        with self._lock:
            data = self._load()
            if self._load_error:
                return None
            user = next(
                (u for u in data.users if u.username == username),
                None,
            )
            if user is None or user.disabled:
                return None

            if user.password_algo == PASSWORD_ALGO_ARGON2:
                if not _verify_argon2(password, user.password_hash):
                    return None
                # Re-hash when the library's default parameters changed.
                if _password_hasher.check_needs_rehash(user.password_hash):
                    user.password_hash = _hash_password_argon2(password)
                    self._save(data)
                return user

            # Legacy salted-SHA256 path: verify, then upgrade to argon2id.
            if not _verify_sha256(
                password,
                user.password_hash,
                user.password_salt,
            ):
                return None
            user.password_hash = _hash_password_argon2(password)
            user.password_salt = ""
            user.password_algo = PASSWORD_ALGO_ARGON2
            self._save(data)
            logger.info(
                "Upgraded password hash for user '%s' to argon2id",
                username,
            )
            return user

    def update_password(self, username: str, new_password: str) -> bool:
        """Set a new argon2id password hash for *username*."""
        if not new_password:
            return False
        with self._lock:
            data = self._load()
            if self._load_error:
                return False
            user = next(
                (u for u in data.users if u.username == username),
                None,
            )
            if user is None:
                return False
            user.password_hash = _hash_password_argon2(new_password)
            user.password_salt = ""
            user.password_algo = PASSWORD_ALGO_ARGON2
            self._save(data)
        logger.info("Password updated for user '%s'", username)
        return True

    def set_disabled(self, username: str, disabled: bool) -> bool:
        """Enable/disable an account. Disabled users fail verification."""
        with self._lock:
            data = self._load()
            if self._load_error:
                return False
            user = next(
                (u for u in data.users if u.username == username),
                None,
            )
            if user is None:
                return False
            user.disabled = disabled
            self._save(data)
        logger.info("User '%s' disabled=%s", username, disabled)
        return True

    # ------------------------------------------------------------------
    # channel identity bindings
    # ------------------------------------------------------------------

    @staticmethod
    def _binding_key(channel: str, external_user_id: str) -> str:
        return f"{channel}:{external_user_id}"

    def bind_identity(
        self,
        channel: str,
        external_user_id: str,
        username: str,
    ) -> bool:
        """Bind a channel-reported identity to a registered username."""
        if not channel or not external_user_id or not username:
            return False
        with self._lock:
            data = self._load()
            if self._load_error:
                return False
            if not any(u.username == username for u in data.users):
                logger.warning(
                    "Refusing identity binding to unknown user '%s'",
                    username,
                )
                return False
            data.identity_bindings[
                self._binding_key(channel, external_user_id)
            ] = username
            self._save(data)
        return True

    def resolve_identity(
        self,
        channel: str,
        external_user_id: str,
    ) -> Optional[str]:
        """Resolve a channel identity to a username, or ``None``."""
        if not channel or not external_user_id:
            return None
        data = self._load()
        if self._load_error:
            return None
        return data.identity_bindings.get(
            self._binding_key(channel, external_user_id),
        )

    def unbind_identity(self, channel: str, external_user_id: str) -> bool:
        """Remove one identity binding. Returns True when it existed."""
        with self._lock:
            data = self._load()
            if self._load_error:
                return False
            key = self._binding_key(channel, external_user_id)
            if key not in data.identity_bindings:
                return False
            del data.identity_bindings[key]
            self._save(data)
        return True
