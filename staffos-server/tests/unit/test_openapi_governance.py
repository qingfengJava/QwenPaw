#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for open API governance (no PG required).

Tests cover:
  - fingerprint_payload: canonical-JSON stability (key order irrelevant),
    distinct payloads → distinct fingerprints
  - check_rate_limit: sliding-window admission, boundary exhaustion,
    retry_after hint, independent per-key windows
  - _rate_limit_rpm: env parsing fallbacks (unset / garbage / clamped)
  - extract_expert_id_from_path: canonical path, deep path, non-experts
    path, placeholder safety
  - IdempotencyConflict: carries the offending idem key
"""

import pytest

from qwenpaw.app.experts.openapi_governance import (
    IdempotencyConflict,
    OpenGovernance,
    extract_expert_id_from_path,
    fingerprint_payload,
)


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_key_order_irrelevant():
    """同内容不同键序 → 同指纹（canonical JSON 语义）."""
    assert fingerprint_payload({"a": 1, "b": 2}) == fingerprint_payload(
        {"b": 2, "a": 1},
    )


def test_fingerprint_distinct_payloads():
    """不同内容 → 不同指纹；中文与嵌套结构稳定."""
    base = {"prompt": "你好", "nested": {"x": [1, 2]}}
    other = {"prompt": "再见", "nested": {"x": [1, 2]}}
    assert fingerprint_payload(base) != fingerprint_payload(other)
    assert fingerprint_payload(base) == fingerprint_payload(
        {"nested": {"x": [1, 2]}, "prompt": "你好"},
    )


# ---------------------------------------------------------------------------
# rate limit（滑动窗口）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_admits_then_rejects(monkeypatch):
    """窗口内达到上限后拒绝，且给出 Retry-After 提示."""
    gov = OpenGovernance()
    monkeypatch.setattr(OpenGovernance, "_rate_limit_rpm", staticmethod(lambda: 3))
    allowed_flags = []
    for _ in range(3):
        allowed, _retry = await gov.check_rate_limit("k1")
        allowed_flags.append(allowed)
    assert allowed_flags == [True, True, True]
    allowed, retry_after = await gov.check_rate_limit("k1")
    assert allowed is False
    assert retry_after >= 1


@pytest.mark.asyncio
async def test_rate_limit_windows_are_per_key(monkeypatch):
    """不同密钥窗口互不影响."""
    gov = OpenGovernance()
    monkeypatch.setattr(OpenGovernance, "_rate_limit_rpm", staticmethod(lambda: 1))
    allowed, _ = await gov.check_rate_limit("ka")
    assert allowed is True
    allowed, _ = await gov.check_rate_limit("kb")
    assert allowed is True
    allowed, _ = await gov.check_rate_limit("ka")
    assert allowed is False


def test_rate_limit_rpm_env_parsing(monkeypatch):
    """环境变量解析：未设/垃圾值回退默认，负值钳到 1."""
    monkeypatch.delenv("QWENPAW_OPEN_RATE_LIMIT_RPM", raising=False)
    assert OpenGovernance._rate_limit_rpm() == 30
    monkeypatch.setenv("QWENPAW_OPEN_RATE_LIMIT_RPM", "abc")
    assert OpenGovernance._rate_limit_rpm() == 30
    monkeypatch.setenv("QWENPAW_OPEN_RATE_LIMIT_RPM", "-5")
    assert OpenGovernance._rate_limit_rpm() == 1
    monkeypatch.setenv("QWENPAW_OPEN_RATE_LIMIT_RPM", "120")
    assert OpenGovernance._rate_limit_rpm() == 120


# ---------------------------------------------------------------------------
# path → expert_id
# ---------------------------------------------------------------------------


def test_extract_expert_id_canonical():
    assert (
        extract_expert_id_from_path("/api/open/experts/emp_123/tasks")
        == "emp_123"
    )


def test_extract_expert_id_profile_path():
    assert extract_expert_id_from_path("/api/open/experts/emp_9") == "emp_9"


def test_extract_expert_id_non_experts_path():
    assert extract_expert_id_from_path("/api/open/other") == ""


def test_extract_expert_id_placeholder_ignored():
    """路径模板占位符（{expert_id}）不当作真实 ID."""
    assert extract_expert_id_from_path("/open/experts/{expert_id}") == ""


# ---------------------------------------------------------------------------
# conflict exception
# ---------------------------------------------------------------------------


def test_idempotency_conflict_carries_key():
    exc = IdempotencyConflict("abc-123")
    assert exc.idem_key == "abc-123"
    assert "abc-123" in str(exc)


def test_module_import_is_side_effect_free():
    """模块导入不触发引擎/事件循环依赖（可在无 PG 环境安全导入）."""
    import qwenpaw.app.experts.openapi_governance as mod

    assert mod.get_open_governance() is mod.get_open_governance()
