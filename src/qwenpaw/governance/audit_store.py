# -*- coding: utf-8 -*-
"""Storage backends for the governance audit log (SQLite retirement).

Two backends implement the same synchronous interface consumed by
:class:`~qwenpaw.governance.audit.AuditLog`:

- :class:`PgAuditStore` — PostgreSQL ``audit_events`` table (the
  authoritative store when ``QWENPAW_PG_DSN`` is configured). Owns a
  private engine on a dedicated loop thread (asyncpg loop affinity),
  mirroring ``agents/context/scroll/pg_history.py``.
- :class:`JsonlAuditStore` — append-only JSONL file fallback for
  personal deployments without PostgreSQL. Rotates at a size bound so
  the file cannot grow without limit.

There is deliberately **no SQLite backend**: the legacy ``audit.db`` is
retired (its rows are imported once by the legacy backfill in
``audit.py``).

@author qingfeng
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..db.async_bridge import AsyncLoopThread
from ..db.base import DEFAULT_TENANT_ID

logger = logging.getLogger(__name__)

#: 行 dict 的固定键序（PG 插入与 JSONL 序列化共用）
_ROW_KEYS = (
    "ts",
    "workspace_dir",
    "agent_id",
    "session_id",
    "tool_name",
    "target",
    "decision",
    "reason",
    "extra",
    "actor_id",
)


class PgAuditStore:
    """PostgreSQL backend for the audit log (``audit_events`` table)."""

    _INSERT_SQL = (
        "INSERT INTO audit_events (tenant_id, ts, workspace_dir, agent_id, "
        "session_id, tool_name, target, decision, reason, extra, actor_id) "
        "VALUES (:tid, :ts, :workspace_dir, :agent_id, :session_id, "
        ":tool_name, :target, :decision, :reason, "
        "CAST(:extra AS JSONB), :actor_id)"
    )

    def __init__(self, dsn: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._closed = False
        self._loop = AsyncLoopThread(thread_name="qwenpaw-pg-audit")
        self._engine = self._loop.run(self._create_engine())

    async def _create_engine(self):
        from sqlalchemy.ext.asyncio import create_async_engine

        return create_async_engine(
            self._dsn,
            pool_size=2,
            max_overflow=4,
            pool_pre_ping=True,
        )

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.run(self._engine.dispose())
        except Exception:  # noqa: BLE001 - teardown must not raise
            pass
        self._loop.close()

    # -- write path ----------------------------------------------------------

    def insert_batch(self, rows: List[dict]) -> None:
        """Insert one batch of audit rows; failures are logged, not raised."""
        try:
            self._loop.run(self._insert_batch_async(rows))
        except Exception as exc:  # noqa: BLE001 - audit must never raise
            logger.error("PgAuditStore.insert_batch failed: %s", exc)

    async def _insert_batch_async(self, rows: List[dict]) -> None:
        from sqlalchemy import text

        params = [
            {**{k: row[k] for k in _ROW_KEYS}, "tid": self._tenant_id}
            for row in rows
        ]
        async with self._engine.begin() as conn:
            await conn.execute(text(self._INSERT_SQL), params)

    # -- read path ------------------------------------------------------------

    def query(
        self,
        *,
        workspace_dir: Optional[str] = None,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        decision: Optional[str] = None,
        since: Optional[int] = None,
        until: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[dict], int]:
        """Return (rows, total) with the same filter semantics as before."""
        try:
            return self._loop.run(
                self._query_async(
                    workspace_dir=workspace_dir,
                    agent_id=agent_id,
                    tool_name=tool_name,
                    decision=decision,
                    since=since,
                    until=until,
                    limit=limit,
                    offset=offset,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - reads degrade to empty
            logger.error("PgAuditStore.query failed: %s", exc)
            return [], 0

    async def _query_async(self, **kw) -> Tuple[List[dict], int]:
        from sqlalchemy import text

        clauses: list[str] = []
        params: dict = {"tid": self._tenant_id}
        if kw.get("workspace_dir"):
            clauses.append("workspace_dir = :workspace_dir")
            params["workspace_dir"] = kw["workspace_dir"]
        if kw.get("agent_id"):
            clauses.append("agent_id = :agent_id")
            params["agent_id"] = kw["agent_id"]
        if kw.get("tool_name"):
            clauses.append("tool_name = :tool_name")
            params["tool_name"] = kw["tool_name"]
        if kw.get("decision"):
            clauses.append("decision = :decision")
            params["decision"] = kw["decision"]
        if kw.get("since"):
            clauses.append("ts >= :since")
            params["since"] = int(kw["since"])
        if kw.get("until"):
            clauses.append("ts <= :until")
            params["until"] = int(kw["until"])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        async with self._engine.connect() as conn:
            total = (
                await conn.execute(
                    text(f"SELECT COUNT(*) FROM audit_events{where}"),
                    params,
                )
            ).scalar() or 0
            result = await conn.execute(
                text(
                    "SELECT ts, workspace_dir, agent_id, session_id, "
                    "tool_name, target, decision, reason, extra, actor_id "
                    f"FROM audit_events{where} "
                    "ORDER BY ts DESC, id DESC LIMIT :limit OFFSET :offset"
                ),
                {
                    **params,
                    "limit": int(kw.get("limit", 100)),
                    "offset": int(kw.get("offset", 0)),
                },
            )
            rows = [dict(r) for r in result.mappings().all()]
        return rows, int(total)

    def count(self) -> int:
        try:
            return self._loop.run(self._count_async())
        except Exception:  # noqa: BLE001
            return 0

    async def _count_async(self) -> int:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT COUNT(*) FROM audit_events"),
                )
            ).scalar() or 0

    def purge_oldest(self, count: int) -> int:
        """Delete the ``count`` oldest rows (auto-cleanup path)."""
        try:
            return self._loop.run(self._purge_oldest_async(count))
        except Exception as exc:  # noqa: BLE001
            logger.error("PgAuditStore.purge_oldest failed: %s", exc)
            return 0

    async def _purge_oldest_async(self, count: int) -> int:
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM audit_events WHERE id IN ("
                    "SELECT id FROM audit_events ORDER BY id ASC LIMIT :n)"
                ),
                {"n": int(count)},
            )
            return result.rowcount or 0

    def purge_before(self, before: int) -> int:
        """Delete rows with ``ts < before`` (legacy purge API)."""
        try:
            return self._loop.run(self._purge_before_async(before))
        except Exception as exc:  # noqa: BLE001
            logger.error("PgAuditStore.purge_before failed: %s", exc)
            return 0

    async def _purge_before_async(self, before: int) -> int:
        from sqlalchemy import text

        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM audit_events WHERE ts < :before"),
                {"before": int(before)},
            )
            return result.rowcount or 0


class JsonlAuditStore:
    """Append-only JSONL fallback (personal deployments without PG).

    Rotates ``audit.jsonl`` to ``audit.jsonl.1`` at a size bound; queries
    scan the live file plus the previous rotation, newest first.
    """

    ROTATE_BYTES = 32 * 1024 * 1024

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def _rotated(self) -> Path:
        return self._path.with_suffix(self._path.suffix + ".1")

    def _iter_rows(self) -> List[dict]:
        rows: list[dict] = []
        for candidate in (self._rotated, self._path):
            if not candidate.is_file():
                continue
            try:
                with open(candidate, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            except OSError as exc:
                logger.warning("JsonlAuditStore read failed: %s", exc)
        return rows

    def insert_batch(self, rows: List[dict]) -> None:
        try:
            with self._lock:
                if (
                    self._path.is_file()
                    and self._path.stat().st_size >= self.ROTATE_BYTES
                    and not self._rotated.exists()
                ):
                    self._path.replace(self._rotated)
                with open(self._path, "a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(
                            json.dumps(
                                {k: row[k] for k in _ROW_KEYS},
                                ensure_ascii=False,
                            )
                            + "\n",
                        )
        except OSError as exc:
            logger.error("JsonlAuditStore.insert_batch failed: %s", exc)

    @staticmethod
    def _matches(row: dict, **kw) -> bool:
        if kw.get("workspace_dir") and row.get("workspace_dir") != kw["workspace_dir"]:
            return False
        if kw.get("agent_id") and row.get("agent_id") != kw["agent_id"]:
            return False
        if kw.get("tool_name") and row.get("tool_name") != kw["tool_name"]:
            return False
        if kw.get("decision") and row.get("decision") != kw["decision"]:
            return False
        if kw.get("since") and int(row.get("ts") or 0) < int(kw["since"]):
            return False
        if kw.get("until") and int(row.get("ts") or 0) > int(kw["until"]):
            return False
        return True

    def query(self, **kw) -> Tuple[List[dict], int]:
        with self._lock:
            rows = self._iter_rows()
        matched = [r for r in rows if self._matches(r, **kw)]
        matched.sort(key=lambda r: int(r.get("ts") or 0), reverse=True)
        offset = int(kw.get("offset", 0))
        limit = int(kw.get("limit", 100))
        return matched[offset : offset + limit], len(matched)

    def count(self) -> int:
        with self._lock:
            return len(self._iter_rows())

    def purge_oldest(self, count: int) -> int:
        with self._lock:
            rows = self._iter_rows()
        keep = rows[count:]
        self._rewrite(keep)
        return len(rows) - len(keep)

    def purge_before(self, before: int) -> int:
        with self._lock:
            rows = self._iter_rows()
        keep = [r for r in rows if int(r.get("ts") or 0) >= int(before)]
        removed = len(rows) - len(keep)
        if removed:
            self._rewrite(keep)
        return removed

    def _rewrite(self, rows: List[dict]) -> None:
        try:
            with self._lock:
                tmp = self._path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(
                            json.dumps(
                                {k: row[k] for k in _ROW_KEYS},
                                ensure_ascii=False,
                            )
                            + "\n",
                        )
                tmp.replace(self._path)
        except OSError as exc:
            logger.error("JsonlAuditStore.rewrite failed: %s", exc)

    def close(self) -> None:
        return None


def create_audit_backend(governance_dir: Path) -> Any:
    """Pick the audit backend: PG when configured, JSONL otherwise."""
    from ..db.engine import get_pg_dsn

    dsn = get_pg_dsn()
    if dsn:
        return PgAuditStore(dsn)
    return JsonlAuditStore(governance_dir / "audit.jsonl")
