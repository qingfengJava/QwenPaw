# -*- coding: utf-8 -*-
"""M6（T6）: wikilink 抽取——保序去重 / 行上下文 / 代码围栏跳过。

@author qingfeng
"""

from __future__ import annotations

import pytest

from qwenpaw.app.kb import links

pytestmark = pytest.mark.unit


def test_extract_wikilinks_with_context() -> None:
    """抽取 [[路径]] 并携带所在行上下文（plan 基准用例）。"""
    md = "妊娠期甲减见 [[孕产/用药/甲减]]，分期标准见 [[妊娠分期]]。\n正文"
    found = links.extract_wikilinks(md)
    assert [path for path, _ in found] == ["孕产/用药/甲减", "妊娠分期"]
    assert "妊娠期甲减" in found[0][1]


def test_extract_wikilinks_dedup_keeps_first() -> None:
    """同一目标重复出现：保序去重，上下文取首次出现处。"""
    md = "先见 [[甲减]]。\n后文又提 [[甲减]] 与 [[分期]]。"
    found = links.extract_wikilinks(md)
    assert [path for path, _ in found] == ["甲减", "分期"]
    assert "先见" in found[0][1]


def test_extract_wikilinks_skips_fenced_code() -> None:
    """代码围栏内的 [[...]] 是语法示例，不得产出边。"""
    md = "正文 [[真链]]\n```\n[[假链]] 语法示例\n```\n尾段 [[尾链]]"
    found = links.extract_wikilinks(md)
    assert [path for path, _ in found] == ["真链", "尾链"]


def test_extract_wikilinks_ignores_empty_and_unclosed() -> None:
    """空路径 [[]] 与未闭合 [[x 不产出边。"""
    md = "空 [[]] 与未闭合 [[x\n正常 [[ok]]"
    found = links.extract_wikilinks(md)
    assert [path for path, _ in found] == ["ok"]


def test_extract_wikilinks_context_capped() -> None:
    """超长行的上下文按 200 字符上限截断。"""
    md = "前" * 300 + " [[目标]]"
    found = links.extract_wikilinks(md)
    assert found and len(found[0][1]) <= 200
