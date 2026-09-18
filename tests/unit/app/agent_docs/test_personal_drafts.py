# -*- coding: utf-8 -*-
"""Unit tests for the personal-draft plane of ``agent_documents`` (T11).

覆盖三层：
- ``annotate_draft_status`` 纯函数：待应用判定必须用内容 hash 比对，
  避免「草稿行存在 = 未应用」的错误信号（apply 后草稿保留为工作副本）；
- store 写路径：个人草稿固定 draft 环境、owner 参数化、不写 revision；
- store 读路径：共享读必须过滤 owner IS NULL（绝不读到他人草稿）、
  列表按 owner 维度收敛。
"""
# pylint: disable=protected-access
from __future__ import annotations

import pytest

from qwenpaw.app.agent_docs.store import (
    AgentDocsStore,
    annotate_draft_status,
    content_hash,
)


class _FakeMappingResult:
    """RETURNING/SELECT 行结果（mappings() 协议）。"""

    def __init__(self, row: dict | None, rows: list | None = None) -> None:
        self._row = row
        self._rows = (
            rows if rows is not None else ([] if row is None else [row])
        )

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

    def __init__(self, unchanged: bool = False, version: int = 1) -> None:
        self.statements: list[tuple[str, dict]] = []
        self._unchanged = unchanged
        self._version = version

    async def execute(self, sql, params):
        self.statements.append((str(sql), dict(params)))
        if "RETURNING version" in str(sql):
            if self._unchanged:
                return _FakeMappingResult(None)
            return _FakeMappingResult({"version": self._version})
        if "SELECT" in str(sql):
            return _FakeMappingResult(None, rows=[])
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


# ---------------------------------------------------------------------------
# annotate_draft_status：待应用 = 与共享行内容分叉
# ---------------------------------------------------------------------------


def test_annotate_marks_diverged_draft_unapplied() -> None:
    drafts = [
        {"doc_type": "profile", "content_hash": content_hash("# draft")},
    ]
    shared = [
        {"doc_type": "profile", "content_hash": content_hash("# shared")},
    ]
    annotated = annotate_draft_status(drafts, shared)
    assert annotated[0]["unapplied"] is True


def test_annotate_same_content_not_unapplied() -> None:
    """apply 后草稿行保留且内容与共享一致：不得再报「未应用」。"""
    same = content_hash("# same")
    annotated = annotate_draft_status(
        [{"doc_type": "profile", "content_hash": same}],
        [{"doc_type": "profile", "content_hash": same}],
    )
    assert annotated[0]["unapplied"] is False


def test_annotate_missing_shared_row_is_unapplied() -> None:
    """共享行缺失（从未发布）：无物可比，视为待应用。"""
    annotated = annotate_draft_status(
        [{"doc_type": "soul", "content_hash": content_hash("# s")}],
        [],
    )
    assert annotated[0]["unapplied"] is True


def test_annotate_keeps_original_fields() -> None:
    draft = {
        "doc_type": "agents",
        "content_hash": content_hash("# a"),
        "owner_user_id": "alice",
        "version": "2",
    }
    annotated = annotate_draft_status([draft], [])
    assert annotated[0]["owner_user_id"] == "alice"
    assert annotated[0]["version"] == "2"


# ---------------------------------------------------------------------------
# store 写路径：个人草稿固定 draft 环境 + 不写 revision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_personal_draft_forces_draft_env_no_revision() -> None:
    engine = _FakeEngine(version=2)
    store = AgentDocsStore(engine=engine)
    written = await store.upsert_document(
        "expert_sales",
        "profile",
        "# my draft",
        owner_user_id="alice",
        updated_by="alice",
    )
    assert written is True
    # 单条语句：个人草稿不写 revision 快照（快照链仅属于共享发布闸门）
    assert len(engine.conn.statements) == 1
    sql, params = engine.conn.statements[0]
    assert "owner_user_id" in sql
    assert params["owner"] == "alice"
    # 正式 agent_id（无 __draft 后缀）也固定 draft 环境承载个人草稿
    assert params["env"] == "draft"
    assert params["uby"] == "alice"


@pytest.mark.asyncio
async def test_upsert_shared_document_still_snapshots_revision() -> None:
    engine = _FakeEngine(version=3)
    store = AgentDocsStore(engine=engine)
    written = await store.upsert_document(
        "expert_sales",
        "profile",
        "# shared",
    )
    assert written is True
    # 共享写三步：upsert + 快照 + 保留窗口清理（行为不变）
    assert len(engine.conn.statements) == 3
    _, params = engine.conn.statements[0]
    assert params["env"] == "production"
    assert params["owner"] is None


# ---------------------------------------------------------------------------
# store 读路径：共享读过滤 owner，草稿读收敛到本人
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_shared_document_filters_owner_null() -> None:
    engine = _FakeEngine()
    store = AgentDocsStore(engine=engine)
    await store.get_document("expert_sales", "profile")
    sql, params = engine.conn.statements[0]
    # 绝不读到他人个人草稿：共享读带 owner IS NOT DISTINCT FROM NULL
    assert "owner_user_id IS NOT DISTINCT FROM :owner" in sql
    assert params["owner"] is None
    assert params["env"] == "production"


@pytest.mark.asyncio
async def test_get_personal_draft_defaults_env_draft() -> None:
    engine = _FakeEngine()
    store = AgentDocsStore(engine=engine)
    await store.get_document(
        "expert_sales",
        "profile",
        owner_user_id="alice",
    )
    sql, params = engine.conn.statements[0]
    assert params["owner"] == "alice"
    assert params["env"] == "draft"


@pytest.mark.asyncio
async def test_list_documents_filters_owner() -> None:
    engine = _FakeEngine()
    store = AgentDocsStore(engine=engine)
    await store.list_documents("expert_sales")
    sql, params = engine.conn.statements[0]
    assert "owner_user_id IS NOT DISTINCT FROM :owner" in sql
    assert params["owner"] is None


@pytest.mark.asyncio
async def test_list_personal_drafts_all_and_single_owner() -> None:
    engine = _FakeEngine()
    store = AgentDocsStore(engine=engine)
    # 全部用户（admin 待应用列表）
    await store.list_personal_drafts("expert_sales")
    sql_all, params_all = engine.conn.statements[0]
    assert "owner_user_id IS NOT NULL" in sql_all
    assert "AND owner_user_id = :owner" not in sql_all
    assert "environment = 'draft'" in sql_all
    assert "ORDER BY updated_at DESC" in sql_all
    assert params_all["owner"] is None
    # 单用户（我的草稿）
    await store.list_personal_drafts("expert_sales", owner_user_id="alice")
    sql_one, params_one = engine.conn.statements[1]
    assert "AND owner_user_id = :owner" in sql_one
    assert params_one["owner"] == "alice"
