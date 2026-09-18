# -*- coding: utf-8 -*-
"""T10-S0: ``kb_search`` 绑定收敛单测（绑定即授权，spec §8 决策点1）。

覆盖裁定基准 task-10-brief.md：
- AC1 越权查不到 + R3 S0 先于 S1（spy 证明 ``svc.search`` 从未以未绑定
  kb_id 被调用 → 先过滤后检索，杜绝越权召回）；
- AC2 未指定 kb_id 时多绑定库融合按 score 降序（用相关度不同文本使排序
  可观测）；
- R2 kb_id ∩ 绑定（命中 / 存在但未绑定 / 不存在 / 绑定但库已删的部分孤
  绑定，均合并 not-found，不泄露库存在性与绑定态）；
- R4 绑定撤销即时生效（同一工具实例两次调用间撤销 → 第二次即无库可查）；
- 空绑定 → 无绑定库提示（不报错、不泄露）。

后端说明（P3-4 偏差记录）：工具层对存储后端透明（仅调 ``svc.search`` /
``svc.list_kbs``），dual/pg 的后端路由已由 test_service_facade.py 覆盖（含
dual read_document 重建），故本文件聚焦 json 后端的绑定收敛逻辑，不重复
测后端路由。

绑定经 monkeypatch ``bindings.list_bound_space_ids`` 注入（隔离 bindings
存储，只验工具收敛逻辑，与 test_kb_wiring 的 builder 门控测同约定）；
json 后端由 autouse 钉桩（T8 教训：防环境变量泄漏误走 pg）。

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
    """钉住 json 后端（本文件测绑定收敛/融合行为，防环境泄漏误走 pg）。"""
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


def _bind(monkeypatch: pytest.MonkeyPatch, space_ids) -> None:
    """把 agent 绑定集钉成 *space_ids*（隔离 bindings 存储）。"""
    import qwenpaw.app.kb.bindings as bindings_mod

    async def _bound(agent_id: str):
        return list(space_ids)

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _bound)


def _spy_search(monkeypatch: pytest.MonkeyPatch, svc: KbService) -> list:
    """记录 ``svc.search`` 被调用的 kb_id，证明 S0 收敛先于 S1 引擎查询。"""
    called: list = []
    orig = svc.search

    def _spy(kb_id, query, **kwargs):
        called.append(kb_id)
        return orig(kb_id, query, **kwargs)

    monkeypatch.setattr(svc, "search", _spy)
    return called


async def test_unbound_kb_never_searched_s0_before_s1(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1+R3：绑定 A，A/B 均有可命中内容；B 文档绝不出现，且引擎只被以 A 调用。"""
    from qwenpaw.app.kb.tool import make_kb_search_tool

    a = service.create_kb("甲库", scope=SCOPE_ENTERPRISE)
    b = service.create_kb("乙库", scope=SCOPE_ENTERPRISE)
    service.ingest_text(a.id, "zeta token 甲库部署手册", title="甲文档")
    service.ingest_text(b.id, "zeta token 乙库机密runbook", title="乙文档")

    _bind(monkeypatch, [a.id])
    called = _spy_search(monkeypatch, service)

    tool = make_kb_search_tool(service, "agent_x")
    text = _hit_text(await tool("zeta token"))

    # 绑定库 A 命中出现在结果
    assert "甲库" in text
    # 未绑定库 B 的正文/标题绝不泄露
    assert "乙库机密runbook" not in text
    assert "乙文档" not in text
    # S0 收敛先于 S1：引擎从未以未绑定库 B.id 被调用
    assert b.id not in called
    assert a.id in called


async def test_multi_bound_fusion_sorted_by_score(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2：绑定 A+B，不指定 kb_id → 跨库命中融合，且溯源行 score 严格降序。

    两库灌入与 query 相关度不同的文本（A 短且高频命中、B 长且单次命中），
    使 BM25 得分可区分，从而真正验证「按分排序」而非仅验证两库都出现。
    """
    import re

    from qwenpaw.app.kb.tool import make_kb_search_tool

    a = service.create_kb("甲库", scope=SCOPE_ENTERPRISE)
    b = service.create_kb("乙库", scope=SCOPE_ENTERPRISE)
    service.ingest_text(
        a.id,
        "alpha bravo charlie alpha bravo charlie",
        title="A文档",
    )
    service.ingest_text(
        b.id,
        "alpha bravo charlie delta echo foxtrot golf hotel india juliet",
        title="B文档",
    )

    _bind(monkeypatch, [a.id, b.id])
    tool = make_kb_search_tool(service, "agent_x")
    text = _hit_text(await tool("alpha bravo charlie"))

    # 两库都命中（融合）
    assert "甲库" in text
    assert "乙库" in text
    # AC2 核心：溯源行 score 序列必须降序（按分排序融合）
    scores = [float(m) for m in re.findall(r"score=([0-9.]+)", text)]
    assert len(scores) >= 2
    assert scores == sorted(scores, reverse=True)


async def test_kb_id_in_bound_hits(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2：指定的 kb_id ∈ 绑定 → 正常检索该库。"""
    from qwenpaw.app.kb.tool import make_kb_search_tool

    a = service.create_kb("甲库", scope=SCOPE_ENTERPRISE)
    service.ingest_text(a.id, "deployment runbook steps", title="甲文档")
    _bind(monkeypatch, [a.id])

    tool = make_kb_search_tool(service, "agent_x")
    text = _hit_text(await tool("deployment runbook", kb_id=a.id))
    assert "甲库" in text


async def test_kb_id_not_bound_merged_not_found(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2：kb_id 存在但未绑定 → 合并 not-found，不泄露正文/存在性。"""
    from qwenpaw.app.kb.tool import make_kb_search_tool

    a = service.create_kb("甲库", scope=SCOPE_ENTERPRISE)
    b = service.create_kb("乙库", scope=SCOPE_ENTERPRISE)
    service.ingest_text(b.id, "secret runbook payload", title="乙文档")
    _bind(monkeypatch, [a.id])

    tool = make_kb_search_tool(service, "agent_x")
    text = _hit_text(await tool("secret runbook", kb_id=b.id))
    assert "not found" in text
    assert "secret runbook payload" not in text


async def test_kb_id_nonexistent_merged_not_found(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2：kb_id 不存在 → 与未绑定同一 not-found 文案（合并，不区分）。"""
    from qwenpaw.app.kb.tool import make_kb_search_tool

    a = service.create_kb("甲库", scope=SCOPE_ENTERPRISE)
    _bind(monkeypatch, [a.id])

    tool = make_kb_search_tool(service, "agent_x")
    text = _hit_text(await tool("x", kb_id="kb_ghost"))
    assert "not found" in text


async def test_no_binding_reports_no_bound_bases(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空绑定：工具返回无绑定库提示（防御性；正常路径 builder 已不注册）。"""
    from qwenpaw.app.kb.tool import make_kb_search_tool

    service.create_kb("甲库", scope=SCOPE_ENTERPRISE)
    _bind(monkeypatch, [])

    tool = make_kb_search_tool(service, "agent_x")
    text = _hit_text(await tool("anything"))
    assert "no bound knowledge bases" in text


async def test_bound_but_deleted_kb_id_merged_not_found(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P3-2：绑定集含已删除库 X，显式 kb_search(kb_id=X) → get_kb 返 None
    → 合并 not-found，且绝不以 X 触发引擎查询。

    部分孤绑定（多库绑定，其一被删）是真实场景；builder 的全孤绑定门控
    （spaces 全空才不注册）不覆盖此路径，须由工具层 kb_id ∈ 绑定但库不存在
    的合并分支兜底。
    """
    from qwenpaw.app.kb.tool import make_kb_search_tool

    a = service.create_kb("甲库", scope=SCOPE_ENTERPRISE)
    # 绑定集含一个已不存在的 space_id（库被删的部分孤绑定）
    _bind(monkeypatch, [a.id, "kb_deleted_ghost"])
    called = _spy_search(monkeypatch, service)

    tool = make_kb_search_tool(service, "agent_x")
    text = _hit_text(await tool("x", kb_id="kb_deleted_ghost"))
    assert "not found" in text
    # 已删库绝不触发引擎查询（S0 收敛先于 S1）
    assert "kb_deleted_ghost" not in called


async def test_binding_revocation_takes_effect_next_call(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R4 安全新鲜度：同一工具实例，两次调用间撤销绑定 → 第二次即无库可查。

    证明工具每次调用重解析绑定（未缓存构造期快照）：若未来重构误将绑定
    缓存到构造期，本用例即失败，守护 R4 核心安全不变式。
    """
    import qwenpaw.app.kb.bindings as bindings_mod
    from qwenpaw.app.kb.tool import make_kb_search_tool

    a = service.create_kb("甲库", scope=SCOPE_ENTERPRISE)
    service.ingest_text(a.id, "deployment runbook", title="甲文档")

    current = [a.id]

    async def _bound(agent_id: str):
        return list(current)

    monkeypatch.setattr(bindings_mod, "list_bound_space_ids", _bound)
    tool = make_kb_search_tool(service, "agent_x")

    # 第一次：绑定 A → 命中
    assert "甲库" in _hit_text(await tool("deployment runbook"))

    # 撤销绑定（不改工具实例）→ 第二次调用即反映
    current.clear()
    text2 = _hit_text(await tool("deployment runbook"))
    assert "no bound knowledge bases" in text2
