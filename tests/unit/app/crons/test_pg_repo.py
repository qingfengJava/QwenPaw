# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the PG cron job repository.

PG 语义层单测（不依赖真实 PostgreSQL）：用可脚本化的 fake engine 验证
SQL 决策（backfill 触发、全量对齐分支、seq 分配与修剪窗口）、投影
缓存写盘、以及 ``build_job_repository`` 按 ``QWENPAW_STORAGE_BACKEND``
的选择与降级行为。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Any, Optional

import pytest

from qwenpaw.app.crons.models import JobsFile
from qwenpaw.app.crons.repo import build_job_repository
from qwenpaw.app.crons.repo.json_repo import JsonJobRepository
from qwenpaw.app.crons.repo.pg_repo import (
    PgJobRepository,
    _aware_utc,
    _dump_spec,
    _payload_hash,
)
from qwenpaw.exceptions import ConfigurationException
from tests.unit.app.conftest import (
    make_cron_job_spec,
    make_execution_record,
)


# ---------------------------------------------------------------------------
# Fakes: scriptable engine recording every (sql, params) pair
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(
        self,
        rows: Optional[list[dict]] = None,
        first_row: Optional[dict] = None,
        rowcount: int = 0,
    ) -> None:
        self._rows = rows or []
        self._first = first_row
        self.rowcount = rowcount

    def mappings(self) -> "_FakeResult":
        return self

    def __iter__(self):
        return iter(self._rows)

    def all(self) -> list[dict]:
        return list(self._rows)

    async def first(self) -> Optional[dict]:
        return self._first


class _FakeConn:
    def __init__(self, script) -> None:
        self._script = script
        self.calls: list[tuple[str, Optional[dict]]] = []

    async def execute(self, stmt: Any, params: Optional[dict] = None):
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


def _default_script(sql: str, params: Optional[dict]):
    """Route by SQL fragment; empty plane by default."""
    if "COALESCE(MAX(seq)" in sql:
        return _FakeResult(first_row={"next_seq": 1})
    return _FakeResult()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_dump_spec_and_hash_are_deterministic():
    spec_a = make_cron_job_spec(job_id="j1", name="A")
    spec_b = make_cron_job_spec(job_id="j1", name="A")
    spec_c = make_cron_job_spec(job_id="j1", name="B")

    payload_a = _dump_spec(spec_a)
    assert payload_a == _dump_spec(spec_b)
    assert _payload_hash(payload_a) == _payload_hash(_dump_spec(spec_b))
    assert _payload_hash(payload_a) != _payload_hash(_dump_spec(spec_c))


def test_aware_utc_normalizes_naive_datetime():
    naive = datetime(2030, 1, 1, 9, 0, 0)
    normalized = _aware_utc(naive)
    assert normalized.tzinfo is not None
    assert normalized.utcoffset().total_seconds() == 0

    aware = datetime(2030, 1, 1, 9, 0, 0, tzinfo=tz.utc)
    assert _aware_utc(aware) is aware


# ---------------------------------------------------------------------------
# build_job_repository backend selection / degradation
# ---------------------------------------------------------------------------


def test_build_backend_json_returns_json_repo(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.db.write_gateway.resolve_storage_backend",
        lambda: "json",
    )
    repo = build_job_repository(agent_id="a1", jobs_path="x/jobs.json")
    assert isinstance(repo, JsonJobRepository)


def test_build_backend_pg_returns_pg_repo(monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.db.write_gateway.resolve_storage_backend",
        lambda: "pg",
    )
    engine = _FakeEngine(_default_script)
    repo = build_job_repository(
        agent_id="a1",
        jobs_path="x/jobs.json",
        engine=engine,
    )
    assert isinstance(repo, PgJobRepository)


@pytest.mark.asyncio
async def test_build_backend_pg_degrades_without_dsn(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qwenpaw.db.write_gateway.resolve_storage_backend",
        lambda: "pg",
    )

    def _raise():
        raise ConfigurationException(
            message="no dsn",
            config_key="QWENPAW_PG_DSN",
        )

    monkeypatch.setattr(
        "qwenpaw.db.engine.create_pg_engine",
        _raise,
    )
    jobs_path = tmp_path / "jobs.json"
    repo = build_job_repository(agent_id="a1", jobs_path=str(jobs_path))
    # 服务不能因 PG 缺席而起不来：降级 json 仓库
    assert isinstance(repo, JsonJobRepository)


# ---------------------------------------------------------------------------
# load / backfill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initialize_backfills_empty_plane_from_legacy(tmp_path):
    legacy = JobsFile(
        version=2,
        jobs=[make_cron_job_spec(job_id="j1")],
    )
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(legacy.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )

    engine = _FakeEngine(_default_script)
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=jobs_path,
        engine=engine,
    )
    # load 永远纯读：不隐式触发 backfill
    assert (await repo.load()).jobs == []

    # 启动钩子显式迁移：导入 legacy 条目 + 把文件重写为空平面
    await repo.initialize()

    inserts = [
        params
        for conn in engine.conns
        for sql, params in conn.calls
        if "INSERT INTO cron_jobs" in sql
    ]
    assert len(inserts) == 1
    assert inserts[0]["jid"] == "j1"
    assert inserts[0]["enabled"] is True
    # backfill 后 legacy 文件被重写为空平面，切断回灌链路
    rewritten = json.loads(jobs_path.read_text(encoding="utf-8"))
    assert rewritten["jobs"] == []


@pytest.mark.asyncio
async def test_delete_last_job_does_not_resurrect_from_projection(tmp_path):
    """删除最后一个任务后，投影缓存不得把数据回灌权威。"""
    jobs_path = tmp_path / "jobs.json"

    # 两个脚本化阶段：delete 时表非空；投影刷新时表空
    state = {"rows": 1}

    def script(sql: str, params):
        if "SELECT job_id, CAST(spec" in sql:
            return _FakeResult(rows=[])
        if "DELETE FROM cron_jobs" in sql:
            state["rows"] = 0
            return _FakeResult(rowcount=1)
        return _FakeResult()

    engine = _FakeEngine(script)
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=jobs_path,
        engine=engine,
    )
    # legacy 文件存在，但 initialize 后被清空为投影平面
    legacy = JobsFile(version=2, jobs=[make_cron_job_spec(job_id="j1")])
    jobs_path.write_text(
        json.dumps(legacy.model_dump(mode="json"), ensure_ascii=False),
        encoding="utf-8",
    )
    await repo.initialize()

    assert await repo.delete_job("j1") is True
    # 删除后运行期 load 纯读（表空、无 backfill 路径可走）
    loaded = await repo.load()
    assert loaded.jobs == []
    # 全程只有 initialize 阶段的那一次导入 INSERT
    inserts = [
        params
        for conn in engine.conns
        for sql, params in conn.calls
        if "INSERT INTO cron_jobs" in sql
    ]
    assert len(inserts) == 1


@pytest.mark.asyncio
async def test_load_serves_pg_rows_without_backfill(tmp_path):
    spec = make_cron_job_spec(job_id="j1", name="From PG")
    rows = [{"job_id": "j1", "spec": _dump_spec(spec)}]
    engine = _FakeEngine(lambda sql, params: _FakeResult(rows=rows))
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=tmp_path / "jobs.json",
        engine=engine,
    )
    loaded = await repo.load()

    assert len(loaded.jobs) == 1
    assert loaded.jobs[0].name == "From PG"
    # PG 平面非空：不触发 backfill INSERT
    assert not any(
        "INSERT INTO cron_jobs" in sql for sql, _ in engine.conns[0].calls
    )


@pytest.mark.asyncio
async def test_load_empty_without_legacy_file_returns_empty(tmp_path):
    engine = _FakeEngine(_default_script)
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=tmp_path / "missing.json",
        engine=engine,
    )
    loaded = await repo.load()
    assert loaded.jobs == []


# ---------------------------------------------------------------------------
# save：全量对齐决策（跳过同 hash / 更新异 hash / 删除多余）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_full_reconcile_branches(tmp_path):
    same = make_cron_job_spec(job_id="j1", name="Same")
    changed = make_cron_job_spec(job_id="j2", name="Changed")
    added = make_cron_job_spec(job_id="j3", name="Added")

    existing_rows = [
        {"job_id": "j1", "content_hash": _payload_hash(_dump_spec(same))},
        # j2 在库里是旧内容 hash（会被 UPDATE）
        {"job_id": "j2", "content_hash": "stale-hash"},
    ]
    engine = _FakeEngine(
        lambda sql, params: _FakeResult(rows=existing_rows),
    )
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=tmp_path / "jobs.json",
        engine=engine,
    )
    await repo.save(JobsFile(version=2, jobs=[same, changed, added]))

    upserts = [
        params
        for sql, params in engine.conns[0].calls
        if "INSERT INTO cron_jobs" in sql
    ]
    # 同 hash 的 j1 零写放大；j2（hash 变）与 j3（新增）各写一次
    assert sorted(p["jid"] for p in upserts) == ["j2", "j3"]

    deletes = [
        params
        for sql, params in engine.conns[0].calls
        if "DELETE FROM cron_jobs" in sql
    ]
    assert len(deletes) == 1
    # 库里残留、但本次 save 平面不含的 j2... 不对——j2 仍在平面内；
    # 被删除的应是库里有而平面没有的 job（此处无），ids 为平面全量
    assert deletes[0]["ids"] == ["j1", "j2", "j3"]


@pytest.mark.asyncio
async def test_save_projects_authoritative_plane_to_json(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    engine = _FakeEngine(_default_script)
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=jobs_path,
        engine=engine,
    )
    job = make_cron_job_spec(job_id="j1")
    await repo.save(JobsFile(version=2, jobs=[job]))

    projected = json.loads(jobs_path.read_text(encoding="utf-8"))
    assert [j["id"] for j in projected["jobs"]] == ["j1"]


# ---------------------------------------------------------------------------
# append_history：seq 分配、naive 时间归一、修剪窗口
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_history_allocates_seq_and_trims(tmp_path):
    engine = _FakeEngine(
        lambda sql, params: _FakeResult(first_row={"next_seq": 7}),
    )
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=tmp_path / "jobs.json",
        engine=engine,
    )
    # get_history 的读取路由：返回空历史
    engine._script = lambda sql, params: (
        _FakeResult()
        if "ORDER BY seq DESC" in sql
        else _FakeResult(first_row={"next_seq": 7})
    )

    record = make_execution_record(
        status="success",
        run_at=datetime(2030, 1, 1, 9, 0, 0),
    )
    await repo.append_history("j1", record, limit=50)

    calls = engine.conns[0].calls
    inserts = [
        params
        for sql, params in calls
        if "INSERT INTO cron_job_history" in sql
    ]
    assert len(inserts) == 1
    assert inserts[0]["seq"] == 7
    # naive run_at 被归一成 aware（TIMESTAMPTZ 安全写入）
    assert inserts[0]["run_at"].tzinfo is not None

    trims = [
        params
        for sql, params in calls
        if "DELETE FROM cron_job_history" in sql and "floor_seq" in params
    ]
    assert len(trims) == 1
    assert trims[0]["floor_seq"] == 7 - 50


@pytest.mark.asyncio
async def test_prune_orphan_history_deletes_outside_valid_ids(tmp_path):
    engine = _FakeEngine(_default_script)
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=tmp_path / "jobs.json",
        engine=engine,
    )
    await repo.prune_orphan_history(valid_job_ids={"b", "a"})

    deletes = [
        params
        for sql, params in engine.conns[0].calls
        if "DELETE FROM cron_job_history" in sql
    ]
    assert len(deletes) == 1
    assert deletes[0]["ids"] == ["a", "b"]


@pytest.mark.asyncio
async def test_prune_with_empty_valid_set_deletes_all_orphans(tmp_path):
    engine = _FakeEngine(_default_script)
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=tmp_path / "jobs.json",
        engine=engine,
    )
    # 空集合：`<> ALL('{}')` 恒真 → 清空该 agent 全部孤儿历史
    await repo.prune_orphan_history(valid_job_ids=set())

    deletes = [
        params
        for sql, params in engine.conns[0].calls
        if "DELETE FROM cron_job_history" in sql
    ]
    assert deletes[0]["ids"] == []


# ---------------------------------------------------------------------------
# delete_job：删除成功后刷新投影
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_job_reports_and_projects(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    engine = _FakeEngine(lambda sql, params: _FakeResult(rowcount=1))
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=jobs_path,
        engine=engine,
    )
    assert await repo.delete_job("j1") is True
    # 投影缓存被刷新为当前权威平面（空）
    projected = json.loads(jobs_path.read_text(encoding="utf-8"))
    assert projected["jobs"] == []


@pytest.mark.asyncio
async def test_delete_job_missing_returns_false(tmp_path):
    engine = _FakeEngine(lambda sql, params: _FakeResult(rowcount=0))
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=tmp_path / "jobs.json",
        engine=engine,
    )
    assert await repo.delete_job("ghost") is False


# ---------------------------------------------------------------------------
# projection failures never propagate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_projection_failure_is_swallowed(tmp_path, monkeypatch):
    jobs_path = tmp_path / "jobs.json"
    engine = _FakeEngine(_default_script)
    repo = PgJobRepository(
        agent_id="a1",
        jobs_path=jobs_path,
        engine=engine,
    )

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(
        "qwenpaw.utils.io_utils.write_json_atomic",
        _boom,
    )
    # 投影失败只告警，不阻塞权威写入路径
    await repo.save(JobsFile(version=2, jobs=[make_cron_job_spec()]))
    assert not jobs_path.exists()
