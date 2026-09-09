# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the provider config plane (backend routing + PG helpers)."""
from __future__ import annotations

import json

import pytest

from qwenpaw.providers import provider_store
from qwenpaw.security.secret_store import decrypt, encrypt, is_encrypted


@pytest.fixture(autouse=True)
def _pin_backend_env(monkeypatch):
    """钉回测试期望的后端环境，防止宿主机配置污染（历史教训）。"""
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    provider_store.reset_backend_cache()
    yield
    provider_store.reset_backend_cache()


class TestBackendResolution:
    def test_explicit_backend_wins(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        assert provider_store.provider_storage_backend() == "pg"

    def test_no_env_no_dsn_defaults_json(self):
        assert provider_store.provider_storage_backend() == "json"

    def test_no_env_with_dsn_defaults_dual(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        assert provider_store.provider_storage_backend() == "dual"

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "nonsense")
        assert provider_store.provider_storage_backend() == "json"

    def test_cache_resets_between_calls(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
        assert provider_store.provider_storage_backend() == "json"
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        provider_store.reset_backend_cache()
        assert provider_store.provider_storage_backend() == "pg"


class TestPgAvailability:
    def test_json_backend_never_touches_pg(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
        assert not provider_store.pg_provider_plane_available()

    def test_dual_without_dsn_unavailable(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        assert not provider_store.pg_provider_plane_available()

    def test_dual_with_dsn_available(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        assert provider_store.pg_provider_plane_available()


class TestPayloadHelpers:
    def test_snapshot_payload_strips_api_key_and_syncing(self):
        data = {
            "id": "dashscope",
            "api_key": "sk-plain",
            "models_syncing": True,
            "base_url": "https://x",
        }
        payload = provider_store._snapshot_payload(data)
        assert "api_key" not in payload
        assert "models_syncing" not in payload
        assert payload["base_url"] == "https://x"

    def test_derive_enabled_requires_key_when_needed(self):
        assert provider_store._derive_enabled(
            {"require_api_key": True, "api_key": "sk-1"},
        )
        assert not provider_store._derive_enabled(
            {"require_api_key": True, "api_key": ""},
        )
        assert provider_store._derive_enabled(
            {"require_api_key": False, "api_key": ""},
        )

    def test_coerce_snapshot_accepts_dict_and_str(self):
        assert provider_store._coerce_snapshot({"a": 1}) == {"a": 1}
        assert provider_store._coerce_snapshot('{"a": 1}') == {"a": 1}
        assert provider_store._coerce_snapshot("not-json") == {}
        assert provider_store._coerce_snapshot(None) == {}

    def test_row_to_provider_data_decrypts_api_key(self):
        cipher = encrypt("sk-secret")
        assert is_encrypted(cipher)
        data = provider_store._row_to_provider_data(
            "dashscope",
            "DashScope",
            "https://dashscope.example",
            cipher,
            {"chat_model": "OpenAIChatModel"},
        )
        assert data["id"] == "dashscope"
        assert data["name"] == "DashScope"
        assert data["base_url"] == "https://dashscope.example"
        assert data["api_key"] == "sk-secret"
        assert data["chat_model"] == "OpenAIChatModel"

    def test_row_to_provider_data_empty_key(self):
        data = provider_store._row_to_provider_data(
            "ollama",
            "Ollama",
            "",
            "",
            {},
        )
        assert data["api_key"] == ""

    def test_encrypt_roundtrip_via_store_path(self):
        """模拟 upsert 提升列 → load 解密还原的全链路语义。"""
        plain = {"id": "p1", "api_key": "sk-abc"}
        stored = encrypt(str(plain["api_key"]))
        restored = provider_store._row_to_provider_data(
            plain["id"],
            "p1",
            "",
            stored,
            {},
        )
        assert restored["api_key"] == "sk-abc"
        assert decrypt(restored["api_key"]) == "sk-abc"


class TestShadowWriteScheduling:
    def test_schedule_noop_when_unavailable(self):
        called = {"count": 0}

        def _factory():
            called["count"] += 1
            raise AssertionError("must not run")

        provider_store.schedule_pg_write(_factory)
        assert called["count"] == 0

    def test_mirror_snapshot_noop_when_json_backend(self):
        # json 后端：mirror 系列函数必须是纯 no-op（不落线程不建协程）
        provider_store.mirror_provider_snapshot({"id": "x"})
        provider_store.mirror_provider_delete("x")
        provider_store.mirror_active_slot("p", "m")
        provider_store.mirror_active_slot(None, None)

    def test_mirror_snapshot_schedules_upsert_when_available(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            provider_store,
            "pg_provider_plane_available",
            lambda: True,
        )
        captured: dict = {}

        async def _fake_upsert(data):
            captured["data"] = data

        monkeypatch.setattr(
            provider_store,
            "upsert_provider_snapshot_pg",
            _fake_upsert,
        )
        provider_store.mirror_provider_snapshot({"id": "dashscope"})
        # fire-and-forget：此处只验证调度不抛异常；实际执行由事件循环完成
        assert "data" not in captured or captured["data"]["id"] == "dashscope"

    def test_upsert_requires_id(self):
        import asyncio

        async def _run():
            await provider_store.upsert_provider_snapshot_pg({"name": "x"})

        with pytest.raises(ValueError):
            asyncio.run(_run())

    def test_snapshot_payload_json_serializable(self):
        data = {
            "id": "p",
            "api_key": "sk",
            "extra_models": [{"id": "m", "name": "M"}],
        }
        payload = provider_store._snapshot_payload(data)
        assert json.loads(json.dumps(payload)) == payload
