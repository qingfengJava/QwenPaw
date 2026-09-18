# -*- coding: utf-8 -*-
"""T9: Agent 接入接线单测（kb_read 工具 + read_document 门面 + builder 注册门控）。

覆盖裁定基准 task-9-brief.md：
- kb_read（T10-S0 绑定收敛）：pg 态返回 content_md 权威全文（见 test_service_facade.py
  的 pg 分支）、json 态从切片按 seq 重建全文、doc 不存在或所属库未绑定均合并 not-found；
- read_document 门面 json 分支（切片重建 / 未命中 None）；
- AC2 builder 注册门控（无绑定不注册不注入 / 有绑定注册 kb_search+kb_read 且注入目录）
  ——该组待 builder.py 接线后追加（冲突协议：builder.py 最后动）。

json 后端由 autouse 钉桩（T8 教训：防环境变量泄漏误走 pg）；pg 分支另在
test_service_facade.py 用 FakeStore 覆盖。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.kb.models import SCOPE_ENTERPRISE
from qwenpaw.app.kb.service import KbService
from qwenpaw.db import write_gateway

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _json_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉住 json 后端（本文件测文件面重建/ACL 行为，防环境泄漏误走 pg）。"""
    monkeypatch.setattr(
        write_gateway,
        "resolve_storage_backend",
        lambda: "json",
    )


@pytest.fixture
def service(tmp_path: Path) -> KbService:
    return KbService(
        registry_path=tmp_path / "kb_registry.json",
        data_dir=tmp_path / "kb_data",
    )


def _hit_text(chunk) -> str:
    block = chunk.content[0]
    if isinstance(block, dict):
        return block["text"]
    return getattr(block, "text", "")


# ---------------------------------------------------------------------------
# read_document 门面（json 分支：切片按 seq 重建全文）
# ---------------------------------------------------------------------------


def test_read_document_json_reconstructs_full_text(service: KbService) -> None:
    """json 态：read_document 从切片按 seq 拼接重建全文。"""
    kb = service.create_kb("Doc库", scope=SCOPE_ENTERPRISE)
    doc = service.ingest_text(
        kb.id,
        "第一段内容\n\n第二段内容\n\n第三段内容",
        title="重建文档",
    )
    assert doc is not None
    text = service.read_document(doc.doc_id)
    assert text is not None
    assert "第一段内容" in text
    assert "第二段内容" in text
    assert "第三段内容" in text


def test_read_document_missing_returns_none(service: KbService) -> None:
    """未命中 doc_id：返回 None（不抛异常）。"""
    assert service.read_document("doc_ghost") is None


def test_get_document_meta_json(service: KbService) -> None:
    """get_document_meta 返回 registry 元数据（kb_id/title 供 ACL+标题）。"""
    kb = service.create_kb("Meta库", scope=SCOPE_ENTERPRISE)
    doc = service.ingest_text(kb.id, "正文", title="元数据文档")
    meta = service.get_document_meta(doc.doc_id)
    assert meta is not None
    assert meta.kb_id == kb.id
    assert meta.title == "元数据文档"
    assert service.get_document_meta("doc_ghost") is None


# ---------------------------------------------------------------------------
# kb_read 工具（json 后端；T10-S0 绑定收敛：doc 所属库 ∈ 绑定才可读）
# ---------------------------------------------------------------------------


async def test_kb_read_tool_returns_content(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """kb_read 命中：doc 所属库 ∈ 绑定 → 返回带标题头的权威全文。"""
    from qwenpaw.app.kb.tool import make_kb_read_tool
    import qwenpaw.app.kb.bindings as bindings_mod

    kb = service.create_kb(" readable ", scope=SCOPE_ENTERPRISE)
    doc = service.ingest_text(kb.id, "甲状腺剂量说明", title="甲减指南")

    async def _bound(agent_id: str):
        return [kb.id]

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _bound)
    tool = make_kb_read_tool(service, "agent_x")
    text = _hit_text(await tool(doc.doc_id))
    assert "甲减指南" in text
    assert "甲状腺剂量说明" in text


async def test_kb_read_tool_not_found(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """kb_read 未命中：doc 不存在 → not found 错误块。"""
    from qwenpaw.app.kb.tool import make_kb_read_tool
    import qwenpaw.app.kb.bindings as bindings_mod

    kb = service.create_kb("lib", scope=SCOPE_ENTERPRISE)

    async def _bound(agent_id: str):
        return [kb.id]

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _bound)
    tool = make_kb_read_tool(service, "agent_x")
    text = _hit_text(await tool("doc_ghost"))
    assert "not found" in text


async def test_kb_read_tool_unbound_merged_not_found(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """kb_read 越权（S0 收敛）：doc 所属库未绑定 → 合并 not-found，不泄正文。"""
    from qwenpaw.app.kb.tool import make_kb_read_tool
    import qwenpaw.app.kb.bindings as bindings_mod

    bound_kb = service.create_kb("bound", scope=SCOPE_ENTERPRISE)
    other = service.create_kb("other", scope=SCOPE_ENTERPRISE)
    doc = service.ingest_text(other.id, "私密runbook正文", title="私密")

    async def _bound(agent_id: str):
        return [bound_kb.id]

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _bound)
    tool = make_kb_read_tool(service, "agent_x")
    text = _hit_text(await tool(doc.doc_id))
    assert "not found" in text
    assert "私密runbook正文" not in text


# ---------------------------------------------------------------------------
# AC2 builder 接线：_collect_kb_tools 绑定门控 + KbCatalogContributor 注入
# ---------------------------------------------------------------------------


async def test_collect_kb_tools_no_binding_no_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2：无绑定 Agent → 不注册工具、目录为空串（零注入）。"""
    from qwenpaw.runtime.builder import AgentBuilder
    import qwenpaw.app.kb.bindings as bindings_mod

    async def _no_bindings(agent_id: str):
        return []

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _no_bindings)
    tools, catalog = await AgentBuilder._collect_kb_tools("agent_x", {}, None)
    assert tools == []
    assert catalog == ""


async def test_collect_kb_tools_bound_registers_and_renders(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC2：有绑定 → 注册 kb_search+kb_read 两工具 + 目录仅含绑定库。"""
    from qwenpaw.runtime.builder import AgentBuilder
    import qwenpaw.app.kb.bindings as bindings_mod
    import qwenpaw.app.kb.service as service_mod

    # json 后端 service：两库，其一绑定给 agent
    svc = KbService(
        registry_path=tmp_path / "kb_registry.json",
        data_dir=tmp_path / "kb_data",
    )
    bound = svc.create_kb(
        "孕产库", scope=SCOPE_ENTERPRISE, description="孕产用药检索"
    )
    svc.create_kb("未绑定库", scope=SCOPE_ENTERPRISE)

    async def _one_binding(agent_id: str):
        return [bound.id]

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _one_binding)
    monkeypatch.setattr(service_mod, "get_kb_service", lambda: svc)
    # 隔离守卫包装（本测只验注册数量+目录，不验 guard 内部）
    monkeypatch.setattr(AgentBuilder, "_wrap_tool", lambda fn, *a, **k: fn)

    tools, catalog = await AgentBuilder._collect_kb_tools("agent_x", {}, None)
    assert len(tools) == 2
    assert "<knowledge-bases>" in catalog
    assert bound.id in catalog
    assert "孕产库" in catalog
    # 只注入绑定库，未绑定库不进目录
    assert "未绑定库" not in catalog


async def test_collect_kb_tools_orphan_binding_no_registration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC3/P3-1：绑定库全被删（孤绑定）→ 不注册工具、目录空。

    T9 按 raw bound_ids 门控（非空即注册），孤绑定时会注册工具但目录空；
    T10-S0 改按解析后 spaces 门控，孤绑定直接不注册不注入。
    """
    from qwenpaw.runtime.builder import AgentBuilder
    import qwenpaw.app.kb.bindings as bindings_mod
    import qwenpaw.app.kb.service as service_mod

    svc = KbService(
        registry_path=tmp_path / "kb_registry.json",
        data_dir=tmp_path / "kb_data",
    )

    # 绑定一个已不存在的 space_id（模拟库被删后的孤绑定）
    async def _orphan(agent_id: str):
        return ["kb_deleted_ghost"]

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _orphan)
    monkeypatch.setattr(service_mod, "get_kb_service", lambda: svc)
    monkeypatch.setattr(AgentBuilder, "_wrap_tool", lambda fn, *a, **k: fn)

    tools, catalog = await AgentBuilder._collect_kb_tools("agent_x", {}, None)
    assert tools == []
    assert catalog == ""


def test_kb_catalog_contributor_injects_block() -> None:
    """AC2：contributor 从 ctx.extras[kb_catalog] 取块注入 prompt。"""
    from types import SimpleNamespace

    from qwenpaw.runtime.prompt_contributors import KbCatalogContributor

    block = "<knowledge-bases>\n<id>kb_x</id>\n</knowledge-bases>"
    ctx = SimpleNamespace(extras={"kb_catalog": block})
    assert KbCatalogContributor().contribute_sync(ctx) == block


def test_kb_catalog_contributor_empty_returns_none() -> None:
    """AC2：无绑定（空串/缺键）→ contributor 返 None，prompt 不含目录块。"""
    from types import SimpleNamespace

    from qwenpaw.runtime.prompt_contributors import KbCatalogContributor

    contrib = KbCatalogContributor()
    assert (
        contrib.contribute_sync(SimpleNamespace(extras={"kb_catalog": ""}))
        is None
    )
    assert contrib.contribute_sync(SimpleNamespace(extras={})) is None


# ---------------------------------------------------------------------------
# T9 审查轮补强（P2-1 json 重建保真证据 + P3-4 空 doc_id 守卫）
# ---------------------------------------------------------------------------


def test_read_document_multichunk_contains_all_paragraphs(
    service: KbService,
) -> None:
    """P2-1 证据：多切片 json 重建须完整覆盖全部原文段落。

    chunk_text 为检索连续性在切片间保留 ~100 字符 overlap，重建文本在
    切片边界处会有少量重复（已知限制，见 read_document docstring）；本
    测只断言重建完整覆盖所有段落，不断言逐字相等。
    """
    kb = service.create_kb("Long", scope=SCOPE_ENTERPRISE)
    paras = [f"段落{i} " + "内容" * 200 for i in range(12)]
    doc = service.ingest_text(kb.id, "\n\n".join(paras), title="长文档")
    assert doc is not None
    out = service.read_document(doc.doc_id)
    assert out is not None
    for i in range(12):
        assert f"段落{i} " in out


async def test_kb_read_tool_empty_doc_id(
    service: KbService,
) -> None:
    """P3-4：空/空白 doc_id 返回错误块（提前校验，不触存储/绑定）。"""
    from qwenpaw.app.kb.tool import make_kb_read_tool

    tool = make_kb_read_tool(service, "agent_x")
    assert "cannot be empty" in _hit_text(await tool(""))
    assert "cannot be empty" in _hit_text(await tool("   "))
