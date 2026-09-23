# -*- coding: utf-8 -*-
"""AuditLog — Audit records for each assert_policy + audit call.

Storage（SQLite 退役专项）: PostgreSQL ``audit_events`` 表（配置了
``QWENPAW_PG_DSN`` 时，权威存储）；未配置 PG 的个人部署降级为
append-only JSONL 文件（``governance/audit.jsonl``，按体量轮转）。
**不再使用 SQLite**。

- record() queues the event (non-blocking); a daemon writer thread
  flushes batches to the backend — call flush() when durability is needed
- query() supports filtering by workspace / agent / tool / decision /
  time range, with pagination
- purge() deletes expired records; total rows reaching 100k triggers
  auto-cleanup of the oldest 10k
- Legacy ``audit.db`` rows are imported once into the active backend
  (marker file ``audit.db.pg_backfilled``) then left untouched.

@author qingfeng
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

from .audit_store import create_audit_backend
from .policy import GovernanceDecision, ToolCallSpec

_logger = logging.getLogger(__name__)


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


def _event_from_row(row: dict) -> AuditEvent:
    """Construct an AuditEvent from a backend row dict."""
    extra = row.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (TypeError, json.JSONDecodeError):
            extra = {}
    return AuditEvent(
        ts=int(row.get("ts") or 0),
        workspace_dir=row.get("workspace_dir") or "",
        agent_id=row.get("agent_id") or "",
        session_id=row.get("session_id") or "",
        tool_name=row.get("tool_name") or "",
        target=row.get("target") or "",
        decision=row.get("decision") or "",
        reason=row.get("reason") or "",
        extra=extra if isinstance(extra, dict) else {},
        actor_id=row.get("actor_id") or "",
    )


def _backfill_legacy_sqlite(backend, db_path: Path) -> None:
    """One-time import of the legacy SQLite ``audit.db`` into the backend.

    Idempotent via the ``audit.db.pg_backfilled`` marker; best-effort —
    a failed import never blocks audit operation (the legacy file stays
    in place for a retry).
    """
    marker = db_path.parent / (db_path.name + ".pg_backfilled")
    if not db_path.is_file() or marker.exists():
        return
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT ts, workspace_dir, agent_id, session_id, tool_name, "
                "target, decision, reason, extra, actor_id "
                "FROM audit_events ORDER BY ts",
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        _logger.warning("Legacy audit.db read failed (skipped): %s", exc)
        return
    if not rows:
        marker.touch()
        return
    payload = []
    for row in rows:
        try:
            extra = json.loads(row["extra"]) if row["extra"] else {}
        except (TypeError, json.JSONDecodeError):
            extra = {}
        payload.append(
            {
                "ts": int(row["ts"]),
                "workspace_dir": row["workspace_dir"],
                "agent_id": row["agent_id"],
                "session_id": row["session_id"],
                "tool_name": row["tool_name"],
                "target": row["target"],
                "decision": row["decision"],
                "reason": row["reason"],
                "extra": extra,
                "actor_id": row["actor_id"] or "",
            },
        )
    backend.insert_batch(payload)
    marker.touch()
    _logger.info(
        "Imported %d legacy audit.db rows into %s",
        len(payload),
        type(backend).__name__,
    )


class AuditLog:
    """Append-only audit log, backend-agnostic, global singleton.

    Shared by multiple ResourceGovernor instances; each audit()
    call (typically after assert_policy()) invokes record().

    .. note:: Threading & async

        ``record()`` is non-blocking: events go onto an in-process
        queue and a daemon writer thread flushes them in batched
        writes to the backend (PG when configured, JSONL otherwise),
        so the event loop never waits on storage fsync. ``flush()``
        blocks until every queued event is durable; tests, graceful
        shutdown, and ``close()`` use it. Reads (``query``) are
        synchronous backend calls.
    """

    MAX_RECORDS = 100_000  # Threshold to trigger auto-cleanup
    PURGE_COUNT = 10_000  # Number of records to delete per cleanup
    _CHECK_INTERVAL = 1_000
    _FLUSH_INTERVAL_S = 0.2  # writer wakes at least this often
    _FLUSH_BATCH = 50  # or this many queued events, whichever first

    _instance: Optional[AuditLog] = None
    _instance_lock = threading.Lock()

    # Sentinel pushed onto the write queue to stop the writer thread.
    _STOP = object()

    @classmethod
    def get_instance(
        cls,
        db_dir: Optional[Path] = None,
    ) -> AuditLog:
        """Get the global singleton, initializing on first call.

        Args:
            db_dir: Optional directory for the storage files. Only
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
                cls._instance = cls._create(resolved_dir)
            return cls._instance

    @classmethod
    def close_instance(cls) -> None:
        """Close the process-wide singleton if it has been initialized."""
        with cls._instance_lock:
            instance = cls._instance
        if instance is not None:
            instance.close()

    @classmethod
    def _create(cls, governance_dir: Path) -> AuditLog:
        """Internal factory: create instance and initialize the backend."""
        obj = object.__new__(cls)
        obj._governance_dir = governance_dir
        governance_dir.mkdir(parents=True, exist_ok=True)
        obj._backend = create_audit_backend(governance_dir)
        # Legacy SQLite audit.db 一次性导入（幂等，best-effort）
        _backfill_legacy_sqlite(obj._backend, governance_dir / "audit.db")
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
        """Drain the write queue in batched transactions.

        Wakes on the flush interval or batch size; the STOP sentinel
        flushes the remainder and exits. ``task_done`` is signaled only
        after a batch is actually durable, so ``flush()``'s ``join()``
        truly waits for the rows to land. Write failures are logged but
        never propagate — an audit outage must not disrupt decisions.
        """
        pending: list[dict] = []
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

    def _flush_rows(self, rows: list[dict]) -> None:
        """Insert one batch via the backend; count-based auto-purge."""
        try:
            self._backend.insert_batch(rows)
            self._insert_count += len(rows)
            if self._insert_count >= self._CHECK_INTERVAL:
                self._insert_count = 0
                if self.count >= self.MAX_RECORDS:
                    self._auto_purge()
        except Exception as exc:  # noqa: BLE001 - audit must never raise
            _logger.error(
                "AuditLog._flush_rows: backend error (%d rows): %s",
                len(rows),
                exc,
                exc_info=True,
            )

    def flush(self) -> None:
        """Block until every queued audit event is durable."""
        self._write_queue.join()

    def close(self) -> None:
        """Close the backend and reset the singleton.

        Drains the write queue first (every queued event becomes durable),
        then stops the writer thread.
        """
        self._write_queue.put(AuditLog._STOP)
        self._write_queue.join()
        self._writer.join(timeout=5)
        self._backend.close()
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
        """
        try:
            self._write_queue.put(
                {
                    "ts": _now_unix_ms(),
                    "workspace_dir": workspace_dir,
                    "agent_id": tc_spec.agent_id,
                    "session_id": tc_spec.session_id,
                    "tool_name": tc_spec.tool_name,
                    "target": tc_spec.target,
                    "decision": str(decision.action.value),
                    "reason": decision.reason,
                    "extra": {},
                    # M4: who performed the call (trusted identity; may be
                    # empty for pre-M4 paths or anonymous turns).
                    "actor_id": getattr(tc_spec, "user_id", "") or "",
                },
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

        Returns:
            (events, total) — event list and total count of matching
            records. Returns ``([], 0)`` on backend error so callers
            (e.g. the Console UI) get a safe empty page rather than an
            unhandled exception.
        """
        try:
            rows, total = self._backend.query(
                workspace_dir=workspace_dir,
                agent_id=agent_id,
                tool_name=tool_name,
                decision=decision,
                since=since,
                until=until,
                limit=limit,
                offset=offset,
            )
            return [_event_from_row(r) for r in rows], total
        except Exception as e:  # noqa: BLE001 - reads degrade to empty
            _logger.error(
                "AuditLog.query: backend error: %s",
                e,
                exc_info=True,
            )
            return [], 0

    def purge(self, before: int) -> int:
        """Delete records before the specified time.

        Args:
            before: Cutoff time (unix ms, UTC), exclusive

        Returns:
            Number of deleted records, or ``0`` on backend error.
        """
        try:
            return self._backend.purge_before(before)
        except Exception as e:  # noqa: BLE001
            _logger.error(
                "AuditLog.purge: backend error: %s",
                e,
                exc_info=True,
            )
            return 0

    @property
    def count(self) -> int:
        """Total number of records."""
        try:
            return self._backend.count()
        except Exception:  # noqa: BLE001
            return 0

    def _auto_purge(self) -> None:
        """Delete the oldest PURGE_COUNT records (caller holds ``_lock``)."""
        deleted = self._backend.purge_oldest(self.PURGE_COUNT)
        if deleted:
            _logger.info(
                "AuditLog: auto-purged %d oldest records.",
                deleted,
            )


atexit.register(AuditLog.close_instance)
