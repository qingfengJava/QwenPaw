# -*- coding: utf-8 -*-
"""Storage backend factory for the chats domain.

``QWENPAW_STORAGE_BACKEND`` selects the persistence backend:

- ``json`` (default): single-file JSON storage — current behavior.
- ``dual``: JSON primary plus PostgreSQL shadow writes, for migration
  rehearsal (M2). Requires ``QWENPAW_PG_DSN`` and the ``qwenpaw[pg]`` extra.
- ``pg``: PostgreSQL-backed storage (M2). Same requirements.

The value is read on every call so tests and runtime reloads can switch
backends by patching the environment.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ...constant import EnvVarLoader
from .repo.base import BaseChatRepository
from .repo.json_repo import JsonChatRepository
from .session import SafeJSONSession
from .session_store import BaseSessionStore

logger = logging.getLogger(__name__)

STORAGE_BACKEND_ENV = "QWENPAW_STORAGE_BACKEND"
STORAGE_BACKEND_JSON = "json"
STORAGE_BACKEND_DUAL = "dual"
STORAGE_BACKEND_PG = "pg"
_VALID_BACKENDS = frozenset(
    {STORAGE_BACKEND_JSON, STORAGE_BACKEND_DUAL, STORAGE_BACKEND_PG},
)


_DEFAULT_BACKEND_LOGGED = False


def _default_storage_backend() -> str:
    """SQLite 退役迁移的动态默认值（Phase A）。

    配置了 ``QWENPAW_PG_DSN`` 时默认 ``dual``（文件 primary + PG 影子双写），
    让所有存储面（chats/session_states/history_entries）开始积累 PG 数据，
    为读切换（``pg``）做准备；未配置 DSN 的个人部署保持 ``json`` 不变。
    显式设置 ``QWENPAW_STORAGE_BACKEND`` 恒优先。
    """
    from ...db.engine import get_pg_dsn

    return STORAGE_BACKEND_DUAL if get_pg_dsn() else STORAGE_BACKEND_JSON


def get_storage_backend() -> str:
    """Return the configured chats storage backend.

    未显式配置时按 ``_default_storage_backend`` 决定（配置了 PG DSN 即
    ``dual``，否则 ``json``）。Invalid values log a warning and fall back
    to the default so a typo never silently changes persistence semantics.
    """
    global _DEFAULT_BACKEND_LOGGED  # pylint: disable=global-statement
    default = _default_storage_backend()
    raw = EnvVarLoader.get_str(STORAGE_BACKEND_ENV, "")
    backend = raw.strip().lower() or default
    if backend not in _VALID_BACKENDS:
        logger.warning(
            "Invalid %s=%r; falling back to %r. Valid values: %s",
            STORAGE_BACKEND_ENV,
            raw,
            default,
            sorted(_VALID_BACKENDS),
        )
        backend = default
    if not _DEFAULT_BACKEND_LOGGED:
        _DEFAULT_BACKEND_LOGGED = True
        logger.info(
            "Storage backend resolved to %r (env=%r); SQLite history is "
            "deprecated — run `python -m qwenpaw.db.backfill_history` then "
            "switch QWENPAW_STORAGE_BACKEND=pg once the backfill completes",
            backend,
            raw or "(unset)",
        )
    return backend


def _pg_engine():
    """Return the shared async engine, or a clear configuration error."""
    from ...db.engine import create_pg_engine

    return create_pg_engine()


def build_chat_repository(
    path: str | Path,
    agent_id: str = "default",
) -> BaseChatRepository:
    """Create the chat repository for the configured storage backend.

    ``agent_id`` scopes the PG side to one digital employee (JSON reads are
    already workspace-isolated by file layout; the shared ``chats`` table
    needs the column). It must be passed by every workspace caller.
    """
    backend = get_storage_backend()
    if backend == STORAGE_BACKEND_JSON:
        return JsonChatRepository(path)
    if backend == STORAGE_BACKEND_PG:
        from .repo.pg_repo import PgChatRepository

        return PgChatRepository(engine=_pg_engine(), agent_id=agent_id)
    # dual: JSON stays authoritative; PostgreSQL shadows every write.
    from .repo.dual_repo import DualChatRepository
    from .repo.pg_repo import PgChatRepository

    return DualChatRepository(
        primary=JsonChatRepository(path),
        shadow=PgChatRepository(engine=_pg_engine(), agent_id=agent_id),
    )


def get_session_store_class() -> type[BaseSessionStore]:
    """Return the session store class for the configured backend.

    The workspace service manager resolves a non-type ``service_class``
    callable to the actual class and instantiates it with ``init_args``
    (``save_dir``); every returned class accepts that keyword — the PG and
    dual backends simply ignore it and resolve the engine from the
    environment.
    """
    backend = get_storage_backend()
    if backend == STORAGE_BACKEND_JSON:
        return SafeJSONSession
    if backend == STORAGE_BACKEND_PG:
        from .pg_session_store import PgSessionStore

        return PgSessionStore
    from .dual_session_store import DualSessionStore

    return DualSessionStore


def build_session_store(
    save_dir: str,
    agent_id: str = "default",
) -> BaseSessionStore:
    """Create the session store for the configured storage backend."""
    return get_session_store_class()(
        save_dir=save_dir,
        agent_id=agent_id,
    )
