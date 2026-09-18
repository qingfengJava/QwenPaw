# -*- coding: utf-8 -*-
"""Unit tests for the driver PG store (``driver_cards`` and
``driver_credentials``).

覆盖 store 层契约（不连真实 PG，用参数捕获 + 行返回的假引擎）：

- 卡写入为单条幂等 upsert（ON CONFLICT + WHERE 变更门 + RETURNING），
  spec/policy 以 JSON 字符串入 CAST(... AS JSONB)，enabled 归一为 bool；
- 行还原：asyncpg 的 JSONB 可能回 dict 或 str、bool 可能被 text() 全
  str 化，store 必须归一（spec→dict、enabled→bool），避免污染类型；
- 凭据密文：put 用 secret_store.encrypt 整包 JSON、get decrypt 还原，
  env: 引用绝不入库；
- 删除/存在性判定走各自 SQL 形态。

@author qingfeng
"""
# pylint: disable=protected-access
from __future__ import annotations

import json

import pytest

from qwenpaw.app.driver_config.pg_store import DriverPgStore
from qwenpaw.security.secret_store import decrypt, is_encrypted


class _FakeResult:
    """mappings()/first/all 与 rowcount 兼容的最小结果对象。"""

    def __init__(self, row=None, rows=None, rowcount=0) -> None:
        self._row = row
        if rows is None:
            rows = [] if row is None else [row]
        self._rows = rows
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _FakeConn:
    """按表名路由的最小假连接，捕获执行语句与参数。"""

    def __init__(self, *, changed=True, card_row=None, card_rows=None,
                 credential_cipher=None, has_cards=False,
                 rowcount=1) -> None:
        self.statements: list[tuple[str, dict]] = []
        self._changed = changed
        self._card_row = card_row
        self._card_rows = card_rows or []
        self._credential_cipher = credential_cipher
        self._has_cards = has_cards
        self._rowcount = rowcount

    async def execute(self, sql, params):
        text_sql = str(sql)
        self.statements.append((text_sql, dict(params)))
        if "driver_credentials" in text_sql:
            if text_sql.strip().upper().startswith("SELECT"):
                if self._credential_cipher is None:
                    return _FakeResult(None)
                return _FakeResult({"cipher": self._credential_cipher})
            return _FakeResult(rowcount=self._rowcount)
        # driver_cards 路径
        if "RETURNING 1" in text_sql:
            return _FakeResult({"?column?": 1} if self._changed else None)
        if "SELECT 1 FROM driver_cards" in text_sql:
            return _FakeResult({"?column?": 1} if self._has_cards else None)
        if text_sql.strip().upper().startswith("SELECT"):
            if "ORDER BY" in text_sql:
                return _FakeResult(rows=self._card_rows)
            return _FakeResult(self._card_row)
        if text_sql.strip().upper().startswith("DELETE"):
            return _FakeResult(rowcount=self._rowcount)
        return _FakeResult(rowcount=self._rowcount)


class _FakeEngine:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    class _Ctx:
        def __init__(self, conn) -> None:
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *args):
            return False

    def begin(self):
        return self._Ctx(self.conn)

    def connect(self):
        return self._Ctx(self.conn)


def _store(conn: _FakeConn) -> DriverPgStore:
    return DriverPgStore(engine=_FakeEngine(conn))


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_card_single_idempotent_statement() -> None:
    conn = _FakeConn(changed=True)
    store = _store(conn)
    written = await store.upsert_card(
        "agent_a",
        name="linear",
        protocol="mcp",
        enabled=True,
        spec={
            "endpoint": {"transport": "stdio"},
            "config": {},
            "credentials": {},
        },
        policy={"default_effect": "deny", "rules": []},
    )
    assert written is True
    assert len(conn.statements) == 1
    sql, params = conn.statements[0]
    assert "ON CONFLICT (tenant_id, agent_id, protocol, name)" in sql
    assert "CAST(:spec AS JSONB)" in sql
    assert "CAST(:policy AS JSONB)" in sql
    assert params["enabled"] is True
    # spec/policy 以 JSON 字符串入参（列侧 CAST 成 JSONB）
    assert isinstance(params["spec"], str)
    assert json.loads(params["spec"])["endpoint"]["transport"] == "stdio"


@pytest.mark.asyncio
async def test_upsert_card_unchanged_returns_false() -> None:
    conn = _FakeConn(changed=False)
    store = _store(conn)
    written = await store.upsert_card(
        "agent_a",
        name="linear",
        protocol="mcp",
        enabled=True,
        spec={},
        policy={},
    )
    assert written is False


@pytest.mark.asyncio
async def test_get_card_normalizes_str_jsonb_and_bool() -> None:
    # 模拟 text() 把 bool 回成 str、JSONB 回成 str 的最坏情况
    conn = _FakeConn(
        card_row={
            "name": "linear",
            "protocol": "mcp",
            "enabled": "false",
            "spec": json.dumps({"endpoint": {"url": "http://x"}}),
            "policy": json.dumps({"default_effect": "allow", "rules": []}),
        },
    )
    store = _store(conn)
    card = await store.get_card("agent_a", "linear", protocol="mcp")
    assert card["enabled"] is False
    assert card["spec"] == {"endpoint": {"url": "http://x"}}
    assert card["policy"]["default_effect"] == "allow"


@pytest.mark.asyncio
async def test_get_card_missing_returns_none() -> None:
    store = _store(_FakeConn(card_row=None))
    assert await store.get_card("agent_a", "nope", protocol="mcp") is None


@pytest.mark.asyncio
async def test_list_cards_protocol_filter() -> None:
    conn = _FakeConn(card_rows=[])
    store = _store(conn)
    # 带协议过滤
    await store.list_cards("agent_a", protocol="mcp")
    sql, params = conn.statements[0]
    assert "AND protocol = :proto" in sql
    assert params["proto"] == "mcp"
    # 无过滤
    await store.list_cards("agent_a")
    sql2, _ = conn.statements[1]
    assert "AND protocol = :proto" not in sql2


@pytest.mark.asyncio
async def test_delete_card_cross_protocol_default() -> None:
    conn = _FakeConn(rowcount=2)
    store = _store(conn)
    removed = await store.delete_card("agent_a", "linear")
    assert removed is True
    sql, _ = conn.statements[0]
    assert sql.strip().upper().startswith("DELETE")
    assert "AND protocol = :proto" not in sql


@pytest.mark.asyncio
async def test_has_any_cards_flag() -> None:
    assert await _store(_FakeConn(has_cards=True)).has_any_cards("a") is True
    assert await _store(_FakeConn(has_cards=False)).has_any_cards("a") is False


# ---------------------------------------------------------------------------
# credentials（密文往返 + env 跳过）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_credential_encrypts_and_skips_env_refs() -> None:
    conn = _FakeConn()
    store = _store(conn)
    # env: 引用指向进程环境，绝不入库
    skipped = await store.put_credential(
        "agent_a",
        {"ref": "env:TOKEN", "kind": "env", "secrets": {"value": "x"}},
    )
    assert skipped is False
    assert conn.statements == []
    # 普通静态凭据入库并加密
    wrote = await store.put_credential(
        "agent_a",
        {
            "ref": "cred:linear",
            "kind": "static",
            "public": {},
            "secrets": {"api_key": "sk-live-123"},
            "meta": {},
        },
    )
    assert wrote is True
    sql, params = conn.statements[0]
    assert "INSERT INTO driver_credentials" in sql
    assert is_encrypted(params["cipher"])
    # 明文绝不出现在密文里
    assert "sk-live-123" not in params["cipher"]


@pytest.mark.asyncio
async def test_get_credential_decrypts_roundtrip() -> None:
    record = {
        "ref": "cred:linear",
        "kind": "static",
        "public": {},
        "secrets": {"api_key": "sk-live-123"},
        "meta": {},
    }
    from qwenpaw.security.secret_store import encrypt

    cipher = encrypt(json.dumps(record, sort_keys=True, ensure_ascii=False))
    store = _store(_FakeConn(credential_cipher=cipher))
    loaded = await store.get_credential("agent_a", "cred:linear")
    assert loaded is not None
    assert loaded["secrets"]["api_key"] == "sk-live-123"
    assert decrypt(cipher) != cipher


@pytest.mark.asyncio
async def test_get_credential_env_and_missing_none() -> None:
    store = _store(_FakeConn(credential_cipher=None))
    # env: 直接返回 None（不落库也不读库）
    assert await store.get_credential("a", "env:X") is None
    # 无行 → None
    assert await store.get_credential("a", "cred:missing") is None


@pytest.mark.asyncio
async def test_delete_credential_skips_env() -> None:
    conn = _FakeConn(rowcount=1)
    store = _store(conn)
    assert await store.delete_credential("a", "env:X") is False
    assert conn.statements == []
    assert await store.delete_credential("a", "cred:linear") is True
