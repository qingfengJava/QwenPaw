# -*- coding: utf-8 -*-
"""Provider config plane contract tests (provider_configs/model_active_slots).

Pins the DB-level behavior of the provider configuration storage plane:

- upsert → load round-trip preserves the full snapshot;
- ``api_key`` is stored as a cipher in ``api_key_encrypted`` (never
  plaintext) and decrypts back to the original value (``ENC1:``
  portable cipher since alembic 0028; legacy ``ENC:`` local cipher
  remains readable);
- upsert is idempotent per ``(tenant_id, provider_id)``;
- active slot save/load/clear behaves like the file-era active_model.json.

Runs only with ``QWENPAW_TEST_PG_DSN`` set (hermetic default run skips).

@author qingfeng
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from qwenpaw.providers import provider_store


@pytest.fixture(autouse=True)
def _pin_backend(monkeypatch):
    """Provider 平面函数自身不做后端判断，但钉回环境防宿主污染。"""
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    provider_store.reset_backend_cache()
    yield
    provider_store.reset_backend_cache()


@pytest.fixture
def engine(pg_engine):  # noqa: F811 - fixture from contract conftest
    """Reuse the migrated/cleaned contract-test engine."""
    return pg_engine


def _snapshot(provider_id: str) -> dict:
    return {
        "id": provider_id,
        "name": f"Provider {provider_id}",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-123456",
        "require_api_key": True,
        "is_custom": False,
        "hidden_model_ids": ["m-hidden"],
        "removed_model_ids": ["m-removed"],
        "extra_models": [{"id": "m-extra", "name": "Extra"}],
        "chat_model": "OpenAIChatModel",
    }


class TestProviderConfigsTable:
    async def test_upsert_and_load_roundtrip(self, engine) -> None:
        pid = f"prov-{uuid.uuid4().hex[:8]}"
        await provider_store.upsert_provider_snapshot_pg(_snapshot(pid), engine=engine)

        snapshots = await provider_store.load_provider_snapshots_pg(engine=engine)
        restored = next(s for s in snapshots if s["id"] == pid)
        assert restored["name"] == "Provider " + pid
        assert restored["base_url"] == "https://api.example.com/v1"
        assert restored["api_key"] == "sk-test-123456"
        assert restored["hidden_model_ids"] == ["m-hidden"]
        assert restored["removed_model_ids"] == ["m-removed"]
        assert restored["extra_models"][0]["id"] == "m-extra"

    async def test_api_key_stored_as_cipher(self, engine) -> None:
        pid = f"prov-{uuid.uuid4().hex[:8]}"
        await provider_store.upsert_provider_snapshot_pg(_snapshot(pid), engine=engine)

        result = await engine.connect()
        rows = (
            await result.execute(
                text(
                    "SELECT api_key_encrypted, snapshot FROM provider_configs "
                    "WHERE provider_id = :pid",
                ),
                {"pid": pid},
            )
        ).all()
        await result.close()

        assert len(rows) == 1
        api_key_encrypted, snapshot = rows[0]
        # 库里必须是密文（ENC1: 可移植或存量 ENC: 本机），
        # 且 snapshot JSONB 不含明文 api_key
        assert api_key_encrypted.startswith(("ENC:", "ENC1:"))
        assert "sk-test-123456" not in str(snapshot)
        assert "sk-test-123456" not in api_key_encrypted

    async def test_upsert_is_idempotent_per_provider(self, engine) -> None:
        pid = f"prov-{uuid.uuid4().hex[:8]}"
        first = _snapshot(pid)
        await provider_store.upsert_provider_snapshot_pg(first, engine=engine)
        updated = _snapshot(pid)
        updated["name"] = "Renamed"
        updated["api_key"] = "sk-rotated"
        await provider_store.upsert_provider_snapshot_pg(updated, engine=engine)

        snapshots = await provider_store.load_provider_snapshots_pg(engine=engine)
        mine = [s for s in snapshots if s["id"] == pid]
        assert len(mine) == 1
        assert mine[0]["name"] == "Renamed"
        assert mine[0]["api_key"] == "sk-rotated"

    async def test_delete_provider_snapshot(self, engine) -> None:
        pid = f"prov-{uuid.uuid4().hex[:8]}"
        await provider_store.upsert_provider_snapshot_pg(_snapshot(pid), engine=engine)
        await provider_store.delete_provider_snapshot_pg(pid, engine=engine)
        snapshots = await provider_store.load_provider_snapshots_pg(engine=engine)
        assert all(s["id"] != pid for s in snapshots)


class TestModelActiveSlots:
    async def test_save_load_clear_slot(self, engine) -> None:
        slot = provider_store.ACTIVE_SLOT_LLM
        assert (
            await provider_store.load_active_slot_pg(slot, engine=engine)
            is None
        )

        await provider_store.save_active_slot_pg(
            slot, "dashscope", "qwen-max", engine=engine,
        )
        loaded = await provider_store.load_active_slot_pg(slot, engine=engine)
        assert loaded == {"provider_id": "dashscope", "model": "qwen-max"}

        # 覆盖写（切换默认模型）
        await provider_store.save_active_slot_pg(
            slot, "openai", "gpt-x", engine=engine,
        )
        loaded = await provider_store.load_active_slot_pg(slot, engine=engine)
        assert loaded == {"provider_id": "openai", "model": "gpt-x"}

        await provider_store.clear_active_slot_pg(slot, engine=engine)
        assert (
            await provider_store.load_active_slot_pg(slot, engine=engine)
            is None
        )


class TestProviderModelsRows:
    """行级模型表：每厂商每模型一行，参数独立，开关投影为 enabled。"""

    async def test_build_model_rows_projects_disabled_and_removed(
        self,
    ) -> None:
        data = {
            "id": "p",
            "require_api_key": True,
            "api_key": "sk-test",
            "removed_model_ids": ["gone"],
            "disabled_model_ids": ["off"],
            "models": [
                {"id": "on", "name": "On", "source": "builtin",
                 "generate_kwargs": {"temperature": 0.7}},
                {"id": "off", "name": "Off", "source": "builtin"},
                {"id": "gone", "name": "Gone", "source": "builtin"},
            ],
            "extra_models": [
                {"id": "user-1", "name": "User 1", "source": "user",
                 "supports_multimodal": True},
            ],
        }
        rows = {
            r["model_id"]: r
            for r in provider_store.build_model_rows(data)
        }
        # removed 不建行；其余全量投影
        assert set(rows) == {"on", "off", "user-1"}
        assert rows["off"]["enabled"] is False
        assert rows["on"]["enabled"] is True
        assert rows["user-1"]["source"] == "user"
        # 提升列外的参数进 config（参数独立保留）
        assert json.loads(rows["on"]["config_json"]) == {
            "generate_kwargs": {"temperature": 0.7},
        }
        assert "supports_multimodal" not in json.loads(
            rows["user-1"]["config_json"],
        )

    async def test_sync_rows_full_replace_and_load(self, engine) -> None:
        pid = f"prov-{uuid.uuid4().hex[:8]}"
        rows = provider_store.build_model_rows(
            {
                "id": pid,
                "require_api_key": True,
                "api_key": "sk-test",
                "models": [
                    {"id": "m-a", "name": "A", "source": "builtin"},
                    {"id": "m-b", "name": "B", "source": "user"},
                ],
                "disabled_model_ids": ["m-b"],
            },
        )
        await provider_store.sync_provider_models_pg(pid, rows, engine=engine)

        loaded = {
            r["model_id"]: r
            for r in await provider_store.load_provider_models_pg(
                pid,
                engine=engine,
            )
        }
        assert set(loaded) == {"m-a", "m-b"}
        assert loaded["m-a"]["enabled"] is True
        assert loaded["m-b"]["enabled"] is False

        # 全量替换语义：重同步时删掉的行不会残留
        rows_v2 = provider_store.build_model_rows(
            {
                "id": pid,
                "require_api_key": True,
                "api_key": "sk-test",
                "models": [
                    {"id": "m-a", "name": "A2", "source": "builtin"},
                ],
            },
        )
        await provider_store.sync_provider_models_pg(
            pid, rows_v2, engine=engine,
        )
        loaded = await provider_store.load_provider_models_pg(
            pid,
            engine=engine,
        )
        assert [r["model_id"] for r in loaded] == ["m-a"]
        assert loaded[0]["name"] == "A2"

    async def test_sync_requires_provider_id(self, engine) -> None:
        with pytest.raises(ValueError):
            await provider_store.sync_provider_models_pg(
                "", [], engine=engine,
            )

    def test_disabled_provider_projects_no_rows(self) -> None:
        """厂商停用（未配 key）→ 不投影任何模型行（停用即清空）。"""
        data = {
            "id": "p",
            "require_api_key": True,
            "api_key": "",
            "models": [
                {"id": "m-1", "name": "M1", "source": "builtin"},
            ],
            "extra_models": [
                {"id": "m-2", "name": "M2", "source": "user"},
            ],
        }
        assert provider_store.build_model_rows(data) == []

        # 厂商启用后目录模型恢复投影
        data["api_key"] = "sk-set"
        rows = provider_store.build_model_rows(data)
        assert [r["model_id"] for r in rows] == ["m-1", "m-2"]
