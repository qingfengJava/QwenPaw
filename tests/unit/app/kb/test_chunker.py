# -*- coding: utf-8 -*-
"""M6-3: 结构化切片器——标题路径保留 / 表格与代码块不拆 / 长节父子回补。

切片是检索质量的地基：`heading_path` 让「TSH 目标」这类只在标题里出现的
专有名词进入 embedding 输入，父子 seq 让命中子块时能拉回整节上下文。

@author qingfeng
"""

from __future__ import annotations

from typing import List

import pytest

from qwenpaw.app.kb.chunker import (
    OVERLAP_SEPARATOR,
    ChunkSpec,
    embed_input,
    estimate_tokens,
    split_markdown,
)
from qwenpaw.app.kb.search import tokenize_mixed

pytestmark = pytest.mark.unit

_MD = """# 孕产用药

## 甲减

### 妊娠早期
左甲状腺素剂量需增加约 20%-30%，每 4 周复查 TSH。

| 分期 | TSH 目标 |
| --- | --- |
| 早期 | <2.5 |
| 中期 | <3.0 |
"""


def _texts(chunks: List[ChunkSpec]) -> List[str]:
    """取全部切片正文，便于断言包含关系。"""
    return [c.text for c in chunks]


# ---------------------------------------------------------------------------
# 标题路径
# ---------------------------------------------------------------------------


def test_heading_path_attached_to_chunks() -> None:
    """每个切片携带完整标题路径。"""
    chunks = split_markdown(_MD)
    target = next(c for c in chunks if "左甲状腺素" in c.text)
    assert target.heading_path == "孕产用药 > 甲减 > 妊娠早期"
    assert "孕产用药 > 甲减 > 妊娠早期" in embed_input(target)


def test_heading_path_is_not_cumulative_across_siblings() -> None:
    """同级标题替换栈顶，不得把兄弟节的路径也带上。"""
    md = "# A\n## B\n甲\n## C\n乙\n"

    chunks = split_markdown(md)
    paths = {c.heading_path for c in chunks}

    assert "A > B" in paths
    assert "A > C" in paths
    assert "A > B > C" not in paths


def test_deeper_heading_pops_when_level_rises() -> None:
    """从 H3 回到 H2 时，H3 层必须出栈。"""
    md = "# A\n## B\n### C\n甲\n## D\n乙\n"

    chunks = split_markdown(md)
    child = next(c for c in chunks if "乙" in c.text)

    assert child.heading_path == "A > D"


def test_document_without_headings_has_empty_path() -> None:
    """无标题文档 heading_path 为空串，embed_input 退化为正文。"""
    md = "第一段。\n\n第二段。\n"

    chunks = split_markdown(md)

    assert chunks
    assert chunks[0].heading_path == ""
    assert embed_input(chunks[0]) == "第一段。\n\n第二段。"


def test_heading_only_section_emits_nothing() -> None:
    """只有标题没有正文的章节不产出切片（避免零信息 chunk 污染召回）。"""
    md = "# A\n## B\n## C\n正文\n"

    chunks = split_markdown(md)

    assert len(chunks) == 1
    assert chunks[0].text == "正文"


# ---------------------------------------------------------------------------
# 原子块：表格与代码块整体成 chunk
# ---------------------------------------------------------------------------


def test_table_kept_whole() -> None:
    """表格整体成 chunk，禁止按行拆散。"""
    chunks = split_markdown(_MD)
    table_chunk = next(c for c in chunks if c.text.lstrip().startswith("|"))
    assert "早期" in table_chunk.text and "中期" in table_chunk.text


def test_table_is_never_packed_with_prose() -> None:
    """表格不并入邻近段落：混排会让 BM25 命中段落却召回整块表格文本。"""
    chunks = split_markdown(_MD)
    prose = next(c for c in chunks if "左甲状腺素" in c.text)
    table = next(c for c in chunks if c.text.lstrip().startswith("|"))

    assert "|" not in prose.text
    assert "左甲状腺素" not in table.text


def test_long_table_not_split_even_below_target() -> None:
    """超目标长度的表格仍保持整体（宁可超预算也不拆行）。"""
    rows = "\n".join(f"| 行{i} | 值{i} |" for i in range(200))
    md = f"# T\n\n| 名称 | 值 |\n| --- | --- |\n{rows}\n"

    chunks = split_markdown(md, target_tokens=60)
    tables = [c for c in chunks if c.text.lstrip().startswith("|")]

    assert len(tables) == 1
    assert "行199" in tables[0].text


def test_fenced_code_block_is_atomic() -> None:
    """围栏代码块整体成 chunk，块内的 # 与 | 不得被当作结构标记。"""
    md = (
        "# T\n\n## 示例\n\n"
        "```python\n"
        "# 这是注释不是标题\n"
        "def f():\n"
        "    return 1\n"
        "```\n\n"
        "后续段落。\n"
    )

    chunks = split_markdown(md)
    code = next(c for c in chunks if c.text.startswith("```"))

    assert "这是注释不是标题" in code.text
    assert "return 1" in code.text
    assert "后续段落" not in code.text
    assert all(
        "这是注释不是标题" not in c.text for c in chunks if c is not code
    )


def test_code_block_heading_does_not_create_section() -> None:
    """代码块内的 ``# 注释`` 不进标题栈。"""
    md = "# T\n\n```\n# 注释\n```\n\n正文\n"

    chunks = split_markdown(md)

    assert {c.heading_path for c in chunks} == {"T"}


def test_table_inside_blockquote_stays_atomic() -> None:
    """引用块内的表格同样整体成块，不得被降级为段落逐行拆散。"""
    md = (
        "# T\n\n## 注意\n\n"
        "> | 分期 | TSH 目标 |\n"
        "> | --- | --- |\n"
        "> | 早期 | <2.5 |\n"
        "> | 中期 | <3.0 |\n"
    )

    chunks = split_markdown(md, target_tokens=10)
    tables = [c for c in chunks if "|" in c.text]

    assert len(tables) == 1
    assert "早期" in tables[0].text and "中期" in tables[0].text


# ---------------------------------------------------------------------------
# 长度控制与父子回补
# ---------------------------------------------------------------------------


def test_long_section_parent_linkage() -> None:
    """超长段拆出的子块 parent_seq 指向父语义块（首块 parent 为 None）。"""
    long_md = "# T\n## H\n" + "\n\n".join("段" * 500 for _ in range(6))
    chunks = split_markdown(long_md)
    assert len(chunks) >= 2
    child = next(c for c in chunks if c.parent_seq is not None)
    assert any(c.seq == child.parent_seq for c in chunks)


def test_parent_seq_points_to_first_chunk_of_section() -> None:
    """父子关系按节成立：每个子块指向本节首块，而非上一块。"""
    md = "# T\n## A\n" + "甲" * 500 + "\n\n" + "乙" * 500 + "\n\n## B\n短\n"

    chunks = split_markdown(md, target_tokens=400)
    section_a = [c for c in chunks if c.heading_path == "T > A"]
    section_b = [c for c in chunks if c.heading_path == "T > B"]

    assert len(section_a) >= 2
    assert section_a[0].parent_seq is None
    assert all(c.parent_seq == section_a[0].seq for c in section_a[1:])
    assert section_b[0].parent_seq is None


def test_seq_is_contiguous_from_zero() -> None:
    """seq 从 0 连续递增（Task 5 按 seq 排序还原阅读顺序）。"""
    md = "# T\n## A\n一段\n\n## B\n" + "乙" * 900 + "\n"

    chunks = split_markdown(md, target_tokens=400)

    assert [c.seq for c in chunks] == list(range(len(chunks)))


def test_prose_chunks_respect_target_tokens() -> None:
    """普通切片不超过目标 token（表格/代码原子块例外）。"""
    md = "# T\n## A\n" + "\n\n".join("内容" * 80 for _ in range(20))

    chunks = split_markdown(md, target_tokens=200)

    assert len(chunks) > 1
    assert all(c.token_count <= 200 for c in chunks)


def _marker_text(count: int, *, offset: int = 0) -> str:
    """生成逐个不重复的标记文本（5 字符一格，便于逐字符验证硬切与零丢失）。"""
    return "".join(f"[{i:03d}]" for i in range(offset, offset + count))


def _squash(text: str) -> str:
    """去掉全部空白：段落间空行属排版而非内容，不参与零丢失比对。"""
    return "".join(text.split())


def _new_content(chunks: List[ChunkSpec], overlap_chars: int) -> str:
    """剥掉续块携带的重叠前缀（含注入换行），拼回各块真正的新增内容。

    这是「内容零丢失 + 块间无空隙」不变式的验证手段：结果必须逐字符
    等于源正文，任何一处截断少字符都会在这里暴露。
    """
    pieces: List[str] = []
    previous = ""
    for chunk in chunks:
        text = chunk.text
        prefix = previous[-overlap_chars:] if previous else ""
        cut = len(prefix) + len(OVERLAP_SEPARATOR)
        if prefix and text.startswith(prefix + OVERLAP_SEPARATOR):
            text = text[cut:]
        pieces.append(text)
        previous = chunk.text
    return "".join(pieces)


def test_continuation_carries_overlap_context() -> None:
    """跨块续读携带上一块尾部文字，且新增内容紧接上块末尾无空隙。"""
    src = _marker_text(200)
    md = f"# T\n## A\n{src}\n"

    chunks = split_markdown(md, target_tokens=100, overlap_chars=8)

    assert len(chunks) >= 2
    prefix = chunks[0].text[-8:]
    assert chunks[1].text.startswith(prefix + OVERLAP_SEPARATOR)
    assert chunks[1].parent_seq == chunks[0].seq
    # 去掉重叠前缀后的新内容，必须正好接在上块末尾之后（源文本无空隙）
    boundary = len(prefix) + len(OVERLAP_SEPARATOR)
    new_content = chunks[1].text[boundary:]
    consumed = len(chunks[0].text)
    assert src.startswith(chunks[0].text)
    assert src[consumed:].startswith(new_content)


def test_overlap_disabled_by_zero() -> None:
    """overlap_chars=0 时续块不加前缀（供调用方关闭重叠）。"""
    md = f"# T\n## A\n{_marker_text(200)}\n"

    chunks = split_markdown(md, target_tokens=100, overlap_chars=0)

    assert len(chunks) >= 2
    assert not chunks[1].text.startswith(chunks[0].text[-8:])
    assert chunks[1].text.startswith("[080]")


def test_overlap_prefix_is_lossless_within_budget() -> None:
    """P0 不变式：加重叠前缀后被截断的残段必须结转入下一块，不得丢弃。"""
    src = _marker_text(200)
    md = f"# T\n## A\n{src}\n"

    chunks = split_markdown(md, target_tokens=100, overlap_chars=8)

    assert len(chunks) >= 3
    assert _new_content(chunks, 8) == src


def test_overlap_prefixing_is_lossless_across_paragraphs() -> None:
    """多段落混排同样零丢失：每个标记必须恰好出现一次于新内容拼接结果。"""
    paras = [
        _marker_text(60, offset=0),
        _marker_text(60, offset=60),
        _marker_text(60, offset=120),
    ]
    md = "# T\n## A\n" + "\n\n".join(paras) + "\n"

    chunks = split_markdown(md, target_tokens=100, overlap_chars=12)

    assert _squash(_new_content(chunks, 12)) == _squash("".join(paras))


def test_oversized_prefix_drops_overlap_but_keeps_budget_and_content() -> None:
    """前缀吃满预算时舍前缀：单块仍不超预算，且内容一字不丢。"""
    src = _marker_text(120)
    md = f"# T\n## A\n{src}\n"

    chunks = split_markdown(md, target_tokens=6, overlap_chars=40)

    assert all(c.token_count <= 6 for c in chunks)
    assert _new_content(chunks, 40) == src


def test_overlap_separator_prevents_fused_tokens() -> None:
    """前缀与正文之间必须有分隔，否则跨块首尾词会黏成一个新 token。"""
    source = "alpha bravo charlie delta echo foxtrot golf " * 30
    md = f"# T\n## A\n{source}\n"

    chunks = split_markdown(md, target_tokens=40, overlap_chars=6)

    prefix, separator, body = chunks[1].text.partition(OVERLAP_SEPARATOR)
    assert separator, "重叠前缀与正文之间缺分隔符"
    assert chunks[0].text.endswith(prefix)
    assert tokenize_mixed(chunks[1].text) == (
        tokenize_mixed(prefix) + tokenize_mixed(body)
    )


# ---------------------------------------------------------------------------
# frontmatter 与 token 估算
# ---------------------------------------------------------------------------


def test_frontmatter_is_stripped_from_chunks() -> None:
    """YAML 头不进检索文本（它是元数据，不是知识内容）。"""
    md = "---\ntitle: 孕产指南\ntags: [endocrine]\n---\n\n# T\n\n正文\n"

    chunks = split_markdown(md)

    assert len(chunks) == 1
    assert chunks[0].text == "正文"
    assert "title" not in chunks[0].text


def test_split_frontmatter_returns_raw_block() -> None:
    """frontmatter 原样返回给调用方解析（Task 6 读元数据）。"""
    from qwenpaw.app.kb.chunker import split_frontmatter

    meta, body = split_frontmatter("---\ntitle: x\n---\n# T\n\n正文\n")

    assert "title: x" in meta
    assert body.startswith("# T")


def test_split_frontmatter_absent_is_noop() -> None:
    """无 frontmatter 时原样返回，不误删首个标题行。"""
    from qwenpaw.app.kb.chunker import split_frontmatter

    meta, body = split_frontmatter("# T\n\n正文\n")

    assert meta == ""
    assert body.startswith("# T")


def test_estimate_tokens_counts_cjk_and_latin_differently() -> None:
    """CJK 约 1 token/字，拉丁约 4 字符/token（避免中文被高估、英文被低估）。"""
    assert estimate_tokens("甲乙丙丁") == 4
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("甲乙 abcd") == 3


def test_estimate_tokens_empty_is_zero() -> None:
    """空文本 token 为 0（表格/代码块打包时的边界）。"""
    assert estimate_tokens("") == 0


# ---------------------------------------------------------------------------
# 契约稳定性
# ---------------------------------------------------------------------------


def test_chunk_spec_fields_are_the_task5_contract() -> None:
    """Task 5/6 依赖的字段名固定：seq/heading_path/text/parent_seq/token_count。"""
    chunk = split_markdown(_MD)[0]

    assert isinstance(chunk, ChunkSpec)
    assert {
        "seq",
        "heading_path",
        "text",
        "parent_seq",
        "token_count",
    } == {f for f in chunk.__dataclass_fields__}


def test_empty_document_yields_no_chunks() -> None:
    """空输入返回空列表而非抛错（摄入端要对上传空文件兜底）。"""
    assert split_markdown("") == []
    assert split_markdown("   \n\n  \n") == []


def test_non_positive_target_tokens_is_rejected() -> None:
    """零/负预算无法切出任何内容，必须报错而非静默产出空列表。"""
    with pytest.raises(ValueError):
        split_markdown("# T\n\n正文\n", target_tokens=0)
    with pytest.raises(ValueError):
        split_markdown("# T\n\n正文\n", target_tokens=-5)


# ---------------------------------------------------------------------------
# 共享分词器（切片端与检索端必须同一套词表）
# ---------------------------------------------------------------------------


def test_tokenize_mixed_exported() -> None:
    """共享分词器兼容 CJK bigram 与英文词。"""
    toks = tokenize_mixed("甲减 levothyroxine")

    assert "levothyroxine" in toks
    assert "甲减" in toks


def test_chunk_text_is_tokenizable_by_shared_tokenizer() -> None:
    """切片正文必须能被共享分词器打出非空 token（否则该块永不可关键词命中）。"""
    for chunk in split_markdown(_MD):
        assert tokenize_mixed(embed_input(chunk)), f"empty tokens: {chunk.seq}"
