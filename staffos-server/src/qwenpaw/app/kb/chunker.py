# -*- coding: utf-8 -*-
"""Markdown 结构化切片器（知识组织层 → 索引层的唯一入口）。

spec §4.3 的三条不变式在这里落地：

1. **标题路径随行**：每个切片携带 ``h1 > h2 > h3`` 形式的 ``heading_path``，
   并由 :func:`embed_input` 拼进 embedding 输入。像「TSH 目标」「妊娠早期」
   这类只出现在标题里的专有名词，否则在向量空间里完全不可见——这是
   「向量库直建但检索不出来」的主要成因之一。
2. **表格与代码块原子**：二者整体成一个切片，永不按行拆散，也不与邻近
   段落打包（混排会让关键词命中段落却召回整块表格文本）。宁可单块超出
   token 预算，也不产生半张表。
3. **父子回补**：同一小节被拆成多块时，首块是该节的父切片，**本节所有非首块**
   的 ``parent_seq`` 都指向首块（不是指向上一块）；命中任一子块时检索端可据
   此拉回整节上下文（Task 5 的 ``expand=section`` 依赖此字段）。
4. **内容零丢失**：重叠前缀吃掉预算时被截断的残段会结转入下一块，任何分支
   都不得少字符——切片器宁可多切一块，也不能静默吞掉文档内容。

刻意不引入 Markdown 解析库：本模块只需要「标题层级 / 围栏 / 表格行」三种
结构信号，行级扫描即可覆盖，而给 fork 仓库新增运行时依赖会长期放大与上游
合并的冲突面。围栏内的 ``#`` 与 ``|`` 不会被误当作标题或表格。

已知结构限制（刻意不做，改动前请先对齐）：

- 只识别 ATX 标题（``#`` 前缀），不支持 Setext 下划线式标题（``===`` / ``---``）：
  ``---`` 与 frontmatter 分隔线、水平线语义冲突，误判代价高于收益。
- 表格识别以「行首（可带引用标记 ``>`` 与缩进）为 ``|``」为准，不校验分隔行；
  因此正文中孤立以 ``|`` 开头的段落行会被当作表格整体成块（保守，不丢内容）。

三态与持久化不属于本模块：切片器是纯函数，写库由 Task 6 的摄入服务负责。

@author qingfeng
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

#: 单块目标 token 数（spec §4.3：600，兼顾召回粒度与上下文完整度）
DEFAULT_TARGET_TOKENS = 600

#: 跨块续读时携带的上一块尾部字符数（0 表示关闭重叠）
DEFAULT_OVERLAP_CHARS = 100

#: 标题栈连接符（读模型与前端面包屑共用同一形式）
HEADING_SEPARATOR = " > "

#: 重叠前缀与正文之间的分隔符（换行不计 token，但可阻断跨块融合 token）
OVERLAP_SEPARATOR = "\n"

_ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
# 行首允许缩进与引用标记（``> | a | b |`` 中的表格仍是一张表），否则引用块
# 里的表格会被降级成普通段落，被按 token 预算逐行拆散。
_TABLE_ROW_RE = re.compile(r"^[ \t]*(?:>[ \t]*)*\|")
# 日文假名与中文同处 CJK 区块，检索需求一致，故共用同一 token 权重
_CJK_RANGES = (
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
)


@dataclass(frozen=True)
class ChunkSpec:
    """一个可检索切片（Task 5/6 依赖的字段契约）。"""

    seq: int
    heading_path: str
    text: str
    parent_seq: Optional[int]
    token_count: int


@dataclass(frozen=True)
class _Block:
    """文档结构块；``atomic`` 为真时禁止拆散与打包。"""

    text: str
    atomic: bool


def _is_cjk(char: str) -> bool:
    """判定单个字符是否落在 CJK 统一表意/假名区块。"""
    code = ord(char)
    return any(start <= code <= end for start, end in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """中英混排的 token 估算（CJK 约 1 token/字，其余约 4 字符/token）。

    刻意不依赖 tiktoken：仓内未安装该依赖，且切片预算只需单调一致的度量，
    不需要与某家 tokenizer 逐 token 对齐。空白字符不计入拉丁预算。
    """
    cjk = 0
    latin = 0
    for char in text:
        if _is_cjk(char):
            cjk += 1
        elif not char.isspace():
            latin += 1
    return cjk + math.ceil(latin / 4)


def _cut_by_tokens(text: str, budget: int) -> int:
    """返回最长前缀的字符数，使该前缀的估算 token 不超过 *budget*。"""
    if budget <= 0:
        return 0
    cjk = 0
    latin = 0
    for index, char in enumerate(text):
        if _is_cjk(char):
            next_cjk, next_latin = cjk + 1, latin
        elif char.isspace():
            next_cjk, next_latin = cjk, latin
        else:
            next_cjk, next_latin = cjk, latin + 1
        if next_cjk + math.ceil(next_latin / 4) > budget:
            return index
        cjk, latin = next_cjk, next_latin
    return len(text)


def split_frontmatter(md_text: str) -> Tuple[str, str]:
    """拆出 YAML frontmatter 与正文；无 frontmatter 时原样返回。

    元数据本身交给 Task 6 解析入库，不混进检索文本，避免「title:」这类
    噪声被切进切片并参与相似度计算。
    """
    if not md_text.startswith("---"):
        return "", md_text
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", md_text
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            body_start = index + 1
            meta = "\n".join(lines[1:index])
            body = "\n".join(lines[body_start:])
            return meta, body
    # 未闭合的 --- 视为正文而非元数据（宁可不剥离，也不吞掉整篇文档）
    return "", md_text


def _sections_of(body: str) -> List[Tuple[str, List[_Block]]]:
    """把正文扫成 ``[(heading_path, blocks)]``。

    行级状态机：围栏块与表格块整体收集，ATX 标题维护层级栈并在标题处切节。
    """
    sections: List[Tuple[str, List[_Block]]] = []
    stack: List[Tuple[int, str]] = []
    path = ""
    blocks: List[_Block] = []
    paragraph: List[str] = []

    def close_paragraph() -> None:
        if paragraph:
            blocks.append(
                _Block(text="\n".join(paragraph).strip(), atomic=False),
            )
            paragraph.clear()

    def close_section() -> None:
        close_paragraph()
        if blocks:
            sections.append((path, list(blocks)))
        blocks.clear()

    lines = body.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]

        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)[0] * 3
            collected = [line]
            index += 1
            while index < len(lines):
                collected.append(lines[index])
                closing = lines[index].strip().startswith(marker)
                index += 1
                if closing:
                    break
            close_paragraph()
            blocks.append(_Block(text="\n".join(collected), atomic=True))
            continue

        if _TABLE_ROW_RE.match(line):
            collected = []
            while index < len(lines) and _TABLE_ROW_RE.match(lines[index]):
                collected.append(lines[index])
                index += 1
            close_paragraph()
            blocks.append(_Block(text="\n".join(collected), atomic=True))
            continue

        heading = _ATX_HEADING_RE.match(line)
        if heading:
            close_section()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            stack = [entry for entry in stack if entry[0] < level]
            stack.append((level, title))
            path = HEADING_SEPARATOR.join(title for _, title in stack)
            index += 1
            continue

        if not line.strip():
            close_paragraph()
            index += 1
            continue

        paragraph.append(line)
        index += 1

    close_section()
    return sections


def _pack_section(
    blocks: List[_Block],
    target_tokens: int,
) -> List[Tuple[str, bool]]:
    """把一节打包成 ``(text, atomic)`` 序列，长段按 token 预算硬切。

    只负责「结构成块 + 预算硬切」，重叠前缀交给 :func:`_apply_overlap`，
    以免两个地方都可以截文本。返回元素顺序即阅读顺序；本函数保证
    拼接后逐字符等于节内原文（按 ``\\n\\n`` 连接）。
    """
    packed: List[Tuple[str, bool]] = []
    buffer: List[str] = []
    buffer_tokens = 0

    def flush() -> None:
        if buffer:
            packed.append(("\n\n".join(buffer), False))
            buffer.clear()

    for block in blocks:
        if block.atomic:
            flush()
            packed.append((block.text, True))
            continue
        block_tokens = estimate_tokens(block.text)
        if buffer and buffer_tokens + block_tokens > target_tokens:
            flush()
            buffer_tokens = 0
        buffer.append(block.text)
        buffer_tokens += block_tokens
        # 单段本身就超预算时，立即切成完整块，不留半截缓冲
        while buffer and buffer_tokens > target_tokens:
            joined = "\n\n".join(buffer)
            cut = _cut_by_tokens(joined, target_tokens)
            if cut <= 0:
                break
            packed.append((joined[:cut], False))
            buffer[:] = [joined[cut:]]
            buffer_tokens = estimate_tokens(buffer[0]) if buffer else 0
    flush()
    return packed


def _apply_overlap(
    packed: List[Tuple[str, bool]],
    target_tokens: int,
    overlap_chars: int,
) -> List[str]:
    """为同节连续的 prose 块补上「上一块尾部」重叠前缀，保证零丢失。

    前缀与正文之间注入 :data:`OVERLAP_SEPARATOR`：换行不耗 token，却阻断
    上一块末词与本块首词被拼成 ``wordawordb`` 这种分词器打不出的融合 token。
    前缀吃掉预算时先舍前缀、保住单块不超预算；正文装不下的残段**结转入队**
    而非丢弃。本函数是全模块唯一会截文本的地方，因此每个分支都必须
    先把残段放回队列再截短。
    """
    chunks: List[str] = []
    queue = list(packed)
    tail = ""
    while queue:
        text, atomic = queue.pop(0)
        if atomic:
            # 原子块不参与重叠：下一块若仍是 prose，也不能从表格/代码尾部长出来
            chunks.append(text)
            tail = ""
            continue
        prefix = tail[-overlap_chars:] if overlap_chars > 0 else ""
        body = text
        if prefix:
            room = target_tokens - estimate_tokens(prefix)
            cut = _cut_by_tokens(body, room)
            if cut <= 0:
                # 前缀已吃满预算：宁可不要重叠，也不能让单块超预算
                prefix, cut = "", _cut_by_tokens(body, target_tokens)
            if cut < len(body):
                queue.insert(0, (body[cut:], False))
                body = body[:cut]
        chunk_text = f"{prefix}{OVERLAP_SEPARATOR}{body}" if prefix else body
        chunks.append(chunk_text)
        tail = chunk_text
    return chunks


def split_markdown(
    md_text: str,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> List[ChunkSpec]:
    """按文档结构切片；空文档返回空列表而非抛错。

    Args:
        md_text: Markdown 原文（可含 YAML frontmatter，会被剥离）。
        target_tokens: 单块 token 预算，原子块可超出；必须 >= 1。
        overlap_chars: 同节 prose 续块携带的上一块尾部字符数，0 关闭。

    Returns:
        按阅读顺序编号（``seq`` 自 0 连续）的 :class:`ChunkSpec` 列表。

    Raises:
        ValueError: ``target_tokens`` 小于 1（零预算会令任何文本都切不出内容）。
    """
    if target_tokens < 1:
        raise ValueError("target_tokens 必须大于等于 1")
    if not md_text or not md_text.strip():
        return []
    _, body = split_frontmatter(md_text)
    specs: List[ChunkSpec] = []
    for path, blocks in _sections_of(body):
        packed = _pack_section(blocks, target_tokens)
        first_seq: Optional[int] = None
        for chunk_text in _apply_overlap(packed, target_tokens, overlap_chars):
            seq = len(specs)
            if first_seq is None:
                first_seq = seq
            specs.append(
                ChunkSpec(
                    seq=seq,
                    heading_path=path,
                    text=chunk_text,
                    parent_seq=None if seq == first_seq else first_seq,
                    token_count=estimate_tokens(chunk_text),
                ),
            )
    return specs


def embed_input(chunk: ChunkSpec) -> str:
    """embedding 输入 = 标题路径 + 正文（spec §4.3 的关键设计）。"""
    if not chunk.heading_path:
        return chunk.text
    return f"{chunk.heading_path}\n{chunk.text}"


__all__ = [
    "ChunkSpec",
    "DEFAULT_OVERLAP_CHARS",
    "DEFAULT_TARGET_TOKENS",
    "HEADING_SEPARATOR",
    "OVERLAP_SEPARATOR",
    "embed_input",
    "estimate_tokens",
    "split_frontmatter",
    "split_markdown",
]
