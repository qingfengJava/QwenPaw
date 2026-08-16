# -*- coding: utf-8 -*-
"""PG-backed media blob store for console chat uploads.

The /console/upload endpoint writes every uploaded file twice:

1. the workspace ``media/`` directory (working copy for agent tooling
   such as ``view_image``), and
2. the ``media_files`` PostgreSQL table (durable copy backing the
   ``GET /console/media/{stored_name}`` recall endpoint).

Both writes go through this module. The PG write is best-effort: when
PostgreSQL is not configured (no ``QWENPAW_PG_DSN``) or briefly down,
uploads still succeed via the local copy and the recall endpoint falls
back to reading the local file.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def save_media_blob(
    *,
    stored_name: str,
    file_name: str,
    media_type: str,
    data: bytes,
) -> bool:
    """Upsert one uploaded media file into PostgreSQL.

    Never raises: returns ``True`` on success, ``False`` when PostgreSQL
    is unavailable (upload then relies on the local copy alone).
    """
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.ext.asyncio import AsyncSession

        from ..db.engine import create_pg_engine
        from ..db.models_media import MediaFileRow
    except ImportError:
        logger.info(
            "PG extras not installed; skipping media blob write for %s",
            stored_name,
        )
        return False

    try:
        engine = create_pg_engine()
        async with AsyncSession(engine) as session:
            stmt = pg_insert(MediaFileRow).values(
                stored_name=stored_name,
                file_name=file_name,
                media_type=media_type,
                size=len(data),
                data=data,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["tenant_id", "stored_name"],
                set_={
                    "file_name": file_name,
                    "media_type": media_type,
                    "size": len(data),
                    "data": data,
                },
            )
            await session.execute(stmt)
            await session.commit()
        return True
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "media blob PG write failed for %s; local copy only",
            stored_name,
            exc_info=True,
        )
        return False


async def load_media_blob(
    stored_name: str,
) -> tuple[bytes, str, str] | None:
    """Load ``(data, media_type, file_name)`` from PostgreSQL.

    Returns ``None`` when the row is missing or PostgreSQL is not
    reachable (caller falls back to the local media file).
    """
    try:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from ..db.engine import create_pg_engine
        from ..db.models_media import MediaFileRow
    except ImportError:
        return None

    try:
        engine = create_pg_engine()
        async with AsyncSession(engine) as session:
            row = (
                await session.execute(
                    select(
                        MediaFileRow.data,
                        MediaFileRow.media_type,
                        MediaFileRow.file_name,
                    ).where(MediaFileRow.stored_name == stored_name),
                )
            ).first()
        if row is None:
            return None
        return bytes(row.data), str(row.media_type), str(row.file_name)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "media blob PG read failed for %s; falling back to local",
            stored_name,
            exc_info=True,
        )
        return None


def resolve_local_media_file(media_dir: Path, stored_name: str) -> Path | None:
    """Resolve *stored_name* inside *media_dir* with traversal protection.

    Returns the absolute file path when it names an existing file
    directly inside ``media_dir``, otherwise ``None``.
    """
    if not stored_name or "/" in stored_name or "\\" in stored_name:
        return None
    if stored_name in {".", ".."} or stored_name.startswith("."):
        return None
    root = media_dir.resolve()
    candidate = (root / stored_name).resolve()
    if candidate.parent != root or not candidate.is_file():
        return None
    return candidate
