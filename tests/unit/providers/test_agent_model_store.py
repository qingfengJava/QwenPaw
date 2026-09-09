# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the agent default model slot plane (三态读写语义)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers import agent_model_store
from qwenpaw.providers import provider_store


@pytest.fixture(autouse=True)
def _pin_backend_env(monkeypatch):
    """钉回测试期望的后端环境，防止宿主机配置污染（历史教训）。"""
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    provider_store.reset_backend_cache()
    yield
    provider_store.reset_backend_cache()


def _agent_config(active_model=None):
    return SimpleNamespace(active_model=active_model)


class TestResolveAgentActiveModel:
    def test_json_backend_reads_file_plane_only(self, monkeypatch):
        """json 后端：不触碰 PG，直接返回 agent.json 的 active_model。"""
        file_slot = ModelSlotConfig(provider_id="p1", model="m1")
        touched = {"count": 0}

        async def _fail_get(agent_id):
            touched["count"] += 1
            raise AssertionError("json backend must not query PG")

        monkeypatch.setattr(agent_model_store, "get_agent_model_slot_pg", _fail_get)
        result = asyncio.run(
            agent_model_store.resolve_agent_active_model("a1", _agent_config(file_slot)),
        )
        assert result is file_slot
        assert touched["count"] == 0

    def test_dual_backend_reads_file_plane_only(self, monkeypatch):
        """dual 后端：读权威在文件平面（本表只影子写，不参与读）。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        file_slot = ModelSlotConfig(provider_id="p1", model="m1")

        async def _fail_get(agent_id):
            raise AssertionError("dual backend must not read PG")

        monkeypatch.setattr(agent_model_store, "get_agent_model_slot_pg", _fail_get)
        result = asyncio.run(
            agent_model_store.resolve_agent_active_model("a1", _agent_config(file_slot)),
        )
        assert result is file_slot

    def test_pg_backend_prefers_agent_model_slots_row(self, monkeypatch):
        """pg 后端：本表存在非空行时权威生效，覆盖 agent.json。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        file_slot = ModelSlotConfig(provider_id="p-file", model="m-file")

        async def _fake_get(agent_id):
            assert agent_id == "a1"
            return {"provider_id": "p-pg", "model": "m-pg"}

        monkeypatch.setattr(agent_model_store, "get_agent_model_slot_pg", _fake_get)
        result = asyncio.run(
            agent_model_store.resolve_agent_active_model("a1", _agent_config(file_slot)),
        )
        assert result is not None
        assert result.provider_id == "p-pg"
        assert result.model == "m-pg"

    def test_pg_backend_falls_back_when_row_missing(self, monkeypatch):
        """pg 后端：本表无行（存量员工）回退 agent.json 兼容。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        file_slot = ModelSlotConfig(provider_id="p-file", model="m-file")

        async def _fake_get(agent_id):
            return None

        monkeypatch.setattr(agent_model_store, "get_agent_model_slot_pg", _fake_get)
        result = asyncio.run(
            agent_model_store.resolve_agent_active_model("a1", _agent_config(file_slot)),
        )
        assert result is file_slot

    def test_pg_backend_silently_falls_back_on_error(self, monkeypatch):
        """pg 后端：PG 异常只降级回文件平面，绝不阻塞业务。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        file_slot = ModelSlotConfig(provider_id="p-file", model="m-file")

        async def _boom(agent_id):
            raise RuntimeError("pg down")

        monkeypatch.setattr(agent_model_store, "get_agent_model_slot_pg", _boom)
        result = asyncio.run(
            agent_model_store.resolve_agent_active_model("a1", _agent_config(file_slot)),
        )
        assert result is file_slot

    def test_pg_backend_empty_slot_row_falls_back(self, monkeypatch):
        """pg 后端：行存在但 provider/model 为空串视为未配置。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")

        async def _fake_get(agent_id):
            return {"provider_id": "", "model": ""}

        monkeypatch.setattr(agent_model_store, "get_agent_model_slot_pg", _fake_get)
        result = asyncio.run(
            agent_model_store.resolve_agent_active_model("a1", _agent_config(None)),
        )
        assert result is None


class TestPersistAgentModelSlot:
    def test_json_backend_never_touches_pg(self, monkeypatch):
        async def _fail_upsert(agent_id, provider_id, model):
            raise AssertionError("json backend must not write PG")

        monkeypatch.setattr(
            agent_model_store, "upsert_agent_model_slot_pg", _fail_upsert
        )
        asyncio.run(agent_model_store.persist_agent_model_slot("a1", "p1", "m1"))

    def test_dual_backend_schedules_shadow_write(self, monkeypatch):
        """dual 后端：走 fire-and-forget 影子调度（不 await 不阻塞）。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        captured = {}

        def _fake_schedule(operation):
            captured["scheduled"] = True

        monkeypatch.setattr(
            provider_store, "schedule_pg_write", _fake_schedule
        )
        asyncio.run(agent_model_store.persist_agent_model_slot("a1", "p1", "m1"))
        assert captured.get("scheduled") is True

    def test_pg_backend_awaits_authoritative_write(self, monkeypatch):
        """pg 后端：await 权威写（调用方拿到成功/失败再热重载）。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        captured = {}

        async def _fake_upsert(agent_id, provider_id, model):
            captured["args"] = (agent_id, provider_id, model)

        monkeypatch.setattr(
            agent_model_store, "upsert_agent_model_slot_pg", _fake_upsert
        )
        asyncio.run(agent_model_store.persist_agent_model_slot("a1", "p1", "m1"))
        assert captured["args"] == ("a1", "p1", "m1")

    def test_pg_backend_write_failure_never_raises(self, monkeypatch):
        """pg 后端：权威写失败仅告警，不向调用方抛异常。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")

        async def _boom(agent_id, provider_id, model):
            raise RuntimeError("pg down")

        monkeypatch.setattr(
            agent_model_store, "upsert_agent_model_slot_pg", _boom
        )
        # 不抛即通过（失败已降级为告警日志）
        asyncio.run(agent_model_store.persist_agent_model_slot("a1", "p1", "m1"))


class TestMirrorAgentModelSlot:
    def test_mirror_noop_when_plane_unavailable(self, monkeypatch):
        # 平面不可用时真实 schedule_pg_write 直接短路，operation 永不执行
        monkeypatch.setattr(
            provider_store, "pg_provider_plane_available", lambda: False
        )
        executed = {"count": 0}

        async def _fail_upsert(agent_id, provider_id, model):
            executed["count"] += 1

        monkeypatch.setattr(
            agent_model_store, "upsert_agent_model_slot_pg", _fail_upsert
        )
        agent_model_store.mirror_agent_model_slot("a1", "p1", "m1")
        assert executed["count"] == 0

    def test_mirror_schedules_when_available(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        provider_store.reset_backend_cache()
        scheduled = {"count": 0}

        def _fake_schedule(operation):
            scheduled["count"] += 1

        monkeypatch.setattr(
            provider_store, "schedule_pg_write", _fake_schedule
        )
        agent_model_store.mirror_agent_model_slot("a1", "p1", "m1")
        assert scheduled["count"] == 1
