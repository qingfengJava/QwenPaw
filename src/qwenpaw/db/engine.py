# -*- coding: utf-8 -*-
"""Async PostgreSQL engine factory.

The DSN comes from ``QWENPAW_PG_DSN`` (asyncpg flavor, e.g.
``postgresql+asyncpg://qwenpaw:secret@127.0.0.1:5432/qwenpaw``). Pool sizing
follows the M2 plan: a modest floor with headroom for burst turns, plus
``pool_pre_ping`` so a restarted database never poisons long-lived workers.

Engines are cached per DSN so the dual-write shadow path and the pg backend
share one pool instead of each opening their own.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..constant import EnvVarLoader
from ..exceptions import ConfigurationException

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

PG_DSN_ENV = "QWENPAW_PG_DSN"

_POOL_SIZE = 20
_MAX_OVERFLOW = 40
_POOL_TIMEOUT_S = 30

_engines: dict[str, "AsyncEngine"] = {}


def get_pg_dsn() -> str:
    """Return the configured PostgreSQL DSN or raise a clear error."""
    dsn = EnvVarLoader.get_str(PG_DSN_ENV, "").strip()
    if not dsn:
        raise ConfigurationException(
            message=(
                f"PostgreSQL storage backend selected but {PG_DSN_ENV} is "
                "not set. Example: postgresql+asyncpg://qwenpaw:***@"
                "127.0.0.1:5432/qwenpaw"
            ),
            config_key=PG_DSN_ENV,
        )
    if dsn.startswith("postgresql://"):
        # Convenience: default to the async driver so operators can paste a
        # canonical DSN without knowing the SQLAlchemy driver suffix.
        dsn = "postgresql+asyncpg://" + dsn[len("postgresql://") :]
    return dsn


def create_pg_engine(dsn: Optional[str] = None) -> "AsyncEngine":
    """Create (or return the cached) pooled async engine for ``dsn``.

    Args:
        dsn: SQLAlchemy async DSN; defaults to ``QWENPAW_PG_DSN``.

    Returns:
        A shared ``AsyncEngine`` (cached per DSN string).
    """
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError as exc:  # pragma: no cover - environment guard
        raise ConfigurationException(
            message=(
                "The PostgreSQL backend requires extra dependencies. "
                "Install them with: pip install 'qwenpaw[pg]'"
            ),
            config_key=PG_DSN_ENV,
        ) from exc

    dsn = dsn or get_pg_dsn()
    engine = _engines.get(dsn)
    if engine is None:
        engine = create_async_engine(
            dsn,
            pool_size=_POOL_SIZE,
            max_overflow=_MAX_OVERFLOW,
            pool_timeout=_POOL_TIMEOUT_S,
            pool_pre_ping=True,
        )
        _engines[dsn] = engine
        logger.info("Created PostgreSQL engine pool (dsn host hidden).")
    return engine


async def dispose_engines() -> None:
    """Dispose all cached engines (test teardown / shutdown hook)."""
    while _engines:
        _, engine = _engines.popitem()
        await engine.dispose()
