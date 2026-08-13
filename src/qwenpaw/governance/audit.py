# -*- coding: utf-8 -*-
"""AuditLog — Audit records for each assert_policy + audit call.

Storage: single-file SQLite (~/.qwenpaw/audit.db), global singleton.
- record() queues the event (non-blocking); a daemon writer thread
  flushes batches to SQLite — call flush() when durability is needed
- query() supports filtering by workspace / agent / tool / decision /
  time range, with pagination
- purge() deletes expired records and VACUUMs to reclaim space
- Auto-cleanup: when total records reach 100k, deletes the oldest 10k
"""

from __future__ import annotations

import atexit
import json
import logging
import queue
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from ..constant import WORKING_DIR

from .policy import GovernanceDecision, ToolCallSpec

_logger = logging.getLogger(__name__)

# ``ts`` is stored as INTEGER (milliseconds since epoch, UTC) so that
# ``WHERE ts >= ? / <= ?`` performs strict numeric comparison instead of
# fragile lexicographic comparison on ISO 8601 strings.
_SCHEMA = """\
CREATE TABLE IF NOT EXISTS audit_events (
    ts            INTEGER NOT NULL,
    workspace_dir TEXT NOT NULL,
    agent_id      TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    target        TEXT NOT NULL,
    decision      TEXT NOT NULL,
    reason        TEXT NOT NULL DEFAULT '',
    extra         TEXT NOT NULL DEFAULT '{}',
    actor_id      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts);
CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_events(workspace_dir);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_events(tool_name);
"""


def _now_unix_ms() -> int:
    """Return current UTC timestamp in milliseconds since epoch."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


@dataclass
class AuditEvent:
    """A single audit record.

    Records 5W: who (agent_id), what (tool_name + target),
    when (ts), outcome (decision), why (reason).
    """

    ts: int  # Milliseconds since epoch, UTC
    workspace_dir: str
    agent_id: str
    session_id: str
    tool_name: str
    target: str
    decision: str  # "allow" | "deny" | "ask" | "sandbox_fallback"
    reason: str = ""  # Additional explanation (e.g. violation cause)
    extra: dict = field(default_factory=dict)
    # M4: the trusted user identity behind the call ("" when anonymous).
    actor_id: str = ""


def _event_from_row(row: sqlite3.Row) -> AuditEvent:
    """Construct an AuditEvent from a SQLite row."""
    try:
        actor_id = row["actor_id"]
    except (KeyError, IndexError):
        # Pre-M4 rows on an unmigrated database have no actor column.
        actor_id = ""
    return AuditEvent(
        ts=row["ts"],
        workspace_dir=row["workspace_dir"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        tool_name=row["tool_name"],
        target=row["target"],
        decision=row["decision"],
        reason=row["reason"],
        extra=json.loads(row["extra"]),
        actor_id=actor_id,
    )


class AuditLog:
    """Append-only audit log, SQLite-backed, global singleton.

    Shared by multiple ResourceGovernor instances; each audit()
    call (typically after assert_policy()) invokes record().

    .. note:: Threading & async

        ``record()`` is non-blocking (M2): events go onto an in-process
        queue and a daemon writer thread flushes them in batched
        transactions, so the event loop never waits on SQLite fsync.
        ``flush()`` blocks until every queued event is durable; tests,
        graceful shutdown, and ``close()`` use it. Reads (``query``)
        stay synchronous on the shared connection.
    """

    MAX_RECORDS = 100_000  # Threshold to trigger auto-cleanup
    PURGE_COUNT = 10_000  # Number of records to delete per cleanup
    _CHECK_INTERVAL = 1_000
    _FLUSH_INTERVAL_S = 0.2  # writer wakes at least this often
    _FLUSH_BATCH = 50  # or this many queued events, whichever first

    _instance: Optional[AuditLog] = None
    _instance_lock = threading.Lock()
    _db_path: Path
    _conn: Optional[sqlite3.Connection]
    _insert_count: int
    _lock: threading.RLock

    # Sentinel pushed onto the write queue to stop the writer thread.
    _STOP = object()

    @classmethod
    def get_instance(
        cls,
        db_dir: Optional[Path] = None,
    ) -> AuditLog:
        """Get the global singleton, initializing on first call.

        Args:
            db_dir: Optional directory to place ``audit.db`` in. Only
                honored on first creation; if the singleton already
                exists in a different directory, the request is logged
                and ignored (the singleton stays shared).
        """
        with cls._instance_lock:
            if cls._instance is None:
                if db_dir is not None:
                    resolved_dir = Path(db_dir)
                else:
                    resolved_dir = WORKING_DIR / "governance"
                cls._instance = cls._create(resolved_dir / "audit.db")
            return cls._instance

    @classmethod
    def close_instance(cls) -> None:
        """Close the process-wide singleton if it has been initialized."""
        with cls._instance_lock:
            instance = cls._instance
        if instance is not None:
            instance.close()

    @classmethod
    def _create(cls, db_path: Path) -> AuditLog:
        """Internal factory method: create instance and initialize database."""
        obj = object.__new__(cls)
        obj._db_path = db_path
        obj._db_path.parent.mkdir(parents=True, exist_ok=True)
        obj._conn = sqlite3.connect(
            str(obj._db_path),
            check_same_thread=False,
        )
        obj._conn.row_factory = sqlite3.Row
        obj._conn.execute("PRAGMA journal_mode=WAL")
        # Drop legacy schema where ``ts`` was TEXT (ISO 8601). Audit data
        # written before the migration is discarded; this is acceptable
        # while the feature is still pre-release.
        cls._migrate_legacy_schema(obj._conn)
        obj._conn.executescript(_SCHEMA)
        obj._conn.commit()
        obj._insert_count = 0
        obj._lock = threading.RLock()
        obj._write_queue: queue.Queue = queue.Queue()
        obj._writer = threading.Thread(
            target=obj._writer_loop,
            name="qwenpaw-audit-writer",
            daemon=True,
        )
        obj._writer.start()
        return obj

    def _writer_loop(self) -> None:
        """Drain the write queue in batched transactions (M2).

        Wakes on the flush interval or batch size; the STOP sentinel
        flushes the remainder and exits. ``task_done`` is signaled only
        after a batch is actually durable, so ``flush()``'s ``join()``
        truly waits for the rows to land. Write failures are logged but
        never propagate — an audit outage must not disrupt decisions.
        """
        pending: list[tuple] = []
        while True:
            try:
                item = self._write_queue.get(timeout=self._FLUSH_INTERVAL_S)
            except queue.Empty:
                item = None
            if item is AuditLog._STOP:
                if pending:
                    self._flush_rows(pending)
                    for _ in pending:
                        self._write_queue.task_done()
                self._write_queue.task_done()
                return
            if item is not None:
                pending.append(item)
            if pending and (item is None or len(pending) >= self._FLUSH_BATCH):
                self._flush_rows(pending)
                for _ in pending:
                    self._write_queue.task_done()
                pending.clear()

    def _flush_rows(self, rows: list[tuple]) -> None:
        """Insert one batch in a single transaction."""
        try:
            with self._lock:
                conn = self._conn
                if conn is None:
                    return
                conn.executemany(
                    "INSERT INTO audit_events "
                    "(ts, workspace_dir, agent_id, session_id, "
                    "tool_name, target, decision, reason, extra, actor_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                conn.commit()
                self._insert_count += len(rows)
                if self._insert_count >= self._CHECK_INTERVAL:
                    self._insert_count = 0
                    if self.count >= self.MAX_RECORDS:
                        self._auto_purge()
        except sqlite3.Error as exc:
            _logger.error(
                "AuditLog._flush_rows: SQLite error (%d rows): %s",
                len(rows),
                exc,
                exc_info=True,
            )

    def flush(self) -> None:
        """Block until every queued audit event is durable."""
        self._write_queue.join()

    @staticmethod
    def _migrate_legacy_schema(conn: sqlite3.Connection) -> None:
        """Drop the table if its ``ts`` column was created as TEXT.

        M4: also backfills the ``actor_id`` column onto pre-M4 tables
        (idempotent ALTER, following the same in-place pattern).
        """
        cursor = conn.execute("PRAGMA table_info(audit_events)")
        rows = cursor.fetchall()
        for row in rows:
            # row: (cid, name, type, notnull, dflt_value, pk)
            if row[1] == "ts" and row[2].upper() != "INTEGER":
                conn.execute("DROP TABLE audit_events")
                conn.commit()
                return
        if rows and not any(row[1] == "actor_id" for row in rows):
            conn.execute(
                "ALTER TABLE audit_events "
                "ADD COLUMN actor_id TEXT NOT NULL DEFAULT ''",
            )
            conn.commit()

    def close(self) -> None:
        """Close the database connection and reset the singleton.

        Drains the write queue first (every queued event becomes durable),
        then stops the writer thread. Runs VACUUM before closing to
        reclaim space from any prior auto-purge DELETE operations
        (VACUUM is intentionally NOT run inside ``_auto_purge`` to avoid
        blocking the event loop).
        """
        self._write_queue.put(AuditLog._STOP)
        self._write_queue.join()
        self._writer.join(timeout=5)
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("VACUUM")
                except sqlite3.Error:
                    pass
                self._conn.close()
                self._conn = None
        with AuditLog._instance_lock:
            if AuditLog._instance is self:
                AuditLog._instance = None

    def record(
        self,
        workspace_dir: str,
        tc_spec: ToolCallSpec,
        decision: GovernanceDecision,
    ) -> None:
        """Record a policy decision (queued; flushed by the writer thread).

        Args:
            workspace_dir: Workspace path this event belongs to
            tc_spec: ToolCallSpec instance
            decision: GovernanceDecision instance (action + reason)
        Errors are caught and logged: an audit-write failure must NOT
        propagate into ``assert_policy`` and disrupt the policy
        decision returned to the caller.

        ``audit_level == "none"`` is handled by
        ``ResourceGovernor.audit()`` before this method is called.
        If finer-grained filtering is needed later (for example,
        ``"write_only"``), apply it at the INSERT boundary.

        M2: the event is queued and flushed by the writer thread; this
        method never blocks on SQLite. A full queue would block — the
        unbounded queue trades that for never dropping audit events.
        """
        try:
            self._write_queue.put(
                (
                    _now_unix_ms(),
                    workspace_dir,
                    tc_spec.agent_id,
                    tc_spec.session_id,
                    tc_spec.tool_name,
                    tc_spec.target,
                    str(decision.action.value),
                    decision.reason,
                    "{}",
                    # M4: who performed the call (trusted identity; may be
                    # empty for pre-M4 paths or anonymous turns).
                    getattr(tc_spec, "user_id", "") or "",
                ),
            )
        except Exception as e:  # noqa: BLE001 - audit must never raise
            _logger.error(
                "AuditLog.record: queue error (tool=%s, target=%r): %s",
                tc_spec.tool_name,
                (tc_spec.target or "")[:120],
                e,
                exc_info=True,
            )

    def query(
        self,
        workspace_dir: Optional[str] = None,
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        decision: Optional[str] = None,
        since: Optional[int] = None,
        until: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[AuditEvent], int]:
        """Query audit events with pagination.

        Args:
            workspace_dir: Filter by workspace
            agent_id: Filter by agent
            tool_name: Filter by tool name
            decision: Filter by decision result
            since: Start time (unix ms, UTC), inclusive
            until: End time (unix ms, UTC), inclusive
            limit: Page size
            offset: Offset (for pagination)

        Returns:
            (events, total) — event list and total count of matching
            records. Returns ``([], 0)`` if a SQLite error occurs so
            callers (e.g. the Console UI) get a safe empty page rather
            than an unhandled exception.
        """
        clauses: list[str] = []
        params: list = []

        if workspace_dir:
            clauses.append("workspace_dir = ?")
            params.append(workspace_dir)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        if decision:
            clauses.append("decision = ?")
            params.append(decision)
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if until:
            clauses.append("ts <= ?")
            params.append(until)

        where = " WHERE " + " AND ".join(clauses) if clauses else ""

        try:
            with self._lock:
                conn = self._conn
                if conn is None:
                    return [], 0
                count_sql = f"SELECT COUNT(*) FROM audit_events{where}"
                total = conn.execute(count_sql, params).fetchone()[0]

                data_sql = (
                    f"SELECT * FROM audit_events{where} "
                    "ORDER BY ts DESC LIMIT ? OFFSET ?"
                )
                data_params = params + [limit, offset]
                rows = conn.execute(data_sql, data_params).fetchall()

                return [_event_from_row(r) for r in rows], total
        except sqlite3.Error as e:
            _logger.error(
                "AuditLog.query: SQLite error: %s",
                e,
                exc_info=True,
            )
            return [], 0

    def purge(self, before: int) -> int:
        """Delete records before the specified time and VACUUM to
        reclaim space.

        Args:
            before: Cutoff time (unix ms, UTC), exclusive

        Returns:
            Number of deleted records, or ``0`` on SQLite error.
        """
        try:
            with self._lock:
                conn = self._conn
                if conn is None:
                    return 0
                cursor = conn.execute(
                    "DELETE FROM audit_events WHERE ts < ?",
                    (before,),
                )
                conn.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    conn.execute("VACUUM")
                return deleted
        except sqlite3.Error as e:
            _logger.error(
                "AuditLog.purge: SQLite error: %s",
                e,
                exc_info=True,
            )
            return 0

    @property
    def count(self) -> int:
        """Total number of records."""
        with self._lock:
            if self._conn is None:
                return 0
            return self._conn.execute(
                "SELECT COUNT(*) FROM audit_events",
            ).fetchone()[0]

    def _auto_purge(self) -> None:
        """Delete the oldest PURGE_COUNT records (caller holds ``_lock``).

        VACUUM is intentionally deferred to ``close()`` to avoid blocking
        the event loop for seconds on a large database.
        """
        # ``OFFSET PURGE_COUNT - 1`` returns the rowid of the PURGE_COUNT-th
        # oldest row; ``DELETE ... WHERE rowid <= ?`` then removes exactly
        # PURGE_COUNT rows. Using ``OFFSET PURGE_COUNT`` would have left an
        # off-by-one bug (deleting PURGE_COUNT + 1 rows).
        if self._conn is None:
            return
        row = self._conn.execute(
            "SELECT rowid FROM audit_events "
            "ORDER BY rowid ASC LIMIT 1 OFFSET ?",
            (self.PURGE_COUNT - 1,),
        ).fetchone()
        if row:
            self._conn.execute(
                "DELETE FROM audit_events WHERE rowid <= ?",
                (row["rowid"],),
            )
            self._conn.commit()
            _logger.info(
                "AuditLog: auto-purged %d oldest records "
                "(VACUUM deferred to close).",
                self.PURGE_COUNT,
            )


atexit.register(AuditLog.close_instance)
