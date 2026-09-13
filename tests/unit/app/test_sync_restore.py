# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the multi-device sync/restore orchestrator (M3 收口)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app import sync_restore
from qwenpaw.db import write_gateway


@pytest.fixture(autouse=True)
def _pin_backend_env(monkeypatch):
    """钉回干净的后端环境，防止宿主机部署态污染（历史教训）。"""
    monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    write_gateway.reset_backend_cache()
    yield
    write_gateway.reset_backend_cache()


# ---------------------------------------------------------------------------
# FakeEngine：仅支撑 count(*) 查询路由
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, scalar_value: int) -> None:
        self._scalar_value = scalar_value

    def scalar(self):
        return self._scalar_value


class _FakeConn:
    def __init__(self, scalar_value: int) -> None:
        self._scalar_value = scalar_value
        self.executed: list[str] = []

    async def execute(self, stmt, params=None):
        self.executed.append(str(stmt))
        return _FakeResult(self._scalar_value)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeEngine:
    def __init__(self, scalar_value: int = 7) -> None:
        self._scalar_value = scalar_value
        self.conns: list[_FakeConn] = []

    def connect(self):
        conn = _FakeConn(self._scalar_value)
        self.conns.append(conn)
        return conn


def _patch_pg_engine(monkeypatch, engine: _FakeEngine) -> None:
    monkeypatch.setattr(
        "qwenpaw.db.engine.create_pg_engine",
        lambda: engine,
    )


def _patch_backend(monkeypatch, backend: str, *, dsn: bool = True) -> None:
    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", backend)
    if dsn:
        monkeypatch.setenv("QWENPAW_PG_DSN", "postgresql+asyncpg://x/y")
    else:
        monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    write_gateway.reset_backend_cache()


# ---------------------------------------------------------------------------
# restore_domains：编排语义
# ---------------------------------------------------------------------------


class TestRestoreDomains:
    async def test_all_domains_ok(self, monkeypatch):
        """全域取回：7 域全部成功 → ok=True 且各域结果齐全。"""
        _patch_backend(monkeypatch, "pg")
        monkeypatch.setattr(
            "qwenpaw.app.agent_docs.reconcile.reconcile_agent_docs",
            _fake_domain_coro({"agents": 3, "overwrite": 1, "restore": 0,
                               "promote": 2, "skip": 5}),
        )
        monkeypatch.setattr(
            "qwenpaw.db.backfill_skill_catalog.run_skill_plane_bootstrap",
            _fake_domain_coro({"backfill": {"count": 0}}),
        )
        manager = SimpleNamespace(
            load_providers_from_pg=_fake_domain_coro(12),
        )
        engine = _FakeEngine(scalar_value=4)
        _patch_pg_engine(monkeypatch, engine)

        result = await sync_restore.restore_domains(provider_manager=manager)

        assert result["ok"] is True
        assert set(result["results"]) == set(sync_restore.RESTORE_DOMAINS)
        assert result["results"]["agent_docs"]["ok"] is True
        assert result["results"]["agent_docs"]["agents"] == 3
        assert result["results"]["skills"]["ok"] is True
        assert result["results"]["providers"] == {"ok": True, "restored": 12}
        # 直读域：计数 4（FakeEngine 固定 scalar）
        assert result["results"]["crons"] == {"ok": True, "jobs": 4}
        assert result["results"]["inbox"] == {"ok": True, "events": 4}
        assert result["results"]["memories"] == {"ok": True, "memories": 4}
        assert result["results"]["chats"] == {"ok": True, "chats": 4}

    async def test_single_domain_failure_isolated(self, monkeypatch):
        """单域异常：该域 ok=False，其余域不受影响；整体 ok=False。"""
        _patch_backend(monkeypatch, "pg")

        async def _boom():
            raise RuntimeError("pg down")

        monkeypatch.setattr(
            "qwenpaw.app.agent_docs.reconcile.reconcile_agent_docs",
            _boom,
        )
        monkeypatch.setattr(
            "qwenpaw.db.backfill_skill_catalog.run_skill_plane_bootstrap",
            _fake_domain_coro({"reconcile": {}}),
        )
        engine = _FakeEngine(scalar_value=1)
        _patch_pg_engine(monkeypatch, engine)

        result = await sync_restore.restore_domains(
            domains=["agent_docs", "skills", "inbox"],
        )

        assert result["ok"] is False
        assert result["results"]["agent_docs"]["ok"] is False
        assert "RuntimeError" in result["results"]["agent_docs"]["error"]
        assert result["results"]["skills"]["ok"] is True
        assert result["results"]["inbox"] == {"ok": True, "events": 1}

    async def test_subset_selection(self, monkeypatch):
        """指定子集：只跑选中的域。"""
        _patch_backend(monkeypatch, "dual")

        async def _unused():
            raise AssertionError("unselected domain must not run")

        monkeypatch.setattr(
            "qwenpaw.app.agent_docs.reconcile.reconcile_agent_docs",
            _unused,
        )
        engine = _FakeEngine(scalar_value=9)
        _patch_pg_engine(monkeypatch, engine)

        result = await sync_restore.restore_domains(domains=["inbox"])

        assert result["ok"] is True
        assert set(result["results"]) == {"inbox"}
        assert result["results"]["inbox"] == {"ok": True, "events": 9}

    async def test_unknown_domain_reports_error(self, monkeypatch):
        """未知域名（绕过路由白名单时）：编排层诚实标注失败。"""
        result = await sync_restore.restore_domains(domains=["nope"])
        assert result["ok"] is False
        assert result["results"]["nope"]["ok"] is False


def _fake_domain_coro(return_value):
    async def _coro(*args, **kwargs):
        return return_value

    return _coro


# ---------------------------------------------------------------------------
# providers 域语义
# ---------------------------------------------------------------------------


class TestProvidersDomain:
    async def test_pg_backend_restores(self, monkeypatch):
        """pg 后端：调 manager.load_providers_from_pg 权威读。"""
        _patch_backend(monkeypatch, "pg")
        calls: list[int] = []

        async def _load():
            calls.append(1)
            return 5

        manager = SimpleNamespace(load_providers_from_pg=_load)
        result = await sync_restore._restore_providers(manager)
        assert result == {"ok": True, "restored": 5}
        assert calls == [1]

    async def test_dual_backend_skipped(self, monkeypatch):
        """dual 后端：文件仍是读权威，取回显式 skipped（防误覆盖）。"""
        _patch_backend(monkeypatch, "dual")

        async def _must_not_call():
            raise AssertionError("dual must not reload from PG")

        manager = SimpleNamespace(load_providers_from_pg=_must_not_call)
        result = await sync_restore._restore_providers(manager)
        assert result["ok"] is True
        assert "skipped" in result

    async def test_pg_without_manager_fails(self, monkeypatch):
        """pg 后端缺 manager：诚实失败（不静默假装成功）。"""
        _patch_backend(monkeypatch, "pg")
        result = await sync_restore._restore_providers(None)
        assert result["ok"] is False
        assert "provider manager" in result["error"]


# ---------------------------------------------------------------------------
# sync_status：可观测性快照
# ---------------------------------------------------------------------------


class TestSyncStatus:
    async def test_status_with_pg(self, monkeypatch):
        """PG 可用：backend/pg_available/各表计数/内存 provider 数。"""
        _patch_backend(monkeypatch, "pg")
        engine = _FakeEngine(scalar_value=42)
        _patch_pg_engine(monkeypatch, engine)
        manager = SimpleNamespace(
            builtin_providers={"a": 1, "b": 2},
            custom_providers={"c": 3},
        )

        status = await sync_restore.sync_status(provider_manager=manager)

        assert status["backend"] == "pg"
        assert status["pg_available"] is True
        assert set(status["pg_counts"]) == set(sync_restore._STATUS_TABLES)
        assert all(v == 42 for v in status["pg_counts"].values())
        assert status["providers"]["in_memory"] == 3

    async def test_status_without_pg(self, monkeypatch):
        """无 PG：pg_available=False，counts/providers 为空。"""
        monkeypatch.delenv("QWENPAW_STORAGE_BACKEND", raising=False)
        monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
        write_gateway.reset_backend_cache()

        status = await sync_restore.sync_status()

        assert status["pg_available"] is False
        assert status["pg_counts"] == {}
        assert status["providers"] == {}

    async def test_count_failure_isolated(self, monkeypatch):
        """单表计数异常：该表 None，其余表照常（快照不整体失败）。"""
        _patch_backend(monkeypatch, "pg")
        # 包装 _count_rows 对指定表抛异常，其余表走真实计数路径
        original = sync_restore._count_rows

        async def _flaky(table: str) -> int:
            if table == "inbox_events":
                raise RuntimeError("boom")
            return await original(table)

        monkeypatch.setattr(sync_restore, "_count_rows", _flaky)
        engine = _FakeEngine(scalar_value=1)
        _patch_pg_engine(monkeypatch, engine)

        status = await sync_restore.sync_status()

        assert status["backend"] == "pg"
        assert status["pg_counts"]["inbox_events"] is None
        assert status["pg_counts"]["cron_jobs"] == 1


class TestCountRowsWhitelist:
    def test_rejects_non_whitelisted_table(self):
        """表名白名单外：ValueError（防标识符注入）。"""

        async def _call():
            await sync_restore._count_rows("users; DROP TABLE x")

        import asyncio

        try:
            asyncio.run(_call())
        except ValueError as exc:
            assert "whitelist" in str(exc)
        else:
            raise AssertionError("expected ValueError")
