# -*- coding: utf-8 -*-
"""Unit tests for the admin personal-draft gate endpoints (T11).

覆盖 ``/admin/experts/{id}/documents/personal-drafts`` 列表与 apply 的
编排逻辑：参数校验（400）、无 PG（503/可用性空态）、草稿不存在（404）、
promote 调用与物化降级（无工作区不报错）。
"""
# pylint: disable=protected-access
from __future__ import annotations

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers.admin import experts as experts_mod


class _FakeDocs:
    """最小 AgentDocsStore 替身：只实现端点消费的方法。"""

    def __init__(self, draft=None, drafts=None, shared=None) -> None:
        self._draft = draft
        self._drafts = drafts or []
        self._shared = shared or []
        self.promoted: list[tuple] = []

    async def get_document(
        self,
        agent_id: str,
        doc_type: str,
        *,
        environment=None,
        owner_user_id=None,
    ):
        return self._draft

    async def promote(
        self,
        agent_id: str,
        doc_type: str,
        content: str,
        *,
        environment: str = "production",
        updated_by=None,
    ):
        self.promoted.append((agent_id, doc_type, content, updated_by))
        return 5

    async def list_personal_drafts(self, agent_id: str, *, owner_user_id=None):
        return self._drafts

    async def list_documents(self, agent_id: str, *, environment=None):
        return self._shared


class _FakeExpertStore:
    def __init__(self, expert=object()) -> None:
        self._expert = expert

    async def get_expert(self, expert_id: str):
        return self._expert


async def test_apply_personal_draft_rejects_unknown_doc_type() -> None:
    with pytest.raises(HTTPException) as excinfo:
        await experts_mod.apply_personal_draft(
            "captest_e1",
            "alice",
            {"doc_type": "bogus"},
        )
    assert excinfo.value.status_code == 400


async def test_apply_personal_draft_requires_pg(monkeypatch) -> None:
    monkeypatch.setattr(experts_mod, "get_agent_docs_store", lambda: None)
    with pytest.raises(HTTPException) as excinfo:
        await experts_mod.apply_personal_draft(
            "captest_e1",
            "alice",
            {"doc_type": "profile"},
        )
    assert excinfo.value.status_code == 503


async def test_apply_personal_draft_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        experts_mod,
        "get_agent_docs_store",
        lambda: _FakeDocs(draft=None),
    )
    with pytest.raises(HTTPException) as excinfo:
        await experts_mod.apply_personal_draft(
            "captest_e1",
            "alice",
            {"doc_type": "profile"},
        )
    assert excinfo.value.status_code == 404


async def test_apply_personal_draft_promotes_and_reports(
    monkeypatch,
    tmp_path,
) -> None:
    fake = _FakeDocs(draft={"content": "# alice draft"})
    monkeypatch.setattr(experts_mod, "get_agent_docs_store", lambda: fake)
    # 工作区不存在（未发布专家）：物化降级为 False，不阻断 apply
    monkeypatch.setattr(
        experts_mod,
        "_expert_workspace_dir",
        lambda _expert_id: tmp_path / "no-such-workspace",
    )
    result = await experts_mod.apply_personal_draft(
        "captest_e1",
        "alice",
        {"doc_type": "profile"},
    )
    assert result["expert_id"] == "captest_e1"
    assert result["owner_user_id"] == "alice"
    assert result["version"] == 5
    assert result["materialized"] is False
    # apply = 草稿内容 promote 到共享行（agent_id=expert_{id}）
    assert fake.promoted == [
        ("expert_captest_e1", "profile", "# alice draft", "apply:alice:admin"),
    ]


async def test_list_personal_drafts_filters_unapplied(monkeypatch) -> None:
    """列表仅返回与共享行分叉的草稿（内容比对，非「行存在」）。"""
    fake = _FakeDocs(
        drafts=[
            {
                "doc_type": "profile",
                "owner_user_id": "alice",
                "content_hash": "a",
            },
            {"doc_type": "soul", "owner_user_id": "bob", "content_hash": "s"},
        ],
        shared=[
            {"doc_type": "profile", "content_hash": "x"},
            {"doc_type": "soul", "content_hash": "s"},
        ],
    )
    monkeypatch.setattr(experts_mod, "get_agent_docs_store", lambda: fake)
    monkeypatch.setattr(
        experts_mod,
        "get_expert_store",
        lambda: _FakeExpertStore(),
    )
    result = await experts_mod.list_personal_drafts("captest_e1")
    assert result["available"] is True
    assert len(result["drafts"]) == 1
    assert result["drafts"][0]["owner_user_id"] == "alice"
    assert result["drafts"][0]["unapplied"] is True


async def test_list_personal_drafts_unavailable_no_pg(monkeypatch) -> None:
    monkeypatch.setattr(experts_mod, "get_agent_docs_store", lambda: None)
    monkeypatch.setattr(
        experts_mod,
        "get_expert_store",
        lambda: _FakeExpertStore(),
    )
    result = await experts_mod.list_personal_drafts("captest_e1")
    assert result == {"drafts": [], "available": False}
