# -*- coding: utf-8 -*-
"""PostgreSQL-backed user store (账号体系 M2 权威存储).

与 :class:`store.UserStore` 方法集一一对应（鸭子类型同接口）：

- 底层复用 ``QWENPAW_PG_DSN`` 的 AsyncEngine；UserStore 的调用方
  （AuthMiddleware / 渠道驱动 / admin 路由）全是同步上下文，因此本类
  用一个专用后台事件循环线程桥接（``run_coroutine_threadsafe``），
  不引入新的同步驱动依赖；
- 全量账号 + 绑定映射做 30s TTL 缓存（企业规模几十~几百账号，缓存
  命中时同步调用零 DB 开销）；写操作落库后主动刷新缓存；
- fail-closed 语义与文件版一致：账号存储不可读时 ``is_active`` 返回
  False、``verify_password`` 返回 None，绝不放行。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerificationError

from ...db.engine import create_pg_engine
from .models import (
    PASSWORD_ALGO_ARGON2,
    PASSWORD_ALGO_SHA256,
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    VALID_ROLES,
    UserRecord,
)

logger = logging.getLogger(__name__)

# Argon2id 参数与 store.py 保持一致（同一套 OWASP 推荐默认值）。
_password_hasher = PasswordHasher()

# 缓存 TTL：多进程部署下的最终一致窗口；写路径会主动失效本进程缓存。
_CACHE_TTL_SECONDS = 30.0

# 同步桥接的单次等待上限（PG 抖动时不至于把请求线程挂死）。
_BRIDGE_TIMEOUT_SECONDS = 10.0


def _hash_password_argon2(password: str) -> str:
    """Hash *password* with argon2id（与 store.py 同源参数）."""
    return _password_hasher.hash(password)


def _verify_argon2(password: str, encoded: str) -> bool:
    try:
        return _password_hasher.verify(encoded, password)
    except (VerificationError, Argon2Error):
        return False


def _verify_sha256(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a legacy salted-SHA256 password（M1 迁移数据兼容）."""
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, stored_hash)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PgUserStore:
    """PG-backed implementation of the user-store contract."""

    def __init__(self, engine=None) -> None:
        self._engine = engine
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_lock = threading.Lock()
        # 账号全量缓存：username -> record；None = 尚未加载。
        self._users: Optional[Dict[str, UserRecord]] = None
        self._users_at: float = 0.0
        # 绑定缓存："{channel}:{external_user_id}" -> username。
        self._bindings: Optional[Dict[str, str]] = None
        self._bindings_at: float = 0.0
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------
    # async bridge (dedicated background loop)
    # ------------------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Lazily start the dedicated loop thread (one per process)."""
        with self._loop_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            loop = asyncio.new_event_loop()

            def _run_loop() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self._loop_thread = threading.Thread(
                target=_run_loop,
                name="qwenpaw-user-store-pg",
                daemon=True,
            )
            self._loop_thread.start()
            self._loop = loop
            return loop

    def _run(self, coro) -> object:
        """Bridge a coroutine onto the background loop (blocking)."""
        loop = self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(
            coro,
            loop,
        ).result(timeout=_BRIDGE_TIMEOUT_SECONDS)

    def _get_engine(self):
        if self._engine is None:
            self._engine = create_pg_engine()
        return self._engine

    # ------------------------------------------------------------------
    # cache helpers
    # ------------------------------------------------------------------

    def _invalidate(self) -> None:
        """Drop caches after a successful write（下次读取重新加载）."""
        with self._cache_lock:
            self._users = None
            self._users_at = 0.0
            self._bindings = None
            self._bindings_at = 0.0

    async def _load_users_async(self) -> Dict[str, UserRecord]:
        """Load all accounts into UserRecord objects（全量，量级小）."""
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT username, password_hash, password_salt, "
                        "password_algo, role, display_name, avatar, "
                        "disabled, org_id, created_at "
                        "FROM qwenpaw_users WHERE tenant_id = 'default'",
                    ),
                )
            ).fetchall()
        users: Dict[str, UserRecord] = {}
        for row in rows:
            record = UserRecord(
                username=str(row[0]),
                password_hash=str(row[1]),
                password_salt=str(row[2] or ""),
                password_algo=str(row[3] or PASSWORD_ALGO_ARGON2),
                role=str(row[4] or ROLE_EMPLOYEE),
                display_name=str(row[5] or ""),
                avatar=str(row[6] or ""),
                disabled=bool(row[7]),
                org_id=str(row[8] or "default"),
                created_at=(
                    row[9] if isinstance(row[9], datetime) else _utcnow()
                ),
            )
            users[record.username] = record
        return users

    def _load_users(self) -> Optional[Dict[str, UserRecord]]:
        """TTL-cached full account map；None 表示存储不可读（fail-closed）."""
        with self._cache_lock:
            if (
                self._users is not None
                and time.monotonic() - self._users_at < _CACHE_TTL_SECONDS
            ):
                return self._users
        try:
            users = self._run(self._load_users_async())
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "pg user store load failed (fail-closed)", exc_info=True
            )
            return None
        with self._cache_lock:
            self._users = users
            self._users_at = time.monotonic()
            return users

    async def _load_bindings_async(self) -> Dict[str, str]:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT channel, external_user_id, username "
                        "FROM user_identity_bindings "
                        "WHERE tenant_id = 'default'",
                    ),
                )
            ).fetchall()
        return {f"{row[0]}:{row[1]}": str(row[2]) for row in rows}

    def _load_bindings(self) -> Optional[Dict[str, str]]:
        with self._cache_lock:
            if (
                self._bindings is not None
                and time.monotonic() - self._bindings_at < _CACHE_TTL_SECONDS
            ):
                return self._bindings
        try:
            bindings = self._run(self._load_bindings_async())
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg identity bindings load failed", exc_info=True)
            return None
        with self._cache_lock:
            self._bindings = bindings
            self._bindings_at = time.monotonic()
            return bindings

    # ------------------------------------------------------------------
    # readiness / bootstrap import
    # ------------------------------------------------------------------

    def ensure_ready(self) -> bool:
        """Verify the tables exist and import file-era data once.

        迁移（alembic 0032）未执行时返回 False，工厂据此回退文件存储；
        表就绪且文件存量存在时做一次幂等导入（账号 + 身份绑定）。
        """
        try:
            self._run(self._ensure_tables_async())
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg user tables not ready", exc_info=True)
            return False
        self._import_file_users()
        return True

    async def _ensure_tables_async(self) -> None:
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT to_regclass('public.qwenpaw_users')"),
                )
            ).fetchone()
            if row is None or row[0] is None:
                raise RuntimeError(
                    "qwenpaw_users table missing (run alembic upgrade)",
                )

    def _import_file_users(self) -> None:
        """One-shot idempotent import of users.json into PG."""
        try:
            from .store import UserStore

            file_store = UserStore()
            file_data = file_store._load()
        except Exception:  # pylint: disable=broad-except
            logger.debug("file user store unavailable for import")
            return
        if not file_data.users and not file_data.identity_bindings:
            return
        try:
            self._run(
                self._import_async(
                    [u.model_dump(mode="json") for u in file_data.users],
                    dict(file_data.identity_bindings),
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("users.json -> pg import failed", exc_info=True)
            return
        self._invalidate()
        logger.info(
            "Imported %d account(s) / %d binding(s) from users.json",
            len(file_data.users),
            len(file_data.identity_bindings),
        )

    async def _import_async(
        self,
        users: List[dict],
        bindings: Dict[str, str],
    ) -> None:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            for user in users:
                # ON CONFLICT 保持幂等：已导入过的账号不覆盖（PG 为权威）。
                await conn.execute(
                    text(
                        "INSERT INTO qwenpaw_users (username, password_hash, "
                        "password_salt, password_algo, role, display_name, "
                        "avatar, disabled, org_id) "
                        "VALUES (:username, :password_hash, :password_salt, "
                        ":password_algo, :role, :display_name, :avatar, "
                        ":disabled, :org_id) ON CONFLICT DO NOTHING",
                    ),
                    {
                        "username": user.get("username") or "",
                        "password_hash": user.get("password_hash") or "",
                        "password_salt": user.get("password_salt") or "",
                        "password_algo": user.get("password_algo")
                        or PASSWORD_ALGO_ARGON2,
                        "role": user.get("role") or ROLE_EMPLOYEE,
                        "display_name": user.get("display_name") or "",
                        "avatar": user.get("avatar") or "",
                        "disabled": bool(user.get("disabled")),
                        "org_id": user.get("org_id") or "default",
                    },
                )
            for key, username in bindings.items():
                channel, _, external = key.partition(":")
                if not channel or not external:
                    continue
                await conn.execute(
                    text(
                        "INSERT INTO user_identity_bindings "
                        "(channel, external_user_id, username) "
                        "VALUES (:channel, :external, :username) "
                        "ON CONFLICT DO NOTHING",
                    ),
                    {
                        "channel": channel,
                        "external": external,
                        "username": username,
                    },
                )

    # ------------------------------------------------------------------
    # queries（与 UserStore 契约一致）
    # ------------------------------------------------------------------

    def has_users(self) -> bool:
        users = self._load_users()
        return bool(users)

    def get_user(self, username: str) -> Optional[UserRecord]:
        users = self._load_users()
        if users is None:
            return None
        return users.get(username)

    def org_id_for_user(self, username: str) -> str:
        """Tenant (org) of one account；unknown/unreadable → ``default``."""
        user = self.get_user(username)
        return user.org_id if user is not None else "default"

    def list_users(self) -> List[UserRecord]:
        users = self._load_users()
        if users is None:
            return []
        return list(users.values())

    def is_active(self, username: str) -> bool:
        users = self._load_users()
        if users is None:
            return False
        user = users.get(username)
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
        org_id: str = "default",
    ) -> Optional[UserRecord]:
        """Create a user；首个账号强制 admin（与文件版语义一致）."""
        username = username.strip()
        if not username or not password:
            return None
        users = self._load_users()
        if users is None:
            return None
        if username in users:
            logger.warning("Refusing to create duplicate user '%s'", username)
            return None
        effective_role = ROLE_ADMIN if not users else (role or ROLE_EMPLOYEE)
        if effective_role not in VALID_ROLES:
            effective_role = ROLE_EMPLOYEE
        record = UserRecord(
            username=username,
            password_hash=_hash_password_argon2(password),
            password_algo=PASSWORD_ALGO_ARGON2,
            role=effective_role,
            display_name=display_name.strip(),
            org_id=org_id.strip() or "default",
        )
        try:
            self._run(self._insert_user_async(record))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg create_user failed", exc_info=True)
            return None
        self._invalidate()
        logger.info(
            "User '%s' created with role '%s' (pg)",
            username,
            effective_role,
        )
        return record

    async def _insert_user_async(self, record: UserRecord) -> None:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO qwenpaw_users (username, password_hash, "
                    "password_salt, password_algo, role, display_name, "
                    "avatar, disabled, org_id) "
                    "VALUES (:username, :password_hash, '', :password_algo, "
                    ":role, :display_name, :avatar, :disabled, :org_id)",
                ),
                {
                    "username": record.username,
                    "password_hash": record.password_hash,
                    "password_algo": record.password_algo,
                    "role": record.role,
                    "display_name": record.display_name,
                    "avatar": record.avatar,
                    "disabled": record.disabled,
                    "org_id": record.org_id,
                },
            )

    def import_legacy_user(self, legacy: dict) -> Optional[UserRecord]:
        """Import the single-user auth.json record as first admin."""
        username = str(legacy.get("username", "")).strip()
        password_hash = str(legacy.get("password_hash", ""))
        password_salt = str(legacy.get("password_salt", ""))
        if not username or not password_hash or not password_salt:
            logger.error("Legacy auth user record is incomplete; not migrated")
            return None
        record = UserRecord(
            username=username,
            password_hash=password_hash,
            password_salt=password_salt,
            password_algo=PASSWORD_ALGO_SHA256,
            role=ROLE_ADMIN,
        )
        try:
            self._run(self._insert_user_async(record))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg import_legacy_user failed", exc_info=True)
            return None
        self._invalidate()
        return record

    def verify_password(
        self,
        username: str,
        password: str,
    ) -> Optional[UserRecord]:
        """Verify credentials；legacy sha256 登录成功后透明升级 argon2id."""
        users = self._load_users()
        if users is None:
            return None
        user = users.get(username)
        if user is None or user.disabled:
            return None

        if user.password_algo == PASSWORD_ALGO_ARGON2:
            if not _verify_argon2(password, user.password_hash):
                return None
            # 参数变化时重散列（库默认值升级跟随）。
            if _password_hasher.check_needs_rehash(user.password_hash):
                self.update_password(username, password)
                return self.get_user(username)
            return user

        # Legacy salted-SHA256 path: verify, then upgrade to argon2id.
        if not _verify_sha256(
            password, user.password_hash, user.password_salt
        ):
            return None
        self.update_password(username, password)
        return self.get_user(username)

    def update_password(self, username: str, new_password: str) -> bool:
        """Set a new argon2id password hash for *username*."""
        if not new_password:
            return False
        return self._update_fields(
            username,
            {
                "password_hash": _hash_password_argon2(new_password),
                "password_salt": "",
                "password_algo": PASSWORD_ALGO_ARGON2,
            },
        )

    def set_disabled(self, username: str, disabled: bool) -> bool:
        return self._update_fields(username, {"disabled": disabled})

    def set_role(self, username: str, role: str) -> bool:
        if role not in VALID_ROLES:
            return False
        return self._update_fields(username, {"role": role})

    def set_display_name(self, username: str, display_name: str) -> bool:
        return self._update_fields(
            username,
            {"display_name": display_name.strip()},
        )

    def set_profile(
        self,
        username: str,
        *,
        display_name: str | None = None,
        avatar: str | None = None,
    ) -> bool:
        """Partial profile update（None 字段保持不变）."""
        fields: dict = {}
        if display_name is not None:
            fields["display_name"] = display_name.strip()
        if avatar is not None:
            fields["avatar"] = avatar.strip()
        if not fields:
            return True
        return self._update_fields(username, fields)

    def _update_fields(self, username: str, fields: dict) -> bool:
        """Shared UPDATE helper；unknown user → False（与文件版一致）."""
        if not fields:
            return False
        users = self._load_users()
        if users is None or username not in users:
            return False
        try:
            self._run(self._update_user_async(username, fields))
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg update user failed", exc_info=True)
            return False
        self._invalidate()
        return True

    async def _update_user_async(self, username: str, fields: dict) -> None:
        from sqlalchemy import text

        sets = ", ".join(f"{name} = :{name}" for name in fields)
        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    f"UPDATE qwenpaw_users SET {sets}, "
                    "updated_at = now() "
                    "WHERE tenant_id = 'default' AND username = :username",
                ),
                {**fields, "username": username},
            )

    def set_org_id(self, username: str, org_id: str) -> bool:
        return self._update_fields(
            username,
            {"org_id": org_id.strip() or "default"},
        )

    # ------------------------------------------------------------------
    # channel identity bindings
    # ------------------------------------------------------------------

    def bind_identity(
        self,
        channel: str,
        external_user_id: str,
        username: str,
    ) -> bool:
        """Bind a channel-reported identity to a registered username."""
        if not channel or not external_user_id or not username:
            return False
        users = self._load_users()
        if users is None or username not in users:
            logger.warning(
                "Refusing identity binding to unknown user '%s'",
                username,
            )
            return False
        try:
            self._run(
                self._upsert_binding_async(channel, external_user_id, username)
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg bind_identity failed", exc_info=True)
            return False
        self._invalidate()
        return True

    async def _upsert_binding_async(
        self,
        channel: str,
        external_user_id: str,
        username: str,
    ) -> None:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO user_identity_bindings "
                    "(channel, external_user_id, username) "
                    "VALUES (:channel, :external, :username) "
                    "ON CONFLICT (tenant_id, channel, external_user_id) "
                    "DO UPDATE SET username = EXCLUDED.username, "
                    "updated_at = now()",
                ),
                {
                    "channel": channel,
                    "external": external_user_id,
                    "username": username,
                },
            )

    def resolve_identity(
        self,
        channel: str,
        external_user_id: str,
    ) -> Optional[str]:
        """Resolve a channel identity to a username, or ``None``."""
        if not channel or not external_user_id:
            return None
        bindings = self._load_bindings()
        if bindings is None:
            return None
        return bindings.get(f"{channel}:{external_user_id}")

    def list_identity_bindings(self) -> List[dict]:
        """All bindings as display rows（admin 绑定管理页数据源）."""
        bindings = self._load_bindings()
        if bindings is None:
            return []
        rows: List[dict] = []
        for key, username in bindings.items():
            channel, _, external = key.partition(":")
            rows.append(
                {
                    "channel": channel,
                    "external_user_id": external,
                    "username": username,
                },
            )
        return rows

    def unbind_identity(self, channel: str, external_user_id: str) -> bool:
        """Remove one identity binding. Returns True when it existed."""
        if not channel or not external_user_id:
            return False
        try:
            deleted = self._run(
                self._delete_binding_async(channel, external_user_id),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning("pg unbind_identity failed", exc_info=True)
            return False
        if deleted:
            self._invalidate()
        return deleted

    async def _delete_binding_async(
        self,
        channel: str,
        external_user_id: str,
    ) -> bool:
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM user_identity_bindings "
                    "WHERE tenant_id = 'default' "
                    "AND channel = :channel "
                    "AND external_user_id = :external",
                ),
                {"channel": channel, "external": external_user_id},
            )
            return bool(result.rowcount)
