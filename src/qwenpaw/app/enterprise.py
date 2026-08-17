# -*- coding: utf-8 -*-
"""Shared foundation for the XianWork enterprise domains.

Provides the pieces every enterprise domain package (orgs / projects /
experts) builds on:

- the tenant context (a request-scoped ``ContextVar`` set by
  ``AuthMiddleware`` right after token verification);
- a guard that turns "PostgreSQL not configured" into a clean HTTP 503
  instead of a stack trace;
- id helpers for the string primary keys used across the enterprise
  tables (``org_``, ``dept_``, ``prj_``, ``task_``, ``exp_``, ``team_``).
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger(__name__)

#: Default tenant for single-org deployments (and pre-enterprise rows).
DEFAULT_TENANT = "default"

#: Set once the 0002_enterprise schema exists and the default org row is
#: ensured. Requests hitting enterprise APIs before this flips (or after a
#: failed bootstrap) get an explicit 503 instead of raw SQL errors.
_schema_ready = False

_current_org_id: ContextVar[Optional[str]] = ContextVar(
    "current_org_id",
    default=None,
)


def set_current_org_id(org_id: Optional[str]) -> None:
    """Bind the authenticated user's organization to this request scope."""
    _current_org_id.set(org_id)


def get_current_org_id() -> Optional[str]:
    """Return the request-scoped org id (``None`` when unknown)."""
    return _current_org_id.get()


def current_tenant_id() -> str:
    """Effective tenant for row filtering: org id or ``default``."""
    return _current_org_id.get() or DEFAULT_TENANT


def enterprise_engine():
    """Return the shared async engine, or ``None`` when PG is unset.

    Callers that can degrade gracefully use this; HTTP handlers should
    prefer :func:`require_enterprise_engine`.
    """
    from ..constant import EnvVarLoader
    from ..db.engine import PG_DSN_ENV, create_pg_engine

    if not EnvVarLoader.get_str(PG_DSN_ENV, "").strip():
        return None
    try:
        return create_pg_engine()
    except Exception:  # pylint: disable=broad-except
        logger.warning("enterprise: engine creation failed", exc_info=True)
        return None


def enterprise_ready() -> bool:
    """True once the enterprise schema has been migrated and bootstrapped."""
    return _schema_ready


def require_enterprise_engine():
    """Return the shared async engine or raise HTTP 503.

    The XianWork collaboration plane is PostgreSQL-backed; deployments
    without ``QWENPAW_PG_DSN`` get an explicit, actionable error, and a
    configured-but-not-yet-migrated database reports initialization pending.
    """
    from ..db.engine import create_pg_engine

    engine = enterprise_engine()
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "XianWork enterprise features require PostgreSQL. Set "
                "QWENPAW_PG_DSN and run the 0002_enterprise migration."
            ),
        )
    if not _schema_ready:
        raise HTTPException(
            status_code=503,
            detail=(
                "XianWork enterprise features are initializing (PostgreSQL "
                "schema migration pending). Retry shortly."
            ),
        )
    return engine


async def bootstrap_enterprise() -> bool:
    """Migrate the enterprise schema and ensure the default org exists.

    Called once from the app lifespan (background startup). Idempotent and
    a no-op when PostgreSQL is not configured. Returns ``True`` when the
    enterprise plane ended up ready.
    """
    global _schema_ready  # pylint: disable=global-statement
    if enterprise_engine() is None:
        return False
    try:
        from ..db.migrate import run_migrations

        await run_migrations()

        from .orgs.service import get_org_service

        await get_org_service().bootstrap_default_org()
        _schema_ready = True
        logger.info("Enterprise schema ready (orgs/projects/experts).")

        # Seed the builtin experts (idempotent by fixed ids; failures
        # never block startup — the market simply starts empty).
        try:
            from .experts.builtins import ensure_builtin_experts

            installed = await ensure_builtin_experts()
            if installed:
                logger.info("Seeded %d builtin experts.", installed)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "builtin expert seeding skipped",
                exc_info=True,
            )
        return True
    except Exception:  # pylint: disable=broad-except
        logger.error(
            "Enterprise bootstrap failed; /api/xian and /api/admin/orgs "
            "will report 503 until the server is restarted with a healthy "
            "PostgreSQL.",
            exc_info=True,
        )
        return False


def new_id(prefix: str) -> str:
    """Generate a short, prefixed id for an enterprise row."""
    return f"{prefix}_{uuid4().hex[:16]}"
