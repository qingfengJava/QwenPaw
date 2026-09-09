# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the one-shot provider config plane bootstrap (env/file → PG)."""
from __future__ import annotations

import json

import pytest

from qwenpaw.providers import provider_env_migration as migration
from qwenpaw.providers import provider_store


class _FakeProvider:
    """Minimal provider stand-in (id/require_api_key/api_key/model_dump)."""

    def __init__(
        self,
        provider_id: str,
        *,
        require_api_key: bool = True,
        api_key: str = "",
    ):
        self.id = provider_id
        self.require_api_key = require_api_key
        self.api_key = api_key

    def model_dump(self, exclude: set[str] | None = None):
        return {
            "id": self.id,
            "require_api_key": self.require_api_key,
            "api_key": "" if "api_key" in (exclude or set()) else self.api_key,
        }

    def model_copy(self, update: dict):
        clone = _FakeProvider(
            self.id,
            require_api_key=self.require_api_key,
            api_key=update.get("api_key", self.api_key),
        )
        return clone


class _FakeManager:
    """ProviderManager stand-in for migration orchestration tests."""

    def __init__(self, providers: list[_FakeProvider], active_model=None):
        self.builtin_providers = {
            p.id: p for p in providers[:1]
        } if providers else {}
        self.custom_providers = {
            p.id: p for p in providers[1:]
        } if providers else {}
        self.plugin_providers = {}
        self.active_model = active_model
        self.saved: list[str] = []

    async def save_provider_config_async(self, provider_id, provider=None):
        self.saved.append(provider_id)
        target = self.builtin_providers.get(provider_id) or (
            self.custom_providers.get(provider_id)
        )
        if target is not None and provider is not None:
            target.api_key = provider.api_key

    async def load_providers_from_pg(self):
        return 0


@pytest.fixture(autouse=True)
def _pin_backend_env(monkeypatch):
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    provider_store.reset_backend_cache()
    yield
    provider_store.reset_backend_cache()


@pytest.fixture(autouse=True)
def _isolated_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(
        migration,
        "_manifest_path",
        lambda: tmp_path / ".provider_pg_migrated.json",
    )


class TestCandidateEnvKeys:
    def test_conventional_name(self):
        assert migration._candidate_env_keys("dashscope") == (
            "DASHSCOPE_API_KEY",
        )

    def test_aliases_first_and_deduped(self):
        keys = migration._candidate_env_keys("gemini")
        assert keys == ("GEMINI_API_KEY", "GOOGLE_API_KEY")

    def test_hyphen_ids_uppercase(self):
        assert migration._candidate_env_keys("siliconflow-cn") == (
            "SILICONFLOW_CN_API_KEY",
        )


class TestMigrateEnvKeys:
    async def test_fills_missing_key_from_env(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")
        manager = _FakeManager(
            [_FakeProvider("dashscope", api_key="")],
        )
        migrated = await migration._migrate_env_keys(manager)
        assert migrated == ["dashscope"]
        assert manager.saved == ["dashscope"]
        assert manager.builtin_providers["dashscope"].api_key == "sk-from-env"

    async def test_never_overwrites_existing_key(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")
        manager = _FakeManager(
            [_FakeProvider("dashscope", api_key="sk-existing")],
        )
        assert await migration._migrate_env_keys(manager) == []
        assert manager.saved == []
        assert (
            manager.builtin_providers["dashscope"].api_key == "sk-existing"
        )

    async def test_skips_providers_without_key_requirement(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("OLLAMA_API_KEY", "sk-unused")
        manager = _FakeManager(
            [_FakeProvider("ollama", require_api_key=False)],
        )
        assert await migration._migrate_env_keys(manager) == []

    async def test_no_env_noop(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        manager = _FakeManager([_FakeProvider("deepseek")])
        assert await migration._migrate_env_keys(manager) == []


class TestRunProviderConfigMigration:
    async def test_unavailable_backend_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            provider_store,
            "pg_provider_plane_available",
            lambda: False,
        )
        assert await migration.run_provider_config_migration(
            _FakeManager([]),
        ) is False

    async def test_manifest_present_skips_import(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            provider_store,
            "pg_provider_plane_available",
            lambda: True,
        )
        manifest = tmp_path / ".provider_pg_migrated.json"
        manifest.write_text(
            json.dumps({"version": migration.MANIFEST_VERSION}),
            encoding="utf-8",
        )
        monkeypatch.setattr(migration, "_manifest_path", lambda: manifest)

        imported = {"count": 0}

        async def _no_import(manager):
            imported["count"] += 1
            return 0

        monkeypatch.setattr(migration, "_import_file_plane_to_pg", _no_import)
        manager = _FakeManager([])
        assert await migration.run_provider_config_migration(manager) is True
        assert imported["count"] == 0

    async def test_stale_manifest_version_reruns_import(
        self,
        monkeypatch,
        tmp_path,
    ):
        """投影结构升级（version 提号）后旧 manifest 自动重跑全量导入。"""
        monkeypatch.setattr(
            provider_store,
            "pg_provider_plane_available",
            lambda: True,
        )
        monkeypatch.setattr(
            provider_store,
            "provider_storage_backend",
            lambda: "dual",
        )
        manifest = tmp_path / ".provider_pg_migrated.json"
        manifest.write_text(json.dumps({"version": 1}), encoding="utf-8")
        monkeypatch.setattr(migration, "_manifest_path", lambda: manifest)

        imported = {"count": 0}

        async def _import(manager):
            imported["count"] += 1
            return 5

        monkeypatch.setattr(migration, "_import_file_plane_to_pg", _import)

        async def _no_env(manager):
            return []

        monkeypatch.setattr(migration, "_migrate_env_keys", _no_env)
        manager = _FakeManager([])
        assert await migration.run_provider_config_migration(manager) is True
        assert imported["count"] == 1
        payload = json.loads(
            manifest.read_text(encoding="utf-8"),
        )
        assert payload["version"] == migration.MANIFEST_VERSION
        assert payload["imported_providers"] == 5

    async def test_fresh_migration_imports_and_writes_manifest(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            provider_store,
            "pg_provider_plane_available",
            lambda: True,
        )
        monkeypatch.setattr(
            provider_store,
            "provider_storage_backend",
            lambda: "dual",
        )

        async def _import(manager):
            return 3

        monkeypatch.setattr(migration, "_import_file_plane_to_pg", _import)

        async def _no_env(manager):
            return []

        monkeypatch.setattr(migration, "_migrate_env_keys", _no_env)
        manager = _FakeManager([])
        assert await migration.run_provider_config_migration(manager) is True
        payload = json.loads(
            migration._manifest_path().read_text(encoding="utf-8"),
        )
        assert payload["imported_providers"] == 3
        assert payload["backend"] == "dual"

    async def test_failure_does_not_write_manifest(self, monkeypatch):
        monkeypatch.setattr(
            provider_store,
            "pg_provider_plane_available",
            lambda: True,
        )

        async def _boom(manager):
            raise RuntimeError("pg down")

        monkeypatch.setattr(migration, "_import_file_plane_to_pg", _boom)
        manager = _FakeManager([])
        assert await migration.run_provider_config_migration(manager) is False
        assert not migration._manifest_path().exists()
