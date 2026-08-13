# -*- coding: utf-8 -*-
"""Quota rule store (``quotas.json`` in ``SECRET_DIR``).

Same storage pattern as the RBAC store: JSON document, mtime-keyed read
cache, ``threading.Lock`` around read-modify-write, fail closed on
parse errors (a corrupt rules file simply disables quota enforcement —
availability beats strictness here, unlike RBAC which denies).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import List, Optional

from ...constant import SECRET_DIR
from .models import (
    VALID_SUBJECT_TYPES,
    VALID_WINDOWS,
    QuotaRule,
    QuotasFile,
)

logger = logging.getLogger(__name__)

QUOTAS_FILE = SECRET_DIR / "quotas.json"


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


class QuotaStore:
    """File-backed quota rule registry."""

    def __init__(self, path: Path | str = QUOTAS_FILE) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._load_error = False
        self._cache_valid = False
        self._cache_key: Optional[int] = None
        self._cache_data: Optional[QuotasFile] = None

    def _load(self) -> QuotasFile:
        try:
            cache_key: Optional[int] = self._path.stat().st_mtime_ns
        except OSError:
            cache_key = None
        if self._cache_valid and cache_key == self._cache_key:
            return self._cache_data  # type: ignore[return-value]

        data = QuotasFile()
        if self._path.is_file():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    data = QuotasFile.model_validate(json.load(fh))
                self._load_error = False
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.error(
                    "Failed to load quotas file %s: %s",
                    self._path,
                    exc,
                )
                self._load_error = True
                return QuotasFile()
        else:
            self._load_error = False
        self._cache_valid = True
        self._cache_key, self._cache_data = cache_key, data
        return data

    def _save(self, data: QuotasFile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(self._path.parent, 0o700)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(
                data.model_dump(mode="json"),
                fh,
                indent=2,
                ensure_ascii=False,
            )
        _chmod_best_effort(self._path, 0o600)
        try:
            self._cache_key = self._path.stat().st_mtime_ns
        except OSError:
            self._cache_key = None
        self._cache_data = data
        self._cache_valid = True

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def list_rules(self) -> List[QuotaRule]:
        return list(self._load().rules.values())

    def matching_rules(
        self,
        subjects: List[tuple],
        model: str,
    ) -> List[QuotaRule]:
        """Rules whose (subject_type, subject) is in *subjects* and whose
        model pattern matches *model* (exact or ``"*"``)."""
        subject_set = set(subjects)
        matched: list[QuotaRule] = []
        for rule in self._load().rules.values():
            if (rule.subject_type, rule.subject) not in subject_set:
                continue
            if rule.model not in ("*", model):
                continue
            matched.append(rule)
        return matched

    # ------------------------------------------------------------------
    # mutation
    # ------------------------------------------------------------------

    def upsert_rule(self, rule: QuotaRule) -> Optional[QuotaRule]:
        """Create or replace one rule (key = subject+model+window)."""
        if rule.subject_type not in VALID_SUBJECT_TYPES:
            return None
        if rule.window not in VALID_WINDOWS:
            return None
        if not rule.subject or rule.limit <= 0:
            return None
        with self._lock:
            data = self._load()
            if self._load_error:
                return None
            data.rules[rule.key()] = rule
            self._save(data)
        return rule

    def delete_rule(
        self,
        subject_type: str,
        subject: str,
        model: str,
        window: str,
    ) -> bool:
        key = QuotaRule(
            subject_type=subject_type,
            subject=subject or "x",
            model=model,
            window=window,
            limit=1,
        ).key()
        with self._lock:
            data = self._load()
            if self._load_error or key not in data.rules:
                return False
            del data.rules[key]
            self._save(data)
        return True


_default_store: Optional[QuotaStore] = None


def get_quota_store() -> QuotaStore:
    """Return the process-wide default quota store (lazy singleton)."""
    global _default_store  # noqa: PLW0603
    if _default_store is None:
        _default_store = QuotaStore()
    return _default_store


def reset_quota_store() -> None:
    """Drop the singleton (tests)."""
    global _default_store  # noqa: PLW0603
    _default_store = None
