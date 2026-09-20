# -*- coding: utf-8 -*-
"""T4 ontology API 端点形状单测（TestClient，零 PG 零真权限）。

打桩点在 :mod:`qwenpaw.app.ontology.api` 引用的 ``service`` 层——端点
语义（503/404/400/201/204 与响应形状）由本文件锁定，store 真库往返由
``test_ontology_store.py``（fake）与集成门控（真库）分层覆盖。
RBAC 在未启用 ``QWENPAW_RBAC_ENFORCE`` 时直通（require_perm 惯例），
本文件显式钉死关闭态避免环境漂移。

@author qingfeng
"""

# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from typing import Any, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.ontology import service as ont_service
from qwenpaw.app.ontology.api import router as ontology_router
from qwenpaw.app.ontology.models import (
    KbObjectLink,
    OntologyObject,
    OntologyType,
)

pytestmark = pytest.mark.unit

_SVC = "qwenpaw.app.ontology.api.service"


@pytest.fixture(autouse=True)
def _rbac_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 RBAC 关闭态（直通 require_perm，测端点本身）。"""
    from qwenpaw.app import rbac as rbac_pkg

    monkeypatch.setattr(rbac_pkg, "rbac_enforcement_enabled", lambda: False)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """挂载 ontology router 的 TestClient（/api/admin 前缀）。"""
    application = FastAPI()
    application.include_router(ontology_router, prefix="/api/admin")
    with TestClient(application) as test_client:
        yield test_client


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    result: Any,
    *,
    raises: bool = False,
) -> None:
    """service 层函数打桩（async 恒返 result / 抛 ValueError）。"""

    async def _fake(*args: Any, **kwargs: Any):
        del args, kwargs
        if raises:
            raise ValueError(str(result))
        return result

    monkeypatch.setattr(ont_service, name, _fake)


# ---------------------------------------------------------------------------
# 503（平面不可用）
# ---------------------------------------------------------------------------


def test_list_types_unavailable_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """平面不可用（service 返 None）→ 503。"""
    _patch(monkeypatch, "list_types", None)
    resp = client.get("/api/admin/ontology/types")
    assert resp.status_code == 503
    assert "unavailable" in resp.json()["detail"]


def test_create_object_unavailable_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create 平面不可用 → 503（先于值级校验语义）。"""
    _patch(monkeypatch, "create_object", None)
    resp = client.post(
        "/api/admin/ontology/objects",
        json={"id": "", "type_id": "l1.project", "name": "P1"},
    )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# objects CRUD
# ---------------------------------------------------------------------------


def test_list_objects_ok(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """list 形状：q/limit 查询参数透传 service。"""
    captured: dict = {}

    async def _fake(**kwargs: Any):
        captured.update(kwargs)
        return [
            OntologyObject(
                id="obj_1", type_id="l1.project", name="PROJECT-10001",
            ),
        ]

    monkeypatch.setattr(ont_service, "list_objects", _fake)
    resp = client.get(
        "/api/admin/ontology/objects",
        params={"type_id": "l1.project", "q": "PROJECT", "limit": 10},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["id"] == "obj_1"
    assert body[0]["status"] == "active"
    assert captured["type_id"] == "l1.project"
    assert captured["keyword"] == "PROJECT"
    assert captured["limit"] == 10


def test_create_object_201(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create 201 形状（服务层返回完整模型）。"""
    _patch(
        monkeypatch,
        "create_object",
        OntologyObject(
            id="obj_new", type_id="l1.project", name="P1",
        ),
    )
    resp = client.post(
        "/api/admin/ontology/objects",
        json={"id": "", "type_id": "l1.project", "name": "P1"},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == "obj_new"


def test_create_object_bad_type_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知类型引用（ValueError）→ 400 带原因。"""
    _patch(monkeypatch, "create_object", "unknown ontology type: l1.x",
           raises=True)
    resp = client.post(
        "/api/admin/ontology/objects",
        json={"id": "", "type_id": "l1.x", "name": "P"},
    )
    assert resp.status_code == 400
    assert "unknown ontology type" in resp.json()["detail"]


def test_get_object_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """路径对象不存在 → 404。"""
    _patch(monkeypatch, "get_object", None)
    resp = client.get("/api/admin/ontology/objects/obj_ghost")
    assert resp.status_code == 404


def test_update_object_404_then_200(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH 先判存在性（404），再返回更新后对象（200）。"""
    updated = OntologyObject(
        id="obj_1", type_id="l1.project", name="renamed",
    )

    async def _get(object_id: str, **_: Any):
        del object_id
        return updated

    async def _update(object_id: str, fields: dict, **_: Any):
        del object_id, fields
        return updated

    monkeypatch.setattr(ont_service, "get_object", _get)
    monkeypatch.setattr(ont_service, "update_object", _update)
    resp = client.patch(
        "/api/admin/ontology/objects/obj_1",
        json={"name": "renamed"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "renamed"

    missing = FastAPI()
    missing.include_router(ontology_router, prefix="/api/admin")

    async def _none(*args: Any, **kwargs: Any):
        del args, kwargs
        return None

    monkeypatch.setattr(ont_service, "get_object", _none)
    resp = TestClient(missing).patch(
        "/api/admin/ontology/objects/obj_ghost",
        json={"name": "x"},
    )
    assert resp.status_code == 404


def test_delete_object_204_or_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE 幂等 204；平面不可用 503。"""
    _patch(monkeypatch, "soft_delete_object", True)
    resp = client.delete("/api/admin/ontology/objects/obj_1")
    assert resp.status_code == 204

    _patch(monkeypatch, "soft_delete_object", None)
    resp = client.delete("/api/admin/ontology/objects/obj_1")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# transitions / relations
# ---------------------------------------------------------------------------


def test_apply_transition_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """迁移端点返回 {transition, object} 双载荷形状（模型序列化）。"""
    from qwenpaw.app.ontology.models import OntologyStateTransition

    async def _apply(object_id: str, to_state: str, **kwargs: Any):
        del object_id, kwargs
        assert to_state == "active"
        return OntologyStateTransition(
            id="trn_1",
            object_id="obj_1",
            from_state="",
            to_state="active",
            trigger_type="kickoff",
        )

    async def _get(object_id: str, **_: Any):
        del object_id
        return OntologyObject(
            id="obj_1", type_id="l1.project", name="P", state="active",
        )

    monkeypatch.setattr(ont_service, "apply_transition", _apply)
    monkeypatch.setattr(ont_service, "get_object", _get)
    resp = client.post(
        "/api/admin/ontology/objects/obj_1/transitions",
        json={"to_state": "active", "trigger_type": "kickoff"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["transition"]["to_state"] == "active"
    assert body["object"]["state"] == "active"


def test_transition_missing_object_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """迁移目标对象不存在（ValueError not found）→ 404 语义区分。

    服务层统一抛 ValueError；api 层消息含 ``not found`` 时升级 404。
    """
    _patch(
        monkeypatch,
        "apply_transition",
        "object not found: obj_ghost",
        raises=True,
    )
    resp = client.post(
        "/api/admin/ontology/objects/obj_ghost/transitions",
        json={"to_state": "active"},
    )
    assert resp.status_code == 404


def test_relations_dual_direction_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对象关系端点返回 {outbound, inbound} 双向形状。"""
    from qwenpaw.app.ontology.models import OntologyRelation

    rel = {
        "id": "rel_1", "type": "belongs_to",
        "from_type": "l1.contract", "from_id": "obj_c1",
        "to_type": "l1.project", "to_id": "obj_1",
    }

    async def _get(object_id: str, **_: Any):
        del object_id
        return OntologyObject(id="obj_1", type_id="l1.project", name="P")

    async def _list(**kwargs: Any):
        if "from_id" in kwargs:
            assert kwargs["from_id"] == "obj_1"
            return []
        assert kwargs["to_id"] == "obj_1"
        return [OntologyRelation(**rel)]

    monkeypatch.setattr(ont_service, "get_object", _get)
    monkeypatch.setattr(ont_service, "list_relations", _list)
    resp = client.get("/api/admin/ontology/objects/obj_1/relations")
    assert resp.status_code == 200
    body = resp.json()
    assert body["outbound"] == []
    assert body["inbound"][0]["id"] == "rel_1"


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------


def test_links_create_and_list(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """互引端点：201 创建形状 + 文档侧清单。"""
    link = KbObjectLink(
        id="lnk_1",
        kb_space_id="kb_a",
        kb_document_id="doc_1",
        object_type="l1.project",
        object_id="obj_1",
    )

    async def _create(payload: KbObjectLink):
        del payload
        return link

    monkeypatch.setattr(ont_service, "create_link", _create)
    resp = client.post(
        "/api/admin/ontology/links",
        json={
            "id": "",
            "kb_space_id": "kb_a",
            "kb_document_id": "doc_1",
            "object_type": "l1.project",
            "object_id": "obj_1",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["relation"] == "knowledge_mentions"

    async def _list(document_id: str = "", object_id: str = ""):
        del object_id
        assert document_id == "doc_1"
        return [link]

    monkeypatch.setattr(ont_service, "list_links", _list)
    resp = client.get(
        "/api/admin/ontology/links", params={"document_id": "doc_1"},
    )
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "lnk_1"


def test_links_missing_object_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """互引目标对象不存在（body 引用违规）→ 400。"""
    _patch(
        monkeypatch,
        "create_link",
        "link target object not found: obj_ghost",
        raises=True,
    )
    resp = client.post(
        "/api/admin/ontology/links",
        json={
            "id": "",
            "kb_space_id": "kb_a",
            "kb_document_id": "doc_1",
            "object_type": "l1.project",
            "object_id": "obj_ghost",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# types 响应形状
# ---------------------------------------------------------------------------


def test_types_response_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """types 端点返回 OntologyType 形状（含 attributes_schema）。"""
    _patch(
        monkeypatch,
        "list_types",
        [OntologyType(
            id="l1.project",
            name="项目",
            layer="L1",
            parent_id="l0.object",
            description="项目/工程对象",
        )],
    )
    resp = client.get("/api/admin/ontology/types", params={"layer": "L1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["id"] == "l1.project"
    assert body[0]["layer"] == "L1"
    assert body[0]["parent_id"] == "l0.object"
