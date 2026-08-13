# -*- coding: utf-8 -*-
"""Per-subject LLM quotas (M4-4).

- :class:`QuotaStore` — file-backed rule registry (``quotas.json``);
- :class:`QuotaCounter` — process-local request/token counters;
- :func:`check_llm_quota` — pre-call gate (raises
  ``ModelQuotaExceededException`` when a rule trips);
- :func:`record_llm_tokens` — post-call token accounting hook.
"""
from .counter import (
    QuotaCounter,
    check_llm_quota,
    get_quota_counter,
    record_llm_tokens,
    reset_quota_counter,
)
from .models import (
    SUBJECT_AGENT,
    SUBJECT_TEAM,
    SUBJECT_USER,
    WINDOW_DAY,
    WINDOW_MINUTE,
    QuotaRule,
    QuotasFile,
)
from .store import QuotaStore, get_quota_store, reset_quota_store

__all__ = [
    "SUBJECT_AGENT",
    "SUBJECT_TEAM",
    "SUBJECT_USER",
    "WINDOW_DAY",
    "WINDOW_MINUTE",
    "QuotaCounter",
    "QuotaRule",
    "QuotaStore",
    "QuotasFile",
    "check_llm_quota",
    "get_quota_counter",
    "get_quota_store",
    "record_llm_tokens",
    "reset_quota_counter",
    "reset_quota_store",
]
