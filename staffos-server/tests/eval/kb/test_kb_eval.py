# -*- coding: utf-8 -*-
"""KB 检索质量评测用例（T8）：Recall@5/MRR + 溯源 + 越权安全。

三个用例共享会话级 ``eval_kb`` 夹具（隔离库 + 12 篇语料一次就位）：
1. 指标门：Recall@5 ≥ 0.9 且 MRR ≥ 0.7（原文片段设计下应满分）；
2. 溯源门：每个命中 chunk 必须携带 kb_id + doc_id（可追溯到源文档）；
3. 安全门：未绑定 agent 的 kb_search 工具不得召回任何语料内容
   （绑定即授权的端到端验证，复用 T10-S0 收敛语义）。

全部用例为**同步 def**：async 工具调用经 ``_run_coro_blocking`` 桥接到
KbService 专用 bridge loop（与夹具摄入同一 loop）。KB 面 pg 协程必须
单循环执行（asyncpg 连接池绑定创建时 loop），pytest-asyncio 的 function
loop 直连 store 会与 bridge loop 共用池造成跨 loop 腐蚀（2026-09-20
诊断定稿，workforce 集成 session loop 教训同源）。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app.kb.service import _run_coro_blocking
from qwenpaw.app.kb.tool import make_kb_search_tool

from .corpus import DOCUMENTS
from .evalset import QA_PAIRS, _validate_snippets
from .runner import MRR_THRESHOLD, RECALL_THRESHOLD, evaluate

pytestmark = [pytest.mark.eval, pytest.mark.p0]

#: 桥接超时（工具调用含绑定解析 + 检索，给足余量）
_TOOL_BRIDGE_TIMEOUT = 30.0


def test_kb_eval_corpus_snippets_verbatim():
    """健全性门：全部片段必须是原文逐字子串（bigram 对齐的前提）。"""
    problems = _validate_snippets()
    assert not problems, "; ".join(problems)


def test_kb_eval_recall_and_mrr(eval_kb):
    """指标门：评测集整体 Recall@5 / MRR 达阈值，失败打印 misses 详单。"""
    report = evaluate(eval_kb.svc, eval_kb.kb_id)
    # misses 详单进断言消息，回归时直接定位是哪几条 query 退化
    assert report.recall_at_5 >= RECALL_THRESHOLD, report.summary()
    assert report.mrr >= MRR_THRESHOLD, report.summary()


def test_kb_eval_hits_carry_provenance(eval_kb):
    """溯源门：全部评测命中的 chunk 都带 kb_id + doc_id 溯源字段。"""
    seen = 0
    for pair in QA_PAIRS:
        hits = eval_kb.svc.search(
            eval_kb.kb_id,
            str(pair["q"]),
            top_k=3,
        )
        for chunk, _score in hits:
            assert chunk.kb_id == eval_kb.kb_id
            assert chunk.doc_id
            assert chunk.chunk_id
            seen += 1
    # 语料与评测集健全性：至少有命中发生，溯源断言才有意义
    assert seen > 0


def test_kb_eval_unbound_agent_no_leak(eval_kb):
    """安全门：未绑定 agent 的 kb_search 不得召回语料的任何片段。"""
    tool = make_kb_search_tool(eval_kb.svc, agent_id="eval_rogue_agent")
    # 工具是 async 闭包，桥接到 bridge loop 执行（禁止测试自建 loop）
    block = _run_coro_blocking(
        tool(query=str(QA_PAIRS[0]["q"])),
        timeout=_TOOL_BRIDGE_TIMEOUT,
    )
    text = str(block)
    # 未绑定返回提示文案，绝不携带任何语料片段（全专名清单逐个排除）
    for anchor in (
        "TravelCloud",
        "StarRing",
        "AuroraVPN",
        "BluewhaleCRM",
        "TianshuBI",
        "Flyingfish",
        "XuanwuSec",
        "ZhuqueRelease",
        "BaizeKB",
        "QilinFinance",
        "QingluanMail",
        "PenglaiDR",
    ):
        assert anchor not in text
    # 语料健全性自检：语料里确实含这些专名（防断言空转）
    joined = "".join(doc["text"] for doc in DOCUMENTS)
    assert "TravelCloud" in joined and "PenglaiDR" in joined
