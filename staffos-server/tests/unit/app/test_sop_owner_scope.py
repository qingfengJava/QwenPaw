# -*- coding: utf-8 -*-
"""Unit tests: SOP 归属可见性与写守卫（无 PG / fake store 注入）。

覆盖 T10 个人 SOP 补漏的三组纪律：
- 列表可见性：无 owner 过滤的跨员工视图仅 production 行（个人 draft
  仅 owner、production 全员）；传 owner_id 时双环境合并草稿优先；
  显式 environment 时单环境行直通；
- AI 工具归属守卫：``sop_update_draft`` / ``sop_publish_draft`` 跨
  owner 一律拒绝，owner 匹配或存量无归属行放行；
- 归属解析兜底：``_resolve_owner_department`` 员工治理 / 用户名回落
  两路解析，无 PG / 解析失败静默 None，绝不阻断写主链路。

@author qingfeng
"""

from __future__ import annotations

import pytest
from agentscope.message import ToolResultState


def _row(
    sop_id: str,
    *,
    owner: str = "",
    environment: str = "production",
    department_id: str | None = None,
):
    """构造一条 SopRecord（仅测试所需字段）。"""
    from qwenpaw.app.experts.models import SopRecord

    return SopRecord(
        id=sop_id,
        name=sop_id,
        owner_id=owner or None,
        environment=environment,
        department_id=department_id,
    )


class _FakeSopStore:
    """按环境分桶返回预置行并记录每次 list_sops 调用的 fake store。"""

    def __init__(self, rows: dict[str, list]):
        self._rows = rows
        self.calls: list[dict] = []

    async def list_sops(
        self,
        status: str = "",
        owner_id: str = "",
        q: str = "",
        full: bool = False,
        environment: str = "",
    ) -> list:
        self.calls.append(
            {
                "status": status,
                "owner_id": owner_id,
                "q": q,
                "full": full,
                "environment": environment,
            },
        )
        return list(self._rows.get(environment, []))


# ---------------------------------------------------------------------------
# 列表可见性（GET /admin/sops 分视图规则）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sops_unscoped_returns_production_only(monkeypatch):
    """无 owner 过滤（跨员工视图）→ 仅 production 行，草稿不外泄。"""
    from qwenpaw.app.routers.admin import expert_capability as mod

    store = _FakeSopStore(
        {
            "draft": [_row("s1", environment="draft")],
            "production": [_row("s1"), _row("s2")],
        },
    )
    monkeypatch.setattr(mod, "get_sop_store", lambda: store)

    result = await mod.list_sops()

    # 仅查 production 一次，且草稿行不出现
    assert [c["environment"] for c in store.calls] == ["production"]
    assert [r.id for r in result] == ["s1", "s2"]
    assert all(r.environment == "production" for r in result)


@pytest.mark.asyncio
async def test_list_sops_owner_scoped_merges_draft_first(monkeypatch):
    """传 owner_id（员工工作集）→ 双环境合并，同 id 草稿优先。"""
    from qwenpaw.app.routers.admin import expert_capability as mod

    store = _FakeSopStore(
        {
            "draft": [_row("s1", owner="eng", environment="draft")],
            "production": [
                _row("s1", owner="eng"),
                _row("s2", owner="eng"),
            ],
        },
    )
    monkeypatch.setattr(mod, "get_sop_store", lambda: store)

    result = await mod.list_sops(owner_id="eng", full=True)

    assert [c["environment"] for c in store.calls] == [
        "draft",
        "production",
    ]
    assert all(c["owner_id"] == "eng" for c in store.calls)
    by_id = {r.id: r.environment for r in result}
    assert by_id == {"s1": "draft", "s2": "production"}


@pytest.mark.asyncio
async def test_list_sops_explicit_environment_passthrough(monkeypatch):
    """显式 environment → 单环境行直通（不合并、不加视图规则）。"""
    from qwenpaw.app.routers.admin import expert_capability as mod

    store = _FakeSopStore({"draft": [_row("s1", environment="draft")]})
    monkeypatch.setattr(mod, "get_sop_store", lambda: store)

    result = await mod.list_sops(owner_id="eng", environment="draft")

    assert [c["environment"] for c in store.calls] == ["draft"]
    assert [r.id for r in result] == ["s1"]


# ---------------------------------------------------------------------------
# AI 工具归属守卫（个人 draft 仅 owner 员工可改/可发）
# ---------------------------------------------------------------------------


class _FakeToolStore:
    """minimal SopStore 替身：按环境返回预置行并记录写调用。"""

    def __init__(self, *, draft=None, production=None):
        self.draft = draft
        self.production = production
        self.updated: list[tuple] = []
        self.promoted: list[tuple] = []

    async def get_sop(self, sop_id: str, environment: str = "production"):
        if environment == "draft":
            return self.draft
        return self.production

    async def update_sop(self, sop_id: str, environment: str = "", **fields):
        self.updated.append((sop_id, environment, fields))
        return self.draft

    async def promote_sop(
        self,
        sop_id: str,
        published_by: str = "",
        change_note: str = "",
    ):
        self.promoted.append((sop_id, published_by, change_note))
        return self.draft or self.production


def _enter_agent(agent_id: str):
    """设置当前 agent 上下文并返回 reset token（用例结束还原）。"""
    from qwenpaw.app import agent_context

    return agent_context._current_agent_id.set(agent_id)  # noqa: SLF001


def _exit_agent(token) -> None:
    from qwenpaw.app import agent_context

    agent_context._current_agent_id.reset(token)  # noqa: SLF001


@pytest.mark.asyncio
async def test_update_draft_rejects_cross_owner(monkeypatch):
    """跨员工改草稿：拒绝且不触发任何写调用。"""
    from qwenpaw.agents.tools import sop_ops

    store = _FakeToolStore(
        draft=_row("s1", owner="beta", environment="draft"),
    )
    monkeypatch.setattr(sop_ops, "get_sop_store", lambda: store)

    token = _enter_agent("expert_alpha")
    try:
        chunk = await sop_ops.sop_update_draft(sop_id="s1", goal="x")
    finally:
        _exit_agent(token)

    assert chunk.state == ToolResultState.ERROR
    assert "private to another expert" in chunk.content[0].text
    assert store.updated == []


@pytest.mark.asyncio
async def test_update_draft_allows_owner_and_unowned(monkeypatch):
    """owner 匹配与存量无归属行放行（写调用正常发生）。"""
    from qwenpaw.agents.tools import sop_ops

    for owner in ("alpha", ""):
        store = _FakeToolStore(
            draft=_row("s1", owner=owner, environment="draft"),
        )
        monkeypatch.setattr(sop_ops, "get_sop_store", lambda: store)

        token = _enter_agent("expert_alpha")
        try:
            chunk = await sop_ops.sop_update_draft(sop_id="s1", goal="x")
        finally:
            _exit_agent(token)

        assert chunk.state == ToolResultState.SUCCESS
        assert store.updated[0][0] == "s1"
        assert store.updated[0][1] == "draft"


@pytest.mark.asyncio
async def test_update_draft_missing_row_reports_not_found(monkeypatch):
    """无草稿行：报错文案保持原语义（create it first）。"""
    from qwenpaw.agents.tools import sop_ops

    store = _FakeToolStore()
    monkeypatch.setattr(sop_ops, "get_sop_store", lambda: store)

    token = _enter_agent("expert_alpha")
    try:
        chunk = await sop_ops.sop_update_draft(sop_id="missing", goal="x")
    finally:
        _exit_agent(token)

    assert chunk.state == ToolResultState.ERROR
    assert "create it first via sop_create_draft" in chunk.content[0].text
    assert store.updated == []


@pytest.mark.asyncio
async def test_publish_draft_rejects_cross_owner(monkeypatch):
    """跨员工发布草稿：拒绝且不触发 promote。"""
    from qwenpaw.agents.tools import sop_ops

    store = _FakeToolStore(
        draft=_row("s1", owner="beta", environment="draft"),
    )
    monkeypatch.setattr(sop_ops, "get_sop_store", lambda: store)

    token = _enter_agent("expert_alpha")
    try:
        chunk = await sop_ops.sop_publish_draft(sop_id="s1")
    finally:
        _exit_agent(token)

    assert chunk.state == ToolResultState.ERROR
    assert "private to another expert" in chunk.content[0].text
    assert store.promoted == []


@pytest.mark.asyncio
async def test_publish_draft_guard_falls_back_to_production_row(monkeypatch):
    """存量 production-only 行：草稿缺失时用线上行做归属守卫。"""
    from qwenpaw.agents.tools import sop_ops

    store = _FakeToolStore(
        production=_row("s1", owner="beta"),
    )
    monkeypatch.setattr(sop_ops, "get_sop_store", lambda: store)

    token = _enter_agent("expert_alpha")
    try:
        chunk = await sop_ops.sop_publish_draft(sop_id="s1")
    finally:
        _exit_agent(token)

    assert chunk.state == ToolResultState.ERROR
    assert "private to another expert" in chunk.content[0].text
    assert store.promoted == []


@pytest.mark.asyncio
async def test_publish_draft_allows_owner(monkeypatch):
    """归属匹配：正常 promote 并以归属员工记 published_by。"""
    from qwenpaw.agents.tools import sop_ops

    store = _FakeToolStore(
        draft=_row("s1", owner="alpha", environment="draft"),
    )
    monkeypatch.setattr(sop_ops, "get_sop_store", lambda: store)

    # 发布成功后工具会调用真实 capability store 绑定员工：
    # 替换为 fake，避免本机 PG 环境被写入垃圾绑定行
    bound: list[tuple] = []

    class _FakeCapabilityStore:
        async def ensure_binding(
            self,
            expert_id,
            resource_type,
            resource_id,
            metadata=None,
        ):
            bound.append((expert_id, resource_type, resource_id))

    monkeypatch.setattr(
        "qwenpaw.app.experts.capability.get_capability_store",
        lambda: _FakeCapabilityStore(),
    )

    token = _enter_agent("expert_alpha")
    try:
        chunk = await sop_ops.sop_publish_draft(sop_id="s1")
    finally:
        _exit_agent(token)

    assert chunk.state == ToolResultState.SUCCESS
    assert store.promoted[0][0] == "s1"
    assert store.promoted[0][1] == "alpha"
    assert bound == [("alpha", "sop", "s1")]


# ---------------------------------------------------------------------------
# 归属解析兜底（_resolve_owner_department）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_owner_department_empty_owner_returns_none():
    """owner 为空：零查询直接 None。"""
    from qwenpaw.app.experts import sops

    assert await sops._resolve_owner_department(None) is None  # noqa: SLF001
    assert await sops._resolve_owner_department("") is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_resolve_owner_department_employee_governance_path(
    monkeypatch,
):
    """员工 owner：治理归属部门 id → 经 org 目录换 path 返回。"""
    from types import SimpleNamespace

    from qwenpaw.app.experts import sops

    class _Store:
        async def get(self, agent_id):
            assert agent_id == "expert_ex1"
            return SimpleNamespace(department_id="dept_a")

    class _Org:
        async def list_departments(self):
            return [SimpleNamespace(id="dept_a", path="dept_a/dept_b")]

        async def resolve_user_scope(self, owner):  # pragma: no cover
            raise AssertionError("治理命中时不应走到用户名回落")

    monkeypatch.setattr(
        "qwenpaw.app.employees.store.get_employee_governance_store",
        lambda: _Store(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.orgs.service.get_org_service",
        lambda: _Org(),
    )

    resolved = await sops._resolve_owner_department("ex1")  # noqa: SLF001
    assert resolved == "dept_a/dept_b"


@pytest.mark.asyncio
async def test_resolve_owner_department_username_fallback(monkeypatch):
    """治理缺行：回落按用户名部门成员解析（SOP 直属用户场景）。"""
    from qwenpaw.app.experts import sops

    class _Store:
        async def get(self, agent_id):
            return None

    class _Org:
        async def list_departments(self):
            return []

        async def resolve_user_scope(self, owner):
            assert owner == "zhangsan"
            return ("default", "dept_x/dept_y")

    monkeypatch.setattr(
        "qwenpaw.app.employees.store.get_employee_governance_store",
        lambda: _Store(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.orgs.service.get_org_service",
        lambda: _Org(),
    )

    resolved = await sops._resolve_owner_department("zhangsan")  # noqa: SLF001
    assert resolved == "dept_x/dept_y"


@pytest.mark.asyncio
async def test_resolve_owner_department_failure_returns_none(monkeypatch):
    """无 PG / 解析失败：静默 None，绝不抛（写主链路不受阻）。"""
    from qwenpaw.app.experts import sops

    class _RaisingStore:
        async def get(self, agent_id):
            raise RuntimeError("pg unavailable")

    monkeypatch.setattr(
        "qwenpaw.app.employees.store.get_employee_governance_store",
        lambda: _RaisingStore(),
    )

    resolved = await sops._resolve_owner_department("somebody")  # noqa: SLF001
    assert resolved is None
