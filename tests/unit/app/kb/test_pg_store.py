# -*- coding: utf-8 -*-
"""Unit tests for the KB PG store plane (M6-2: 三态与幂等语义)。

沿用 ``tests/unit/app/agent_docs/test_store.py`` 的 FakeEngine 约定：只捕获
参数化 SQL 与调用次序，不连真库；真库契约由
``tests/integration/test_kb_pg_plane.py`` 覆盖。
"""

# pylint: disable=protected-access
from __future__ import annotations

from typing import Any, List, Optional, Tuple

import pytest

from qwenpaw.app.kb import pg_store
from qwenpaw.app.kb.models import KbDocument, KbSpace

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fake engine（捕获 SQL + 可编程返回行）
# ---------------------------------------------------------------------------


class _FakeResult:
    """最小 Result 协议：rowcount / fetchone / mappings().first/all()。"""

    def __init__(
        self,
        rowcount: int = 1,
        row: Optional[dict] = None,
        rows: Optional[List[dict]] = None,
        tuple_row: Optional[Tuple] = None,
    ) -> None:
        self.rowcount = rowcount
        self._row = row
        self._rows = (
            rows if rows is not None else ([] if row is None else [row])
        )
        self._tuple_row = tuple_row

    def mappings(self) -> "_FakeResult":
        return self

    def first(self) -> Optional[dict]:
        return self._row

    def all(self) -> List[dict]:
        return list(self._rows)

    def fetchone(self) -> Optional[Tuple]:
        return self._tuple_row


class _FakeConn:
    """记录执行序列，并按语句特征回放可预期的结果。"""

    def __init__(
        self,
        *,
        unchanged: bool = False,
        regclass_row: Optional[Tuple] = None,
        next_version: int = 3,
    ) -> None:
        self.statements: List[Tuple[str, dict]] = []
        self._unchanged = unchanged
        self._regclass_row = regclass_row
        self._next_version = next_version

    async def execute(
        self,
        sql: Any,
        params: Optional[dict] = None,
    ) -> _FakeResult:
        statement = str(sql)
        self.statements.append((statement, dict(params or {})))
        if "to_regclass" in statement:
            return _FakeResult(tuple_row=self._regclass_row)
        if "RETURNING id" in statement:
            # 内容未变时 WHERE 拦截 → RETURNING 空集
            if self._unchanged:
                return _FakeResult(rowcount=0)
            return _FakeResult(rowcount=1, row={"id": params["doc_id"]})
        if "MAX(version)" in statement:
            return _FakeResult(
                rowcount=1,
                row={"next_version": self._next_version},
            )
        if statement.lstrip().upper().startswith("SELECT"):
            return _FakeResult(rowcount=1, rows=[])
        return _FakeResult(0 if self._unchanged else 1)


class _FakeEngine:
    """提供 begin() / connect() 两个异步上下文，共用同一个 FakeConn。"""

    def __init__(self, **kwargs: Any) -> None:
        self.conn = _FakeConn(**kwargs)

    class _Ctx:
        def __init__(self, conn: _FakeConn) -> None:
            self._conn = conn

        async def __aenter__(self) -> _FakeConn:
            return self._conn

        async def __aexit__(self, *args: Any) -> bool:
            return False

    def begin(self) -> "_FakeEngine._Ctx":
        return self._Ctx(self.conn)

    def connect(self) -> "_FakeEngine._Ctx":
        return self._Ctx(self.conn)


@pytest.fixture(autouse=True)
def _pg_backend(monkeypatch: pytest.MonkeyPatch) -> Any:
    """本文件默认在 dual/pg 后端下运行（单测不得依赖进程环境变量）。

    三态判定本身由 :func:`test_backend_json_does_nothing` 等用例显式
    改写为 json 后另行覆盖。
    """
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: True,
    )
    pg_store.reset_store_for_tests()
    yield
    pg_store.reset_store_for_tests()


def _space_row(**overrides: Any) -> KbSpace:
    """构造一条测试用知识空间读模型。"""
    data: dict[str, Any] = {
        "id": "kb_a",
        "name": "孕产知识库",
        "description": "孕产相关问题时检索我",
        "scope": "enterprise",
    }
    data.update(overrides)
    return KbSpace(**data)


def _doc_row(**overrides: Any) -> KbDocument:
    """构造一条测试用知识文档读模型。"""
    data: dict[str, Any] = {
        "id": "d1",
        "space_id": "kb_a",
        "path": "/guideline.md",
        "title": "guideline",
        "content_md": "# hello",
    }
    data.update(overrides)
    return KbDocument(**data)


# ---------------------------------------------------------------------------
# 三态开关：json 后端零动作
# ---------------------------------------------------------------------------


async def test_backend_json_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json 后端：所有写方法零动作零异常，且不触碰 engine。"""
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: False,
    )
    engine = _FakeEngine()
    store = pg_store.KbPgStore(engine=engine)

    assert await store.upsert_space(_space_row()) is False
    assert await store.upsert_document(_doc_row()) is False
    assert await store.delete_space("kb_a") is False
    assert await store.list_spaces() == []
    assert await store.get_space("kb_a") is None
    assert engine.conn.statements == []


async def test_dsn_required_for_plane_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """可用性判定直接委托写网关，不在本层重复实现三态逻辑。"""
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: True,
    )
    assert pg_store.kb_pg_plane_available() is True
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: False,
    )
    assert pg_store.kb_pg_plane_available() is False


# ---------------------------------------------------------------------------
# 文档写入的 hash 护栏与版本快照
# ---------------------------------------------------------------------------


async def test_upsert_document_hash_unchanged_skips() -> None:
    """内容 hash 相同：WHERE 拦截 → 返回 False，不产生版本快照。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(unchanged=True))

    written = await store.upsert_document(_doc_row(content_md="# hello"))

    assert written is False
    statements = store._engine.conn.statements
    assert len(statements) == 1
    assert "INSERT INTO kb_documents" in statements[0][0]
    assert not any("kb_document_versions" in sql for sql, _ in statements)


async def test_upsert_document_uses_hash_guard() -> None:
    """upsert 必须带 IS DISTINCT FROM 护栏并回填 content_hash。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.upsert_document(_doc_row(content_md="# hello")) is True

    sql, params = store._engine.conn.statements[0]
    assert "ON CONFLICT (tenant_id, id) DO UPDATE" in sql
    hash_guard = (
        "kb_documents.content_hash IS DISTINCT FROM " "EXCLUDED.content_hash"
    )
    assert hash_guard in sql
    assert params["chash"] == pg_store.content_hash("# hello")
    assert params["space_id"] == "kb_a"
    assert params["doc_id"] == "d1"


async def test_upsert_document_snapshots_new_version() -> None:
    """内容变化：同事务内落版本快照；超出保留窗口才做最旧快照清理。"""
    store = pg_store.KbPgStore(
        engine=_FakeEngine(next_version=pg_store.VERSION_RETENTION + 5),
    )

    assert await store.upsert_document(_doc_row()) is True

    executed = [sql for sql, _ in store._engine.conn.statements]
    assert any("INSERT INTO kb_documents" in sql for sql in executed)
    assert any("INSERT INTO kb_document_versions" in sql for sql in executed)
    assert any("DELETE FROM kb_document_versions" in sql for sql in executed)


async def test_upsert_document_keeps_recent_versions_only() -> None:
    """未超保留窗口时不得发出任何清理语句，避免误删历史版本。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(next_version=2))

    assert await store.upsert_document(_doc_row()) is True

    executed = [sql for sql, _ in store._engine.conn.statements]
    assert any("INSERT INTO kb_document_versions" in sql for sql in executed)
    assert not any(
        "DELETE FROM kb_document_versions" in sql for sql in executed
    )


async def test_upsert_document_path_must_not_be_empty() -> None:
    """空 path 会撞部分唯一索引，写入入口必须拒绝（T1 遗留 M-3）。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    with pytest.raises(ValueError):
        await store.upsert_document(_doc_row(path=""))


async def test_list_documents_excludes_deleted_by_default() -> None:
    """列表默认只看未删除文档，避免回收站内容混入检索目录。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.list_documents("kb_a") == []

    sql, params = store._engine.conn.statements[0]
    assert "FROM kb_documents" in sql
    assert "is_delete = FALSE" in sql
    assert params["space_id"] == "kb_a"


async def test_delete_document_is_soft_delete() -> None:
    """删除走 is_delete 置位，禁止物理删除以保证可追溯。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.delete_document("d1") is True

    sql = store._engine.conn.statements[0][0]
    assert "UPDATE kb_documents" in sql
    assert "SET is_delete = TRUE" in sql


# ---------------------------------------------------------------------------
# 表就绪探测（缺表回退 json 平面）
# ---------------------------------------------------------------------------


async def test_ensure_ready_true_when_all_tables_present() -> None:
    """六表齐备 → 就绪，工厂据此走 PG 权威读。"""
    all_present = (
        "kb_spaces",
        "kb_documents",
        "kb_document_versions",
        "kb_chunks",
        "kb_links",
        "agent_kb_bindings",
    )
    store = pg_store.KbPgStore(
        engine=_FakeEngine(regclass_row=all_present),
    )

    assert await store.ensure_ready() is True


async def test_ensure_ready_false_when_table_missing() -> None:
    """迁移未执行（探测返回 NULL）→ 未就绪，调用方回退文件平面。"""
    store = pg_store.KbPgStore(
        engine=_FakeEngine(
            regclass_row=("kb_spaces", None, None, None, None, None),
        ),
    )

    assert await store.ensure_ready() is False


async def test_ensure_ready_short_circuits_without_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json 后端不做探测，直接判定未就绪。"""
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: False,
    )
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.ensure_ready() is False
    assert store._engine.conn.statements == []


# ---------------------------------------------------------------------------
# 影子写调度（同步调用方不阻塞）
# ---------------------------------------------------------------------------


async def test_schedule_upsert_document_submits_shadow_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """schedule_* 经写网关提交影子写，domain 带 kb_ 前缀便于 grep。"""
    submitted: List[Any] = []
    monkeypatch.setattr(
        pg_store.write_gateway,
        "submit_shadow_write",
        lambda operation, *, domain="pg": submitted.append(
            (operation, domain)
        ),
    )
    store = pg_store.KbPgStore(engine=_FakeEngine())

    store.schedule_upsert_document(_doc_row())

    assert len(submitted) == 1
    assert submitted[0][1] == "kb_document"


async def test_schedule_upsert_space_submits_shadow_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空间写入同样走影子写，保持与文档平面一致的降级语义。"""
    submitted: List[Any] = []
    monkeypatch.setattr(
        pg_store.write_gateway,
        "submit_shadow_write",
        lambda operation, *, domain="pg": submitted.append(
            (operation, domain)
        ),
    )
    store = pg_store.KbPgStore(engine=_FakeEngine())

    store.schedule_upsert_space(_space_row())

    assert len(submitted) == 1
    assert submitted[0][1] == "kb_space"


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


async def test_get_kb_pg_store_returns_shared_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工厂在 dual/pg 后端返回单例，json 后端返回 None。"""
    pg_store.reset_store_for_tests()
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: False,
    )
    assert pg_store.get_kb_pg_store() is None

    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: True,
    )
    first = pg_store.get_kb_pg_store(engine=_FakeEngine())
    second = pg_store.get_kb_pg_store(engine=_FakeEngine())
    assert first is second
    pg_store.reset_store_for_tests()
