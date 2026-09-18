# -*- coding: utf-8 -*-
"""Integration tests for the driver PG authoritative plane (T12).

对真实 PostgreSQL（5433 隔离库）验证 ``driver_cards`` / ``driver_credentials``
双表与 :class:`DriverConfigService` 双平面：

- 卡写入幂等（内容未变重放不刷新）、读优先 PG、删双平面移除；
- 凭据密文往返（secret_store 加密入 cipher、读回解密）；
- backfill 把存量文件卡/凭据种入 PG，PG 已有卡时跳过。

仅在 ``QWENPAW_TEST_PG_DSN`` 设置时运行；全部数据用 ``captest_`` 前缀，
夹具按前缀定点清理，绝不触碰存量业务数据。

@author qingfeng
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

# 定点清理（仅 captest_ 前缀；逐条静态语句，零插值）
_CLEANUP_STATEMENTS = (
    "DELETE FROM driver_cards WHERE agent_id LIKE 'captest_%'",
    "DELETE FROM driver_credentials WHERE agent_id LIKE 'captest_%'",
)


@pytest.fixture
async def driver_env(monkeypatch):
    """Bootstrap schema to head (incl 0039), clean captest_ rows."""
    if not DSN:
        pytest.skip("QWENPAW_TEST_PG_DSN not set")
    monkeypatch.setenv("QWENPAW_PG_DSN", DSN)

    from qwenpaw.app import driver_config as _pkg  # noqa: F401 (ensure import)
    from qwenpaw.app import enterprise as ent_mod
    from qwenpaw.app.driver_config import pg_store as store_mod
    from qwenpaw.db import engine as engine_mod

    engine_mod._engines.clear()
    ent_mod._schema_ready = False
    store_mod.reset_store_for_tests()
    ok = await ent_mod.bootstrap_enterprise()
    assert ok, "enterprise bootstrap failed against the test database"
    engine = engine_mod.create_pg_engine(DSN)
    async with engine.begin() as conn:
        for statement in _CLEANUP_STATEMENTS:
            await conn.execute(text(statement))
    try:
        yield store_mod.get_driver_pg_store()
    finally:
        async with engine.begin() as conn:
            for statement in _CLEANUP_STATEMENTS:
                await conn.execute(text(statement))
        store_mod.reset_store_for_tests()
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


def _workspace(tmp_path: Path, agent_id: str) -> SimpleNamespace:
    ws_dir = tmp_path / agent_id
    ws_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(workspace_dir=ws_dir, agent_id=agent_id)


def _card(name: str):
    from qwenpaw.drivers.contracts import DriverCard

    return DriverCard(
        name=name,
        protocol="mcp",
        endpoint={"transport": "stdio", "command": "npx"},
        config={"display_name": name.title()},
        credentials={},
        enabled=True,
    )


@pytest.mark.asyncio
async def test_card_upsert_idempotent_and_read(driver_env) -> None:
    store = driver_env
    written = await store.upsert_card(
        "captest_drv_a",
        name="linear",
        protocol="mcp",
        enabled=True,
        spec={"endpoint": {"command": "npx"}, "config": {}, "credentials": {}},
        policy={"default_effect": "deny", "rules": []},
    )
    assert written is True
    # 幂等重放：内容未变不再刷新
    replay = await store.upsert_card(
        "captest_drv_a",
        name="linear",
        protocol="mcp",
        enabled=True,
        spec={"endpoint": {"command": "npx"}, "config": {}, "credentials": {}},
        policy={"default_effect": "deny", "rules": []},
    )
    assert replay is False
    card = await store.get_card("captest_drv_a", "linear", protocol="mcp")
    assert card is not None
    assert card["enabled"] is True
    assert card["spec"]["endpoint"]["command"] == "npx"
    # 变更 enabled → 写入返回 True
    changed = await store.upsert_card(
        "captest_drv_a",
        name="linear",
        protocol="mcp",
        enabled=False,
        spec={"endpoint": {"command": "npx"}, "config": {}, "credentials": {}},
        policy={"default_effect": "deny", "rules": []},
    )
    assert changed is True
    assert (await store.get_card(
        "captest_drv_a", "linear", protocol="mcp",
    ))["enabled"] is False


@pytest.mark.asyncio
async def test_credential_cipher_roundtrip(driver_env) -> None:
    store = driver_env
    from qwenpaw.security.secret_store import is_encrypted

    # env: 引用绝不入库
    assert await store.put_credential(
        "captest_drv_b",
        {"ref": "env:TOKEN", "kind": "env", "secrets": {"value": "x"}},
    ) is False
    record = {
        "ref": "cred:linear",
        "kind": "static",
        "public": {"base": "https://api"},
        "secrets": {"api_key": "sk-live-secret"},
        "meta": {"note": "t12"},
    }
    assert await store.put_credential("captest_drv_b", record) is True
    loaded = await store.get_credential("captest_drv_b", "cred:linear")
    assert loaded is not None
    assert loaded["secrets"]["api_key"] == "sk-live-secret"
    assert loaded["public"]["base"] == "https://api"
    # 密文列不含明文
    engine = store._engine
    async with engine.connect() as conn:
        raw = (
            await conn.execute(
                text(
                    "SELECT cipher FROM driver_credentials WHERE "
                    "agent_id = 'captest_drv_b' AND ref = 'cred:linear'"
                ),
            )
        ).scalar_one()
    assert is_encrypted(raw)
    assert "sk-live-secret" not in raw
    assert await store.delete_credential("captest_drv_b", "cred:linear") is True
    assert await store.get_credential("captest_drv_b", "cred:linear") is None


@pytest.mark.asyncio
async def test_service_write_read_delete_dual_plane(
    driver_env, tmp_path, monkeypatch,
) -> None:
    from qwenpaw.app import driver_config_service as svc_mod
    from qwenpaw.app.driver_config_service import DriverConfigService

    store = driver_env
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: store)
    ws = _workspace(tmp_path, "captest_drv_c")
    service = DriverConfigService(ws)
    await service.save_card(_card("linear"), reload_driver=False)
    # PG 权威行 + 文件投影都在
    assert await store.get_card("captest_drv_c", "linear", protocol="mcp")
    assert (ws.workspace_dir / "drivers" / "mcp" / "linear.yaml").is_file()
    # 读优先 PG
    loaded = await service.load_card("linear", protocol="mcp")
    assert loaded.name == "linear"
    await service.delete_driver_best_effort("linear")
    assert await store.get_card("captest_drv_c", "linear", protocol="mcp") is None


@pytest.mark.asyncio
async def test_backfill_seeds_files_into_pg(
    driver_env, tmp_path, monkeypatch,
) -> None:
    from qwenpaw.app import driver_config_service as svc_mod
    from qwenpaw.app.driver_config_service import DriverConfigService

    store = driver_env
    ws = _workspace(tmp_path, "captest_drv_d")
    # 先以「无 PG」模式纯写文件（模拟存量 legacy 卡）
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: None)
    s0 = DriverConfigService(ws)
    await s0.save_card(_card("alpha"), reload_driver=False)
    await s0.save_card(_card("beta"), reload_driver=False)
    # 切回真实 PG，PG 尚空 → 回填种入
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: store)
    seeded = await DriverConfigService(ws).backfill_to_pg()
    assert seeded == 2
    names = {c["name"] for c in await store.list_cards("captest_drv_d")}
    assert names == {"alpha", "beta"}
    # 再回填一次：PG 已有卡 → 跳过
    assert await DriverConfigService(ws).backfill_to_pg() == 0
