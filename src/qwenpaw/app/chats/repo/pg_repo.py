# -*- coding: utf-8 -*-
"""PostgreSQL chat repository (M2).

Implements ``BaseChatRepository`` over the ``chats`` table. Convenience
operations are overridden with single statements so the hot path never pays
the JSON backend's load-modify-save round trip; ``load``/``save`` keep the
whole-registry semantics for the migration script and compatibility shims.

Concurrency: mutations run inside real transactions, so the per-owner /
global write locks carried by the file-era ``ChatManager`` become a no-op
safety net here (the plan removes them once the pg backend is authoritative).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from ....db.base import DEFAULT_TENANT_ID
from ..models import ChatSpec, ChatsFile, SessionSource
from ...channels.schema import DEFAULT_CHANNEL
from .base import BaseChatRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


def _row_to_spec(row) -> ChatSpec:
    """Rehydrate a ``ChatSpec`` from a ``chats`` table row mapping."""
    import json

    meta = row["meta"]
    # text() results carry no type processor: JSONB arrives as text.
    if isinstance(meta, str):
        meta = json.loads(meta)
    return ChatSpec(
        id=row["id"],
        name=row["name"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        owner_id=row["owner_id"],
        channel=row["channel"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        meta=meta or {},
        status=row["status"],
        pinned=row["pinned"],
        archived_at=row["archived_at"],
        source=SessionSource(row["source"]),
    )


def _spec_to_values(spec: ChatSpec, tenant_id: str) -> dict:
    """Flatten a ``ChatSpec`` into column values for insert/upsert."""
    import json

    return {
        "tenant_id": tenant_id,
        "id": spec.id,
        "session_id": spec.session_id,
        "user_id": spec.user_id,
        "owner_id": spec.owner_id,
        "channel": spec.channel,
        "name": spec.name,
        "status": spec.status,
        "pinned": spec.pinned,
        "archived_at": spec.archived_at,
        "source": spec.source.value,
        # text() parameters carry no type context: send JSON text and
        # CAST at the SQL site.
        "meta": json.dumps(spec.meta, ensure_ascii=False),
        "created_at": spec.created_at,
        "updated_at": spec.updated_at,
    }


class PgChatRepository(BaseChatRepository):
    """``chats`` table repository sharing the process-wide engine pool."""

    #: Row-level transactions replace the file-era manager locks.
    transactional = True

    def __init__(
        self,
        engine: "AsyncEngine",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        self._engine = engine
        self._tenant_id = tenant_id

    @property
    def path(self) -> str:
        """Storage identity (the JSON backend exposes a file path)."""
        return f"pg://chats/{self._tenant_id}"

    # -- row helpers ----------------------------------------------------

    async def _fetch_all(self) -> list[ChatSpec]:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, session_id, user_id, owner_id, channel, "
                    "name, status, pinned, archived_at, source, meta, "
                    "created_at, updated_at FROM chats "
                    "WHERE tenant_id = :tid ORDER BY created_at, id",
                ),
                {"tid": self._tenant_id},
            )
            return [_row_to_spec(row._mapping) for row in result]

    # -- contract: whole-registry semantics ------------------------------

    async def load(self) -> ChatsFile:
        """Load every chat spec of this tenant."""
        return ChatsFile(version=1, chats=await self._fetch_all())

    async def save(self, chats_file: ChatsFile) -> None:
        """Replace the tenant's registry with ``chats_file`` atomically.

        Runs in one transaction: upsert every given spec, then delete rows
        absent from the file — the exact semantics of the JSON atomic
        rewrite, without its cross-owner write amplification.
        """
        from sqlalchemy import text

        values = [
            _spec_to_values(spec, self._tenant_id)
            for spec in chats_file.chats
        ]
        async with self._engine.begin() as conn:
            if values:
                await conn.execute(
                    text(
                        "INSERT INTO chats (tenant_id, id, session_id, "
                        "user_id, owner_id, channel, name, status, pinned, "
                        "archived_at, source, meta, created_at, updated_at) "
                        "VALUES (:tenant_id, :id, :session_id, :user_id, "
                        ":owner_id, :channel, :name, :status, :pinned, "
                        ":archived_at, :source, CAST(:meta AS JSONB), "
                        ":created_at, :updated_at) "
                        "ON CONFLICT (tenant_id, id) DO UPDATE SET "
                        "session_id = EXCLUDED.session_id, "
                        "user_id = EXCLUDED.user_id, "
                        "owner_id = EXCLUDED.owner_id, "
                        "channel = EXCLUDED.channel, "
                        "name = EXCLUDED.name, "
                        "status = EXCLUDED.status, "
                        "pinned = EXCLUDED.pinned, "
                        "archived_at = EXCLUDED.archived_at, "
                        "source = EXCLUDED.source, "
                        "meta = EXCLUDED.meta, "
                        "created_at = EXCLUDED.created_at, "
                        "updated_at = EXCLUDED.updated_at"
                    ),
                    values,
                )
            await conn.execute(
                text(
                    "DELETE FROM chats WHERE tenant_id = :tid "
                    "AND id <> ALL(:keep_ids)",
                ),
                {
                    "tid": self._tenant_id,
                    "keep_ids": [v["id"] for v in values],
                },
            )

    # -- convenience operations (single-statement overrides) -------------

    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, session_id, user_id, owner_id, channel, "
                    "name, status, pinned, archived_at, source, meta, "
                    "created_at, updated_at FROM chats "
                    "WHERE tenant_id = :tid AND id = :cid",
                ),
                {"tid": self._tenant_id, "cid": chat_id},
            )
            row = result.first()
            return _row_to_spec(row._mapping) if row else None

    async def get_chat_by_id(
        self,
        session_id: str,
        user_id: str,
        channel: str = DEFAULT_CHANNEL,
    ) -> Optional[ChatSpec]:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, session_id, user_id, owner_id, channel, "
                    "name, status, pinned, archived_at, source, meta, "
                    "created_at, updated_at FROM chats "
                    "WHERE tenant_id = :tid AND session_id = :sid "
                    "AND user_id = :uid AND channel = :chan "
                    "ORDER BY updated_at DESC LIMIT 1",
                ),
                {
                    "tid": self._tenant_id,
                    "sid": session_id,
                    "uid": user_id,
                    "chan": channel,
                },
            )
            row = result.first()
            return _row_to_spec(row._mapping) if row else None

    async def upsert_chat(self, spec: ChatSpec) -> None:
        """Insert or update one spec — no full-registry round trip."""
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO chats (tenant_id, id, session_id, user_id, "
                    "owner_id, channel, name, status, pinned, archived_at, "
                    "source, meta, created_at, updated_at) "
                    "VALUES (:tenant_id, :id, :session_id, :user_id, "
                    ":owner_id, :channel, :name, :status, :pinned, "
                    ":archived_at, :source, CAST(:meta AS JSONB), "
                    ":created_at, :updated_at) "
                    "ON CONFLICT (tenant_id, id) DO UPDATE SET "
                    "session_id = EXCLUDED.session_id, "
                    "user_id = EXCLUDED.user_id, "
                    "owner_id = EXCLUDED.owner_id, "
                    "channel = EXCLUDED.channel, "
                    "name = EXCLUDED.name, "
                    "status = EXCLUDED.status, "
                    "pinned = EXCLUDED.pinned, "
                    "archived_at = EXCLUDED.archived_at, "
                    "source = EXCLUDED.source, "
                    "meta = EXCLUDED.meta, "
                    "created_at = EXCLUDED.created_at, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                _spec_to_values(spec, self._tenant_id),
            )

    async def touch_chat_by_session(
        self,
        session_id: str,
        channel: str,
        user_id: str | None = None,
    ) -> Optional[ChatSpec]:
        """Touch the most recent matching chat in one UPDATE."""
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            if user_id:
                result = await conn.execute(
                    text(
                        "UPDATE chats SET updated_at = :now WHERE "
                        "tenant_id = :tid AND id = ("
                        "  SELECT id FROM chats WHERE tenant_id = :tid "
                        "  AND session_id = :sid AND channel = :chan "
                        "  AND user_id = :uid "
                        "  ORDER BY updated_at DESC LIMIT 1"
                        ") RETURNING id, session_id, user_id, owner_id, "
                        "channel, name, status, pinned, archived_at, "
                        "source, meta, created_at, updated_at"
                    ),
                    {
                        "now": datetime.now(timezone.utc),
                        "tid": self._tenant_id,
                        "sid": session_id,
                        "chan": channel,
                        "uid": user_id,
                    },
                )
            else:
                result = await conn.execute(
                    text(
                        "UPDATE chats SET updated_at = :now WHERE "
                        "tenant_id = :tid AND id = ("
                        "  SELECT id FROM chats WHERE tenant_id = :tid "
                        "  AND session_id = :sid AND channel = :chan "
                        "  ORDER BY updated_at DESC LIMIT 1"
                        ") RETURNING id, session_id, user_id, owner_id, "
                        "channel, name, status, pinned, archived_at, "
                        "source, meta, created_at, updated_at"
                    ),
                    {
                        "now": datetime.now(timezone.utc),
                        "tid": self._tenant_id,
                        "sid": session_id,
                        "chan": channel,
                    },
                )
            row = result.first()
            return _row_to_spec(row._mapping) if row else None

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        if not chat_ids:
            return False
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM chats WHERE tenant_id = :tid "
                    "AND id = ANY(:ids)",
                ),
                {"tid": self._tenant_id, "ids": chat_ids},
            )
            return result.rowcount > 0

    async def filter_chats(
        self,
        user_id: Optional[str] = None,
        channel: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> list[ChatSpec]:
        from sqlalchemy import text

        clauses = ["tenant_id = :tid"]
        params: dict = {"tid": self._tenant_id}
        if user_id is not None:
            clauses.append("user_id = :uid")
            params["uid"] = user_id
        if channel is not None:
            clauses.append("channel = :chan")
            params["chan"] = channel
        if archived is True:
            clauses.append("archived_at IS NOT NULL")
        elif archived is False:
            clauses.append("archived_at IS NULL")

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, session_id, user_id, owner_id, channel, "
                    "name, status, pinned, archived_at, source, meta, "
                    "created_at, updated_at FROM chats WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY created_at, id",
                ),
                params,
            )
            return [_row_to_spec(row._mapping) for row in result]
