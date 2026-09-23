# -*- coding: utf-8 -*-
"""Quota domain models (M4-4).

A quota rule caps usage for one *subject* (a user, a team, or an agent)
on one *model* over one *window*:

- ``window="minute"`` → ``limit`` counts LLM requests per sliding minute
- ``window="day"``    → ``limit`` counts total tokens per UTC day

``model="*"`` matches every model.  Multiple matching rules are all
enforced — the first exceeded one rejects the call (fail closed).
Rules live in ``quotas.json`` (file-backed, like ``rbac.json``); counters
are in-process (single-worker topology, no Redis).
"""
from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field

SUBJECT_USER = "user"
SUBJECT_TEAM = "team"
SUBJECT_AGENT = "agent"
VALID_SUBJECT_TYPES = frozenset({SUBJECT_USER, SUBJECT_TEAM, SUBJECT_AGENT})

WINDOW_MINUTE = "minute"
WINDOW_DAY = "day"
VALID_WINDOWS = frozenset({WINDOW_MINUTE, WINDOW_DAY})


class QuotaRule(BaseModel):
    """One quota rule, keyed by (subject_type, subject, model, window)."""

    subject_type: str
    subject: str
    model: str = "*"
    window: str = WINDOW_MINUTE
    limit: int = 0
    description: str = ""

    def key(self) -> str:
        return f"{self.subject_type}:{self.subject}:{self.model}:{self.window}"


class QuotasFile(BaseModel):
    """``quotas.json`` root document."""

    version: int = 1
    rules: Dict[str, QuotaRule] = Field(default_factory=dict)
