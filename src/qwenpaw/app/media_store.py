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

0007_media_registry turned the table into a session file registry:
``save_media_blob`` now accepts registry metadata (chat/session/owner,
source, storage type/URI, sha256), and the agent-side media hooks write
``agent_output`` snapshots through the same upsert so deleted workspace
files can be restored from the database copy.

All statements below are SQLAlchemy Core expressions whose values are
bound parameters — no query text is ever assembled from input strings.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def save_media_blob(
    *,
    stored_name: str,
    file_name: str,
    media_type: str,
    data: bytes,
    chat_id: str | None = None,
    session_id: str | None = None,
    owner_id: str | None = None,
    source: str = "upload",
    storage_type: str = "db",
    storage_uri: str | None = None,
    sha256: str | None = None,
) -> bool:
    """Upsert one media file (bytes + registry metadata) into PostgreSQL.

    Never raises: returns ``True`` on success, ``False`` when PostgreSQL
    is unavailable (upload then relies on the local copy alone). The
    registry kwargs default to the legacy upload semantics so existing
    callers keep working unchanged.
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
            # 单表达式直传 execute：字段值全部走 SQLAlchemy 绑定参数
            await session.execute(
                pg_insert(MediaFileRow)
                .values(
                    stored_name=stored_name,
                    file_name=file_name,
                    media_type=media_type,
                    size=len(data),
                    data=data,
                    chat_id=chat_id,
                    session_id=session_id,
                    owner_id=owner_id,
                    source=source,
                    storage_type=storage_type,
                    storage_uri=storage_uri,
                    sha256=sha256,
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "stored_name"],
                    set_={
                        "file_name": file_name,
                        "media_type": media_type,
                        "size": len(data),
                        "data": data,
                        "chat_id": chat_id,
                        "session_id": session_id,
                        "owner_id": owner_id,
                        "source": source,
                        "storage_type": storage_type,
                        "storage_uri": storage_uri,
                        "sha256": sha256,
                    },
                ),
            )
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


async def load_media_record(stored_name: str) -> dict[str, Any] | None:
    """Load the full registry row (metadata + bytes) for one file.

    Returns ``None`` when the row is missing or PostgreSQL is not
    reachable. Used by the restore endpoint to write the durable copy
    back to its recorded local path.
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
                    select(MediaFileRow).where(
                        MediaFileRow.stored_name == stored_name,
                    ),
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "stored_name": row.stored_name,
            "file_name": row.file_name,
            "media_type": row.media_type,
            "size": row.size,
            "data": bytes(row.data) if row.data is not None else None,
            "chat_id": row.chat_id,
            "session_id": row.session_id,
            "owner_id": row.owner_id,
            "source": row.source,
            "storage_type": row.storage_type,
            "storage_uri": row.storage_uri,
            "sha256": row.sha256,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "media record PG read failed for %s",
            stored_name,
            exc_info=True,
        )
        return None


async def list_media_records(
    *,
    chat_id: str,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """List registry rows linked to a chat (by chat_id OR session_id).

    Ordered newest-first; each dict mirrors ``load_media_record`` minus
    the heavy ``data`` blob. Returns an empty list when PostgreSQL is
    not reachable — listing is best-effort metadata only.
    """
    try:
        from sqlalchemy import or_, select
        from sqlalchemy.ext.asyncio import AsyncSession

        from ..db.engine import create_pg_engine
        from ..db.models_media import MediaFileRow
    except ImportError:
        return []

    try:
        engine = create_pg_engine()
        async with AsyncSession(engine) as session:
            # 会话关联键：chat_id 直连，或 agent 侧 session_id（Agent 产出链路）
            predicates = [MediaFileRow.chat_id == chat_id]
            if session_id:
                predicates.append(MediaFileRow.session_id == session_id)
            rows = (
                await session.execute(
                    select(MediaFileRow)
                    .where(or_(*predicates))
                    .order_by(MediaFileRow.created_at.desc()),
                )
            ).scalars()
            return [
                {
                    "stored_name": r.stored_name,
                    "file_name": r.file_name,
                    "media_type": r.media_type,
                    "size": r.size,
                    "chat_id": r.chat_id,
                    "session_id": r.session_id,
                    "owner_id": r.owner_id,
                    "source": r.source,
                    "storage_type": r.storage_type,
                    "storage_uri": r.storage_uri,
                    "sha256": r.sha256,
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                }
                for r in rows
            ]
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "media records PG list failed for chat %s",
            chat_id,
            exc_info=True,
        )
        return []


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
