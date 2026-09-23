# -*- coding: utf-8 -*-
"""T4 摄入互引集成：frontmatter ``objects`` → ``kb_object_links``。

覆盖两层面：

1. **解析矩阵**：``_parse_object_refs`` 支持 list / dict / 逗号分隔
   字符串三种形态，坏项静默丢弃；
2. **fail-soft 契约**：本体平面关闭 → 零写入不告警升级；对象缺失 →
   跳过单条；relation 非法 → 回落默认；写入异常 → 吞掉不影响摄入
   结果（互引是附加能力，摄入主链路永不因互引失败而 failed）。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from qwenpaw.app.kb.ingest import (
    _parse_object_refs,
    _sync_object_links,
)
from qwenpaw.app.ontology import models
from qwenpaw.app.ontology import store as ont_store_mod
from qwenpaw.app.ontology.models import KbObjectLink, OntologyObject

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 解析矩阵
# ---------------------------------------------------------------------------


def test_parse_refs_list_form() -> None:
    """list 形态："Type:ID" 条目。"""
    refs = _parse_object_refs(
        {"objects": ["Project:PROJECT-10001", "Customer:C001"]},
    )
    assert refs == [
        ("Project", "PROJECT-10001"),
        ("Customer", "C001"),
    ]


def test_parse_refs_dict_form() -> None:
    """dict 形态：{"Type": [ids]}；标量值也容忍。"""
    refs = _parse_object_refs(
        {"objects": {"Project": ["P1", "P2"], "Task": "T9"}},
    )
    assert refs == [("Project", "P1"), ("Project", "P2"), ("Task", "T9")]


def test_parse_refs_csv_string_form() -> None:
    """逗号分隔字符串形态。"""
    refs = _parse_object_refs({"objects": "Project:P1, Task:T1"})
    assert refs == [("Project", "P1"), ("Task", "T1")]


def test_parse_refs_drops_bad_items() -> None:
    """无冒号 / 空段 / 空 objects 静默丢弃，返回空列表不报错。"""
    assert _parse_object_refs({}) == []
    assert _parse_object_refs({"objects": None}) == []
    assert _parse_object_refs({"objects": ["no-colon", ":half", "a:"]}) == []


# ---------------------------------------------------------------------------
# fail-soft 契约
# ---------------------------------------------------------------------------


class _FakeOntStore:
    """记录互引写入序列；对象存在性由 ``objects`` 集合控制。"""

    def __init__(
        self,
        objects: Optional[Dict[str, OntologyObject]] = None,
        fail: bool = False,
    ) -> None:
        self.objects = objects or {}
        self.fail = fail
        self.created: List[KbObjectLink] = []

    async def get_object(self, object_id: str) -> Optional[OntologyObject]:
        """存在性查询（fake 字典直查）。"""
        return self.objects.get(object_id)

    async def create_link(self, link: Any) -> bool:
        """互引写入（fail=True 时模拟底库异常）。"""
        if self.fail:
            raise RuntimeError("link boom")
        self.created.append(link)
        return True


@pytest.fixture()
def _ontology_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """本体平面关闭（工厂返回 None）。"""

    async def _none():
        return None

    monkeypatch.setattr(ont_store_mod, "get_ready_ontology_store", _none)


async def test_sync_links_plain_off_is_silent(
    monkeypatch: pytest.MonkeyPatch,
    _ontology_off: None,
) -> None:
    """平面关闭：静默跳过、零写入、不抛出。"""
    del _ontology_off
    await _sync_object_links(
        store=object(),
        space_id="kb_a",
        doc_id="doc_1",
        meta={"objects": ["Project:P1"]},
    )


async def test_sync_links_empty_meta_is_noop() -> None:
    """无 objects 键：解析即短路，零副作用零异常。"""
    await _sync_object_links(
        store=object(),
        space_id="kb_a",
        doc_id="doc_1",
        meta={},
    )


async def test_sync_links_writes_for_existing_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """对象存在 → 写互引；relation 非法回落默认；缺失对象跳过。"""
    fake = _FakeOntStore(
        objects={
            "P1": OntologyObject(
                id="P1", type_id="l1.project", name="PROJECT-1",
            ),
        },
    )

    async def _factory():
        return fake

    monkeypatch.setattr(ont_store_mod, "get_ready_ontology_store", _factory)
    await _sync_object_links(
        store=object(),
        space_id="kb_a",
        doc_id="doc_1",
        meta={
            "objects": ["Project:P1", "Project:MISSING"],
            "objects_relation": "not-a-relation",
        },
    )
    assert len(fake.created) == 1
    link = fake.created[0]
    assert link.kb_document_id == "doc_1"
    assert link.object_id == "P1"
    assert link.relation == models.LINK_RELATION_MENTIONS
    assert link.id.startswith("lnk_")


async def test_sync_links_valid_relation_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """合法 relation（knowledge_supports_object）原样落表。"""
    fake = _FakeOntStore(
        objects={
            "P1": OntologyObject(
                id="P1", type_id="l1.project", name="PROJECT-1",
            ),
        },
    )

    async def _factory():
        return fake

    monkeypatch.setattr(ont_store_mod, "get_ready_ontology_store", _factory)
    await _sync_object_links(
        store=object(),
        space_id="kb_a",
        doc_id="doc_1",
        meta={
            "objects": ["Project:P1"],
            "objects_relation": models.LINK_RELATION_SUPPORTS,
        },
    )
    assert fake.created[0].relation == models.LINK_RELATION_SUPPORTS


async def test_sync_links_write_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """写入异常吞掉（fail-soft）：不影响摄入返回值。"""
    fake = _FakeOntStore(
        objects={
            "P1": OntologyObject(
                id="P1", type_id="l1.project", name="PROJECT-1",
            ),
        },
        fail=True,
    )

    async def _factory():
        return fake

    monkeypatch.setattr(ont_store_mod, "get_ready_ontology_store", _factory)
    await _sync_object_links(
        store=object(),
        space_id="kb_a",
        doc_id="doc_1",
        meta={"objects": ["Project:P1"]},
    )
    assert fake.created == []
