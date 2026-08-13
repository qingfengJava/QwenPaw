# -*- coding: utf-8 -*-
"""Storage backend factory for the chats domain.

``QWENPAW_STORAGE_BACKEND`` selects the persistence backend:

- ``json`` (default): single-file JSON storage — current behavior.
- ``dual``: JSON primary plus PostgreSQL shadow writes, for migration
  rehearsal. Available from the M2 milestone.
- ``pg``: PostgreSQL-backed storage. Available from the M2 milestone.

The value is read on every call so tests and runtime reloads can switch
backends by patching the environment.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ...constant import EnvVarLoader
from ...exceptions import ConfigurationException
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


def _unsupported_backend(backend: str) -> ConfigurationException:
    """Build the error for backends scheduled for the M2 milestone."""
    return ConfigurationException(
        message=(
            f"Storage backend '{backend}' requires the PostgreSQL storage "
            f"module, which is not available in this build. "
            f"Set {STORAGE_BACKEND_ENV}=json."
        ),
        config_key=STORAGE_BACKEND_ENV,
    )


def build_chat_repository(path: str | Path) -> BaseChatRepository:
    """Create the chat repository for the configured storage backend."""
    backend = get_storage_backend()
    if backend == STORAGE_BACKEND_JSON:
        return JsonChatRepository(path)
    raise _unsupported_backend(backend)


def get_session_store_class() -> type[BaseSessionStore]:
    """Return the session store class for the configured backend.

    The workspace service manager resolves a non-type ``service_class``
    callable to the actual class and instantiates it with ``init_args``;
    returning the class here keeps that contract intact.
    """
    backend = get_storage_backend()
    if backend == STORAGE_BACKEND_JSON:
        return SafeJSONSession
    raise _unsupported_backend(backend)


def build_session_store(save_dir: str) -> BaseSessionStore:
    """Create the session store for the configured storage backend."""
    return get_session_store_class()(save_dir=save_dir)
