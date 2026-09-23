# -*- coding: utf-8 -*-
"""History store contract tests.

Every ``BaseHistoryStore`` implementation (SQLite ``HistoryStore`` today,
``PgHistoryStore`` from M2) must satisfy these contracts so the scroll
machinery stays backend-agnostic.
"""
from __future__ import annotations

from abc import abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qwenpaw.agents.context.scroll.base_history import (
    METADATA_UNSET,
    BaseHistoryStore,
)
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.types import LogEntry

from .. import BaseContractTest


def _entry(content: str, **overrides) -> LogEntry:
    return LogEntry(kind="context_msg", role="user", content=content, **overrides)


class HistoryStoreContractTest(BaseContractTest):
    """Contract: every history store backend behaves identically."""

    @abstractmethod
    def create_instance(self) -> BaseHistoryStore:
        """Provide a history store backed by a fresh, empty storage."""

    @pytest.fixture(autouse=True)
    def _close_store(self):
        yield
        store = getattr(self, "_store", None)
        if store is not None:
            store.close()

    def _new_store(self) -> BaseHistoryStore:
        self._store = self.create_instance()
        return self._store

    # ------------------------------------------------------------------
    # append / dedup
    # ------------------------------------------------------------------

    def test_append_assigns_increasing_seqs(self):
        store = self._new_store()
        seq1 = store.append(session_id="s1", entry=_entry("one"))
        seq2 = store.append(session_id="s1", entry=_entry("two"))
        assert seq1 > 0
        assert seq2 > seq1

    def test_append_with_dedup_key_is_idempotent(self):
        store = self._new_store()
        seq = store.append(
            session_id="s1",
            entry=_entry("hello"),
            dedup_key="k1",
        )
        again = store.append(
            session_id="s1",
            entry=_entry("hello"),
            dedup_key="k1",
        )
        assert again == seq
        assert store.count("s1") == 1

    def test_none_dedup_key_never_dedupes(self):
        store = self._new_store()
        store.append(session_id="s1", entry=_entry("a"))
        store.append(session_id="s1", entry=_entry("a"))
        assert store.count("s1") == 2

    def test_append_many_counts_only_new_rows(self):
        store = self._new_store()
        entries = [
            (_entry("first"), "k1"),
            (_entry("second"), "k2"),
        ]
        assert store.append_many(session_id="s1", entries=entries) == 2
        # Replaying the batch inserts nothing.
        assert store.append_many(session_id="s1", entries=entries) == 0
        assert store.count("s1") == 2

    def test_owner_id_is_persisted(self):
        store = self._new_store()
        seq = store.append(
            session_id="s1",
            entry=_entry("owned"),
            owner_id="alice",
        )
        assert seq > 0
        assert store.count("s1") == 1

    # ------------------------------------------------------------------
    # update_entry
    # ------------------------------------------------------------------

    def test_update_entry_replaces_content(self):
        store = self._new_store()
        seq = store.append(
            session_id="s1",
            entry=_entry("draft"),
            dedup_key="k1",
        )
        store.update_entry(
            seq,
            content="final",
            headline="h",
            blocks=[{"type": "text", "text": "final"}],
        )
        assert store.contents_by_seqs({seq})[seq] == "final"

    def test_update_entry_unset_metadata_is_kept(self):
        store = self._new_store()
        seq = store.append(
            session_id="s1",
            entry=_entry("body", metadata={"m": 1}),
            dedup_key="k1",
        )
        store.update_entry(
            seq,
            content="body2",
            headline=None,
            blocks=None,
            metadata=METADATA_UNSET,
        )
        assert store.contents_by_seqs({seq})[seq] == "body2"

    # ------------------------------------------------------------------
    # read helpers
    # ------------------------------------------------------------------

    def test_existing_seqs_filters_missing(self):
        store = self._new_store()
        seq = store.append(session_id="s1", entry=_entry("x"))
        existing = store.existing_seqs({seq, seq + 1000})
        assert existing == {seq}

    def test_contents_by_seqs_returns_exact_content(self):
        store = self._new_store()
        seq = store.append(session_id="s1", entry=_entry("payload"))
        assert store.contents_by_seqs({seq}) == {seq: "payload"}

    def test_claim_session_assigns_unowned_rows(self):
        store = self._new_store()
        store.append(session_id="s1", entry=_entry("orphan"))
        claimed = store.claim_session("s1", "agent-a")
        assert claimed == 1
        # Already-owned rows are not reclaimed.
        assert store.claim_session("s1", "agent-b") == 0

    # ------------------------------------------------------------------
    # retention
    # ------------------------------------------------------------------

    def test_purge_removes_old_rows(self):
        store = self._new_store()
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        store.append(
            session_id="s1",
            entry=_entry("ancient", created_at=old_ts),
        )
        store.append(session_id="s1", entry=_entry("fresh"))

        # Cutoff sits between the two rows: only the 30-day-old one goes.
        before = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        estimate = store.estimate_purge(before=before)
        assert estimate["rows"] == 1
        assert estimate["content_bytes"] > 0
        # dry_run changes nothing.
        assert store.purge(before=before, dry_run=True) == 1
        assert store.count("s1") == 2
        assert store.purge(before=before) == 1
        assert store.count("s1") == 1


class TestSqliteHistoryStoreContract(HistoryStoreContractTest):
    """SQLite file backend (reference implementation)."""

    @pytest.fixture(autouse=True)
    def _storage(self, tmp_path: Path) -> None:
        self._db_path = tmp_path / "history.db"

    def create_instance(self) -> BaseHistoryStore:
        return HistoryStore(self._db_path)


class TestPgHistoryStoreContract(HistoryStoreContractTest):
    """PostgreSQL backend (M2). Runs only with QWENPAW_TEST_PG_DSN set."""

    @pytest.fixture(autouse=True)
    def _storage(self, pg_dsn: str) -> None:
        self._dsn = pg_dsn

    def create_instance(self) -> BaseHistoryStore:
        from qwenpaw.agents.context.scroll.pg_history import PgHistoryStore

        return PgHistoryStore(dsn=self._dsn, identity="pg:test")
