# -*- coding: utf-8 -*-
"""Unit tests for qwenpaw.app.media_store.

Covers the local media-file resolver (traversal protection) and the PG
blob helpers' graceful degradation when PostgreSQL is unavailable.
"""
from __future__ import annotations

# pylint: disable=protected-access

from pathlib import Path

import pytest

from qwenpaw.app.media_store import (
    load_media_blob,
    resolve_local_media_file,
    save_media_blob,
)
from qwenpaw.exceptions import ConfigurationException


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    (tmp_path / "8a4c3219aed943bfae3a55ded71f4d89_image.png").write_bytes(
        b"png-bytes",
    )
    return tmp_path


class TestResolveLocalMediaFile:
    def test_existing_file(self, media_dir: Path):
        stored = "8a4c3219aed943bfae3a55ded71f4d89_image.png"
        resolved = resolve_local_media_file(media_dir, stored)
        assert resolved == (media_dir / stored).resolve()

    def test_missing_file(self, media_dir: Path):
        assert resolve_local_media_file(media_dir, "nope.png") is None

    def test_rejects_path_separators(self, media_dir: Path):
        assert resolve_local_media_file(media_dir, "sub/a.png") is None
        assert resolve_local_media_file(media_dir, "sub\\a.png") is None

    def test_rejects_traversal(self, media_dir: Path):
        assert resolve_local_media_file(media_dir, "..") is None
        assert resolve_local_media_file(media_dir, ".") is None

    def test_rejects_hidden_names(self, media_dir: Path):
        assert resolve_local_media_file(media_dir, ".env") is None

    def test_empty_name(self, media_dir: Path):
        assert resolve_local_media_file(media_dir, "") is None


class TestPgDegradation:
    """When PostgreSQL is not configured the helpers degrade, not raise."""

    @pytest.mark.asyncio
    async def test_save_returns_false(self, monkeypatch):
        def _raise():
            raise ConfigurationException(
                message="no dsn",
                config_key="QWENPAW_PG_DSN",
            )

        monkeypatch.setattr(
            "qwenpaw.db.engine.create_pg_engine",
            _raise,
        )
        ok = await save_media_blob(
            stored_name="a.png",
            file_name="a.png",
            media_type="image/png",
            data=b"x",
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_load_returns_none(self, monkeypatch):
        def _raise():
            raise ConfigurationException(
                message="no dsn",
                config_key="QWENPAW_PG_DSN",
            )

        monkeypatch.setattr(
            "qwenpaw.db.engine.create_pg_engine",
            _raise,
        )
        assert await load_media_blob("a.png") is None
