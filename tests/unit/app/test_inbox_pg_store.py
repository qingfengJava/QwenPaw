# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the PG inbox events plane.

收件箱事件 PG 语义层单测（不依赖真实 PostgreSQL）：用可脚本化的
fake engine 验证 SQL 决策（append+修剪、过滤读取、未读计数、ACL
标记、删除+run_id 引用检查）、启动 backfill（表空导入 + 种子清空、
表非空跳过）、以及读失败降级文件 / 写失败不落文件的降级语义。
"""
from __future__ import annotations

import json
from typing import Any, Optional

import pytest

from qwenpaw.app import inbox_store


# ---------------------------------------------------------------------------
# Fakes: scriptable engine recording every (sql, params) pair
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(
        self,
        rows: Optional[list[dict]] = None,
        first_row: Optional[dict] = None,
        scalar_value: Any = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._first = first_row
        self._scalar = scalar_value
        self.rowcount = rowcount

    def mappings(self) -> "_FakeResult":
        return self

    def __iter__(self):
        return iter(self._rows)

    def all(self) -> list[dict]:
        return list(self._rows)

    def first(self) -> Optional[dict]:
        return self._first

    def scalar(self) -> Any:
        return self._scalar


class _FakeConn:
    def __init__(self, script) -> None:
        self._script = script
        self.calls: list[tuple[str, Any]] = []

    async def execute(self, stmt: Any, params: Any = None):
        sql = str(stmt)
        self.calls.append((sql, params))
        return self._script(sql, params)

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeEngine:
    def __init__(self, script) -> None:
        self._script = script
        self.conns: list[_FakeConn] = []

    def _mk(self) -> _FakeConn:
        conn = _FakeConn(self._script)
        self.conns.append(conn)
        return conn

    def connect(self) -> _FakeConn:
        return self._mk()

    def begin(self) -> _FakeConn:
        return self._mk()


def _event(event_id: str = "e1", **kw) -> dict:
    base = {
        "id": event_id,
        "agent_id": "default",
        "source_type": "cron",
        "source_id": "j1",
        "event_type": "created",
        "status": "active",
        "severity": "info",
        "title": "T",
        "body": "B",
        "payload": {"run_id": "r1"},
        "read": False,
        "created_at": 1.0,
    }
    base.update(kw)
    return base


def _row(event_id: str = "e1", **kw) -> dict:
    base = {
        "event_id": event_id,
        "agent_id": "default",
        "source_type": "cron",
        "source_id": "j1",
        "event_type": "created",
        "status": "active",
        "severity": "info",
        "title": "T",
        "body": "B",
        "payload": {"run_id": "r1"},
        "is_read": False,
        "created_at": 1.0,
    }
    base.update(kw)
    return base


def _patch_engine(monkeypatch, script) -> _FakeEngine:
    engine = _FakeEngine(script)
    monkeypatch.setattr(
        "qwenpaw.db.engine.create_pg_engine",
        lambda: engine,
    )
    return engine


@pytest.fixture
def pg_on(monkeypatch):
    monkeypatch.setattr(inbox_store, "_pg_plane_available", lambda: True)


@pytest.fixture
def inbox_file(tmp_path, monkeypatch):
    path = tmp_path / "inbox_events.json"
    monkeypatch.setattr(inbox_store, "_INBOX_PATH", path)
    return path


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _all_calls(engine: _FakeEngine) -> list[tuple[str, Any]]:
    return [call for conn in engine.conns for call in conn.calls]


# ---------------------------------------------------------------------------
# Write path: append / prune
# ---------------------------------------------------------------------------


def test_append_pg_inserts_and_prunes(pg_on, inbox_file, monkeypatch):
    engine = _patch_engine(monkeypatch, lambda sql, params: _FakeResult())

    event = _run(inbox_store.append_event(
        agent_id="default",
        source_type="cron",
        source_id="j1",
        event_type="created",
        status="active",
        title="T",
        body="B",
    ))

    assert event["id"]
    calls = _all_calls(engine)
    inserts = [c for c in calls if "INSERT INTO inbox_events" in c[0]]
    prunes = [c for c in calls if "DELETE FROM inbox_events" in c[0]]
    assert len(inserts) == 1
    assert len(prunes) == 1
    params = inserts[0][1]
    assert params["event_id"] == event["id"]
    assert params["tenant_id"] == "default"
    assert json.loads(params["payload"]) == {}
    assert params["is_read"] is False
    assert not inbox_file.exists()


def test_append_pg_failure_does_not_write_file(pg_on, inbox_file, monkeypatch):
    def _boom(sql, params):
        raise RuntimeError("pg down")

    _patch_engine(monkeypatch, _boom)

    event = _run(inbox_store.append_event(
        agent_id=None,
        source_type="cron",
        source_id=None,
        event_type="created",
        status="active",
        title="T",
        body="B",
    ))

    assert event["id"]
    # 写失败仅告警：投影文件不得产生孤儿数据
    assert not inbox_file.exists()


def test_append_json_backend_writes_file(inbox_file, monkeypatch):
    monkeypatch.setattr(inbox_store, "_pg_plane_available", lambda: False)

    event = _run(inbox_store.append_event(
        agent_id="default",
        source_type="cron",
        source_id="j1",
        event_type="created",
        status="active",
        title="T",
        body="B",
    ))

    assert inbox_file.exists()
    data = json.loads(inbox_file.read_text(encoding="utf-8"))
    assert data[0]["id"] == event["id"]


# ---------------------------------------------------------------------------
# Read path: list / query / degrade
# ---------------------------------------------------------------------------


def test_list_events_pg_rows_and_filters(pg_on, inbox_file, monkeypatch):
    rows = [_row("e2"), _row("e1", payload="not-json", is_read=True)]

    def _script(sql, params):
        if "FROM inbox_events WHERE" in sql:
            assert params["limit"] == 50
            assert params["offset"] == 0
            assert "source_type = :source_type" in sql
            return _FakeResult(rows=rows)
        return _FakeResult()

    _patch_engine(monkeypatch, _script)

    events = _run(inbox_store.list_events(source_type="cron"))

    assert [e["id"] for e in events] == ["e2", "e1"]
    # payload 为非法 JSON 字符串时优雅降级为空 dict
    assert events[1]["payload"] == {}
    assert events[1]["read"] is True


def test_query_events_counts_and_page(pg_on, inbox_file, monkeypatch):
    def _script(sql, params):
        if "count(*) AS total" in sql:
            assert "count(*) FILTER (WHERE NOT is_read)" in sql
            assert "source_type = ANY(:source_types)" in sql
            assert params["source_types"] == ["cron", "mailbox"]
            return _FakeResult(first_row={"total": 12, "unread": 3})
        if "ORDER BY id DESC" in sql:
            assert params["limit"] == 10
            assert params["offset"] == 5
            return _FakeResult(rows=[_row("e9")])
        return _FakeResult()

    _patch_engine(monkeypatch, _script)

    page, total, unread = _run(inbox_store.query_events(
        limit=10,
        offset=5,
        source_types={"mailbox", "cron"},
    ))

    assert total == 12
    assert unread == 3
    assert [e["id"] for e in page] == ["e9"]


def test_list_events_degrades_to_file_on_pg_error(
    pg_on,
    inbox_file,
    monkeypatch,
):
    inbox_file.write_text(
        json.dumps([_event("file-1")]),
        encoding="utf-8",
    )

    def _boom(sql, params):
        raise RuntimeError("pg down")

    _patch_engine(monkeypatch, _boom)

    events = _run(inbox_store.list_events())

    assert [e["id"] for e in events] == ["file-1"]


# ---------------------------------------------------------------------------
# Mark read / ACL
# ---------------------------------------------------------------------------


def test_mark_read_pg_rowcount(pg_on, inbox_file, monkeypatch):
    def _script(sql, params):
        assert "event_id = ANY(:event_ids)" in sql
        assert params["event_ids"] == ["e1", "e2"]
        return _FakeResult(rowcount=2)

    _patch_engine(monkeypatch, _script)

    updated = _run(inbox_store.mark_read(["e1", "e2"]))
    assert updated == 2


def test_mark_all_read_pg(pg_on, inbox_file, monkeypatch):
    def _script(sql, params):
        assert "is_read = FALSE" in sql
        return _FakeResult(rowcount=5)

    _patch_engine(monkeypatch, _script)

    assert _run(inbox_store.mark_all_read()) == 5


def test_mark_read_by_acl_sender_pg(pg_on, inbox_file, monkeypatch):
    def _script(sql, params):
        assert "payload->>'acl_status' = 'pending'" in sql
        assert "lower(payload->>'acl_sender_address') = :needle" in sql
        assert params["needle"] == "a@b.com"
        assert params["agent_id"] == "default"
        return _FakeResult(rowcount=1)

    _patch_engine(monkeypatch, _script)

    updated = _run(inbox_store.mark_read_by_acl_sender(
        "default",
        "  A@B.com ",
    ))
    assert updated == 1


# ---------------------------------------------------------------------------
# Delete + run_id reference check
# ---------------------------------------------------------------------------


def test_delete_event_pg_with_run_refs(pg_on, inbox_file, monkeypatch):
    def _script(sql, params):
        if "RETURNING payload->>'run_id'" in sql:
            assert params["event_id"] == "e1"
            return _FakeResult(first_row={"run_id": "r1"}, rowcount=1)
        if "count(*)" in sql:
            return _FakeResult(scalar_value=1)
        return _FakeResult()

    _patch_engine(monkeypatch, _script)

    deleted, run_id, referenced = _run(inbox_store.delete_event("e1"))
    assert deleted is True
    assert run_id == "r1"
    assert referenced is True


def test_delete_event_pg_missing(pg_on, inbox_file, monkeypatch):
    def _script(sql, params):
        if "RETURNING payload->>'run_id'" in sql:
            return _FakeResult(first_row=None, rowcount=0)
        return _FakeResult()

    _patch_engine(monkeypatch, _script)

    deleted, run_id, referenced = _run(inbox_store.delete_event("nope"))
    assert (deleted, run_id, referenced) == (False, None, False)


# ---------------------------------------------------------------------------
# Startup backfill: seed import / skip / noop
# ---------------------------------------------------------------------------


def test_initialize_imports_and_clears_seed(pg_on, inbox_file, monkeypatch):
    inbox_file.write_text(
        json.dumps([
            _event("s1", payload={"k": 1}),
            _event("s2", read=True),
        ]),
        encoding="utf-8",
    )
    state = {"count": 0}

    def _script(sql, params):
        if "SELECT count(*) FROM inbox_events" in sql:
            return _FakeResult(scalar_value=state["count"])
        if "INSERT INTO inbox_events" in sql:
            state["rows"] = params
            return _FakeResult()
        return _FakeResult()

    _patch_engine(monkeypatch, _script)

    _run(inbox_store.initialize())

    # 种子文件被清空：删除/已读状态不得被投影文件“复活”
    assert json.loads(inbox_file.read_text(encoding="utf-8")) == []
    rows = state["rows"]
    assert isinstance(rows, list) and len(rows) == 2
    assert rows[0]["event_id"] == "s1"
    assert rows[1]["is_read"] is True


def test_initialize_skips_when_table_not_empty(pg_on, inbox_file, monkeypatch):
    inbox_file.write_text(
        json.dumps([_event("s1")]),
        encoding="utf-8",
    )

    def _script(sql, params):
        if "SELECT count(*) FROM inbox_events" in sql:
            return _FakeResult(scalar_value=7)
        return _FakeResult()

    engine = _patch_engine(monkeypatch, _script)

    _run(inbox_store.initialize())

    # 表非空：不导入、不动种子文件
    assert "INSERT INTO inbox_events" not in str(_all_calls(engine))
    data = json.loads(inbox_file.read_text(encoding="utf-8"))
    assert data[0]["id"] == "s1"


def test_initialize_noop_when_backend_json(inbox_file, monkeypatch):
    monkeypatch.setattr(inbox_store, "_pg_plane_available", lambda: False)
    inbox_file.write_text(
        json.dumps([_event("s1")]),
        encoding="utf-8",
    )

    _run(inbox_store.initialize())

    # json 后端零动作
    data = json.loads(inbox_file.read_text(encoding="utf-8"))
    assert data[0]["id"] == "s1"


def test_read_never_triggers_backfill(pg_on, inbox_file, monkeypatch):
    # 运行期“表空”是合法状态：读路径必须纯读，不得回灌种子文件
    inbox_file.write_text(
        json.dumps([_event("stale")]),
        encoding="utf-8",
    )

    def _script(sql, params):
        if "FROM inbox_events WHERE" in sql:
            return _FakeResult(rows=[])
        if "SELECT count(*) FROM inbox_events" in sql:
            raise AssertionError("read path must not probe the table count")
        return _FakeResult()

    _patch_engine(monkeypatch, _script)

    events = _run(inbox_store.list_events())
    assert events == []
    # 种子文件未被触碰
    data = json.loads(inbox_file.read_text(encoding="utf-8"))
    assert data[0]["id"] == "stale"
