# -*- coding: utf-8 -*-
"""T8 审计接线守护：KB 生命周期 / 本体 / 绑定管理面写路径的审计 spy。

不启 app、不走 RBAC 中间件：直接调端点函数，服务层与存储层全部打桩，
只验证「写成功后审计行确实落、失败/幂等重放不落」的接线契约。

@author qingfeng
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app import write_audit
from qwenpaw.app.ontology import api as ontology_api
from qwenpaw.app.ontology import service as ontology_service
from qwenpaw.app.ontology.models import (
    KbObjectLink,
    OntologyObject,
    OntologyRelation,
)
from qwenpaw.app.routers import agents as agents_router
from qwenpaw.app.routers.admin import expert_teams as admin_teams
from qwenpaw.app.routers.admin import kb as admin_kb
from qwenpaw.app.routers.agents import KbBindingBody
from qwenpaw.app.routers.admin.kb import AdminMetaBody, AdminReviewBody


class _AuditSpy:
    """审计后端替身：记录 record 入参。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, workspace_dir, tc_spec, decision) -> None:
        self.calls.append(
            {
                "tool_name": tc_spec.tool_name,
                "target": tc_spec.target,
                "actor_id": tc_spec.user_id,
                "raw_params": tc_spec.raw_params,
            },
        )


@pytest.fixture()
def audit_spy(monkeypatch):
    """注入替身审计后端（write_audit._audit_log 工厂）。"""
    spy = _AuditSpy()
    monkeypatch.setattr(write_audit, "_audit_log", lambda: spy)
    return spy


# ------------------------------------------------------------------
# admin KB：生命周期 / meta / 冲突
# ------------------------------------------------------------------


def test_admin_kb_review_audits_lifecycle(audit_spy, monkeypatch):
    """review 写成功后落 kb_review 审计行（actor=审核人）。"""

    class _FakeSvc:
        def pg_ready(self):
            return True

        def pg_review_document(self, kb_id, doc_id, action, reviewer, comment):
            return SimpleNamespace(
                id=doc_id,
                space_id=kb_id,
                knowledge_status="published",
                reviewed_by=reviewer,
                review_note=comment,
            )

    monkeypatch.setattr(admin_kb, "get_kb_service", lambda: _FakeSvc())
    body = AdminReviewBody(action="approve", comment="ok", reviewer="alice")
    out = admin_kb.admin_review_document("kb1", "doc1", body)
    assert out["knowledge_status"] == "published"
    assert len(audit_spy.calls) == 1
    call = audit_spy.calls[0]
    assert call["tool_name"] == "kb_review"
    assert call["target"] == "kb1:doc1"
    assert call["actor_id"] == "alice"
    assert call["raw_params"]["after"]["action"] == "approve"


def test_admin_kb_review_404_no_audit(audit_spy, monkeypatch):
    """404 路径不留审计行（没有发生的写不留痕）。"""

    class _FakeSvc:
        def pg_ready(self):
            return True

        def pg_review_document(self, *a, **k):
            return None

    monkeypatch.setattr(admin_kb, "get_kb_service", lambda: _FakeSvc())
    with pytest.raises(Exception):
        admin_kb.admin_review_document(
            "kb1",
            "doc1",
            AdminReviewBody(action="approve"),
        )
    assert audit_spy.calls == []


def test_admin_kb_meta_audits_before_after(audit_spy, monkeypatch):
    """meta 更新审计携带更新前字段快照与提交字段。"""
    prev = SimpleNamespace(
        domain="old-domain",
        doc_type="faq",
        confidence=0.5,
        valid_from=None,
        valid_to=None,
    )

    class _FakeSvc:
        def pg_ready(self):
            return True

        def pg_document_detail(self, kb_id, doc_id):
            return prev, None

        def pg_update_knowledge_meta(self, doc_id, **fields):
            return True

    monkeypatch.setattr(admin_kb, "get_kb_service", lambda: _FakeSvc())
    admin_kb.admin_update_document_meta(
        "kb1",
        "doc1",
        AdminMetaBody(domain="new-domain"),
    )
    call = audit_spy.calls[0]
    assert call["tool_name"] == "kb_doc_meta.update"
    assert call["raw_params"]["before"] == {"domain": "old-domain"}
    assert call["raw_params"]["after"] == {"domain": "new-domain"}


def test_admin_kb_resolve_conflict_audits(audit_spy, monkeypatch):
    """冲突裁决落 kb_conflict.resolve 审计行。"""

    class _FakeSvc:
        def pg_resolve_conflict(self, conflict_id, resolver):
            return True

    monkeypatch.setattr(admin_kb, "get_kb_service", lambda: _FakeSvc())
    admin_kb.admin_resolve_conflict("kb1", "cft1")
    call = audit_spy.calls[0]
    assert call["tool_name"] == "kb_conflict.resolve"
    assert call["target"] == "cft1"


# ------------------------------------------------------------------
# ontology：对象 / 关系 / 互引
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ontology_create_object_audits(audit_spy, monkeypatch):
    """对象新建落 ontology.object.create 审计行。"""
    obj = OntologyObject(id="obj1", type_id="t1", name="A", owner_id="bob")

    async def _fake_create(payload, store=None):
        return obj

    monkeypatch.setattr(ontology_service, "create_object", _fake_create)
    await ontology_api.create_object(obj)
    call = audit_spy.calls[0]
    assert call["tool_name"] == "ontology.object.create"
    assert call["target"] == "obj1"
    assert call["actor_id"] == "bob"


@pytest.mark.asyncio
async def test_ontology_update_object_audits(audit_spy, monkeypatch):
    """对象更新审计携带更新前快照与提交字段清单。"""
    prev = OntologyObject(id="obj1", type_id="t1", name="A", state="draft")
    updated = OntologyObject(id="obj1", type_id="t1", name="A", state="live")

    async def _fake_get(object_id, store=None):
        return prev

    async def _fake_update(object_id, fields, store=None):
        return updated

    monkeypatch.setattr(ontology_service, "get_object", _fake_get)
    monkeypatch.setattr(ontology_service, "update_object", _fake_update)
    await ontology_api.update_object("obj1", {"state": "live"})
    call = audit_spy.calls[0]
    assert call["tool_name"] == "ontology.object.update"
    assert call["raw_params"]["before"]["state"] == "draft"
    assert call["raw_params"]["after"]["fields"] == ["state"]
    assert call["raw_params"]["after"]["state"] == "live"


@pytest.mark.asyncio
async def test_ontology_delete_relation_audits(audit_spy, monkeypatch):
    """关系删除：真删行才记审计，幂等重放（False）不记。"""

    async def _fake_del(relation_id, store=None):
        return True

    monkeypatch.setattr(ontology_service, "delete_relation", _fake_del)
    await ontology_api.delete_relation("rel1")
    assert len(audit_spy.calls) == 1

    async def _fake_del_miss(relation_id, store=None):
        return False

    monkeypatch.setattr(ontology_service, "delete_relation", _fake_del_miss)
    await ontology_api.delete_relation("rel1")
    assert len(audit_spy.calls) == 1


@pytest.mark.asyncio
async def test_ontology_create_link_audits(audit_spy, monkeypatch):
    """知识↔本体互引新建落 ontology.link.create 审计行。"""
    link = KbObjectLink(
        id="lnk1",
        kb_space_id="kb1",
        kb_document_id="doc1",
        object_type="product",
        object_id="obj1",
    )

    async def _fake_create(payload, store=None):
        return link

    monkeypatch.setattr(ontology_service, "create_link", _fake_create)
    await ontology_api.create_link(link)
    call = audit_spy.calls[0]
    assert call["tool_name"] == "ontology.link.create"
    assert call["raw_params"]["after"]["kb_document_id"] == "doc1"


# ------------------------------------------------------------------
# 绑定管理面：agent 主体 / team 主体
# ------------------------------------------------------------------


class _FakeRequest:
    """最小 request 替身（仅 state.user）。"""

    def __init__(self, user: str) -> None:
        self.state = SimpleNamespace(user=user)


@pytest.mark.asyncio
async def test_agent_bind_endpoint_audits(audit_spy, monkeypatch):
    """agent 绑定写成功落 agent_kb.binding.bind 审计行（actor=操作者）。"""
    row = {"space_id": "kb1", "space_name": "Demo", "scope": "personal"}
    # 有状态绑定表：写前空、bind 后入行（写后读回才能取到真实行）
    table: list[dict] = []

    async def _fake_can_manage(space_id, username, **kwargs):
        return True

    async def _fake_list(agent_id, principal_type=None):
        return list(table)

    async def _fake_bind(**kwargs):
        table.append(row)
        return True

    monkeypatch.setattr(
        agents_router.kb_bindings,
        "can_manage_space",
        _fake_can_manage,
    )
    monkeypatch.setattr(agents_router.kb_bindings, "list_bindings", _fake_list)
    monkeypatch.setattr(agents_router.kb_bindings, "bind_agent_kb", _fake_bind)
    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        lambda agent_id: SimpleNamespace(name="A"),
    )
    out = await agents_router.bind_agent_kb_endpoint(
        _FakeRequest("admin"),
        KbBindingBody(space_id="kb1"),
        "agent1",
    )
    assert out.status_code == 201
    call = audit_spy.calls[0]
    assert call["tool_name"] == "agent_kb.binding.bind"
    assert call["target"] == "agent1:kb1"
    assert call["actor_id"] == "admin"


@pytest.mark.asyncio
async def test_agent_unbind_endpoint_audits(audit_spy, monkeypatch):
    """agent 解绑落 agent_kb.binding.unbind 审计行。"""

    async def _fake_can_manage(space_id, username, **kwargs):
        return True

    async def _fake_unbind(agent_id, space_id, **kwargs):
        return True

    monkeypatch.setattr(
        agents_router.kb_bindings,
        "can_manage_space",
        _fake_can_manage,
    )
    monkeypatch.setattr(
        agents_router.kb_bindings,
        "unbind_agent_kb",
        _fake_unbind,
    )
    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        lambda agent_id: SimpleNamespace(name="A"),
    )
    await agents_router.unbind_agent_kb_endpoint(
        _FakeRequest("alice"),
        "agent1",
        "kb1",
    )
    call = audit_spy.calls[0]
    assert call["tool_name"] == "agent_kb.binding.unbind"
    assert call["target"] == "agent1:kb1"
    assert call["actor_id"] == "alice"


@pytest.mark.asyncio
async def test_team_unbind_endpoint_audits(audit_spy, monkeypatch):
    """团队主体解绑落 team_kb.binding.unbind 审计行（target=team_ 形态）。"""

    class _FakeStore:
        async def get_team(self, team_id):
            return SimpleNamespace(id=team_id, name="T")

    monkeypatch.setattr(admin_teams, "get_expert_store", lambda: _FakeStore())

    async def _fake_unbind(agent_id, space_id, **kwargs):
        return True

    monkeypatch.setattr(
        admin_teams.kb_bindings,
        "unbind_agent_kb",
        _fake_unbind,
    )
    await admin_teams.unbind_team_kb("team1", "kb1", _FakeRequest("admin"))
    call = audit_spy.calls[0]
    assert call["tool_name"] == "team_kb.binding.unbind"
    assert call["target"] == "team_team1:kb1"
