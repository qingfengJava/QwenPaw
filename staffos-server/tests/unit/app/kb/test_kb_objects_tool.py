# -*- coding: utf-8 -*-
"""T5 ``kb_objects`` 工具单测：参数守卫 / 对象卡渲染 / 绑定收敛透传。

工具层聚焦编排与渲染；grounding 内部逻辑（ACL 收敛、fail-soft）由
``tests/unit/app/ontology/test_grounding.py`` 覆盖，本文件经
monkeypatch ``grounding`` 函数注入隔离。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from qwenpaw.app.kb.tool import make_kb_objects_tool
from qwenpaw.app.ontology import grounding
from qwenpaw.app.ontology.models import OntologyObject
from qwenpaw.db import write_gateway

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _json_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉住 json 后端（防环境泄漏误走 pg）。"""
    monkeypatch.setattr(
        write_gateway,
        "resolve_storage_backend",
        lambda: "json",
    )


def _bind(monkeypatch: pytest.MonkeyPatch, space_ids: List[str]) -> None:
    """把 agent 绑定集钉成 *space_ids*。"""
    import qwenpaw.app.kb.bindings as bindings_mod

    async def _bound(agent_id: str):
        del agent_id
        return list(space_ids)

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _bound)


def _stub_grounding(
    monkeypatch: pytest.MonkeyPatch,
    *,
    objects: Optional[List[OntologyObject]] = None,
    cards: Dict[str, Dict[str, Any]] = None,
) -> None:
    """钉 grounding 函数对。"""
    objects = objects or []
    cards = cards or {}

    async def _ground(keyword, type_id="", limit=3, store=None):
        del keyword, type_id, limit, store
        return objects

    async def _card(object_id, bound_space_ids=None, store=None):
        del bound_space_ids, store
        return cards.get(object_id)

    monkeypatch.setattr(grounding, "ground_objects", _ground)
    monkeypatch.setattr(grounding, "object_card", _card)


def _text(result: Any) -> str:
    """取 ToolChunk 文本。"""
    block = result.content[0]
    if isinstance(block, dict):
        return block["text"]
    return getattr(block, "text", "")


async def test_empty_params_rejected() -> None:
    """name 与 object_id 全空 → 显式报错（不静默 no-match）。"""
    tool = make_kb_objects_tool(agent_id="agent_x")
    out = _text(await tool())
    assert out.startswith("Error:")


async def test_object_id_exact_card_rendered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """object_id 精确取卡：状态/属性/关系/关联知识逐行渲染。"""
    _bind(monkeypatch, ["kb_a"])
    _stub_grounding(
        monkeypatch,
        cards={
            "P1": {
                "id": "P1",
                "type_id": "l1.project",
                "name": "PROJECT-10001",
                "aliases": ["P1"],
                "state": "执行中",
                "attributes": {"code": "PROJECT-10001"},
                "relations": {
                    "outbound": [
                        {
                            "type": "belongs_to",
                            "to_id": "org1",
                            "to_type": "l1.org",
                        },
                    ],
                    "inbound": [],
                },
                "linked_docs": [
                    {
                        "doc_id": "doc_a",
                        "kb_space_id": "kb_a",
                        "relation": "knowledge_mentions",
                    },
                ],
            },
        },
    )
    tool = make_kb_objects_tool(agent_id="agent_x")
    out = _text(await tool(object_id="P1"))
    assert "[对象] PROJECT-10001" in out
    assert "状态: 执行中" in out
    assert "—[belongs_to]→ org1" in out
    assert "doc_a" in out
    assert "kb_read" in out


async def test_name_grounding_no_match_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """name 无命中 → no-match 提示（不报错）。"""
    _bind(monkeypatch, ["kb_a"])
    _stub_grounding(monkeypatch, objects=[])
    tool = make_kb_objects_tool(agent_id="agent_x")
    out = _text(await tool(name="不存在"))
    assert out == "(no matching ontology objects)"


async def test_name_grounding_renders_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """name 命中 → grounding 对象逐个转卡渲染。"""
    _bind(monkeypatch, ["kb_a"])
    _stub_grounding(
        monkeypatch,
        objects=[
            OntologyObject(
                id="P1",
                type_id="l1.project",
                name="PROJECT-10001",
            ),
        ],
        cards={
            "P1": {
                "id": "P1",
                "type_id": "l1.project",
                "name": "PROJECT-10001",
                "aliases": [],
                "state": "",
                "attributes": {},
                "relations": {"outbound": [], "inbound": []},
                "linked_docs": [],
            },
        },
    )
    tool = make_kb_objects_tool(agent_id="agent_x")
    out = _text(await tool(name="PROJECT"))
    assert "[对象] PROJECT-10001" in out


async def test_bound_ids_forwarded_to_grounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """绑定集透传 grounding（S0 收敛在卡组装层生效）。"""
    captured: dict = {}

    async def _ground(keyword, type_id="", limit=3, store=None):
        del keyword, type_id, limit, store
        return [OntologyObject(
            id="P1", type_id="l1.project", name="PROJECT-10001",
        )]

    async def _card(object_id, bound_space_ids=None, store=None):
        del object_id, store
        captured["bound"] = list(bound_space_ids or [])
        return None

    import qwenpaw.app.kb.bindings as bindings_mod

    async def _bound(agent_id: str):
        del agent_id
        return ["kb_x", "kb_y"]

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _bound)
    monkeypatch.setattr(grounding, "ground_objects", _ground)
    monkeypatch.setattr(grounding, "object_card", _card)

    tool = make_kb_objects_tool(agent_id="agent_x")
    await tool(name="PROJECT")
    assert captured["bound"] == ["kb_x", "kb_y"]
