# -*- coding: utf-8 -*-
"""Shared env pinning for provider unit tests.

宿主机可能配置 ``QWENPAW_PG_DSN``/``QWENPAW_STORAGE_BACKEND``（用户级
环境变量）。provider 单测必须与真实 PG 完全隔离：钉回 json 后端，
防止 PG 影子写路径向真实库发射守护线程写入。
"""
from __future__ import annotations

import pytest

from qwenpaw.providers import provider_store


@pytest.fixture(autouse=True)
def _pin_json_backend(monkeypatch):
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    monkeypatch.delenv("QWENPAW_TEST_PG_DSN", raising=False)
    provider_store.reset_backend_cache()
    yield
    provider_store.reset_backend_cache()
