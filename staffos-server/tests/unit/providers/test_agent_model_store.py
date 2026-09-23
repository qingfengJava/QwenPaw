# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the agent default model slot plane (三态读写语义)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.db import write_gateway
from qwenpaw.providers import agent_model_store


@pytest.fixture(autouse=True)
def _pin_backend_env(monkeypatch):
    """钉回测试期望的后端环境，防止宿主机配置污染（历史教训）。"""
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    write_gateway.reset_backend_cache()
    yield
    write_gateway.reset_backend_cache()


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
            return {
                "provider_id": "p-pg",
                "model": "m-pg",
                "overrides": {
                    "max_input_length": 1048576,
                    "reasoning_effort": "high",
                },
            }

        monkeypatch.setattr(agent_model_store, "get_agent_model_slot_pg", _fake_get)
        result = asyncio.run(
            agent_model_store.resolve_agent_active_model("a1", _agent_config(file_slot)),
        )
        assert result is not None
        assert result.provider_id == "p-pg"
        assert result.model == "m-pg"
        # 行内覆盖字段随槽位回填（员工级参数覆盖层）
        assert result.max_input_length == 1048576
        assert result.reasoning_effort == "high"
        assert result.thinking_enabled is None

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
        async def _fail_upsert(agent_id, provider_id, model, overrides=None):
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

        def _fake_schedule(operation, *, domain="pg"):
            captured["scheduled"] = True
            captured["domain"] = domain

        monkeypatch.setattr(
            write_gateway, "submit_shadow_write", _fake_schedule
        )
        asyncio.run(agent_model_store.persist_agent_model_slot("a1", "p1", "m1"))
        assert captured.get("scheduled") is True

    def test_pg_backend_awaits_authoritative_write(self, monkeypatch):
        """pg 后端：await 权威写（调用方拿到成功/失败再热重载）。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        captured = {}

        async def _fake_upsert(agent_id, provider_id, model, overrides=None):
            captured["args"] = (agent_id, provider_id, model)
            captured["overrides"] = overrides

        monkeypatch.setattr(
            agent_model_store, "upsert_agent_model_slot_pg", _fake_upsert
        )
        asyncio.run(agent_model_store.persist_agent_model_slot("a1", "p1", "m1"))
        assert captured["args"] == ("a1", "p1", "m1")
        # 不传覆盖时透传 None（语义：仅切模型，不碰既有参数）
        assert captured["overrides"] is None

    def test_pg_backend_forwards_overrides(self, monkeypatch):
        """pg 后端：覆盖字典透传到 PG 写入路径（字段级清除语义）。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        captured = {}

        async def _fake_upsert(agent_id, provider_id, model, overrides=None):
            captured["overrides"] = overrides

        monkeypatch.setattr(
            agent_model_store, "upsert_agent_model_slot_pg", _fake_upsert
        )
        overrides = {
            "max_input_length": 1048576,
            "thinking_enabled": True,
            "thinking_budget": None,
            "reasoning_effort": "high",
        }
        asyncio.run(
            agent_model_store.persist_agent_model_slot(
                "a1", "p1", "m1", overrides=dict(overrides)
            )
        )
        assert captured["overrides"] == overrides

    def test_pg_backend_write_failure_never_raises(self, monkeypatch):
        """pg 后端：权威写失败仅告警，不向调用方抛异常。"""
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")

        async def _boom(agent_id, provider_id, model, overrides=None):
            raise RuntimeError("pg down")

        monkeypatch.setattr(
            agent_model_store, "upsert_agent_model_slot_pg", _boom
        )
        # 不抛即通过（失败已降级为告警日志）
        asyncio.run(agent_model_store.persist_agent_model_slot("a1", "p1", "m1"))


class TestMirrorAgentModelSlot:
    def test_mirror_noop_when_plane_unavailable(self, monkeypatch):
        # 平面不可用时网关影子调度直接短路，operation 永不执行
        monkeypatch.setattr(
            write_gateway, "pg_write_available", lambda: False
        )
        executed = {"count": 0}

        async def _fail_upsert(agent_id, provider_id, model, overrides=None):
            executed["count"] += 1

        monkeypatch.setattr(
            agent_model_store, "upsert_agent_model_slot_pg", _fail_upsert
        )
        agent_model_store.mirror_agent_model_slot("a1", "p1", "m1")
        assert executed["count"] == 0

    def test_mirror_schedules_when_available(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        write_gateway.reset_backend_cache()
        scheduled = {"count": 0}

        def _fake_schedule(operation, *, domain="pg"):
            scheduled["count"] += 1
            scheduled["domain"] = domain

        monkeypatch.setattr(
            write_gateway, "submit_shadow_write", _fake_schedule
        )
        agent_model_store.mirror_agent_model_slot("a1", "p1", "m1")
        assert scheduled["count"] == 1
        # M2 收敛：影子写日志域名归属 agent_model_slots（不再误归 provider）
        assert scheduled["domain"] == "agent_model_slots"


class TestConfigJsonRoundTrip:
    """agent_model_slots.config JSONB 序列化与解析（员工级覆盖层）。"""

    def test_config_to_json_drops_empty_overrides(self):
        # 全部覆盖字段为空 → 存 NULL（与旧行完全兼容）
        assert (
            agent_model_store._config_to_json(
                ModelSlotConfig(provider_id="p", model="m")
            )
            is None
        )
        assert agent_model_store._config_to_json(None) is None

    def test_config_to_json_keeps_only_set_fields(self):
        payload = agent_model_store._config_to_json(
            ModelSlotConfig(
                provider_id="p",
                model="m",
                max_input_length=1048576,
                reasoning_effort="high",
            )
        )
        assert payload is not None
        assert '"max_input_length": 1048576' in payload
        assert '"reasoning_effort": "high"' in payload
        assert "thinking_enabled" not in payload

    def test_json_to_overrides_round_trip(self):
        raw = (
            '{"max_input_length": 1048576, "thinking_enabled": true, '
            '"thinking_budget": 8192, "reasoning_effort": "medium"}'
        )
        overrides = agent_model_store._json_to_overrides(raw)
        assert overrides == {
            "max_input_length": 1048576,
            "thinking_enabled": True,
            "thinking_budget": 8192,
            "reasoning_effort": "medium",
        }

    def test_json_to_overrides_rejects_dirty_data(self):
        # 非法 JSON / 非 dict / 字段越界（ge=1000）一律丢弃不抛
        assert agent_model_store._json_to_overrides("not-json") == {}
        assert agent_model_store._json_to_overrides("[1, 2]") == {}
        assert agent_model_store._json_to_overrides(None) == {}
        assert (
            agent_model_store._json_to_overrides(
                '{"max_input_length": 10}'
            )
            == {}
        )


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeConn:
    """记录 execute 调用序列的假连接（用于断言两步事务 SQL）。"""

    def __init__(self, results=None):
        self._results = list(results or [])
        self.executed = []

    async def execute(self, clause, params=None):
        self.executed.append((str(clause), params))
        row = self._results.pop(0) if self._results else None
        return _FakeResult(row)


class _FakeCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, results=None):
        self.conn = _FakeConn(results)

    def connect(self):
        return _FakeCtx(self.conn)

    def begin(self):
        return _FakeCtx(self.conn)


class TestProfileActivationSemantics:
    """档案化语义：切换模型 = 取消旧激活 + 激活目标档案（单事务两步）。"""

    def test_upsert_deactivates_then_activates_without_config(self):
        # overrides=None：不触碰目标档案既有 config（切回即恢复历史参数）
        engine = _FakeEngine()
        asyncio.run(
            agent_model_store.upsert_agent_model_slot_pg(
                "a1", "p1", "m1", engine=engine
            )
        )
        assert len(engine.conn.executed) == 2
        deactivate_sql, deactivate_params = engine.conn.executed[0]
        assert "SET is_active = FALSE" in deactivate_sql
        assert deactivate_params["agent_id"] == "a1"
        activate_sql, activate_params = engine.conn.executed[1]
        assert "INSERT INTO agent_model_slots" in activate_sql
        assert "is_active" in activate_sql
        # 不带参数：不写 config（新档案 NULL，已有档案保留）
        assert "config" not in activate_params

    def test_upsert_with_overrides_writes_profile_config(self):
        engine = _FakeEngine()
        asyncio.run(
            agent_model_store.upsert_agent_model_slot_pg(
                "a1",
                "p1",
                "m1",
                overrides={"max_input_length": 1048576},
                engine=engine,
            )
        )
        _, activate_params = engine.conn.executed[1]
        assert activate_params["config"] is not None
        assert "max_input_length" in activate_params["config"]

    def test_upsert_on_conflict_targets_profile_key(self):
        # 冲突键含模型维度：同一员工多模型档案共存，激活行唯一
        engine = _FakeEngine()
        asyncio.run(
            agent_model_store.upsert_agent_model_slot_pg(
                "a1", "p1", "m1", engine=engine
            )
        )
        activate_sql, _ = engine.conn.executed[1]
        assert "tenant_id, agent_id, slot_name, provider_id, model" in activate_sql

    def test_clear_only_removes_active_profile(self):
        # 恢复跟随全局：只删激活行，其余模型档案保留（参数记忆不丢）
        engine = _FakeEngine()
        asyncio.run(
            agent_model_store.clear_agent_model_slot_pg("a1", engine=engine)
        )
        delete_sql, _ = engine.conn.executed[0]
        assert "DELETE FROM agent_model_slots" in delete_sql
        assert "AND is_active" in delete_sql

    def test_get_profile_returns_empty_when_absent(self):
        engine = _FakeEngine(results=[None])
        result = asyncio.run(
            agent_model_store.get_agent_model_profile_pg(
                "a1", "p1", "m1", engine=engine
            )
        )
        assert result == {}

    def test_get_profile_parses_config(self):
        engine = _FakeEngine(results=[('{"reasoning_effort": "high"}',)])
        result = asyncio.run(
            agent_model_store.get_agent_model_profile_pg(
                "a1", "p1", "m1", engine=engine
            )
        )
        assert result == {"reasoning_effort": "high"}
