# -*- coding: utf-8 -*-
"""wikilink 抽取（Task 6）：正文 ``[[路径]]`` → 出边数据源。

语义（spec §5.3 与 task-6-brief R12）：

- 逐行扫描：wikilink 是行内语法，跨行不成立（未闭合的 ``[[x`` 不产出边）；
- 跳过代码围栏（``` / ~~~）内的行：那里的 ``[[...]]`` 是语法示例；
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

#: 代码围栏开关（``` / ~~~ 三连起算，与切片器的围栏口径一致）
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
    fenced = False
    for raw_line in (md_text or "").splitlines():
        if _FENCE_RE.match(raw_line):
            # 围栏边界行：翻转状态，自身不参与抽取
            fenced = not fenced
            continue
        if fenced:
            continue
        line = raw_line.strip()
        for match in _WIKILINK_RE.finditer(line):
            target = match.group(1).strip()
            if not target or target in seen:
                continue
            seen.add(target)
            found.append((target, line[:CONTEXT_LIMIT]))
    return found


__all__ = [
    "CONTEXT_LIMIT",
    "extract_wikilinks",
]
