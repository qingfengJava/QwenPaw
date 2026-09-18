# -*- coding: utf-8 -*-
"""wikilink 抽取（Task 6）：正文 ``[[路径]]`` → 出边数据源。

语义（spec §5.3 与 task-6-brief R12）：

- 逐行扫描：wikilink 是行内语法，跨行不成立（未闭合的 ``[[x`` 不产出边）；
- 围栏配对扫描（与切片器同款）：开栏取族标记（``` / ~~~），向后找到同族
  闭合行；围栏内的 ``[[...]]`` 是语法示例不产出边，异族行不解围，未闭合
  围栏吞到文档尾（宁少不假）；
- 同一目标重复出现只保留首次（保序去重），上下文取首次出现行；
- 上下文 = 所在行 strip 后截断 :data:`CONTEXT_LIMIT` 字符（图扩展展示用）。

本模块是纯函数面：dst 解析归一化与落表由摄入服务（``ingest.py``）与
``pg_store`` 的 links 访问器负责。

@author qingfeng
"""

from __future__ import annotations

import re
from typing import List, Tuple

#: 单个 wikilink 目标：非贪婪且不允许内嵌括号（``[[a[b]]`` 不产出边）
_WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")

#: 代码围栏开栏（``` / ~~~ 三连起算，配对扫描语义与切片器同款）
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")

#: 行上下文截断上限（字符数）
CONTEXT_LIMIT = 200


def extract_wikilinks(md_text: str) -> List[Tuple[str, str]]:
    """抽取文档中的 wikilink，返回 ``[(dst_path, context_snippet)]``。

    Args:
        md_text: Markdown 原文（可含 frontmatter 与代码围栏）。

    Returns:
        按首次出现顺序排列的去重 ``(dst_path, context)`` 列表；
        无链接（或全在围栏内）时为空列表。
    """
    found: List[Tuple[str, str]] = []
    seen: set = set()
    lines = (md_text or "").splitlines()
    index = 0
    while index < len(lines):
        fence = _FENCE_RE.match(lines[index])
        if fence:
            # 配对扫描（与切片器同款）：同族标记才有资格闭合，异族行
            # （``` 区内的 ~~~）不解围；未闭合围栏吞到文档尾（宁少不假）
            marker = fence.group(1)[0] * 3
            index += 1
            while index < len(lines):
                closing = lines[index].strip().startswith(marker)
                index += 1
                if closing:
                    break
            continue
        line = lines[index].strip()
        for match in _WIKILINK_RE.finditer(line):
            target = match.group(1).strip()
            if not target or target in seen:
                continue
            seen.add(target)
            found.append((target, line[:CONTEXT_LIMIT]))
        index += 1
    return found


__all__ = [
    "CONTEXT_LIMIT",
    "extract_wikilinks",
]
