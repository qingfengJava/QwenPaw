# -*- coding: utf-8 -*-
"""Unit tests for the agent_documents shadow store (Phase A/B)."""
# pylint: disable=protected-access
import asyncio
import threading
import time

import pytest

from qwenpaw.app.agent_docs import store as agent_docs_store
from qwenpaw.app.agent_docs.store import (
    AgentDocsStore,
    DOC_TYPE_BY_FILENAME,
    content_hash,
    environment_for_agent,
    promote_documents,
)


class _FakeMappingResult:
    """RETURNING/SELECT 行结果（mappings() 协议）。"""

    def __init__(self, row: dict | None, rows: list | None = None) -> None:
        self._row = row
        self._rows = rows if rows is not None else ([] if row is None else [row])

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeConn:
    """Records executed statements; simulates the idempotent WHERE gate."""

    def __init__(
        self,
        unchanged: bool = False,
        version: int = 1,
    ) -> None:
        self.statements: list[tuple[str, dict]] = []
        self._unchanged = unchanged
        self._version = version

    async def execute(self, sql, params):
        self.statements.append((str(sql), dict(params)))
        if "RETURNING version" in str(sql):
            # WHERE 拦截时返回空集（内容未变的幂等重放）
            if self._unchanged:
                return _FakeMappingResult(None)
            return _FakeMappingResult({"version": self._version})
        if "SELECT" in str(sql) and "agent_document_revisions" in str(sql):
            return _FakeMappingResult(None, rows=[])
        # WHERE content_hash IS DISTINCT FROM EXCLUDED.content_hash 拦截时
        # rowcount 为 0（内容未变的幂等重放）
        return _FakeResult(0 if self._unchanged else 1)


class _FakeEngine:
    def __init__(self, unchanged: bool = False, version: int = 1) -> None:
        self.conn = _FakeConn(unchanged, version)

    class _BeginCtx:
        def __init__(self, conn) -> None:
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *args):
            return False

    class _ConnectCtx:
        def __init__(self, conn) -> None:
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *args):
            return False

    def begin(self):
        return self._BeginCtx(self.conn)

    def connect(self):
        return self._ConnectCtx(self.conn)


def test_environment_for_agent_draft_suffix() -> None:
    """带 __draft 后缀的草稿实例映射 draft，其余映射 production。"""
    assert environment_for_agent("expert_a1__draft") == "draft"
    assert environment_for_agent("expert_a1") == "production"
    assert environment_for_agent("default") == "production"


def test_doc_type_whitelist_covers_identity_files() -> None:
    """档案文件白名单固定四类；未知文件名不进表。"""
    assert DOC_TYPE_BY_FILENAME == {
        "PROFILE.md": "profile",
        "AGENTS.md": "agents",
        "SOUL.md": "soul",
        "agent.json": "agent_json",
    }


def test_content_hash_stable() -> None:
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")


@pytest.mark.asyncio
async def test_upsert_document_writes_parameterized_insert() -> None:
    engine = _FakeEngine()
    store = AgentDocsStore(engine=engine)
    written = await store.upsert_document(
        "analyst",
        "profile",
        "# PROFILE",
        updated_by="qingfeng",
    )
    assert written is True
    sql, params = engine.conn.statements[0]
    assert "INSERT INTO agent_documents" in sql
    assert "ON CONFLICT (tenant_id, agent_id, doc_type, environment)" in sql
    assert params["aid"] == "analyst"
    assert params["dtype"] == "profile"
    assert params["env"] == "production"
    assert params["chash"] == content_hash("# PROFILE")
    assert params["uby"] == "qingfeng"


@pytest.mark.asyncio
async def test_upsert_document_idempotent_replay_writes_nothing() -> None:
    """内容未变（hash 相同）时 WHERE 拦截 → 返回 False，版本不抖动。"""
    engine = _FakeEngine(unchanged=True)
    store = AgentDocsStore(engine=engine)
    written = await store.upsert_document("analyst", "profile", "# PROFILE")
    assert written is False


@pytest.mark.asyncio
async def test_upsert_documents_batch_single_transaction() -> None:
    engine = _FakeEngine()
    store = AgentDocsStore(engine=engine)
    written = await store.upsert_documents(
        "analyst",
        {"profile": "# P", "soul": "# S"},
    )
    assert written == 2
    assert len(engine.conn.statements) == 2


# -- Phase B: promote / revisions ------------------------------------------


@pytest.mark.asyncio
async def test_promote_writes_row_revision_and_retention() -> None:
    """promote 单事务三步：production upsert（RETURNING version）+
    不可变快照插入 + 保留窗口清理。"""
    engine = _FakeEngine(version=3)
    store = AgentDocsStore(engine=engine)
    version = await store.promote(
        "analyst",
        "profile",
        "# v3",
        updated_by="qingfeng",
    )
    assert version == 3
    assert len(engine.conn.statements) == 3
    upsert_sql, upsert_params = engine.conn.statements[0]
    assert "INSERT INTO agent_documents" in upsert_sql
    assert "RETURNING version" in upsert_sql
    assert upsert_params["env"] == "production"
    revision_sql, revision_params = engine.conn.statements[1]
    assert "INSERT INTO agent_document_revisions" in revision_sql
    assert revision_params["ver"] == 3
    assert revision_params["chash"] == content_hash("# v3")
    cleanup_sql, cleanup_params = engine.conn.statements[2]
    assert "DELETE FROM agent_document_revisions" in cleanup_sql
    assert cleanup_params["keep"] == agent_docs_store.REVISION_RETENTION


@pytest.mark.asyncio
async def test_promote_unchanged_writes_nothing() -> None:
    """内容未变：RETURNING 空集 → 返回 None，不写快照。"""
    engine = _FakeEngine(unchanged=True)
    store = AgentDocsStore(engine=engine)
    version = await store.promote("analyst", "profile", "# same")
    assert version is None
    # 仅 upsert 一条语句（无快照/清理）
    assert len(engine.conn.statements) == 1


@pytest.mark.asyncio
async def test_list_and_get_revision_queries() -> None:
    engine = _FakeEngine()
    store = AgentDocsStore(engine=engine)
    await store.list_revisions("analyst", "profile")
    sql, params = engine.conn.statements[0]
    assert "FROM agent_document_revisions" in sql
    assert params["dtype"] == "profile"
    assert params["env"] == "production"


@pytest.mark.asyncio
async def test_promote_documents_skips_invalid_doc_type(monkeypatch) -> None:
    """promote_documents 拒绝非白名单类型；PG 不可用返回 False。"""
    engine = _FakeEngine(version=1)
    store = AgentDocsStore(engine=engine)
    monkeypatch.setattr(
        agent_docs_store,
        "get_agent_docs_store",
        lambda: store,
    )
    ok = await promote_documents(
        "analyst",
        {"profile": "# P", "bogus": "x"},
    )
    assert ok is True
    # 只有 profile 落库（bogus 被拒）
    assert len(engine.conn.statements) == 3


@pytest.mark.asyncio
async def test_promote_documents_returns_false_without_pg(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_docs_store,
        "get_agent_docs_store",
        lambda: None,
    )
    ok = await promote_documents("analyst", {"profile": "# P"})
    assert ok is False


def test_shadow_write_document_ignores_unknown_filename() -> None:
    """非档案文件绝不触发影子写（无 PG / 无事件循环也必须静默）。"""
    # 无事件循环的同步上下文：未知文件名直接 return；已知文件名也无循环
    # 可创建任务 → 静默跳过且不抛异常
    agent_docs_store.shadow_write_document("analyst", "notes.md", "x")
    agent_docs_store.shadow_write_document("analyst", "PROFILE.md", "x")


def test_shadow_write_document_schedules_task_in_loop(monkeypatch) -> None:
    """有事件循环且有 store 时为已知档案文件调度影子写任务。"""
    calls: list[tuple[str, str, str]] = []

    class _FakeStore:
        async def upsert_document(self, agent_id, doc_type, content, **kw):
            calls.append((agent_id, doc_type, content))

    async def _run():
        agent_docs_store.shadow_write_document("analyst", "SOUL.md", "x")
        if agent_docs_store._shadow_tasks:
            await asyncio.gather(*list(agent_docs_store._shadow_tasks))

    monkeypatch.setattr(
        agent_docs_store,
        "get_agent_docs_store",
        lambda: _FakeStore(),
    )
    asyncio.run(_run())
    assert calls == [("analyst", "soul", "x")]


def test_shadow_write_document_noop_without_store(monkeypatch) -> None:
    """未配置 PG DSN（store 为 None）时不调度任何任务。"""
    monkeypatch.setattr(
        agent_docs_store,
        "get_agent_docs_store",
        lambda: None,
    )

    async def _run():
        agent_docs_store.shadow_write_document("analyst", "SOUL.md", "x")
        return len(agent_docs_store._shadow_tasks)

    assert asyncio.run(_run()) == 0


def test_shadow_write_document_sync_context_background_loop(
    monkeypatch,
) -> None:
    """CLI 等无事件循环的同步上下文：影子写经共享后台循环兜底落库。"""
    calls: list[tuple[str, str, str]] = []

    class _FakeStore:
        async def upsert_document(self, agent_id, doc_type, content, **kw):
            calls.append((agent_id, doc_type, content))

    monkeypatch.setattr(
        agent_docs_store,
        "get_agent_docs_store",
        lambda: _FakeStore(),
    )
    # 同步上下文直接调用（无 running loop）
    agent_docs_store.shadow_write_document("analyst", "PROFILE.md", "sync")
    # 等待后台循环完成（future 集合清空或超时）
    deadline = time.time() + 5
    while agent_docs_store._shadow_futures and time.time() < deadline:
        time.sleep(0.02)
    assert calls == [("analyst", "profile", "sync")]
