# -*- coding: utf-8 -*-
"""History store factory — scroll's half of the storage-backend switch.

Shares ``QWENPAW_STORAGE_BACKEND`` with the chats domain so one flag moves
every storage plane together:

- ``json``: SQLite ``HistoryStore`` (current behavior).
- ``dual``: SQLite primary + PostgreSQL shadow writes (migration rehearsal).
- ``pg``: PostgreSQL ``history_entries`` table.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .base_history import BaseHistoryStore
from .history import HistoryStore

logger = logging.getLogger(__name__)


def build_history_store(db_path: str | Path) -> BaseHistoryStore:
    """Create the scroll history store for the configured backend."""
    from ....app.chats.factory import (
        STORAGE_BACKEND_JSON,
        STORAGE_BACKEND_PG,
        get_storage_backend,
    )

    backend = get_storage_backend()
    if backend == STORAGE_BACKEND_JSON:
        return HistoryStore(db_path)
    from ....db.engine import get_pg_dsn
    from .pg_history import PgHistoryStore

    # PgHistoryStore owns a private engine on its own loop thread (asyncpg
    # connections are loop-affine), so it takes the DSN, not a shared engine.
    dsn = get_pg_dsn()
    if backend == STORAGE_BACKEND_PG:
        return PgHistoryStore(dsn=dsn, identity=f"pg:{db_path}")
    from .dual_history import DualHistoryStore

    return DualHistoryStore(
        primary=HistoryStore(db_path),
        shadow=PgHistoryStore(dsn=dsn, identity=f"pg:{db_path}"),
    )
