# -*- coding: utf-8 -*-
"""In-process quota counters and the LLM call gate (M4-4).

Counters are process-local (single-worker topology; no Redis):

- request windows: fixed-window counters keyed by
  ``(rule_key, minute_bucket)`` — a fixed minute window is good enough
  for quota enforcement and far cheaper than a sliding deque;
- token days: counters keyed by ``(rule_key, date_bucket)`` fed from
  ``TokenRecordingModelWrapper`` after each LLM response.

The gate evaluates every matching rule before an LLM call proceeds;
the first exceeded rule raises :class:`ModelQuotaExceededException`,
which channels already translate into a ``rate_limited`` SSE event.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date
from typing import List, Optional, Tuple

from .models import (
    SUBJECT_AGENT,
    SUBJECT_TEAM,
    SUBJECT_USER,
    WINDOW_DAY,
    WINDOW_MINUTE,
    QuotaRule,
)
from .store import get_quota_store

logger = logging.getLogger(__name__)

# Sweep counter buckets older than this many seconds on writes.
_BUCKET_TTL_S = 2 * 24 * 3600


class QuotaCounter:
    """Process-local quota counters with rule evaluation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key: (rule_key, bucket) -> value
        self._counters: dict[tuple[str, str], int] = {}
        self._last_sweep = time.monotonic()

    # ------------------------------------------------------------------
    # bucket helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bucket_for(window: str, now: Optional[float] = None) -> str:
        if window == WINDOW_DAY:
            return date.today().isoformat()
        # minute window
        epoch_minute = int((now or time.time()) // 60)
        return str(epoch_minute)

    def _sweep_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_sweep < 300:
            return
        self._last_sweep = now
        cutoff_minute = int((time.time() - _BUCKET_TTL_S) // 60)
        cutoff_day = date.fromtimestamp(
            time.time() - _BUCKET_TTL_S,
        ).isoformat()
        stale = []
        for rule_key, bucket in self._counters:
            # day buckets contain "-", minute buckets are pure digits.
            if "-" in bucket:
                if bucket < cutoff_day:
                    stale.append((rule_key, bucket))
            else:
                try:
                    if int(bucket) < cutoff_minute:
                        stale.append((rule_key, bucket))
                except ValueError:
                    stale.append((rule_key, bucket))
        for key in stale:
            self._counters.pop(key, None)

    # ------------------------------------------------------------------
    # counting
    # ------------------------------------------------------------------

    def _increment(self, rule_key: str, bucket: str, amount: int) -> int:
        with self._lock:
            self._sweep_if_due()
            key = (rule_key, bucket)
            value = self._counters.get(key, 0) + amount
            self._counters[key] = value
            return value

    def current(self, rule_key: str, window: str) -> int:
        """Current-window value for one rule (observability/tests)."""
        bucket = self._bucket_for(window)
        with self._lock:
            return self._counters.get((rule_key, bucket), 0)

    def record_tokens(self, rule: QuotaRule, tokens: int) -> None:
        """Accumulate *tokens* into a day-window rule's bucket."""
        if rule.window != WINDOW_DAY or tokens <= 0:
            return
        self._increment(rule.key(), self._bucket_for(WINDOW_DAY), tokens)

    def count_request(self, rule: QuotaRule) -> int:
        """Increment a minute-window rule's request bucket; returns the
        post-increment value."""
        return self._increment(
            rule.key(),
            self._bucket_for(WINDOW_MINUTE),
            1,
        )

    def exceeded(self, rule: QuotaRule) -> bool:
        """Whether the rule's current window already exceeds its limit."""
        return self.current(rule.key(), rule.window) >= rule.limit

    def reset(self) -> None:
        """Drop all counters (tests)."""
        with self._lock:
            self._counters.clear()


_counter = QuotaCounter()


def get_quota_counter() -> QuotaCounter:
    return _counter


def reset_quota_counter() -> None:
    _counter.reset()


# ---------------------------------------------------------------------------
# subject resolution + gate
# ---------------------------------------------------------------------------


def _subjects_for(
    user_id: str,
    agent_id: str,
) -> List[Tuple[str, str]]:
    """All (subject_type, subject) pairs a call is accountable to."""
    subjects: list[tuple[str, str]] = []
    if user_id:
        subjects.append((SUBJECT_USER, user_id))
        try:
            from ..rbac.store import get_rbac_store

            for team in get_rbac_store().teams_for_user(user_id):
                subjects.append((SUBJECT_TEAM, team))
        except Exception:  # pylint: disable=broad-except
            pass
    if agent_id:
        subjects.append((SUBJECT_AGENT, agent_id))
    return subjects


def check_llm_quota(
    user_id: str,
    agent_id: str,
    model_key: str,
) -> None:
    """Raise ``ModelQuotaExceededException`` when a quota rule is exceeded.

    Called before every LLM call (alongside the M3 rate limiter).  With
    no rules configured (the default) this is a cheap no-op.
    """
    store = get_quota_store()
    if store._load_error:  # pylint: disable=protected-access
        return  # corrupt rules file: stay available, enforce nothing
    subjects = _subjects_for(user_id, agent_id)
    if not subjects:
        return
    rules = store.matching_rules(subjects, model_key)
    if not rules:
        return

    counter = get_quota_counter()
    for rule in rules:
        if rule.window == WINDOW_DAY:
            # Token-day circuit breaker: trips once the accumulated
            # tokens cross the limit; checked without incrementing.
            if counter.exceeded(rule):
                _raise_quota(rule)
        else:
            value = counter.count_request(rule)
            if value > rule.limit:
                _raise_quota(rule)


def record_llm_tokens(
    user_id: str,
    agent_id: str,
    model_key: str,
    tokens: int,
) -> None:
    """Feed one call's token usage into matching day-window rules."""
    if tokens <= 0:
        return
    store = get_quota_store()
    subjects = _subjects_for(user_id, agent_id)
    if not subjects:
        return
    counter = get_quota_counter()
    for rule in store.matching_rules(subjects, model_key):
        if rule.window == WINDOW_DAY:
            counter.record_tokens(rule, tokens)


def _raise_quota(rule: QuotaRule) -> None:
    from ...exceptions import ModelQuotaExceededException

    logger.warning(
        "quota exceeded: %s=%s model=%s window=%s limit=%d",
        rule.subject_type,
        rule.subject,
        rule.model,
        rule.window,
        rule.limit,
    )
    raise ModelQuotaExceededException(
        rule.model,
        details={
            "reason": (
                f"Quota exceeded for {rule.subject_type} "
                f"'{rule.subject}' ({rule.window} limit {rule.limit})"
            ),
            "subject_type": rule.subject_type,
            "subject": rule.subject,
            "window": rule.window,
            "limit": rule.limit,
        },
    )
