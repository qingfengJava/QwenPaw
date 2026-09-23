# -*- coding: utf-8 -*-
"""PostgreSQL history store (M2).

Implements the synchronous ``BaseHistoryStore`` contract over the
``history_entries`` table. The contract is sync (the SQLite reference uses a
guarded connection), so this store owns a dedicated event-loop thread and
bridges every call with ``run_coroutine_threadsafe`` — callers keep their
sync semantics, the database keeps the pooled asyncpg driver.

Durability flags mirror the file backend: a failed write flips ``degraded``
and increments ``write_failures``; ``quarantined_to`` stays ``None`` (there
is no local file to quarantine).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from ....db.async_bridge import AsyncLoopThread
from ..types import LogEntry
from .base_history import METADATA_UNSET, BaseHistoryStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_UNSET = METADATA_UNSET


def _json_text(value: Any) -> str | None:
    """Serialize a JSONB-bound value for ``text()`` statements.

    ``text()`` parameters carry no column type context, so JSONB values are
    sent as JSON strings with an explicit ``CAST(... AS JSONB)`` at the SQL
    site.
    """
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


class PgHistoryStore(BaseHistoryStore):
    """Synchronous BaseHistoryStore façade over async PostgreSQL.

    Owns its engine: asyncpg connections are loop-affine, so sharing the
    process-wide pool with the FastAPI loop would break with "attached to a
    different loop". The store therefore builds a small private pool on its
    own loop thread from the given DSN.
    """

    def __init__(
        self,
        dsn: str,
        tenant_id: str = "default",
        identity: Optional[str] = None,
    ) -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        # ``path`` identifies the storage location; for PG that is the
        # (redacted) identity passed by the factory, never credentials.
        self._identity = identity or "postgresql://history_entries"
        self.degraded = False
        self.write_failures = 0
        self.quarantined_to = None
        self._closed = False
        self._loop = AsyncLoopThread(thread_name="qwenpaw-pg-history")
        self._engine = self._loop.run(self._create_engine())

    async def _create_engine(self) -> "AsyncEngine":
        """Build the private pool on the store's own loop thread."""
        from sqlalchemy.ext.asyncio import create_async_engine

        return create_async_engine(
            self._dsn,
            pool_size=2,
            max_overflow=4,
            pool_pre_ping=True,
        )

    # -- lifecycle ---------------------------------------------------------

    @property
    def path(self) -> str:
        return self._identity

    @property
    def closed(self) -> bool:
        return self._closed

    def note_write_failure(self, exc: BaseException) -> None:
        self.degraded = True
        self.write_failures += 1
        logger.error("PgHistoryStore write failure: %s", exc)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.run(self._engine.dispose())
        except Exception:  # noqa: BLE001 - teardown must not raise
            pass
        self._loop.close()

    def _run(self, coro):
        try:
            return self._loop.run(coro)
        except Exception:
            self._closed = self._closed or self._loop._closed  # noqa: SLF001
            raise

    # -- async primitives ---------------------------------------------------

    @staticmethod
    def _entry_values(
        tenant_id: str,
        session_id: str,
        agent_id: str | None,
        owner_id: str | None,
        entry: LogEntry,
        dedup_key: str | None,
    ) -> dict:
        created = entry.created_at
        if isinstance(created, str) and created:
            created_at: datetime | None = datetime.fromisoformat(created)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        elif isinstance(created, datetime):
            created_at = created
        else:
            created_at = datetime.now(timezone.utc)
        return {
            "tid": tenant_id,
            "sid": session_id,
            "aid": agent_id,
            "oid": owner_id,
            "kind": entry.kind,
            "role": entry.role,
            "name": entry.name,
            "content": entry.content,
            "tcid": entry.tool_call_id,
            "tinput": _json_text(entry.tool_input),
            "tstate": entry.tool_state,
            "headline": entry.headline,
            "blocks": _json_text(entry.blocks),
            # The history schema canonically stores empty metadata as NULL.
            "meta": _json_text(entry.metadata) if entry.metadata else None,
            "created": created_at,
            "dedup": dedup_key,
        }

    _INSERT_SQL = (
        "INSERT INTO history_entries (tenant_id, session_id, agent_id, "
        "owner_id, kind, role, name, content, tool_call_id, tool_input, "
        "tool_state, headline, blocks, metadata, created_at, dedup_key) "
        "VALUES (:tid, :sid, :aid, :oid, :kind, :role, :name, :content, "
        ":tcid, CAST(:tinput AS JSONB), :tstate, :headline, "
        "CAST(:blocks AS JSONB), CAST(:meta AS JSONB), :created, "
        ":dedup) "
        "ON CONFLICT (tenant_id, session_id, dedup_key) "
        "WHERE dedup_key IS NOT NULL DO NOTHING "
        "RETURNING seq"
    )

    async def _append_async(self, values: dict) -> int:
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            result = await conn.execute(text(self._INSERT_SQL), values)
            row = result.first()
            if row is not None:
                return int(row[0])
            # Dedup conflict: return the existing row's seq (re-link only).
            existing = await conn.execute(
                text(
                    "SELECT seq FROM history_entries "
                    "WHERE tenant_id = :tid AND session_id = :sid "
                    "AND dedup_key = :dedup",
                ),
                {
                    "tid": values["tid"],
                    "sid": values["sid"],
                    "dedup": values["dedup"],
                },
            )
            found = existing.first()
            return int(found[0]) if found else 0

    # -- write path ----------------------------------------------------------

    def append(
        self,
        *,
        session_id: str,
        entry: LogEntry,
        agent_id: str | None = None,
        owner_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        """Write-through one event; dedup conflicts return the existing seq."""
        values = self._entry_values(
            self._tenant_id,
            session_id,
            agent_id,
            owner_id,
            entry,
            dedup_key,
        )
        try:
            return self._run(self._append_async(values))
        except Exception as exc:
            self.note_write_failure(exc)
            raise

    def append_many(
        self,
        *,
        session_id: str,
        entries: Sequence[tuple[LogEntry, str | None]],
        agent_id: str | None = None,
        owner_id: str | None = None,
    ) -> int:
        """Append a group of events in one transaction (dedup no-ops)."""
        if not entries:
            return 0

        async def _batch() -> int:
            from sqlalchemy import text

            inserted = 0
            async with self._engine.begin() as conn:
                for entry, dedup_key in entries:
                    values = self._entry_values(
                        self._tenant_id,
                        session_id,
                        agent_id,
                        owner_id,
                        entry,
                        dedup_key,
                    )
                    result = await conn.execute(
                        text(self._INSERT_SQL),
                        values,
                    )
                    if result.first() is not None:
                        inserted += 1
            return inserted

        try:
            return self._run(_batch())
        except Exception as exc:
            self.note_write_failure(exc)
            raise

    def update_entry(
        self,
        seq: int,
        *,
        content: str | None,
        headline: str | None,
        blocks,
        tool_call_id: str | None = None,
        name: str | None = None,
        tool_state: str | None = None,
        tool_input: Any = None,
        metadata: Any = _UNSET,
    ) -> None:
        """Refresh an already-appended row in place; ``seq`` unchanged."""

        async def _update() -> None:
            from sqlalchemy import text

            assignments = (
                "content = :content, headline = :headline, "
                "blocks = CAST(:blocks AS JSONB), tool_call_id = :tcid, "
                "name = :name, tool_state = :tstate, "
                "tool_input = CAST(:tinput AS JSONB)"
            )
            params: dict[str, Any] = {
                "seq": seq,
                "tid": self._tenant_id,
                "content": content,
                "headline": headline,
                "blocks": _json_text(blocks),
                "tcid": tool_call_id,
                "name": name,
                "tstate": tool_state,
                "tinput": _json_text(tool_input),
            }
            if metadata is not _UNSET:
                assignments += ", metadata = CAST(:meta AS JSONB)"
                params["meta"] = _json_text(metadata) if metadata else None
            async with self._engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE history_entries SET " + assignments
                        + " WHERE tenant_id = :tid AND seq = :seq",
                    ),
                    params,
                )

        try:
            self._run(_update())
        except Exception as exc:
            self.note_write_failure(exc)
            raise

    # -- read path -----------------------------------------------------------

    def count(self, session_id: str) -> int:
        async def _count() -> int:
            from sqlalchemy import text

            async with self._engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM history_entries "
                        "WHERE tenant_id = :tid AND session_id = :sid",
                    ),
                    {"tid": self._tenant_id, "sid": session_id},
                )
                return int(result.scalar() or 0)

        return self._run(_count())

    def claim_session(self, session_id: str, agent_id: str | None) -> int:
        """Assign legacy unowned rows in a canonical session to an agent."""
        if not session_id or not agent_id:
            return 0

        async def _claim() -> int:
            from sqlalchemy import text

            async with self._engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "UPDATE history_entries SET agent_id = :aid "
                        "WHERE tenant_id = :tid AND session_id = :sid "
                        "AND agent_id IS NULL",
                    ),
                    {
                        "aid": agent_id,
                        "tid": self._tenant_id,
                        "sid": session_id,
                    },
                )
                return int(result.rowcount or 0)

        try:
            return self._run(_claim())
        except Exception as exc:
            self.note_write_failure(exc)
            raise

    def reconcile_session_rows(
        self,
        source_ids: set[str],
        target_id: str,
        dedup_keys: set[str],
        *,
        agent_id: str | None = None,
    ) -> tuple[int, int, int]:
        """Move proven rows into the canonical session (dedup-safe)."""
        sources = sorted(
            source_id
            for source_id in source_ids
            if source_id and source_id != target_id
        )
        keys = sorted(str(key) for key in dedup_keys if key)
        if not sources or not target_id or not keys:
            return (0, 0, self.claim_session(target_id, agent_id))

        async def _reconcile() -> tuple[int, int, int]:
            from sqlalchemy import text

            moved = 0
            deduplicated = 0
            claimed = 0
            async with self._engine.begin() as conn:
                for source_id in sources:
                    rows = (
                        await conn.execute(
                            text(
                                "SELECT seq, dedup_key FROM history_entries "
                                "WHERE tenant_id = :tid AND session_id = :src "
                                "AND dedup_key = ANY(:keys)"
                                + (
                                    " AND (agent_id = :aid "
                                    "OR agent_id IS NULL)"
                                    if agent_id
                                    else ""
                                ),
                            ),
                            {
                                "tid": self._tenant_id,
                                "src": source_id,
                                "keys": keys,
                                **({"aid": agent_id} if agent_id else {}),
                            },
                        )
                    ).fetchall()
                    if not rows:
                        continue
                    row_keys = [str(r._mapping["dedup_key"]) for r in rows]
                    existing = (
                        await conn.execute(
                            text(
                                "SELECT dedup_key FROM history_entries "
                                "WHERE tenant_id = :tid AND session_id = :tgt "
                                "AND dedup_key = ANY(:keys)",
                            ),
                            {
                                "tid": self._tenant_id,
                                "tgt": target_id,
                                "keys": row_keys,
                            },
                        )
                    ).fetchall()
                    existing_keys = {
                        str(r._mapping["dedup_key"]) for r in existing
                    }
                    duplicates = [
                        int(r._mapping["seq"])
                        for r in rows
                        if str(r._mapping["dedup_key"]) in existing_keys
                    ]
                    movable = [
                        int(r._mapping["seq"])
                        for r in rows
                        if str(r._mapping["dedup_key"]) not in existing_keys
                    ]
                    if duplicates:
                        await conn.execute(
                            text(
                                "DELETE FROM history_entries "
                                "WHERE tenant_id = :tid AND seq = ANY(:seqs)",
                            ),
                            {"tid": self._tenant_id, "seqs": duplicates},
                        )
                        deduplicated += len(duplicates)
                    if movable:
                        result = await conn.execute(
                            text(
                                "UPDATE history_entries SET session_id = :tgt,"
                                " agent_id = COALESCE(agent_id, :aid) "
                                "WHERE tenant_id = :tid AND seq = ANY(:seqs)",
                            ),
                            {
                                "tid": self._tenant_id,
                                "tgt": target_id,
                                "aid": agent_id,
                                "seqs": movable,
                            },
                        )
                        moved += int(result.rowcount or 0)
                if agent_id:
                    result = await conn.execute(
                        text(
                            "UPDATE history_entries SET agent_id = :aid "
                            "WHERE tenant_id = :tid AND session_id = :tgt "
                            "AND agent_id IS NULL",
                        ),
                        {
                            "tid": self._tenant_id,
                            "tgt": target_id,
                            "aid": agent_id,
                        },
                    )
                    claimed = int(result.rowcount or 0)
            return (moved, deduplicated, claimed)

        try:
            return self._run(_reconcile())
        except Exception as exc:
            self.note_write_failure(exc)
            raise

    def existing_seqs(self, seqs: set[int]) -> set[int]:
        """Return the subset of globally addressed rows that exist."""
        if not seqs:
            return set()

        async def _check() -> set[int]:
            from sqlalchemy import text

            async with self._engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT seq FROM history_entries "
                        "WHERE tenant_id = :tid AND seq = ANY(:seqs)",
                    ),
                    {"tid": self._tenant_id, "seqs": sorted(seqs)},
                )
                return {int(r[0]) for r in result}

        return self._run(_check())

    def contents_by_seqs(self, seqs: set[int]) -> dict[int, str | None]:
        """Return exact persisted content for globally addressed rows."""
        if not seqs:
            return {}

        async def _fetch() -> dict[int, str | None]:
            from sqlalchemy import text

            async with self._engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT seq, content FROM history_entries "
                        "WHERE tenant_id = :tid AND seq = ANY(:seqs)",
                    ),
                    {"tid": self._tenant_id, "seqs": sorted(seqs)},
                )
                return {int(r[0]): r[1] for r in result}

        return self._run(_fetch())

    # -- retention / maintenance ----------------------------------------------

    def _purge_params(
        self,
        before: str,
        kinds: tuple[str, ...] | None,
    ) -> tuple[str, dict]:
        cutoff = datetime.fromisoformat(before)
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        where = "tenant_id = :tid AND created_at < :before"
        params: dict[str, Any] = {"tid": self._tenant_id, "before": cutoff}
        if kinds:
            where += " AND kind = ANY(:kinds)"
            params["kinds"] = list(kinds)
        return where, params

    def estimate_purge(
        self,
        *,
        before: str,
        kinds: tuple[str, ...] | None = None,
    ) -> dict:
        """Dry-run estimate of what ``purge(before=...)`` would remove."""
        where, params = self._purge_params(before, kinds)

        async def _estimate() -> dict:
            from sqlalchemy import text

            async with self._engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT COUNT(*), COALESCE(SUM(octet_length("
                        "coalesce(content, ''))), 0) FROM history_entries "
                        "WHERE " + where,
                    ),
                    params,
                )
                row = result.first()
                return {
                    "rows": int(row[0] or 0),
                    "content_bytes": int(row[1] or 0),
                }

        return self._run(_estimate())

    def purge(
        self,
        *,
        before: str,
        dry_run: bool = False,
        kinds: tuple[str, ...] | None = None,
    ) -> int:
        """Delete history rows with ``created_at < before`` (ISO-8601)."""
        if dry_run:
            return int(self.estimate_purge(before=before, kinds=kinds)["rows"])
        where, params = self._purge_params(before, kinds)

        async def _purge() -> int:
            from sqlalchemy import text

            async with self._engine.begin() as conn:
                result = await conn.execute(
                    text("DELETE FROM history_entries WHERE " + where),
                    params,
                )
                return int(result.rowcount or 0)

        try:
            return self._run(_purge())
        except Exception as exc:
            self.note_write_failure(exc)
            raise

    def vacuum(self) -> None:
        """No-op: PostgreSQL autovacuum reclaims purge space by itself.

        A manual ``VACUUM`` cannot run inside a transaction or pooled
        connection; the contract explicitly allows a backend-specific no-op.
        """
