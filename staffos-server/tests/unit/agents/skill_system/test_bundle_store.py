# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the personal skill bundle PG plane (bundle_store).

覆盖 S2 个人技能平面数据层：三态后端门槛（json 零动作）、JSONB 防御性
解析、行映射、以及 owner 作用域 CRUD 的 SQL 谓词——跨人隔离在数据层即
成立（每条查询恒带 ``owner_user_id`` 谓词，不存在跨用户泄露路径）。用可
脚本化 fake engine 验证 SQL 决策，不依赖真实 PostgreSQL。
"""
from __future__ import annotations

from typing import Optional

import pytest

from qwenpaw.agents.skill_system import bundle_store


# ------------------------------------------------------------------ #
# fake engine：记录每条 (sql, params)
# ------------------------------------------------------------------ #


class _FakeResult:
    def __init__(self, rows=None, first_row=None, rowcount=0):
        self._rows = rows or []
        self._first = first_row
        self.rowcount = rowcount

    def all(self):
        return list(self._rows)

    def first(self):
        return self._first


class _FakeConn:
    def __init__(self, script):
        self._script = script
        self.calls: list[tuple[str, Optional[dict]]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        return self._script(sql, params)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, script):
        self._script = script
        self.conns: list[_FakeConn] = []

    def _mk(self):
        conn = _FakeConn(self._script)
        self.conns.append(conn)
        return conn

    def connect(self):
        return self._mk()

    def begin(self):
        return self._mk()


def _default_script(sql, params):
    return _FakeResult()


# ------------------------------------------------------------------ #
# 三态后端门槛（与 catalog_store 同源开关）
# ------------------------------------------------------------------ #


def test_plane_available_requires_backend_and_dsn(monkeypatch) -> None:
    from qwenpaw.db import write_gateway

    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    write_gateway.reset_backend_cache()
    assert bundle_store.bundle_pg_plane_available() is False

    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
    monkeypatch.setenv(
        "QWENPAW_PG_DSN",
        "postgresql+asyncpg://u:p@localhost:5432/db",
    )
    write_gateway.reset_backend_cache()
    assert bundle_store.bundle_pg_plane_available() is True


# ------------------------------------------------------------------ #
# 纯 helper：JSONB 防御性解析 + 行映射
# ------------------------------------------------------------------ #


def test_json_loads_defensive() -> None:
    assert bundle_store._json_loads(None, {}) == {}
    assert bundle_store._json_loads('{"a": 1}', {}) == {"a": 1}
    assert bundle_store._json_loads("bad{", {"x": 1}) == {"x": 1}
    assert bundle_store._json_loads({"y": 2}, {}) == {"y": 2}


def test_row_to_bundle_maps_fields() -> None:
    row = ("demo", {"SKILL.md": "x"}, True, 3, "/root/eng", None)
    assert bundle_store._row_to_bundle(row) == {
        "name": "demo",
        "files": {"SKILL.md": "x"},
        "enabled": True,
        "version": 3,
        "department_id": "/root/eng",
        "project_id": None,
    }


def test_row_to_bundle_defaults_bad_files_and_version() -> None:
    row = ("demo", "bad{", False, None, None, None)
    bundle = bundle_store._row_to_bundle(row)
    assert bundle["files"] == {}
    assert bundle["version"] == 1
    assert bundle["enabled"] is False


# ------------------------------------------------------------------ #
# owner 作用域 CRUD：SQL 谓词（跨人隔离在数据层成立）
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_upsert_scopes_by_owner_and_casts_files() -> None:
    engine = _FakeEngine(_default_script)
    await bundle_store.upsert_skill_bundle_pg(
        "a1",
        "alice",
        "demo",
        {"SKILL.md": "body"},
        enabled=True,
        version=2,
        department_id="/root/eng",
        engine=engine,
    )
    sql, params = engine.conns[0].calls[0]
    assert "INSERT INTO agent_skill_bundles" in sql
    # files 以 JSON 字符串 + CAST 写入（规避 asyncpg dict→JSONB 陷阱）
    assert "CAST(:files AS JSONB)" in sql
    assert isinstance(params["files"], str)
    assert "SKILL.md" in params["files"]
    assert "ON CONFLICT (tenant_id, agent_id, owner_user_id, name)" in sql
    assert params["owner"] == "alice"
    assert params["name"] == "demo"
    assert params["version"] == 2
    assert params["dept"] == "/root/eng"
    assert params["proj"] is None


@pytest.mark.asyncio
async def test_delete_scopes_by_owner() -> None:
    engine = _FakeEngine(lambda sql, params: _FakeResult(rowcount=1))
    ok = await bundle_store.delete_skill_bundle_pg(
        "a1", "alice", "demo", engine=engine,
    )
    assert ok is True
    sql, params = engine.conns[0].calls[0]
    assert "DELETE FROM agent_skill_bundles" in sql
    assert "owner_user_id = :owner" in sql
    assert params["owner"] == "alice"
    assert params["name"] == "demo"


@pytest.mark.asyncio
async def test_delete_returns_false_when_no_row() -> None:
    engine = _FakeEngine(lambda sql, params: _FakeResult(rowcount=0))
    ok = await bundle_store.delete_skill_bundle_pg(
        "a1", "alice", "ghost", engine=engine,
    )
    assert ok is False


@pytest.mark.asyncio
async def test_load_one_scopes_by_owner_and_name() -> None:
    row = ("demo", {"SKILL.md": "x"}, True, 1, None, None)
    engine = _FakeEngine(lambda sql, params: _FakeResult(first_row=row))
    bundle = await bundle_store.load_skill_bundle_pg(
        "a1", "alice", "demo", engine=engine,
    )
    assert bundle is not None
    assert bundle["name"] == "demo"
    sql, params = engine.conns[0].calls[0]
    assert "owner_user_id = :owner" in sql
    assert "name = :name" in sql
    assert params["owner"] == "alice"


@pytest.mark.asyncio
async def test_load_one_returns_none_when_absent() -> None:
    engine = _FakeEngine(lambda sql, params: _FakeResult(first_row=None))
    bundle = await bundle_store.load_skill_bundle_pg(
        "a1", "alice", "ghost", engine=engine,
    )
    assert bundle is None


@pytest.mark.asyncio
async def test_load_owner_bundles_scopes_by_owner() -> None:
    rows = [
        ("alpha", {"SKILL.md": "a"}, True, 1, None, None),
        ("beta", {"SKILL.md": "b"}, False, 2, "/root/eng", None),
    ]
    engine = _FakeEngine(lambda sql, params: _FakeResult(rows=rows))
    bundles = await bundle_store.load_owner_bundles_pg(
        "a1", "alice", engine=engine,
    )
    assert [b["name"] for b in bundles] == ["alpha", "beta"]
    assert bundles[1]["enabled"] is False
    sql, params = engine.conns[0].calls[0]
    # 严格 owner 作用域：查询恒带 owner 谓词，无跨用户泄露路径
    assert "owner_user_id = :owner" in sql
    assert "ORDER BY name" in sql
    assert params["owner"] == "alice"


# ------------------------------------------------------------------ #
# 物化：bundle files 全树 → .personal_skills/{owner}/{skill}/
# ------------------------------------------------------------------ #


def test_sanitize_owner_dirname_rejects_traversal() -> None:
    assert bundle_store.sanitize_owner_dirname("alice") == "alice"
    assert bundle_store.sanitize_owner_dirname("..") == "_anonymous"
    assert bundle_store.sanitize_owner_dirname("") == "_anonymous"
    # 路径分隔符被净化为 _（无法穿越出根目录）
    assert bundle_store.sanitize_owner_dirname("a/b") == "a_b"


def test_get_personal_skills_dir(tmp_path) -> None:
    d = bundle_store.get_personal_skills_dir(tmp_path, "alice")
    assert d == tmp_path / ".personal_skills" / "alice"


def test_materialize_bundle_files_writes_tree(tmp_path) -> None:
    skill_dir = tmp_path / "demo"
    ok = bundle_store.materialize_bundle_files(
        skill_dir,
        {
            "SKILL.md": "---\nname: demo\n---\nbody\n",
            "references/ref.md": "ref content",
            "scripts/run.py": "print(1)\n",
        },
    )
    assert ok is True
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "references" / "ref.md").exists()
    assert (skill_dir / "scripts" / "run.py").exists()


def test_materialize_bundle_files_rejects_traversal(tmp_path) -> None:
    skill_dir = tmp_path / "demo"
    ok = bundle_store.materialize_bundle_files(
        skill_dir,
        {"SKILL.md": "x", "../escape.md": "evil", "/abs.md": "evil"},
    )
    assert ok is True  # SKILL.md 仍写出
    assert (skill_dir / "SKILL.md").exists()
    # 穿越/绝对路径条目被拒绝，未落到 skill_dir 外
    assert not (tmp_path / "escape.md").exists()


def test_materialize_bundle_files_no_skill_md_returns_false(tmp_path) -> None:
    assert bundle_store.materialize_bundle_files(
        tmp_path / "demo", {"references/x.md": "y"},
    ) is False


def test_materialize_bundle_files_empty_returns_false(tmp_path) -> None:
    result = bundle_store.materialize_bundle_files(tmp_path / "demo", {})
    assert result is False


def test_materialize_owner_bundles_skips_disabled(tmp_path) -> None:
    bundles = [
        {"name": "active", "enabled": True, "files": {"SKILL.md": "a"}},
        {"name": "off", "enabled": False, "files": {"SKILL.md": "b"}},
    ]
    root = bundle_store.materialize_owner_bundles(tmp_path, "alice", bundles)
    assert root == tmp_path / ".personal_skills" / "alice"
    assert (root / "active" / "SKILL.md").exists()
    assert not (root / "off").exists()
