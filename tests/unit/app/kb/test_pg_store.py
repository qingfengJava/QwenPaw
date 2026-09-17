# -*- coding: utf-8 -*-
"""Unit tests for the KB PG store plane (M6-2: 三态、幂等与读回链路)。

沿用 ``tests/unit/app/agent_docs/test_store.py`` 的 FakeEngine 约定：只捕获
参数化 SQL 与调用次序，不连真库。Fake 会按语句特征**回放真实行**，因此
「列名写错 → 读模型字段全空」这类缺陷会在此处失败，而不是静默通过。
真库读写闭环由 ``tests/integration/test_kb_pg_plane.py`` 门控覆盖。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

import pytest
from pydantic import ValidationError

from qwenpaw.app.kb import pg_store
from qwenpaw.app.kb.models import KbDocument, KbSpace

pytestmark = pytest.mark.unit

#: 探测通过时的六表返回值（与 pg_store._KB_TABLES 同序）
_ALL_TABLES = pg_store._KB_TABLES


# ---------------------------------------------------------------------------
# Fake engine（捕获 SQL + 按语句特征回放行）
# ---------------------------------------------------------------------------


class _FakeResult:
    """最小 Result 协议：rowcount / fetchone / first / mappings().first/all()。"""

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

    def first(self) -> Optional[Any]:
        return self._tuple_row if self._tuple_row is not None else self._row

    def all(self) -> List[Any]:
        return list(self._rows)

    def fetchone(self) -> Optional[Tuple]:
        return self._tuple_row


class _FakeConn:
    """记录执行序列，并按语句特征返回可预期的行（含读回链路）。"""

    def __init__(
        self,
        *,
        unchanged: bool = False,
        regclass_row: Optional[Tuple] = _ALL_TABLES,
        next_version: int = 3,
        space_row: Optional[dict] = None,
        doc_row: Optional[dict] = None,
        doc_rows: Optional[List[dict]] = None,
        occupied: bool = False,
        lock_present: bool = True,
        probe_error: bool = False,
    ) -> None:
        self.statements: List[Tuple[str, dict]] = []
        self._unchanged = unchanged
        self._regclass_row = regclass_row
        self._next_version = next_version
        self._space_row = space_row
        self._doc_row = doc_row
        self._doc_rows = doc_rows
        self._occupied = occupied
        self._lock_present = lock_present
        self._probe_error = probe_error

    async def execute(
        self,
        sql: Any,
        params: Optional[dict] = None,
    ) -> _FakeResult:
        statement = str(sql)
        bound = dict(params or {})
        self.statements.append((statement, bound))
        if "to_regclass" in statement:
            if self._probe_error:
                raise RuntimeError("probe boom")
            return _FakeResult(tuple_row=self._regclass_row)
        if "FOR UPDATE" in statement:
            # 文档行锁：命中返回一行，未命中返回空集（文档不存在）
            return _FakeResult(
                tuple_row=(1,) if self._lock_present else None,
            )
        if "SELECT 1 FROM kb_documents" in statement:
            return _FakeResult(
                tuple_row=(1,) if self._occupied else None,
            )
        if "RETURNING id" in statement:
            if self._unchanged:
                return _FakeResult(rowcount=0)
            return _FakeResult(rowcount=1, row={"id": bound["doc_id"]})
        if "MAX(version)" in statement:
            return _FakeResult(
                rowcount=1,
                row={"next_version": self._next_version},
            )
        if "FROM kb_spaces" in statement:
            if "id = :space_id" in statement:
                return _FakeResult(rowcount=1, row=self._space_row)
            return _FakeResult(
                rowcount=1,
                rows=[] if self._space_row is None else [self._space_row],
            )
        if "FROM kb_documents" in statement:
            if "path = :path" in statement:
                return _FakeResult(rowcount=1, row=self._doc_row)
            if "id = :doc_id" in statement:
                return _FakeResult(rowcount=1, row=self._doc_row)
            return _FakeResult(
                rowcount=1,
                rows=self._doc_rows or [],
            )
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

    三态判定本身由 :func:`test_backend_json_does_nothing` 等用例显式改写为
    json 后另行覆盖。
    """
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: True,
    )
    pg_store.reset_store_for_tests()
    yield
    pg_store.reset_store_for_tests()


def _space(**overrides: Any) -> KbSpace:
    """构造一条测试用知识空间读模型。"""
    data: dict[str, Any] = {
        "id": "kb_a",
        "name": "孕产知识库",
        "description": "孕产相关问题时检索我",
        "scope": "enterprise",
    }
    data.update(overrides)
    return KbSpace(**data)


def _doc(**overrides: Any) -> KbDocument:
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


def _space_db_row(**overrides: Any) -> dict:
    """``kb_spaces`` 的一行原样返回值（JSONB 以 str 到达，贴近 asyncpg）。"""
    row = {
        "id": "kb_a",
        "name": "孕产知识库",
        "description": "孕产相关问题时检索我",
        "scope": "enterprise",
        "owner_id": "u1",
        "team_id": "",
        "grants": '{"roles": ["kb_admin"]}',
        "embedding_model": "text-embedding-v4",
        "engine": "pgvector",
        "created_at": datetime(2026, 9, 17, 1, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 17, 2, 0, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _doc_db_row(**overrides: Any) -> dict:
    """``kb_documents`` 的一行原样返回值（不含 grants 类的空间字段）。"""
    row = {
        "id": "d1",
        "space_id": "kb_a",
        "path": "/guideline.md",
        "title": "guideline",
        "content_md": "# hello",
        "content_hash": pg_store.content_hash("# hello"),
        "source": "upload",
        "source_meta": '{"file_name": "a.md"}',
        "ingest_status": "processing",
        "error": "",
        "is_delete": False,
        "updated_by": "u1",
        "created_at": datetime(2026, 9, 17, 1, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 17, 2, 0, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 三态开关：json 后端零动作
# ---------------------------------------------------------------------------


async def test_backend_json_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json 后端：所有读写方法零动作零异常，且不触碰 engine。"""
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: False,
    )
    engine = _FakeEngine()
    store = pg_store.KbPgStore(engine=engine)

    assert await store.upsert_space(_space()) is False
    assert await store.upsert_document(_doc()) is False
    assert await store.delete_space("kb_a") is False
    assert await store.delete_document("d1") is False
    assert await store.update_document_meta("d1", title="改名") is False
    assert await store.update_ingest_status("d1", "processing") is False
    assert await store.add_document_version("d1", "x") == 0
    assert await store.list_spaces() == []
    assert await store.list_documents("kb_a") == []
    assert await store.get_space("kb_a") is None
    assert await store.get_document("d1") is None
    assert await store.get_document_by_path("kb_a", "/a.md") is None
    assert await store.ensure_ready() is False
    assert engine.conn.statements == []


async def test_path_invariant_holds_on_json_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """path 非空是数据不变式而非 PG 特性：json 后端同样早失败。"""
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: False,
    )
    store = pg_store.KbPgStore(engine=_FakeEngine())

    with pytest.raises(ValueError):
        await store.upsert_document(_doc(path="  "))


async def test_dsn_judgement_is_delegated(
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
# 文档写入：hash 护栏、版本链、状态回退
# ---------------------------------------------------------------------------


async def test_upsert_document_hash_unchanged_skips() -> None:
    """内容 hash 相同：WHERE 拦截 → 返回 False，不锁行也不追加快照。"""
    store = pg_store.KbPgStore(
        engine=_FakeEngine(unchanged=True),
    )

    written = await store.upsert_document(_doc(content_md="# hello"))

    assert written is False
    executed = store._engine.conn.statements
    # 只允许出现「就绪探测 + 主写」两条语句
    assert len(executed) == 2
    assert any("INSERT INTO kb_documents" in sql for sql, _ in executed)
    # 探测语句里包含了表名，因此只能按语句类型断言，不能按表名子串
    assert not any(
        "INSERT INTO kb_document_versions" in sql for sql, _ in executed
    )
    assert not any("FOR UPDATE" in sql for sql, _ in executed)


async def test_upsert_document_uses_hash_guard() -> None:
    """upsert 必须带 IS DISTINCT FROM 护栏，并回填重算后的 content_hash。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.upsert_document(_doc(content_md="# hello")) is True

    sql, params = store._engine.conn.statements[1]
    assert "INSERT INTO kb_documents" in sql
    assert "ON CONFLICT (tenant_id, id) DO UPDATE" in sql
    hash_guard = (
        "kb_documents.content_hash IS DISTINCT FROM EXCLUDED.content_hash"
    )
    assert hash_guard in sql
    assert params["chash"] == pg_store.content_hash("# hello")
    assert params["space_id"] == "kb_a"
    assert params["doc_id"] == "d1"


async def test_upsert_document_recomputes_hash_ignoring_caller() -> None:
    """入参 hash 与正文不符时以正文为准，杜绝「旧 hash + 新正文」脏写。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert (
        await store.upsert_document(
            _doc(content_md="# new body", content_hash="stale-digest"),
        )
        is True
    )

    _, params = store._engine.conn.statements[1]
    assert params["chash"] == pg_store.content_hash("# new body")
    assert params["chash"] != "stale-digest"


async def test_upsert_document_resets_ingest_status() -> None:
    """内容变化即打回 pending 并清空 error，避免旧切片被当成已就绪。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.upsert_document(_doc()) is True

    sql, params = store._engine.conn.statements[1]
    assert "ingest_status = :reset_status" in sql
    assert params["reset_status"] == "pending"
    assert "error = ''" in sql


async def test_upsert_document_does_not_resurrect_deleted() -> None:
    """内容写不得改 is_delete：恢复只能走 update_document_meta。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.upsert_document(_doc(is_delete=True)) is True

    sql = store._engine.conn.statements[1][0]
    update_part = sql.split("DO UPDATE SET", 1)[1].split(" WHERE ", 1)[0]
    assert "is_delete" not in update_part


async def test_upsert_document_locks_row_before_version() -> None:
    """版本号取号前必须先锁文档行，否则并发会静默吞掉真实快照。"""
    store = pg_store.KbPgStore(
        engine=_FakeEngine(next_version=pg_store.VERSION_RETENTION + 5),
    )

    assert await store.upsert_document(_doc()) is True

    order = [sql for sql, _ in store._engine.conn.statements]
    lock_at = next(
        index for index, sql in enumerate(order) if "FOR UPDATE" in sql
    )
    version_at = next(
        index for index, sql in enumerate(order) if "MAX(version)" in sql
    )
    insert_at = next(
        index
        for index, sql in enumerate(order)
        if "INSERT INTO kb_document_versions" in sql
    )
    purge_at = next(
        index
        for index, sql in enumerate(order)
        if "DELETE FROM kb_document_versions" in sql
    )
    assert lock_at < version_at < insert_at < purge_at


async def test_version_snapshot_insert_is_not_swallowed() -> None:
    """快照写入不得带 DO NOTHING：撞号必须抛错回滚，而非静默丢历史。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.upsert_document(_doc()) is True

    snapshot_sql = next(
        sql
        for sql, _ in store._engine.conn.statements
        if "INSERT INTO kb_document_versions" in sql
    )
    assert "DO NOTHING" not in snapshot_sql


async def test_upsert_document_keeps_recent_versions_only() -> None:
    """未超保留窗口时不得发出任何清理语句，避免误删历史版本。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(next_version=2))

    assert await store.upsert_document(_doc()) is True

    assert not any(
        "DELETE FROM kb_document_versions" in sql
        for sql, _ in store._engine.conn.statements
    )


async def test_upsert_document_path_must_not_be_empty() -> None:
    """空 path 会撞部分唯一索引，写入入口必须拒绝（T1 遗留 M-3）。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    with pytest.raises(ValueError):
        await store.upsert_document(_doc(path=""))

    assert store._engine.conn.statements == []


async def test_add_document_version_requires_existing_document() -> None:
    """0034 无外键，孤儿快照只能靠锁行时判定主体存在来拦。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(lock_present=False))

    with pytest.raises(ValueError):
        await store.add_document_version("ghost", "# x")


async def test_add_document_version_returns_locked_number() -> None:
    """独立补版本：返回真实落库的号，且首写不发清理。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(next_version=4))

    assert await store.add_document_version("d1", "# x") == 4

    executed = store._engine.conn.statements
    assert any("FOR UPDATE" in sql for sql, _ in executed)
    assert not any("INSERT INTO kb_documents" in sql for sql, _ in executed)


# ---------------------------------------------------------------------------
# 元数据写入（改名 / 移动 / 恢复）
# ---------------------------------------------------------------------------


async def test_update_document_meta_writes_only_requested_columns() -> None:
    """改名只写 path/title 与 updated_at，不得触碰正文与版本链。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert (
        await store.update_document_meta(
            "d1",
            path="/new.md",
            title="new",
        )
        is True
    )

    sql, params = store._engine.conn.statements[1]
    assert "UPDATE kb_documents SET" in sql
    assert "path = :path" in sql
    assert "title = :title" in sql
    assert "updated_at = now()" in sql
    assert "content_md" not in sql
    assert params["path"] == "/new.md"


async def test_update_document_meta_can_restore_soft_delete() -> None:
    """回收站恢复是纯元数据写，不受内容 hash 护栏影响。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.update_document_meta("d1", is_delete=False) is True

    sql = store._engine.conn.statements[1][0]
    assert "is_delete = :is_delete" in sql
    assert "content_hash IS DISTINCT FROM" not in sql


async def test_update_document_meta_rejects_unknown_field() -> None:
    """白名单外的键直接拒绝，避免把列名变成可注入面。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    with pytest.raises(ValueError):
        await store.update_document_meta("d1", content_md="# hack")


async def test_update_document_meta_rejects_empty_path() -> None:
    """改名成空串同样撞部分唯一索引，必须早失败。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    with pytest.raises(ValueError):
        await store.update_document_meta("d1", path="   ")


async def test_update_document_meta_no_fields_is_noop() -> None:
    """空字段集不产生任何往返。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.update_document_meta("d1") is False
    assert store._engine.conn.statements == []


# ---------------------------------------------------------------------------
# 读回链路（列名写错必须在这里失败）
# ---------------------------------------------------------------------------


async def test_get_space_reads_back_every_column() -> None:
    """空间读回：JSONB 以 str 到达也要解成 dict，时间列保持 datetime。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(space_row=_space_db_row()))

    space = await store.get_space("kb_a")

    assert space is not None
    assert space.id == "kb_a"
    assert space.name == "孕产知识库"
    assert space.scope == "enterprise"
    assert space.engine == "pgvector"
    assert space.embedding_model == "text-embedding-v4"
    assert space.grants == {"roles": ["kb_admin"]}
    assert space.created_at == datetime(
        2026,
        9,
        17,
        1,
        0,
        0,
        tzinfo=timezone.utc,
    )


async def test_list_spaces_maps_every_row() -> None:
    """列表读回走多行分支，逐行映射不得只取首行。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(space_row=_space_db_row()))

    spaces = await store.list_spaces()

    assert [s.id for s in spaces] == ["kb_a"]
    assert spaces[0].grants == {"roles": ["kb_admin"]}


async def test_get_document_reads_back_content_and_meta() -> None:
    """文档详情读回：正文、source_meta JSONB、状态机字段全部落地。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(doc_row=_doc_db_row()))

    doc = await store.get_document("d1")

    assert doc is not None
    assert doc.path == "/guideline.md"
    assert doc.content_md == "# hello"
    assert doc.content_hash == pg_store.content_hash("# hello")
    assert doc.source == "upload"
    assert doc.source_meta == {"file_name": "a.md"}
    assert doc.ingest_status == "processing"
    assert doc.is_delete is False


async def test_list_documents_projects_no_content() -> None:
    """列表投影不取正文：读模型 content_md 必须为空串。"""
    store = pg_store.KbPgStore(
        engine=_FakeEngine(doc_rows=[_doc_db_row(), _doc_db_row(id="d2")]),
    )

    docs = await store.list_documents("kb_a")

    assert [d.id for d in docs] == ["d1", "d2"]
    assert all(d.content_md == "" for d in docs)
    sql = store._engine.conn.statements[1][0]
    assert "content_md" not in sql
    assert "is_delete = FALSE" in sql


async def test_list_documents_can_include_deleted() -> None:
    """include_deleted 打开后才允许回收站内容出现。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    await store.list_documents("kb_a", include_deleted=True)

    sql = store._engine.conn.statements[1][0]
    assert "is_delete = FALSE" not in sql


async def test_get_document_by_path_binds_path() -> None:
    """按 path 定位是唯一业务键入口，必须把 path 作为绑定参数下推。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(doc_row=_doc_db_row()))

    doc = await store.get_document_by_path("kb_a", "/guideline.md")

    assert doc is not None and doc.id == "d1"
    sql, params = store._engine.conn.statements[1]
    assert "path = :path" in sql
    assert params["path"] == "/guideline.md"


async def test_get_document_by_path_rejects_empty_path() -> None:
    """空 path 定位没有意义且不可能命中，直接拒绝而非返回 None。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    with pytest.raises(ValueError):
        await store.get_document_by_path("kb_a", "")


async def test_space_and_document_missing_return_none() -> None:
    """未命中返回 None（False 语义），不得凭空造对象。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.get_space("nope") is None
    assert await store.get_document("nope") is None


# ---------------------------------------------------------------------------
# 删除语义
# ---------------------------------------------------------------------------


async def test_delete_document_is_soft_delete() -> None:
    """删除走 is_delete 置位，禁止物理删除以保证可追溯。"""
    store = pg_store.KbPgStore(engine=_FakeEngine())

    assert await store.delete_document("d1") is True

    sql = store._engine.conn.statements[1][0]
    assert "UPDATE kb_documents" in sql
    assert "SET is_delete = TRUE" in sql


async def test_delete_space_refuses_when_not_empty() -> None:
    """空间仍有活文档时拒绝删除，避免可达孤儿切片与孤儿绑定。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(occupied=True))

    assert await store.delete_space("kb_a") is False

    executed = store._engine.conn.statements
    guard = next(
        sql for sql, _ in executed if "SELECT 1 FROM kb_documents" in sql
    )
    # 守卫只看活文档：回收站内容不该把空间锁死（真库往返测出的语义）
    assert "is_delete = FALSE" in guard
    assert not any("DELETE FROM kb_spaces" in sql for sql, _ in executed)


async def test_delete_space_removes_empty_space() -> None:
    """空空间删除按 rowcount 返回真假，二次删除返回 False。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(occupied=False))

    assert await store.delete_space("kb_a") is True

    executed = store._engine.conn.statements
    assert any("DELETE FROM kb_spaces" in sql for sql, _ in executed)


# ---------------------------------------------------------------------------
# 表就绪探测（缺表回退 json 平面）
# ---------------------------------------------------------------------------


async def test_ensure_ready_true_when_all_tables_present() -> None:
    """六表齐备 → 就绪，工厂据此走 PG 权威读。"""
    store = pg_store.KbPgStore(engine=_FakeEngine(regclass_row=_ALL_TABLES))

    assert await store.ensure_ready() is True


async def test_ensure_ready_false_when_table_missing() -> None:
    """迁移未执行（探测返回 NULL）→ 未就绪，调用方回退文件平面。"""
    store = pg_store.KbPgStore(
        engine=_FakeEngine(
            regclass_row=("kb_spaces", None, None, None, None, None),
        ),
    )

    assert await store.ensure_ready() is False


async def test_ready_negative_result_expires_and_reprobes() -> None:
    """负结果只缓存一个冷却窗口：迁移补跑后同进程自动恢复。"""
    missing_row = ("kb_spaces", None, None, None, None, None)
    engine = _FakeEngine(regclass_row=missing_row)
    store = pg_store.KbPgStore(engine=engine)

    assert await store.ensure_ready() is False
    assert len(engine.conn.statements) == 1
    # 冷却窗口内不重复往返
    assert await store.ensure_ready() is False
    assert len(engine.conn.statements) == 1

    # 错过窗口后重新探测（此处表仍缺失，但证明负结果未被永久缓存）
    store._tables_checked_at = 0.0
    assert await store.ensure_ready() is False
    assert len(engine.conn.statements) == 2


async def test_ready_positive_result_is_cached_forever() -> None:
    """正结果不再重复往返（表不会在运行期消失）。"""
    engine = _FakeEngine()
    store = pg_store.KbPgStore(engine=engine)

    assert await store.ensure_ready() is True
    assert await store.ensure_ready() is True
    assert len([s for s, _ in engine.conn.statements]) == 1


async def test_ensure_ready_does_not_cache_probe_exception() -> None:
    """网络抖动不得把平面永久降级：异常后下次仍会重探。"""
    engine = _FakeEngine(probe_error=True)
    store = pg_store.KbPgStore(engine=engine)

    assert await store.ensure_ready() is False
    assert store._tables_ready is None
    assert await store.ensure_ready() is False
    assert len(store._engine.conn.statements) == 2


async def test_missing_tables_short_circuit_writes_without_error() -> None:
    """表缺失时写方法返回 False 而不是抛 UndefinedTable。"""
    store = pg_store.KbPgStore(
        engine=_FakeEngine(
            regclass_row=("kb_spaces", None, None, None, None, None),
        ),
    )

    assert await store.upsert_space(_space()) is False
    assert await store.upsert_document(_doc()) is False
    assert await store.get_space("kb_a") is None


# ---------------------------------------------------------------------------
# 影子写调度（同步调用方不阻塞）
# ---------------------------------------------------------------------------


async def test_schedule_upsert_document_executes_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """影子写提交的是可执行协程：跑通写入且异常不外抛。"""
    submitted: List[Any] = []
    monkeypatch.setattr(
        pg_store.write_gateway,
        "submit_shadow_write",
        lambda operation, *, domain="pg": submitted.append(
            (operation, domain)
        ),
    )
    store = pg_store.KbPgStore(engine=_FakeEngine())

    store.schedule_upsert_document(_doc())

    assert [domain for _, domain in submitted] == ["kb_document"]
    assert await submitted[0][0]() is True


async def test_schedule_upsert_space_executes_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空间影子写同文档平面保持一套语义。"""
    submitted: List[Any] = []
    monkeypatch.setattr(
        pg_store.write_gateway,
        "submit_shadow_write",
        lambda operation, *, domain="pg": submitted.append(
            (operation, domain)
        ),
    )
    store = pg_store.KbPgStore(engine=_FakeEngine())

    store.schedule_upsert_space(_space())

    assert [domain for _, domain in submitted] == ["kb_space"]
    assert await submitted[0][0]() is True


# ---------------------------------------------------------------------------
# 模型层枚举前置校验（M-2）
# ---------------------------------------------------------------------------


def test_model_rejects_out_of_check_enum_values() -> None:
    """非法枚举在模型层即失败，不留到 DB CHECK 抛 IntegrityError。"""
    with pytest.raises(ValidationError):
        _space(engine="neo4j")
    with pytest.raises(ValidationError):
        _space(scope="galaxy")
    with pytest.raises(ValidationError):
        _doc(source="ftp")
    with pytest.raises(ValidationError):
        _doc(ingest_status="queued")


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------


async def test_get_kb_pg_store_returns_shared_instance() -> None:
    """工厂返回单例（多次传入 engine 也只建一次），且两个入口共享实例。"""
    first = pg_store.get_kb_pg_store(engine=_FakeEngine())
    second = pg_store.get_kb_pg_store(engine=_FakeEngine())
    assert first is second

    store = await pg_store.get_ready_kb_pg_store()
    assert store is first
    assert await store.ensure_ready() is True


async def test_get_ready_store_is_none_when_tables_missing() -> None:
    """表未就绪时「确定可用」工厂返回 None，门面据此回退 json 平面。"""
    store = pg_store.get_kb_pg_store(
        engine=_FakeEngine(
            regclass_row=("kb_spaces", None, None, None, None, None),
        ),
    )

    assert store is not None
    assert await pg_store.get_ready_kb_pg_store() is None


async def test_get_kb_pg_store_returns_none_on_json_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json 后端下工厂直接返回 None，个人部署不建连接池。"""
    monkeypatch.setattr(
        pg_store.write_gateway,
        "pg_write_available",
        lambda: False,
    )

    assert pg_store.get_kb_pg_store(engine=_FakeEngine()) is None
