# -*- coding: utf-8 -*-
"""Unit tests for the chats storage backend factory."""

from __future__ import annotations

import pytest

from qwenpaw.app.chats.factory import (
    STORAGE_BACKEND_ENV,
    build_chat_repository,
    build_session_store,
    get_session_store_class,
    get_storage_backend,
)
from qwenpaw.app.chats.repo.json_repo import JsonChatRepository
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.exceptions import ConfigurationException

LEGACY_STORAGE_BACKEND_ENV = "COPAW_STORAGE_BACKEND"


@pytest.fixture(autouse=True)
def _clean_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts without any backend override."""
    monkeypatch.delenv(STORAGE_BACKEND_ENV, raising=False)
    monkeypatch.delenv(LEGACY_STORAGE_BACKEND_ENV, raising=False)


def test_default_backend_is_json() -> None:
    assert get_storage_backend() == "json"


def test_explicit_json_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STORAGE_BACKEND_ENV, "json")
    assert get_storage_backend() == "json"


def test_backend_value_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STORAGE_BACKEND_ENV, " JSON ")
    assert get_storage_backend() == "json"


def test_invalid_backend_falls_back_to_json(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(STORAGE_BACKEND_ENV, "not-a-backend")
    with caplog.at_level("WARNING"):
        assert get_storage_backend() == "json"
    assert STORAGE_BACKEND_ENV in caplog.text


def test_legacy_copaw_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LEGACY_STORAGE_BACKEND_ENV, "dual")
    assert get_storage_backend() == "dual"


def test_primary_env_wins_over_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STORAGE_BACKEND_ENV, "json")
    monkeypatch.setenv(LEGACY_STORAGE_BACKEND_ENV, "dual")
    assert get_storage_backend() == "json"


def test_build_chat_repository_json(tmp_path) -> None:
    repo = build_chat_repository(tmp_path / "chats.json")
    assert isinstance(repo, JsonChatRepository)


def test_build_session_store_json(tmp_path) -> None:
    store = build_session_store(str(tmp_path))
    assert isinstance(store, SafeJSONSession)


def test_get_session_store_class_json() -> None:
    assert get_session_store_class() is SafeJSONSession


@pytest.mark.parametrize("backend", ["dual", "pg"])
def test_dual_and_pg_backends_require_pg_dsn(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    tmp_path,
) -> None:
    """M2: dual/pg need QWENPAW_PG_DSN; missing it is a clear error."""
    monkeypatch.setenv(STORAGE_BACKEND_ENV, backend)
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    monkeypatch.delenv("COPAW_PG_DSN", raising=False)
    with pytest.raises(ConfigurationException, match="QWENPAW_PG_DSN"):
        build_chat_repository(tmp_path / "chats.json")
    with pytest.raises(ConfigurationException, match="QWENPAW_PG_DSN"):
        build_session_store(str(tmp_path))
    with pytest.raises(ConfigurationException, match="QWENPAW_PG_DSN"):
        get_session_store_class()(save_dir=str(tmp_path))


@pytest.mark.parametrize("backend", ["dual", "pg"])
def test_dual_and_pg_backends_build_with_dsn(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    tmp_path,
) -> None:
    """Engine creation is lazy (no connection), so building is offline-safe."""
    from qwenpaw.app.chats.dual_session_store import DualSessionStore
    from qwenpaw.app.chats.pg_session_store import PgSessionStore
    from qwenpaw.app.chats.repo.dual_repo import DualChatRepository
    from qwenpaw.app.chats.repo.pg_repo import PgChatRepository

    monkeypatch.setenv(STORAGE_BACKEND_ENV, backend)
    monkeypatch.setenv(
        "QWENPAW_PG_DSN",
        "postgresql+asyncpg://u:p@127.0.0.1:5432/qwenpaw",
    )

    repo = build_chat_repository(tmp_path / "chats.json")
    expected_repo = PgChatRepository if backend == "pg" else DualChatRepository
    assert isinstance(repo, expected_repo)

    store = build_session_store(str(tmp_path))
    expected_store = PgSessionStore if backend == "pg" else DualSessionStore
    assert isinstance(store, expected_store)
