# -*- coding: utf-8 -*-
"""Abstract history store contract for scroll conversation history.

The SQLite-backed ``HistoryStore`` in ``history.py`` is the reference
implementation; this contract exists so a PostgreSQL-backed store (M2
milestone) can replace it behind the workspace wiring without touching
``MemorySpace`` or the runtime.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from ..types import LogEntry

# Sentinel for "argument omitted" on ``update_entry`` — distinct from None,
# which is a storable value. Shared by all implementations so caller-side
# default handling stays identical across backends.
METADATA_UNSET: Any = object()


class BaseHistoryStore(ABC):
    """Abstract write-through store for durable conversation history.

    Implementations must also expose these attributes (enforced by the
    storage contract tests rather than the ABC, so backends may keep plain
    instance attributes):

    - ``path``: location identity of the underlying storage
    - ``degraded``: True once a write-through failure broke durability
    - ``write_failures``: cumulative count of write-through failures
    - ``quarantined_to``: path of a quarantined corrupt store, if any
    - ``closed``: True after :meth:`close` has run
    """

    # --- write path ----------------------------------------------------

    @abstractmethod
    def append(
        self,
        *,
        session_id: str,
        entry: LogEntry,
        agent_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        """Write-through one event. Returns the assigned ``seq`` watermark.

        A second append carrying the same ``(session_id, dedup_key)`` is a
        no-op returning the *existing* seq; a ``None`` key is never deduped.
        """
        raise NotImplementedError

    @abstractmethod
    def append_many(
        self,
        *,
        session_id: str,
        entries: Sequence[tuple[LogEntry, str | None]],
        agent_id: str | None = None,
    ) -> int:
        """Append a group of events in one transaction.

        Returns the number of newly inserted rows; duplicate keys remain
        no-ops, matching :meth:`append`.
        """
        raise NotImplementedError

    @abstractmethod
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
        metadata: Any = METADATA_UNSET,
    ) -> None:
        """Refresh an already-appended row in place; ``seq`` is unchanged.

        Omitting ``metadata`` (the ``METADATA_UNSET`` default) keeps the
        stored value unchanged.
        """
        raise NotImplementedError

    # --- read path -----------------------------------------------------

    @abstractmethod
    def count(self, session_id: str) -> int:
        """Return the number of rows stored for one session."""
        raise NotImplementedError

    @abstractmethod
    def claim_session(self, session_id: str, agent_id: str | None) -> int:
        """Assign legacy unowned rows in a canonical session to an agent."""
        raise NotImplementedError

    @abstractmethod
    def reconcile_session_rows(
        self,
        source_ids: set[str],
        target_id: str,
        dedup_keys: set[str],
        *,
        agent_id: str | None = None,
    ) -> tuple[int, int, int]:
        """Move rows proven to come from one file into its canonical session.

        Returns ``(moved, deduplicated, claimed)``.
        """
        raise NotImplementedError

    @abstractmethod
    def existing_seqs(self, seqs: set[int]) -> set[int]:
        """Return the subset of globally addressed history rows that exist."""
        raise NotImplementedError

    @abstractmethod
    def contents_by_seqs(self, seqs: set[int]) -> dict[int, str | None]:
        """Return exact persisted content for globally addressed rows."""
        raise NotImplementedError

    # --- retention / maintenance ---------------------------------------

    @abstractmethod
    def estimate_purge(
        self,
        *,
        before: str,
        kinds: tuple[str, ...] | None = None,
    ) -> dict:
        """Dry-run estimate of what ``purge(before=...)`` would remove.

        Returns ``{"rows": n, "content_bytes": b}``.
        """
        raise NotImplementedError

    @abstractmethod
    def purge(
        self,
        *,
        before: str,
        dry_run: bool = False,
        kinds: tuple[str, ...] | None = None,
    ) -> int:
        """Delete history rows with ``created_at < before`` (ISO-8601)."""
        raise NotImplementedError

    @abstractmethod
    def vacuum(self) -> None:
        """Reclaim space freed by :meth:`purge` (backend-specific no-op ok)."""
        raise NotImplementedError

    # --- durability / lifecycle -----------------------------------------

    @abstractmethod
    def note_write_failure(self, exc: BaseException) -> None:
        """Record a write-through failure; durability is degraded afterwards."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Close the store; the storage itself is never dropped."""
        raise NotImplementedError
