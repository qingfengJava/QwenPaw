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
def test_dual_and_pg_backends_rejected_until_m2(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    tmp_path,
) -> None:
    monkeypatch.setenv(STORAGE_BACKEND_ENV, backend)
    with pytest.raises(ConfigurationException, match="not available"):
        build_chat_repository(tmp_path / "chats.json")
    with pytest.raises(ConfigurationException, match="not available"):
        build_session_store(str(tmp_path))
    with pytest.raises(ConfigurationException, match="not available"):
        get_session_store_class()
