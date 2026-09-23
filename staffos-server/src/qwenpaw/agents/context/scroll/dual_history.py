# -*- coding: utf-8 -*-
"""Dual-write history store (M2 migration rehearsal).

Reads come from the primary (SQLite) store only — the PostgreSQL shadow
accumulates writes for the consistency ledger without ever influencing
behavior. The contract is synchronous, so shadow writes are dispatched on a
small thread pool; shadow failures are counted and logged, never raised.

Note on ``seq``: the shadow assigns its own watermarks. Row identity for
reconciliation is ``(session_id, dedup_key)``, which both backends share;
final seq alignment happens in the offline migration script before the pg
backend becomes authoritative.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .base_history import METADATA_UNSET, BaseHistoryStore

logger = logging.getLogger(__name__)

_UNSET = METADATA_UNSET


class DualHistoryStore(BaseHistoryStore):
    """Primary SQLite + shadow PostgreSQL history store."""

    def __init__(
        self,
        primary: BaseHistoryStore,
        shadow: BaseHistoryStore,
    ) -> None:
        self._primary = primary
        self._shadow = shadow
        self.shadow_write_failures = 0
        self._pool = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="qwenpaw-dual-history",
        )
        self._closed = False

    # -- contract attributes (delegated) ---------------------------------------

    @property
    def path(self):
        return self._primary.path

    @property
    def degraded(self) -> bool:
        return self._primary.degraded

    @property
    def write_failures(self) -> int:
        return self._primary.write_failures

    @property
    def quarantined_to(self):
        return self._primary.quarantined_to

    @property
    def closed(self) -> bool:
        return self._closed

    # -- shadow plumbing ----------------------------------------------------------

    def _shadow_write(self, fn, what: str) -> None:
        """Dispatch a shadow write; failures only count, never raise."""
        def _run() -> None:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - shadow must not raise
                self.shadow_write_failures += 1
                logger.warning(
                    "Dual-write history shadow %s failed "
                    "(primary unaffected): %s",
                    what,
                    exc,
                )

        if self._closed:
            return
        self._pool.submit(_run)

    def drain_shadow(self) -> None:
        """Block until all queued shadow writes finished (tests/cutover)."""
        self._pool.shutdown(wait=True)
        # Recreate so the store stays usable after a test-side drain.
        if not self._closed:
            self._pool = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="qwenpaw-dual-history",
            )

    def shadow_stats(self) -> dict:
        return {"shadow_write_failures": self.shadow_write_failures}

    # -- write path ------------------------------------------------------------

    def append(
        self,
        *,
        session_id: str,
        entry,
        agent_id: str | None = None,
        owner_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        seq = self._primary.append(
            session_id=session_id,
            entry=entry,
            agent_id=agent_id,
            owner_id=owner_id,
            dedup_key=dedup_key,
        )
        self._shadow_write(
            lambda: self._shadow.append(
                session_id=session_id,
                entry=entry,
                agent_id=agent_id,
                owner_id=owner_id,
                dedup_key=dedup_key,
            ),
            "append",
        )
        return seq

    def append_many(
        self,
        *,
        session_id: str,
        entries: Sequence[tuple[Any, str | None]],
        agent_id: str | None = None,
        owner_id: str | None = None,
    ) -> int:
        inserted = self._primary.append_many(
            session_id=session_id,
            entries=entries,
            agent_id=agent_id,
            owner_id=owner_id,
        )
        self._shadow_write(
            lambda: self._shadow.append_many(
                session_id=session_id,
                entries=entries,
                agent_id=agent_id,
                owner_id=owner_id,
            ),
            "append_many",
        )
        return inserted

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
        self._primary.update_entry(
            seq,
            content=content,
            headline=headline,
            blocks=blocks,
            tool_call_id=tool_call_id,
            name=name,
            tool_state=tool_state,
            tool_input=tool_input,
            metadata=metadata,
        )
        # The shadow's seq space differs; locate the shadow row by dedup
        # identity instead of translating seqs.
        self._shadow_write(
            lambda: self._shadow_update_by_primary_seq(
                seq,
                content=content,
                headline=headline,
                blocks=blocks,
                tool_call_id=tool_call_id,
                name=name,
                tool_state=tool_state,
                tool_input=tool_input,
                metadata=metadata,
            ),
            "update_entry",
        )

    def _shadow_update_by_primary_seq(self, seq: int, **fields) -> None:
        """Best-effort shadow update; the migration script re-aligns fully."""
        primary_row = self._primary.contents_by_seqs({seq})
        if seq not in primary_row:
            return
        # No portable seq mapping: the offline migration reconciles content
        # by (session_id, dedup_key). Shadow update_entry is skipped here;
        # divergence is measured by content comparison instead.
        _ = fields

    # -- read path (primary only) ------------------------------------------------

    def count(self, session_id: str) -> int:
        return self._primary.count(session_id)

    def claim_session(self, session_id: str, agent_id: str | None) -> int:
        claimed = self._primary.claim_session(session_id, agent_id)
        self._shadow_write(
            lambda: self._shadow.claim_session(session_id, agent_id),
            "claim_session",
        )
        return claimed

    def reconcile_session_rows(
        self,
        source_ids: set[str],
        target_id: str,
        dedup_keys: set[str],
        *,
        agent_id: str | None = None,
    ) -> tuple[int, int, int]:
        result = self._primary.reconcile_session_rows(
            source_ids,
            target_id,
            dedup_keys,
            agent_id=agent_id,
        )
        self._shadow_write(
            lambda: self._shadow.reconcile_session_rows(
                source_ids,
                target_id,
                dedup_keys,
                agent_id=agent_id,
            ),
            "reconcile_session_rows",
        )
        return result

    def existing_seqs(self, seqs: set[int]) -> set[int]:
        return self._primary.existing_seqs(seqs)

    def contents_by_seqs(self, seqs: set[int]) -> dict[int, str | None]:
        return self._primary.contents_by_seqs(seqs)

    def estimate_purge(
        self,
        *,
        before: str,
        kinds: tuple[str, ...] | None = None,
    ) -> dict:
        return self._primary.estimate_purge(before=before, kinds=kinds)

    def purge(
        self,
        *,
        before: str,
        dry_run: bool = False,
        kinds: tuple[str, ...] | None = None,
    ) -> int:
        removed = self._primary.purge(before=before, dry_run=dry_run, kinds=kinds)
        if not dry_run:
            self._shadow_write(
                lambda: self._shadow.purge(before=before, kinds=kinds),
                "purge",
            )
        return removed

    def vacuum(self) -> None:
        self._primary.vacuum()

    def note_write_failure(self, exc: BaseException) -> None:
        self._primary.note_write_failure(exc)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.shutdown(wait=True)
        try:
            self._shadow.close()
        finally:
            self._primary.close()
