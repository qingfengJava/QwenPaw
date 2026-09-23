# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the M4-4 per-subject LLM quotas."""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.quotas.counter import (
    QuotaCounter,
    check_llm_quota,
    record_llm_tokens,
)
from qwenpaw.app.quotas.models import (
    SUBJECT_AGENT,
    SUBJECT_TEAM,
    SUBJECT_USER,
    WINDOW_DAY,
    WINDOW_MINUTE,
    QuotaRule,
)
from qwenpaw.app.quotas.store import QuotaStore
from qwenpaw.exceptions import ModelQuotaExceededException


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> QuotaStore:
    s = QuotaStore(tmp_path / "quotas.json")
    monkeypatch.setattr(
        "qwenpaw.app.quotas.counter.get_quota_store",
        lambda: s,
    )
    return s


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch) -> QuotaCounter:
    c = QuotaCounter()
    monkeypatch.setattr(
        "qwenpaw.app.quotas.counter.get_quota_counter",
        lambda: c,
    )
    return c


def _rule(**kw) -> QuotaRule:
    defaults = {
        "subject_type": SUBJECT_USER,
        "subject": "alice",
        "model": "*",
        "window": WINDOW_MINUTE,
        "limit": 2,
    }
    defaults.update(kw)
    return QuotaRule(**defaults)


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


def test_upsert_and_list(store: QuotaStore) -> None:
    assert store.upsert_rule(_rule()) is not None
    assert store.upsert_rule(_rule(subject="bob", model="m1")) is not None
    assert len(store.list_rules()) == 2


def test_upsert_rejects_invalid(store: QuotaStore) -> None:
    assert store.upsert_rule(_rule(subject_type="org")) is None
    assert store.upsert_rule(_rule(window="hour")) is None
    assert store.upsert_rule(_rule(subject="")) is None
    assert store.upsert_rule(_rule(limit=0)) is None


def test_delete_rule(store: QuotaStore) -> None:
    store.upsert_rule(_rule())
    assert (
        store.delete_rule(SUBJECT_USER, "alice", "*", WINDOW_MINUTE) is True
    )
    assert store.list_rules() == []
    assert (
        store.delete_rule(SUBJECT_USER, "alice", "*", WINDOW_MINUTE) is False
    )


def test_matching_rules_model_patterns(store: QuotaStore) -> None:
    store.upsert_rule(_rule(model="*"))
    store.upsert_rule(_rule(model="p:m1"))
    store.upsert_rule(_rule(subject="bob"))
    matched = store.matching_rules([(SUBJECT_USER, "alice")], "p:m1")
    assert len(matched) == 2
    matched = store.matching_rules([(SUBJECT_USER, "alice")], "p:other")
    assert len(matched) == 1  # only the wildcard rule


# ---------------------------------------------------------------------------
# counter + gate
# ---------------------------------------------------------------------------


def test_minute_window_trips_at_limit(
    store: QuotaStore,
    counter: QuotaCounter,
) -> None:
    store.upsert_rule(_rule(limit=2))
    # two requests pass
    check_llm_quota("alice", "", "p:m1")
    check_llm_quota("alice", "", "p:m1")
    with pytest.raises(ModelQuotaExceededException):
        check_llm_quota("alice", "", "p:m1")


def test_other_user_unaffected(
    store: QuotaStore,
    counter: QuotaCounter,
) -> None:
    store.upsert_rule(_rule(limit=1))
    check_llm_quota("alice", "", "p:m1")
    check_llm_quota("bob", "", "p:m1")  # no raise


def test_agent_subject_rule(
    store: QuotaStore,
    counter: QuotaCounter,
) -> None:
    store.upsert_rule(
        _rule(subject_type=SUBJECT_AGENT, subject="bot-1", limit=1),
    )
    check_llm_quota("alice", "bot-1", "p:m1")
    with pytest.raises(ModelQuotaExceededException):
        check_llm_quota("alice", "bot-1", "p:m1")
    # A different agent is not covered by the rule.
    check_llm_quota("alice", "bot-2", "p:m1")


def test_team_subject_rule(
    store: QuotaStore,
    counter: QuotaCounter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app.rbac.store import RbacStore

    rbac = RbacStore(store._path.parent / "rbac.json")
    rbac.upsert_team("core", ["alice"])
    monkeypatch.setattr(
        "qwenpaw.app.rbac.store.get_rbac_store",
        lambda: rbac,
    )
    store.upsert_rule(
        _rule(subject_type=SUBJECT_TEAM, subject="core", limit=1),
    )
    check_llm_quota("alice", "", "p:m1")
    with pytest.raises(ModelQuotaExceededException):
        check_llm_quota("alice", "", "p:m1")


def test_day_token_circuit_breaker(
    store: QuotaStore,
    counter: QuotaCounter,
) -> None:
    store.upsert_rule(_rule(window=WINDOW_DAY, limit=100))
    record_llm_tokens("alice", "", "p:m1", 60)
    check_llm_quota("alice", "", "p:m1")  # 60 < 100: passes
    record_llm_tokens("alice", "", "p:m1", 60)
    with pytest.raises(ModelQuotaExceededException):
        check_llm_quota("alice", "", "p:m1")  # 120 >= 100: tripped


def test_no_rules_is_noop(
    store: QuotaStore,
    counter: QuotaCounter,
) -> None:
    check_llm_quota("alice", "bot", "p:m1")  # no store rules → no raise
    record_llm_tokens("alice", "bot", "p:m1", 10_000)


def test_wildcard_model_matches_any(
    store: QuotaStore,
    counter: QuotaCounter,
) -> None:
    store.upsert_rule(_rule(model="*", limit=1))
    check_llm_quota("alice", "", "p:m1")
    with pytest.raises(ModelQuotaExceededException):
        check_llm_quota("alice", "", "another:model")


def test_exact_model_only_matches_it(
    store: QuotaStore,
    counter: QuotaCounter,
) -> None:
    store.upsert_rule(_rule(model="p:m1", limit=1))
    check_llm_quota("alice", "", "p:other")  # not counted
    check_llm_quota("alice", "", "p:m1")
    with pytest.raises(ModelQuotaExceededException):
        check_llm_quota("alice", "", "p:m1")
