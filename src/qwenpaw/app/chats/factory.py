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


def get_storage_backend() -> str:
    """Return the configured chats storage backend (default ``json``).

    Invalid values log a warning and fall back to ``json`` so a typo never
    silently changes persistence semantics.
    """
    raw = EnvVarLoader.get_str(STORAGE_BACKEND_ENV, STORAGE_BACKEND_JSON)
    backend = raw.strip().lower() or STORAGE_BACKEND_JSON
    if backend not in _VALID_BACKENDS:
        logger.warning(
            "Invalid %s=%r; falling back to %r. Valid values: %s",
            STORAGE_BACKEND_ENV,
            raw,
            STORAGE_BACKEND_JSON,
            sorted(_VALID_BACKENDS),
        )
        return STORAGE_BACKEND_JSON
    return backend


def _pg_engine():
    """Return the shared async engine, or a clear configuration error."""
    from ...db.engine import create_pg_engine

    return create_pg_engine()


def build_chat_repository(path: str | Path) -> BaseChatRepository:
    """Create the chat repository for the configured storage backend."""
    backend = get_storage_backend()
    if backend == STORAGE_BACKEND_JSON:
        return JsonChatRepository(path)
    if backend == STORAGE_BACKEND_PG:
        from .repo.pg_repo import PgChatRepository

        return PgChatRepository(engine=_pg_engine())
    # dual: JSON stays authoritative; PostgreSQL shadows every write.
    from .repo.dual_repo import DualChatRepository
    from .repo.pg_repo import PgChatRepository

    return DualChatRepository(
        primary=JsonChatRepository(path),
        shadow=PgChatRepository(engine=_pg_engine()),
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


def build_session_store(save_dir: str) -> BaseSessionStore:
    """Create the session store for the configured storage backend."""
    return get_session_store_class()(save_dir=save_dir)
