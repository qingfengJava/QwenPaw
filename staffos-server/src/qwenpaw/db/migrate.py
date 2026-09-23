# -*- coding: utf-8 -*-
"""Programmatic Alembic runner (no ``alembic.ini`` required).

Private deployments apply schema upgrades in-process — either at startup
when the pg backend is selected, or from the offline migration script —
so the migration environment lives entirely inside this package.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .engine import create_pg_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_ALEMBIC_DIR = Path(__file__).parent / "alembic"


def _upgrade_to_head(connection: "Connection") -> None:
    """Run ``alembic upgrade head`` on a checked-out sync connection."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


async def run_migrations(engine: Optional["AsyncEngine"] = None) -> None:
    """Apply all pending migrations (idempotent, safe at startup)."""
    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade_to_head)
    logger.info("PostgreSQL schema is up to date.")
