# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the unified PG write gateway (M2 收敛点)."""

from __future__ import annotations

import asyncio
import threading

import pytest

from qwenpaw.db import write_gateway


@pytest.fixture(autouse=True)
def _pin_backend_env(monkeypatch):
    """钉回干净的后端环境，防止宿主机配置污染（历史教训）。"""
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    write_gateway.reset_backend_cache()
    yield
    write_gateway.reset_backend_cache()


# ---------------------------------------------------------------------------
# 三态判定
# ---------------------------------------------------------------------------


class TestResolveStorageBackend:
    def test_explicit_env_backend_wins(self, monkeypatch):
        """显式 QWENPAW_STORAGE_BACKEND 恒优先于动态默认。"""
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        assert write_gateway.resolve_storage_backend() == "pg"

    def test_invalid_env_falls_back_to_json_without_dsn(self, monkeypatch):
        """无效值 + 无 DSN → 动态默认 json（个人部署不变）。"""
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "sqlite")
        assert write_gateway.resolve_storage_backend() == "json"

    def test_invalid_env_falls_back_to_dual_with_dsn(self, monkeypatch):
        """无效值 + 已配置 DSN → 动态默认 dual（影子平面自动启用）。"""
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "sqlite")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        assert write_gateway.resolve_storage_backend() == "dual"

    def test_backend_cache_survives_env_change_until_reset(
        self, monkeypatch
    ):
        """缓存生效：首次解析后改 env 不影响结果，reset 后重新解析。"""
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
        assert write_gateway.resolve_storage_backend() == "json"
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        assert write_gateway.resolve_storage_backend() == "json"
        write_gateway.reset_backend_cache()
        assert write_gateway.resolve_storage_backend() == "pg"


class TestPgWriteAvailable:
    def test_json_backend_never_available(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        assert write_gateway.pg_write_available() is False

    def test_dual_without_dsn_not_available(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
        write_gateway.reset_backend_cache()
        assert write_gateway.pg_write_available() is False

    def test_dual_with_dsn_available(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        write_gateway.reset_backend_cache()
        assert write_gateway.pg_write_available() is True

    def test_pg_with_dsn_available(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "pg")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        write_gateway.reset_backend_cache()
        assert write_gateway.pg_write_available() is True


# ---------------------------------------------------------------------------
# 影子写调度（fire-and-forget）
# ---------------------------------------------------------------------------


class TestSubmitShadowWrite:
    def test_noop_when_plane_unavailable(self, monkeypatch):
        """json 后端直接短路，operation 永不执行。"""
        executed = {"count": 0}

        async def _operation():
            executed["count"] += 1

        write_gateway.submit_shadow_write(_operation, domain="t")
        assert executed["count"] == 0

    def test_runs_on_shadow_loop_without_event_loop(self, monkeypatch):
        """无事件循环（CLI/启动路径）：提交到影子写守护 loop 执行。"""
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        write_gateway.reset_backend_cache()
        done = threading.Event()
        ran_in = {"loop": None}

        async def _operation():
            ran_in["loop"] = asyncio.get_running_loop()
            done.set()

        # 当前线程无事件循环（历史实现起一次性线程 loop；现行收敛到单例守护 loop）
        write_gateway.submit_shadow_write(_operation, domain="t")
        assert done.wait(timeout=5.0)
        assert ran_in["loop"] is write_gateway._get_shadow_loop()

    def test_swallows_operation_exceptions(self, monkeypatch, caplog):
        """operation 抛异常仅告警（统一域名日志），绝不向调用方传播。"""
        import time

        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        write_gateway.reset_backend_cache()

        async def _boom():
            raise RuntimeError("pg down")

        # 无事件循环路径：网关开守护线程执行，异常必须被网关吞掉
        write_gateway.submit_shadow_write(_boom, domain="t_probe")
        # 轮询等待守护线程内的告警日志出现（最长 5s）
        expected = "t_probe PG shadow write failed"
        for _ in range(100):
            if any(expected in rec.getMessage() for rec in caplog.records):
                break
            time.sleep(0.05)
        assert any(
            expected in rec.getMessage() for rec in caplog.records
        )

    def test_running_loop_submission_goes_to_shadow_loop(self, monkeypatch):
        """事件循环内提交也收敛到影子写守护 loop（防跨 loop 池腐蚀）。"""
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        write_gateway.reset_backend_cache()
        executed = {"loop": None}

        async def _operation():
            executed["loop"] = asyncio.get_running_loop()

        async def _driver():
            write_gateway.submit_shadow_write(_operation, domain="t")
            # 跨线程调度不保证单次让出即执行，轮询等待完成（最长 5s）
            for _ in range(500):
                if executed["loop"] is not None:
                    break
                await asyncio.sleep(0.01)
            assert executed["loop"] is not None
            # 执行 loop 必须是影子写守护 loop，而非当前业务 loop
            assert executed["loop"] is write_gateway._get_shadow_loop()
            assert executed["loop"] is not asyncio.get_running_loop()

        asyncio.run(_driver())

    def test_shadow_loop_is_singleton_across_calls(self, monkeypatch):
        """多次提交复用同一守护 loop（不每笔一线程一 loop）。"""
        monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x")
        write_gateway.reset_backend_cache()
        loops = []
        done = threading.Event()

        def _make_op():
            async def _op():
                loops.append(asyncio.get_running_loop())
                if len(loops) == 2:
                    done.set()

            return _op

        write_gateway.submit_shadow_write(_make_op(), domain="t")
        write_gateway.submit_shadow_write(_make_op(), domain="t")
        assert done.wait(timeout=5.0)
        assert loops[0] is loops[1]
        assert loops[0] is write_gateway._get_shadow_loop()


# ---------------------------------------------------------------------------
# 权威写
# ---------------------------------------------------------------------------


class TestAuthoritativeWrite:
    @pytest.mark.asyncio
    async def test_success_returns_true(self):
        ran = {"count": 0}

        async def _operation():
            ran["count"] += 1

        ok = await write_gateway.authoritative_write(
            _operation, domain="t"
        )
        assert ok is True
        assert ran["count"] == 1

    @pytest.mark.asyncio
    async def test_failure_returns_false_never_raises(self):
        """权威写失败仅告警（禁止降级写文件），返回 False 不抛。"""

        async def _boom():
            raise RuntimeError("pg down")

        ok = await write_gateway.authoritative_write(_boom, domain="t")
        assert ok is False
