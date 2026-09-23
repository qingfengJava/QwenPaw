# -*- coding: utf-8 -*-
"""T4 ontology store CRUD 单测（FakeConn 回放，零 PG）。

沿用 ``tests/unit/app/kb/test_pg_store.py`` 的 FakeEngine 约定：只捕获
参数化 SQL 与调用次序，fake 按**语句特征回放真实行**——投影列写错会
在此处 KeyError 早失败，而非静默落默认值。真库往返由集成门控覆盖。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

from qwenpaw.app.ontology import store as store_mod
from qwenpaw.app.ontology.models import (
    KbObjectLink,
    OntologyObject,
    OntologyRelation,
)

pytestmark = pytest.mark.unit

_STAMP_1 = datetime(2026, 9, 20, 1, 0, 0, tzinfo=timezone.utc)
_STAMP_2 = datetime(2026, 9, 20, 2, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 行夹具（kb_documents 同款全列形态，投影严格索引）
# ---------------------------------------------------------------------------


def _type_row(**overrides: Any) -> Dict[str, Any]:
    """``ontology_types`` 一行（l1.project 种子形态）。"""
    row = {
        "id": "l1.project",
        "name": "项目",
        "layer": "L1",
        "parent_id": "l0.object",
        "description": "项目/工程对象",
        "attributes_schema": {},
        "created_at": _STAMP_1,
    }
    row.update(overrides)
    return row


def _object_row(**overrides: Any) -> Dict[str, Any]:
    """``ontology_objects`` 一行（全列，JSONB 列原样 dict/list）。"""
    row = {
        "id": "obj_1",
        "type_id": "l1.project",
        "name": "PROJECT-10001",
        "aliases": ["P10001"],
        "attributes": {"code": "PROJECT-10001"},
        "state": "",
        "state_detail": {},
        "owner_id": "u1",
        "org_id": "default",
        "department_id": "",
        "status": "active",
        "source": "manual",
        "evidence_refs": [],
        "is_delete": False,
        "created_at": _STAMP_1,
        "updated_at": _STAMP_2,
    }
    row.update(overrides)
    return row


def _relation_row(**overrides: Any) -> Dict[str, Any]:
    """``ontology_relations`` 一行。"""
    row = {
        "id": "rel_1",
        "type": "belongs_to",
        "from_type": "l1.contract",
        "from_id": "obj_c1",
        "to_type": "l1.project",
        "to_id": "obj_1",
        "valid_from": None,
        "valid_to": None,
        "confidence": 1.0,
        "source": "manual",
        "evidence_refs": [],
        "created_at": _STAMP_1,
    }
    row.update(overrides)
    return row


def _link_row(**overrides: Any) -> Dict[str, Any]:
    """``kb_object_links`` 一行。"""
    row = {
        "id": "lnk_1",
        "kb_space_id": "kb_a",
        "kb_document_id": "doc_1",
        "object_type": "l1.project",
        "object_id": "obj_1",
        "relation": "knowledge_mentions",
        "created_at": _STAMP_1,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Fake conn / engine（按语句特征回放）
# ---------------------------------------------------------------------------


def _projected_columns(statement: str) -> List[str]:
    """取回 ``SELECT a, b FROM ...`` 的投影列名清单。"""
    head = statement.split(" FROM ", 1)[0].strip()
    head = head.removeprefix("SELECT")
    return [col.strip() for col in head.split(",") if col.strip()]


def _project(row: Dict[str, Any], statement: str) -> Dict[str, Any]:
    """按语句投影裁剪一行（缺列 KeyError 早失败）。"""
    return {col: row[col] for col in _projected_columns(statement)}


class _FakeResult:
    """最小 Result 协议：rowcount / first / mappings().first/all()。"""

    def __init__(
        self,
        rowcount: int = 1,
        row: Optional[Dict[str, Any]] = None,
        rows: Optional[List[Dict[str, Any]]] = None,
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
    """记录执行序列，按表名特征回放行。"""

    def __init__(
        self,
        *,
        unchanged: bool = False,
        regclass_row: Optional[Tuple] = store_mod._ONT_TABLES,
        type_rows: Optional[List[Dict[str, Any]]] = None,
        object_row: Optional[Dict[str, Any]] = None,
        object_rows: Optional[List[Dict[str, Any]]] = None,
        relation_rows: Optional[List[Dict[str, Any]]] = None,
        link_rows: Optional[List[Dict[str, Any]]] = None,
        duplicate: bool = False,
    ) -> None:
        self.statements: List[Tuple[str, Dict[str, Any]]] = []
        self._unchanged = unchanged
        self._regclass_row = regclass_row
        self._type_rows = type_rows or []
        self._object_row = object_row
        self._object_rows = object_rows or []
        self._relation_rows = relation_rows or []
        self._link_rows = link_rows or []
        self._duplicate = duplicate

    async def execute(
        self,
        sql: Any,
        params: Optional[Dict[str, Any]] = None,
    ) -> _FakeResult:
        statement = str(sql)
        bound = dict(params or {})
        self.statements.append((statement, bound))
        if "to_regclass" in statement:
            return _FakeResult(tuple_row=self._regclass_row)
        if "INSERT INTO ontology_objects" in statement:
            return _FakeResult(rowcount=0 if self._duplicate else 1)
        if "FROM ontology_objects" in statement:
            if "id = :oid" in statement and "UPDATE" not in statement:
                row = self._object_row
                if row is None:
                    return _FakeResult(rowcount=1, row=None)
                # 回放真库过滤行为：语句限存活行而夹具已删 → 空集
                if (
                    "is_delete = FALSE" in statement
                    and row.get("is_delete")
                ):
                    return _FakeResult(rowcount=1, row=None)
                return _FakeResult(rowcount=1, row=_project(row, statement))
            return _FakeResult(
                rowcount=1,
                rows=[
                    _project(row, statement) for row in self._object_rows
                ],
            )
        if "UPDATE ontology_objects" in statement:
            return _FakeResult(rowcount=0 if self._unchanged else 1)
        if "FROM ontology_types" in statement:
            if "id = :tid2" in statement:
                if not self._type_rows:
                    return _FakeResult(rowcount=1, row=None)
                return _FakeResult(
                    rowcount=1,
                    row=_project(self._type_rows[0], statement),
                )
            return _FakeResult(
                rowcount=1,
                rows=[
                    _project(row, statement) for row in self._type_rows
                ],
            )
        if "INSERT INTO ontology_relations" in statement:
            return _FakeResult(rowcount=0 if self._duplicate else 1)
        if "DELETE FROM ontology_relations" in statement:
            return _FakeResult(rowcount=0 if self._unchanged else 1)
        if "FROM ontology_relations" in statement:
            return _FakeResult(
                rowcount=1,
                rows=[
                    _project(row, statement) for row in self._relation_rows
                ],
            )
        if "INSERT INTO ontology_state_transitions" in statement:
            return _FakeResult(rowcount=0 if self._duplicate else 1)
        if "FROM ontology_state_transitions" in statement:
            return _FakeResult(rowcount=1, rows=[])
        if "INSERT INTO ontology_rules" in statement:
            return _FakeResult(rowcount=0 if self._duplicate else 1)
        if "FROM ontology_rules" in statement:
            return _FakeResult(rowcount=1, rows=[])
        if "INSERT INTO ontology_actions" in statement:
            return _FakeResult(rowcount=0 if self._duplicate else 1)
        if "FROM ontology_actions" in statement:
            return _FakeResult(rowcount=1, rows=[])
        if "INSERT INTO kb_object_links" in statement:
            return _FakeResult(rowcount=0 if self._duplicate else 1)
        if "DELETE FROM kb_object_links" in statement:
            return _FakeResult(rowcount=0 if self._unchanged else 1)
        if "FROM kb_object_links" in statement:
            return _FakeResult(
                rowcount=1,
                rows=[_project(row, statement) for row in self._link_rows],
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
def _pg_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """本文件默认在 dual/pg 后端下运行（单测不依赖进程环境变量）。"""
    monkeypatch.setattr(
        store_mod.write_gateway,
        "pg_write_available",
        lambda: True,
    )


def _make_store(**conn_kwargs: Any) -> store_mod.PgOntologyStore:
    """构造带 FakeEngine 的 store（不触碰工厂单例）。"""
    return store_mod.PgOntologyStore(engine=_FakeEngine(**conn_kwargs))


# ---------------------------------------------------------------------------
# readiness / types
# ---------------------------------------------------------------------------


async def test_json_plane_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """json 后端（三态不可用）→ 全部读路径返回空、写路径 False。"""
    monkeypatch.setattr(store_mod, "ont_pg_plane_available", lambda: False)
    store = _make_store()
    assert await store.list_types() == []
    assert await store.get_object("obj_1") is None
    assert await store.list_objects() == []
    assert (
        await store.create_object(
            OntologyObject(id="obj_x", type_id="l1.project", name="n"),
        )
        is False
    )
    # 平面不可用时不发任何 SQL
    assert store._engine.conn.statements == []


async def test_list_types_filters_layer() -> None:
    """list_types layer 过滤下推 SQL（L0 只回九类元模型）。"""
    store = _make_store(type_rows=[_type_row()])
    items = await store.list_types("L1")
    assert [item.id for item in items] == ["l1.project"]
    statement, bound = store._engine.conn.statements[-1]
    assert "layer = :layer" in statement
    assert bound["layer"] == "L1"


async def test_get_type_hit_and_miss() -> None:
    """get_type 命中回读模型；未命中返回 None。"""
    store = _make_store(type_rows=[_type_row()])
    assert (await store.get_type("l1.project")).name == "项目"

    empty = _make_store(type_rows=[])
    assert await empty.get_type("l1.ghost") is None


# ---------------------------------------------------------------------------
# objects
# ---------------------------------------------------------------------------


async def test_create_object_duplicate_id_returns_false() -> None:
    """重复 id（rowcount=0）→ False（API 层转 409/400）。"""
    store = _make_store(duplicate=True)
    ok = await store.create_object(
        OntologyObject(id="obj_1", type_id="l1.project", name="P1"),
    )
    assert ok is False


async def test_get_object_filters_soft_deleted() -> None:
    """get_object 默认过滤逻辑删除行；include_deleted 放行。"""
    deleted = _object_row(is_delete=True)
    store = _make_store(object_row=deleted)
    assert await store.get_object("obj_1") is None
    live = await store.get_object("obj_1", include_deleted=True)
    assert live is not None and live.is_delete is True
    # SQL 携带 is_delete 过滤（排除探测语句后取第一条读语句）
    select_statements = [
        statement
        for statement, _ in store._engine.conn.statements
        if "FROM ontology_objects" in statement
    ]
    assert select_statements
    assert "is_delete = FALSE" in select_statements[0]


async def test_list_objects_conditions_pushdown() -> None:
    """list_objects 多条件 AND 下推（type/org/status/keyword）。"""
    store = _make_store(object_rows=[_object_row()])
    items = await store.list_objects(
        type_id="l1.project",
        org_id="default",
        status="active",
        keyword="PROJECT",
        limit=50,
    )
    assert len(items) == 1
    statement, bound = store._engine.conn.statements[-1]
    for fragment in (
        "type_id = :type_id",
        "org_id = :org_id",
        "status = :status",
        "name ILIKE :kw",
        "LIMIT :lim",
    ):
        assert fragment in statement, fragment
    assert bound["kw"] == "%PROJECT%"
    assert bound["lim"] == 50


async def test_update_object_whitelist_and_jsonb() -> None:
    """update_object 白名单外键被丢弃；JSONB 字段序列化落参数。"""
    store = _make_store(object_row=_object_row())
    ok = await store.update_object(
        "obj_1",
        {
            "name": "renamed",
            "aliases": ["A", "B"],
            "evil_column": "x",
        },
    )
    assert ok is True
    statement, bound = store._engine.conn.statements[-1]
    assert "name = :name" in statement
    assert "aliases = CAST(:aliases AS JSONB)" in statement
    assert "evil_column" not in statement
    assert bound["aliases"] == '["A", "B"]'
    assert "updated_at = now()" in statement


async def test_update_object_empty_fields_short_circuits() -> None:
    """空白名单短路：不发 UPDATE、返回 False。"""
    store = _make_store(object_row=_object_row())
    assert await store.update_object("obj_1", {"evil": 1}) is False
    assert not any(
        "UPDATE" in statement
        for statement, _ in store._engine.conn.statements
    )


async def test_soft_delete_object_sql() -> None:
    """逻辑删除 SQL 携带 is_delete = TRUE 且只作用存活行。"""
    store = _make_store()
    assert await store.soft_delete_object("obj_1") is True
    statement, _ = store._engine.conn.statements[-1]
    assert "is_delete = TRUE" in statement
    assert "is_delete = FALSE" in statement


# ---------------------------------------------------------------------------
# relations / links
# ---------------------------------------------------------------------------


async def test_relation_roundtrip_and_filters() -> None:
    """关系创建参数完整；list_relations 端点过滤下推。"""
    store = _make_store(relation_rows=[_relation_row()])
    rel = OntologyRelation(
        id="rel_2",
        type="belongs_to",
        from_type="l1.contract",
        from_id="obj_c1",
        to_type="l1.project",
        to_id="obj_1",
    )
    assert await store.create_relation(rel) is True
    statement, bound = store._engine.conn.statements[-1]
    assert bound["rtype"] == "belongs_to"
    assert bound["from_id"] == "obj_c1"

    items = await store.list_relations(to_id="obj_1", rel_type="belongs_to")
    assert [item.id for item in items] == ["rel_1"]
    statement, bound = store._engine.conn.statements[-1]
    assert "to_id = :to_id" in statement
    assert bound["rtype"] == "belongs_to"


async def test_delete_relation_rowcount_semantics() -> None:
    """delete_relation 行数语义：未命中（rowcount=0）返回 False。"""
    store = _make_store(unchanged=True)
    assert await store.delete_relation("rel_1") is False


async def test_link_roundtrip_and_dual_views() -> None:
    """互引创建 + 文档/对象两侧视角查询。"""
    store = _make_store(link_rows=[_link_row()])
    link = KbObjectLink(
        id="lnk_2",
        kb_space_id="kb_a",
        kb_document_id="doc_9",
        object_type="l1.project",
        object_id="obj_1",
    )
    assert await store.create_link(link) is True
    statement, bound = store._engine.conn.statements[-1]
    assert bound["relation"] == "knowledge_mentions"

    by_doc = await store.list_links_for_document("doc_1")
    assert [item.id for item in by_doc] == ["lnk_1"]
    statement, bound = store._engine.conn.statements[-1]
    assert "kb_document_id = :did" in statement
    assert bound["did"] == "doc_1"

    by_obj = await store.list_links_for_object("obj_1")
    assert [item.id for item in by_obj] == ["lnk_1"]


# ---------------------------------------------------------------------------
# row 转换容缺
# ---------------------------------------------------------------------------


def test_object_from_row_tolerates_missing_keys() -> None:
    """行转换对非时间戳列容缺（读模型落默认值不炸）。

    created_at/updated_at 刻意严格（投影漂移哨兵，同 kb 平面惯例），
    由下一用例锁定。
    """
    obj = store_mod.object_from_row(
        {
            "id": "obj_x",
            "name": "n",
            "created_at": _STAMP_1,
            "updated_at": _STAMP_2,
        },
    )
    assert obj.id == "obj_x"
    assert obj.aliases == []
    assert obj.status == "active"
    assert obj.source == "manual"
    assert obj.created_at == _STAMP_1


def test_object_from_row_requires_stamps() -> None:
    """完整读链缺 NOT NULL 时间戳列必须早失败（投影漂移哨兵）。"""
    with pytest.raises(KeyError):
        store_mod.object_from_row(
            {"id": "obj_x", "name": "n", "updated_at": _STAMP_2},
        )
