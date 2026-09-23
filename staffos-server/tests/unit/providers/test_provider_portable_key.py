# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the portable provider api_key cipher (``ENC1:``).

可移植密钥层单测（不依赖真实 PostgreSQL）：验证 ENC1: 加解密闭环、
app_portable_keys 密钥的惰性创建与复用、upsert 入库密文形态、以及
读取时 ENC1:/ENC: 双形态按前缀分派解密。
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import pytest
from cryptography.fernet import Fernet

from qwenpaw.providers import provider_store


class _FakeResult:
    def __init__(
        self,
        rows: Optional[list[tuple]] = None,
        first_row: Optional[tuple] = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._first = first_row
        self.rowcount = rowcount

    def mappings(self) -> "_FakeResult":
        return self

    def __iter__(self):
        return iter(self._rows)

    def all(self) -> list[tuple]:
        return list(self._rows)

    def first(self) -> Optional[tuple]:
        return self._first


class _FakeConn:
    def __init__(self, script) -> None:
        self._script = script
        self.calls: list[tuple[str, Any]] = []

    async def execute(self, stmt: Any, params: Any = None):
        sql = str(stmt)
        self.calls.append((sql, params))
        return self._script(sql, params)

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeEngine:
    def __init__(self, script) -> None:
        self._script = script
        self.conns: list[_FakeConn] = []

    def _mk(self) -> _FakeConn:
        conn = _FakeConn(self._script)
        self.conns.append(conn)
        return conn

    def connect(self) -> _FakeConn:
        return self._mk()

    def begin(self) -> _FakeConn:
        return self._mk()


@pytest.fixture(autouse=True)
def _reset_key_cache():
    provider_store._portable_key_cache = None
    yield
    provider_store._portable_key_cache = None


def _calls(engine: _FakeEngine) -> list[tuple[str, Any]]:
    return [call for conn in engine.conns for call in conn.calls]


# ---------------------------------------------------------------------------
# Cipher helpers
# ---------------------------------------------------------------------------


def test_portable_roundtrip():
    key = Fernet.generate_key()
    token = provider_store._portable_encrypt("sk-secret", key)
    assert token.startswith("ENC1:")
    assert "sk-secret" not in token
    assert provider_store._portable_decrypt(token, key) == "sk-secret"


def test_portable_decrypt_degrades_on_bad_token():
    key = Fernet.generate_key()
    assert provider_store._portable_decrypt("ENC1:not-a-token", key) == (
        "ENC1:not-a-token"
    )


# ---------------------------------------------------------------------------
# Key material: lazy load / create
# ---------------------------------------------------------------------------


def test_load_or_create_portable_key_existing_row(monkeypatch):
    key = Fernet.generate_key()

    def _script(sql, params):
        if "SELECT key_value FROM app_portable_keys" in sql:
            assert params["key_name"] == "provider_api_key"
            return _FakeResult(first_row=(key.decode("ascii"),))
        raise AssertionError(f"unexpected sql: {sql}")

    monkeypatch.setattr(
        "qwenpaw.db.engine.create_pg_engine",
        lambda: _FakeEngine(_script),
    )

    loaded = asyncio.run(provider_store._load_or_create_portable_key())
    assert loaded == key


def test_load_or_create_portable_key_creates_when_missing(monkeypatch):
    generated: dict = {}
    existing_key = Fernet.generate_key()

    def _script(sql, params):
        if "SELECT key_value FROM app_portable_keys" in sql:
            # 首次 miss，INSERT 后重读命中
            if generated:
                return _FakeResult(
                    first_row=(generated["key_value"],),
                )
            return _FakeResult(first_row=None)
        if "INSERT INTO app_portable_keys" in sql:
            generated.update(params)
            return _FakeResult()
        raise AssertionError(f"unexpected sql: {sql}")

    monkeypatch.setattr(
        "qwenpaw.db.engine.create_pg_engine",
        lambda: _FakeEngine(_script),
    )

    loaded = asyncio.run(provider_store._load_or_create_portable_key())

    # 生成的是合法 Fernet key 且与 INSERT 入库值一致
    Fernet(loaded)
    assert generated["key_value"] == loaded.decode("ascii")
    assert generated["key_name"] == "provider_api_key"
    assert generated["tenant_id"] == "default"
    # 与既有 key 不同（新生成）
    assert loaded != existing_key


# ---------------------------------------------------------------------------
# Upsert / load integration (fake engine)
# ---------------------------------------------------------------------------


def test_upsert_stores_portable_cipher(monkeypatch):
    key = Fernet.generate_key()

    def _script(sql, params):
        if "SELECT key_value FROM app_portable_keys" in sql:
            return _FakeResult(first_row=(key.decode("ascii"),))
        if "INSERT INTO provider_configs" in sql:
            return _FakeResult()
        raise AssertionError(f"unexpected sql: {sql}")

    engine = _FakeEngine(_script)

    asyncio.run(provider_store.upsert_provider_snapshot_pg(
        {"id": "p1", "api_key": "sk-secret"},
        engine=engine,
    ))

    inserts = [
        c for c in _calls(engine) if "INSERT INTO provider_configs" in c[0]
    ]
    assert len(inserts) == 1
    params = inserts[0][1]
    cipher = params["api_key_encrypted"]
    assert cipher.startswith("ENC1:")
    assert "sk-secret" not in cipher
    # snapshot JSONB 载荷不含明文 api_key
    assert "api_key" not in params["snapshot_json"]


def test_upsert_empty_key_stores_empty_cipher(monkeypatch):
    def _script(sql, params):
        if "SELECT key_value FROM app_portable_keys" in sql:
            raise AssertionError("empty key must not touch the key table")
        if "INSERT INTO provider_configs" in sql:
            return _FakeResult()
        raise AssertionError(f"unexpected sql: {sql}")

    engine = _FakeEngine(_script)

    asyncio.run(provider_store.upsert_provider_snapshot_pg(
        {"id": "p1", "api_key": ""},
        engine=engine,
    ))

    inserts = [
        c for c in _calls(engine) if "INSERT INTO provider_configs" in c[0]
    ]
    assert inserts[0][1]["api_key_encrypted"] == ""


def test_load_snapshots_decrypts_portable_cipher(monkeypatch):
    key = Fernet.generate_key()
    cipher = provider_store._portable_encrypt("sk-secret", key)

    def _script(sql, params):
        if "SELECT key_value FROM app_portable_keys" in sql:
            return _FakeResult(first_row=(key.decode("ascii"),))
        if "SELECT provider_id, name, base_url" in sql:
            return _FakeResult(rows=[
                ("p1", "P1", "https://x", cipher, {"is_custom": False}),
            ])
        raise AssertionError(f"unexpected sql: {sql}")

    monkeypatch.setattr(
        "qwenpaw.db.engine.create_pg_engine",
        lambda: _FakeEngine(_script),
    )

    snapshots = asyncio.run(provider_store.load_provider_snapshots_pg())
    assert snapshots[0]["api_key"] == "sk-secret"


def test_row_to_provider_data_legacy_local_cipher(monkeypatch):
    """存量 ``ENC:`` 本机密文走 keychain 解密（前缀分派兼容）。"""
    from qwenpaw.security import secret_store

    monkeypatch.setattr(
        provider_store,
        "decrypt",
        lambda value: "sk-local" if value.startswith("ENC:") else value,
    )
    data = provider_store._row_to_provider_data(
        "p1",
        "P1",
        "https://x",
        secret_store.encrypt("sk-local"),
        {},
        portable_key=None,
    )
    assert data["api_key"] == "sk-local"
