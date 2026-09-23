# -*- coding: utf-8 -*-
"""T9: 知识库目录注入渲染单测（catalog.render_kb_catalog）。

覆盖裁定基准 task-9-brief.md AC1：
- 单库渲染出 <knowledge-bases> 块 + <id>/<name>/<description> + kb_search 引导语；
- 空列表返回 ""（无绑定 Agent 零注入）；
- 多库渲染多个 <knowledge-base> 节点；
- description 缺失容错（不崩、仍出 id/name）。

纯逻辑零依赖：render_kb_catalog 只吃 KbSpace 序列吐字符串，不触存储/后端，
故无需钉桩后端（区别于 test_kb_wiring.py）。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app.kb.catalog import render_kb_catalog
from qwenpaw.app.kb.models import KbSpace

pytestmark = pytest.mark.unit


def test_render_catalog_block() -> None:
    """单库：块标记 + id + 引导语齐备（plan Step1 给定断言）。"""
    spaces = [
        KbSpace(
            id="kb_yunchan",
            name="孕产知识库",
            description="涉及孕产用药、产检问题时检索本库。",
        ),
    ]
    out = render_kb_catalog(spaces)
    assert "<knowledge-bases>" in out
    assert "</knowledge-bases>" in out
    assert "<id>kb_yunchan</id>" in out
    assert "必须先调用 kb_search" in out


def test_render_empty_returns_blank() -> None:
    """空绑定：返回空串（builder 据此零注入、零注册）。"""
    assert render_kb_catalog([]) == ""


def test_render_includes_name_and_description() -> None:
    """name 与 description 原文进块（description 即 Agent 路由信号）。"""
    spaces = [
        KbSpace(
            id="kb_hr",
            name="人事制度库",
            description="考勤、请假、报销流程问题时检索本库。",
        ),
    ]
    out = render_kb_catalog(spaces)
    assert "<name>人事制度库</name>" in out
    assert "考勤、请假、报销流程问题时检索本库。" in out


def test_render_multiple_spaces_each_node() -> None:
    """多库：每库一个 <knowledge-base> 节点，id/name 均在。"""
    spaces = [
        KbSpace(id="kb_a", name="甲库", description="甲域检索"),
        KbSpace(id="kb_b", name="乙库", description="乙域检索"),
    ]
    out = render_kb_catalog(spaces)
    assert out.count("<knowledge-base>") == 2
    assert "<id>kb_a</id>" in out
    assert "<id>kb_b</id>" in out
    assert "<name>甲库</name>" in out
    assert "<name>乙库</name>" in out


def test_render_missing_description_tolerated() -> None:
    """description 缺省容错：仍出 id/name，不抛异常。"""
    spaces = [KbSpace(id="kb_nodesc", name="无描述库")]
    out = render_kb_catalog(spaces)
    assert "<id>kb_nodesc</id>" in out
    assert "<name>无描述库</name>" in out
