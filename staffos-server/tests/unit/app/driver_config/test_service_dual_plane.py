# -*- coding: utf-8 -*-
"""Unit tests for the dual-plane (PG authoritative + file projection) of
:class:`DriverConfigService` (T12).

用假 PG store 替换模块内 ``get_driver_pg_store``，配真实临时 workspace
（文件投影走真实 ``AsyncDriverCardStore`` / ``AsyncCredentialStore``），
覆盖：

- 写：save_card / save_credential 既镜像 PG 又落文件投影；
- 读：load_card / list_cards 优先读 PG，PG 无行/无 PG 时回退文件；
- json 后端（store=None）：完全不触 PG，行为不变；
- 删：delete_driver_best_effort / delete_credential 双平面移除；
- backfill：PG 空时把文件卡种入 PG，PG 已有卡时跳过。

@author qingfeng
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app import driver_config_service as svc_mod
from qwenpaw.app.driver_config_service import DriverConfigService
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.credentials.types import CredentialRecord


class _FakePgStore:
    """记录调用并可编排读取返回值的假 store。"""

    def __init__(self, *, cards=None, card=None, credential=None,
                 has_cards=False) -> None:
        self.upserts: list[dict] = []
        self.deletes: list[tuple] = []
        self.cred_puts: list[tuple] = []
        self.cred_deletes: list[tuple] = []
        self._cards = cards if cards is not None else []
        self._card = card
        self._credential = credential
        self._has_cards = has_cards

    async def upsert_card(self, agent_id, **kwargs):
        self.upserts.append({"agent_id": agent_id, **kwargs})
        return True

    async def get_card(self, agent_id, name, *, protocol):
        return self._card

    async def list_cards(self, agent_id, *, protocol=None):
        return self._cards

    async def delete_card(self, agent_id, name, *, protocol=None):
        self.deletes.append((agent_id, name, protocol))
        return True

    async def put_credential(self, agent_id, record):
        self.cred_puts.append((agent_id, record))
        return True

    async def get_credential(self, agent_id, ref):
        return self._credential

    async def delete_credential(self, agent_id, ref):
        self.cred_deletes.append((agent_id, ref))
        return True

    async def has_any_cards(self, agent_id):
        return self._has_cards


def _workspace(tmp_path: Path):
    """无 driver_manager 的 workspace：文件投影用真实 store。"""
    ws_dir = tmp_path / "agent_xyz"
    ws_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(workspace_dir=ws_dir, agent_id="agent_xyz")


def _card(name="linear") -> DriverCard:
    return DriverCard(
        name=name,
        protocol="mcp",
        endpoint={"transport": "stdio", "command": "npx"},
        config={"display_name": "Linear"},
        credentials={},
        enabled=True,
    )


@pytest.fixture
def no_pg(monkeypatch):
    """默认让工厂返回 None（json 后端），逐个用例显式覆盖。"""
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: None)


# ---------------------------------------------------------------------------
# 写：PG 镜像 + 文件投影 / json 后端零动作
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_card_mirrors_pg_and_projects_file(tmp_path, monkeypatch):
    fake = _FakePgStore()
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    ws = _workspace(tmp_path)
    service = DriverConfigService(ws)
    await service.save_card(_card(), reload_driver=False)
    # PG 权威镜像发生（自然键 + spec/policy 齐全）
    assert len(fake.upserts) == 1
    up = fake.upserts[0]
    assert up["agent_id"] == "agent_xyz"
    assert up["name"] == "linear"
    assert up["protocol"] == "mcp"
    assert up["enabled"] is True
    assert up["spec"]["endpoint"]["command"] == "npx"
    # 文件投影同时落盘（运行时热路径据此构建）
    card_file = ws.workspace_dir / "drivers" / "mcp" / "linear.yaml"
    assert card_file.is_file()


@pytest.mark.asyncio
async def test_save_card_json_backend_no_pg(tmp_path, no_pg):
    ws = _workspace(tmp_path)
    service = DriverConfigService(ws)
    # get_driver_pg_store=None → 纯文件，不触任何 PG
    await service.save_card(_card(), reload_driver=False)
    card_file = ws.workspace_dir / "drivers" / "mcp" / "linear.yaml"
    assert card_file.is_file()


# ---------------------------------------------------------------------------
# 读：PG 优先 / PG 无行回退文件
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_card_prefers_pg(tmp_path, monkeypatch):
    payload = {
        "name": "linear",
        "protocol": "mcp",
        "enabled": True,
        "spec": {
            "endpoint": {"transport": "http", "url": "http://pg"},
            "config": {"display_name": "FromPG"},
            "credentials": {},
        },
        "policy": {"default_effect": "allow", "rules": []},
    }
    fake = _FakePgStore(card=payload)
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    service = DriverConfigService(_workspace(tmp_path))
    card = await service.load_card("linear", protocol="mcp")
    # 读到 PG 权威（endpoint.url=http://pg），未落文件也不 404
    assert card.endpoint["url"] == "http://pg"
    assert card.config["display_name"] == "FromPG"


@pytest.mark.asyncio
async def test_load_card_falls_back_to_file(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    service = DriverConfigService(ws)
    # 先写文件投影
    await service.save_card(_card(), reload_driver=False)
    # PG 无该行 → 回退文件读
    fake = _FakePgStore(card=None)
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    card = await service.load_card("linear", protocol="mcp")
    assert card.name == "linear"


@pytest.mark.asyncio
async def test_list_cards_prefers_pg(tmp_path, monkeypatch):
    fake = _FakePgStore(
        cards=[
            {
                "name": "frompg",
                "protocol": "mcp",
                "enabled": True,
                "spec": {"endpoint": {}, "config": {}, "credentials": {}},
                "policy": {},
            },
        ],
    )
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    service = DriverConfigService(_workspace(tmp_path))
    cards = await service.list_cards(protocol="mcp")
    assert [c.name for c in cards] == ["frompg"]


# ---------------------------------------------------------------------------
# 凭据：PG 镜像 + 文件 / 读优先 PG
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_credential_mirrors_pg_and_file(tmp_path, monkeypatch):
    fake = _FakePgStore()
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    service = DriverConfigService(_workspace(tmp_path))
    record = CredentialRecord(
        ref="cred:linear",
        kind="static",
        secrets={"api_key": "sk-1"},
    )
    await service.save_credential(record)
    assert fake.cred_puts and fake.cred_puts[0][1]["ref"] == "cred:linear"
    # 文件投影可读回（best-effort 加密落 credentials.yaml）
    loaded = await service.credential_store.get("cred:linear")
    assert loaded.secrets["api_key"] == "sk-1"


@pytest.mark.asyncio
async def test_load_optional_credential_prefers_pg(tmp_path, monkeypatch):
    fake = _FakePgStore(
        credential={
            "ref": "cred:linear",
            "kind": "static",
            "public": {},
            "secrets": {"api_key": "sk-pg"},
            "meta": {},
        },
    )
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    service = DriverConfigService(_workspace(tmp_path))
    record = await service.load_optional_credential("cred:linear")
    assert record is not None
    assert record.secrets["api_key"] == "sk-pg"


@pytest.mark.asyncio
async def test_delete_credential_both_planes(tmp_path, monkeypatch):
    fake = _FakePgStore()
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    service = DriverConfigService(_workspace(tmp_path))
    await service.save_credential(
        CredentialRecord(ref="cred:linear", kind="static",
                         secrets={"api_key": "sk-1"}),
    )
    await service.delete_credential("cred:linear")
    assert ("agent_xyz", "cred:linear") in fake.cred_deletes
    # 文件投影同步移除（缺失引用不再列于 refs）
    assert "cred:linear" not in await service.credential_store.list_refs()


# ---------------------------------------------------------------------------
# 删除：双平面移除
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_driver_removes_pg(tmp_path, monkeypatch):
    fake = _FakePgStore()
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    ws = _workspace(tmp_path)
    service = DriverConfigService(ws)
    await service.save_card(_card(), reload_driver=False)
    await service.delete_driver_best_effort("linear")
    assert fake.deletes and fake.deletes[0][1] == "linear"
    assert not (ws.workspace_dir / "drivers" / "mcp" / "linear.yaml").exists()


# ---------------------------------------------------------------------------
# backfill：PG 空则种入，PG 有则跳过
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_seeds_when_pg_empty(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    # 无 PG 下先写两张文件卡
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: None)
    service0 = DriverConfigService(ws)
    await service0.save_card(_card("alpha"), reload_driver=False)
    await service0.save_card(_card("beta"), reload_driver=False)
    # PG 尚空 → 回填种入两张
    fake = _FakePgStore(has_cards=False)
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    seeded = await DriverConfigService(ws).backfill_to_pg()
    assert seeded == 2
    names = {u["name"] for u in fake.upserts}
    assert names == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_backfill_skips_when_pg_present(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: None)
    await DriverConfigService(ws).save_card(_card(), reload_driver=False)
    fake = _FakePgStore(has_cards=True)
    monkeypatch.setattr(svc_mod, "get_driver_pg_store", lambda: fake)
    seeded = await DriverConfigService(ws).backfill_to_pg()
    assert seeded == 0
    assert fake.upserts == []


@pytest.mark.asyncio
async def test_backfill_no_pg_returns_zero(tmp_path, no_pg):
    service = DriverConfigService(_workspace(tmp_path))
    assert await service.backfill_to_pg() == 0
