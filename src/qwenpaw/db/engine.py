# -*- coding: utf-8 -*-
"""Async PostgreSQL engine factory.

The DSN comes from ``QWENPAW_PG_DSN`` (asyncpg flavor, e.g.
``postgresql+asyncpg://qwenpaw:secret@127.0.0.1:5432/qwenpaw``). Pool sizing
follows the M2 plan: a modest floor with headroom for burst turns, plus
``pool_pre_ping`` so a restarted database never poisons long-lived workers.

Engines are cached per (DSN, event loop): an asyncpg pool is bound to the
loop that created it, so sharing one pool across loops (main lifespan loop,
KB bridge loop, shadow-write loop) corrupts connections — the "Future
attached to a different loop" hang that leaks ``idle in transaction``
sessions. Each loop therefore gets its own pool; within one loop the
dual-write shadow path and the pg backend still share it.
"""
from __future__ import annotations

import asyncio
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

_engines: dict[tuple[str, int], "AsyncEngine"] = {}


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
        dsn = "postgresql+asyncpg://" + dsn[len("postgresql://"):]
    return dsn


def create_pg_engine(
    dsn: Optional[str] = None,
    dedicated: bool = False,
) -> "AsyncEngine":
    """Create (or return the cached) pooled async engine for ``dsn``.

    Args:
        dsn: SQLAlchemy async DSN; defaults to ``QWENPAW_PG_DSN``.
        dedicated: When ``True`` return a NEW engine that is NOT stored in
            the shared per-DSN cache. Background-loop stores (users / RBAC)
            use a dedicated engine so their asyncpg connections are created
            and reused exclusively on the store's own event loop, avoiding
            the "Future attached to a different loop" corruption that occurs
            when a single engine's pool is shared across the main event loop
            (migrations / org services) and a store's bridge loop.

    Returns:
        A shared ``AsyncEngine`` (cached per DSN string) unless ``dedicated``.
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
    if dedicated:
        # 专属引擎：不入缓存，连接只服务于调用方（store）的后台循环。
        return create_async_engine(
            dsn,
            pool_size=_POOL_SIZE,
            max_overflow=_MAX_OVERFLOW,
            pool_timeout=_POOL_TIMEOUT_S,
            pool_pre_ping=True,
        )
    # 跨 loop 防腐：asyncpg 池绑定创建时的事件循环，跨 loop 复用共享池
    # 会把连接永久挂在语句上（idle in transaction 泄漏 → 池耗尽）。缓存
    # 键加 loop id：每个事件循环各自一池，同 loop 内 shadow/权威写共享。
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        # 无运行 loop（不应发生：engine 仅在 async 上下文使用）。退化为
        # 不入缓存的专属引擎，避免污染任何 loop 的池。
        return create_async_engine(
            dsn,
            pool_size=_POOL_SIZE,
            max_overflow=_MAX_OVERFLOW,
            pool_timeout=_POOL_TIMEOUT_S,
            pool_pre_ping=True,
        )
    cache_key = (dsn, loop_key)
    engine = _engines.get(cache_key)
    if engine is None:
        engine = create_async_engine(
            dsn,
            pool_size=_POOL_SIZE,
            max_overflow=_MAX_OVERFLOW,
            pool_timeout=_POOL_TIMEOUT_S,
            pool_pre_ping=True,
        )
        _engines[cache_key] = engine
        logger.info("Created PostgreSQL engine pool (dsn host hidden).")
    return engine


async def dispose_engines() -> None:
    """Dispose all cached engines (test teardown / shutdown hook)."""
    while _engines:
        _, engine = _engines.popitem()
        await engine.dispose()
