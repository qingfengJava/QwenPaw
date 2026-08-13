# -*- coding: utf-8 -*-
"""PostgreSQL storage layer (M2).

Importing this package is dependency-free: SQLAlchemy/asyncpg are only
imported inside functions so the default JSON deployment never pays for
(or fails on) the optional ``qwenpaw[pg]`` extra.
"""
from __future__ import annotations

from .engine import PG_DSN_ENV, create_pg_engine, dispose_engines, get_pg_dsn
from .migrate import run_migrations

__all__ = [
    "PG_DSN_ENV",
    "create_pg_engine",
    "dispose_engines",
    "get_pg_dsn",
    "run_migrations",
]
