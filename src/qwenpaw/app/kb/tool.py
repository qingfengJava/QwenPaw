# -*- coding: utf-8 -*-
"""``kb_search`` / ``kb_read`` agent tools: retrieval over bound bases.

T10-S0 绑定收敛（spec §6 L171 + §8 决策点1 L240「绑定即授权」）：agent
工具链的检索可见域 = ``agent_kb_bindings(agent_id)``，**不叠加**对话人
ACL（严格模式一期不开启）。工具由 :class:`AgentBuilder` 仅在 agent 有
绑定库时注册（见 builder._collect_kb_tools），无绑定则 prompt 零变化。
人侧 HTTP ``/api/kb/search`` 不受影响，始终走既有 ``can_access`` ACL。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from .service import KbService, get_kb_service

logger = logging.getLogger(__name__)

_MAX_SNIPPET_CHARS = 600

#: S2 expand=section 单节合并全文的字符上限（一节可跨多块，预算高于单块）
_MAX_SECTION_CHARS = 2400

#: S2 expand=section 全部命中的总输出预算：对齐 ToolResultPruningMiddleware
#: 的裁剪阈值，防「小节扩展放大输出反被上下文层截断」抵消收益（每节
#: 额度按命中数动态分配，总额不超此值）。
_MAX_TOTAL_CHARS = 16000

#: expand 合法取值（T5 起 graph 实装：wikilink 出边图 ≤3 跳；
#: 未支持值显式报错而非静默降级）
_VALID_EXPAND = frozenset({"none", "section", "graph"})

#: expand=graph 相关文档链的行数上限（预算友好的延伸阅读）
_MAX_GRAPH_LINES = 12

#: S3 精排候选池大小（spec §6 L181：候选 20 → qwen3-rerank → top max_results）。
#: per-kb 检索超量取回此数，融合后取前 20 交精排；缺凭证时精排原序截断。
_RERANK_CANDIDATES = 20


def _tool_chunk(text: str, *, ok: bool = True) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS if ok else ToolResultState.ERROR,
        content=[TextBlock(type="text", text=text)],
    )


def _clip(text: str, limit: int) -> str:
    """按字符预算截断，超出加省略号（单块 snippet 用）。"""
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _section_key(chunk: Any) -> int:
    """小节精确键（chunker 父子回补不变式）。

    同节非首块 ``parent_seq`` 指向节首块 seq，节首块 ``parent_seq`` 为 None
    → 用自身 seq。故同节所有块 section_key 相同；文档内**同名 heading_path**
    的两个不同小节因节首 seq 不同而键不同，不会被误并（比按 heading 字符串
    归组更精确）。parent_seq 缺失（L0/扁平切片）→ 退化为按 seq 各自成节。
    """
    parent = getattr(chunk, "parent_seq", None)
    if parent is not None:
        return int(parent)
    return int(getattr(chunk, "seq", 0) or 0)


def _join_blocks_cap(texts: list, limit: int) -> tuple[str, int, int]:
    """按块边界拼接兄弟块，超预算即停（不切断块/表格/代码）。

    返回 ``(拼接文本, 已含块数, 总块数)``；``已含 < 总`` 时调用方追加省略
    标记，使「小节被截断」对 agent 可见（不静默丢证据）。至少保留首块。
    """
    kept: list = []
    total = 0
    for text in texts:
        extra = len(text) + (2 if kept else 0)
        if kept and total + extra > limit:
            break
        kept.append(text)
        total += extra
    return "\n\n".join(kept), len(kept), len(texts)


def _build_section_index(svc: KbService, top: list) -> dict:
    """预建 ``{(kb_id, doc_id, section_key): (heading, [块文本 by seq])}``。

    S2 expand=section 核心（brief D5 + 审查修复）：
    - 每份文档只调一次 ``svc.document_chunks``（防 per-hit N+1，规范 §2.4）；
    - 取数用**命中元组里 S0 校验过的** ``kb.id``（非数据行 ``chunk.kb_id``），
      键含 kb 维度 → 绝不因扩展触碰未绑定库（AC5），且同 doc_id 跨库不串号；
    - 仅为**命中所在小节**归组（section_key 精确键），不为整篇所有小节建索引；
    - heading_path 空的命中不入索引（L0/json 面 → 调用方降级为单块）。
    每 doc 取数异常隔离（WARN + 跳过该 doc），绝不抛穿「永不报错的检索」。
    """
    # (kb.id, doc_id) → 命中的 section_key 集（仅 heading_path 非空的命中）
    wanted: dict = {}
    for kb, chunk, _score in top:
        heading = getattr(chunk, "heading_path", "") or ""
        if not heading:
            continue
        wanted.setdefault((kb.id, chunk.doc_id), set()).add(
            _section_key(chunk),
        )
    index: dict = {}
    for (kb_id, doc_id), keys in wanted.items():
        try:
            siblings = svc.document_chunks(kb_id, doc_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] document_chunks failed; degrade doc=%s",
                doc_id,
                exc_info=True,
            )
            continue
        # 同文档内按 section_key 归组（仅命中所在小节），seq 升序
        groups: dict = {}
        for c in sorted(siblings, key=lambda x: x.seq):
            sk = _section_key(c)
            if sk in keys:
                groups.setdefault(sk, []).append(c)
        for sk, chunks in groups.items():
            heading = next(
                (
                    getattr(c, "heading_path", "") or ""
                    for c in chunks
                    if getattr(c, "heading_path", "")
                ),
                "",
            )
            index[(kb_id, doc_id, sk)] = (heading, [c.text for c in chunks])
    return index


def _current_identity() -> tuple[str, dict]:
    """Trusted caller identity + RBAC context.

    T10-S0 起 agent 工具链改走绑定收敛（绑定即授权），本函数**一期不再
    用于 scope**；保留供未来「严格模式」（agent 检索再 ∩ 对话人可见库，
    spec §8 L243 预留）复用其 RBAC 解析，勿删。
    """
    try:
        from ..agent_context import get_current_user_id
        from ..rbac.deps import _resolve_flat_role
        from ..rbac.store import get_rbac_store

        username = get_current_user_id() or ""
        flat_role = _resolve_flat_role(username) if username else ""
        store = get_rbac_store()
        return username, {
            "flat_role": flat_role,
            "user_roles": store.roles_for_user(username, flat_role),
            "user_teams": store.teams_for_user(username),
        }
    except Exception:  # pylint: disable=broad-except
        return "", {}


def make_kb_search_tool(
    service: Optional[KbService] = None,
    agent_id: str = "",
) -> Callable[..., Any]:
    """Build the ``kb_search`` tool bound to a KB service + agent.

    T10-S0 绑定收敛：检索可见域 = ``list_bound_space_ids(agent_id)``，
    绑定即授权（spec §8 决策点1），不叠加对话人 ACL。
    """
    svc = service or get_kb_service()

    async def kb_search(
        query: str,
        kb_id: str = "",
        max_results: int = 5,
        expand: str = "none",
    ) -> ToolChunk:
        """Search the knowledge bases bound to you for relevant snippets.

        Use this tool to answer questions about shared company/team
        documents: policies, runbooks, product specs, meeting notes that
        were ingested into a knowledge base. Only knowledge bases bound
        to you are searched. For the user's personal long-term memory,
        use ``memory_search`` instead.

        Args:
            query (`str`):
                The search query describing what to find.
            kb_id (`str`, optional):
                Restrict the search to one of your bound knowledge bases;
                empty searches every base bound to you.
            max_results (`int`, optional):
                Maximum snippets to return. Defaults to 5.
            expand (`str`, optional):
                ``"section"`` expands each hit to its full section (all
                sibling chunks under the same heading), giving more context
                than the matched snippet alone; ``"graph"`` appends the
                wiki-link related-document chain (up to 3 hops, pg plane
                only — honestly degrades to no chain elsewhere); ``"none"``
                (default) returns just the matched snippet. Section
                expansion needs a structure-aware backend (pg/milvus); on
                the file backend it gracefully degrades to the single
                snippet.

        Returns:
            `ToolResponse`:
                Ranked snippets with knowledge base and document titles.
        """
        query = (query or "").strip()
        if not query:
            return _tool_chunk("Error: query cannot be empty", ok=False)

        # S0 权限收敛（先过滤后检索，杜绝越权召回，spec §6 L171-172）：
        # 候选 space_ids = agent 绑定集 ∩ kb_id；每次调用重解析绑定，
        # 绑定撤销下次调用即生效（不用 build 期快照）。
        from .bindings import list_bound_space_ids

        bound_ids = set(await list_bound_space_ids(agent_id))
        if kb_id:
            # 未绑定或不存在合并 not-found，不泄露库存在性/绑定态（R2）
            if kb_id not in bound_ids:
                return _tool_chunk(
                    f"Error: knowledge base '{kb_id}' not found",
                    ok=False,
                )
            kb = svc.get_kb(kb_id)
            if kb is None:
                return _tool_chunk(
                    f"Error: knowledge base '{kb_id}' not found",
                    ok=False,
                )
            kbs = [kb]
        else:
            # 绑定集 ∩ 现存库（孤绑定库已删自然过滤）
            kbs = [kb for kb in svc.list_kbs() if kb.id in bound_ids]
        if not kbs:
            return _tool_chunk("(no bound knowledge bases)")

        cap = max(1, min(int(max_results or 5), 20))

        # expand 白名单校验（先于检索，非法值不浪费 S1/S3）：未支持值
        # （含尚未实装的 graph）显式报错，不静默按 none 降级。
        expand_mode = str(expand or "none").strip().lower()
        if expand_mode not in _VALID_EXPAND:
            return _tool_chunk(
                f"Error: expand must be one of {sorted(_VALID_EXPAND)}",
                ok=False,
            )

        # S1 库内混合检索：超量取回候选池供 S3 精排（rerank.py L102 要求
        # 超量取回，否则精排只能在已截断小集合内换位，收益有限）。
        hits: list[tuple[Any, Any, float]] = []
        for kb in kbs:
            for chunk, score in svc.search(
                kb.id,
                query,
                top_k=_RERANK_CANDIDATES,
            ):
                hits.append((kb, chunk, score))
        if not hits:
            return _tool_chunk("(no matching knowledge snippets)")
        hits.sort(key=lambda item: item[2], reverse=True)

        # S3 rerank（融合后、截断前、expand 前，plan L819 / spec §6 L181）：
        # 候选池交 qwen3-rerank 精排选 cap 条；缺凭证/单条/超时/坏序 →
        # rerank_hits 原序截断（RRF 序），检索永不因精排报错（降级内建 T4）。
        # 返回同一批 chunk 对象，用 id 映射还原 (kb, score) 三元组（D3）。
        from .rerank import rerank_hits

        pool = hits[:_RERANK_CANDIDATES]
        chunk_meta: dict = {}
        for kb, chunk, score in pool:
            chunk_meta.setdefault(id(chunk), (kb, score))
        ranked = await rerank_hits(
            query,
            [chunk for (_kb, chunk, _score) in pool],
            top_n=cap,
            agent_id=agent_id,
        )
        top: list[tuple[Any, Any, float]] = []
        for chunk in ranked:
            meta_kb, meta_score = chunk_meta[id(chunk)]
            top.append((meta_kb, chunk, meta_score))

        # S2 expand=section：命中块回补同小节兄弟块。异常整体隔离 → 降级
        # 单块（brief D5/AC3 + 审查 P2-7：扩展是增强路径，绝不让检索报错）。
        sections: dict = {}
        if expand_mode == "section":
            try:
                sections = _build_section_index(svc, top)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "[kb] section expansion failed; degrade to snippets",
                    exc_info=True,
                )
                sections = {}

        # 每节额度按命中数动态分配，总额受 _MAX_TOTAL_CHARS 约束（审查
        # P2-4：防扩展后输出超 tool-result 裁剪阈值反被截断）。
        per_section = max(
            _MAX_SNIPPET_CHARS,
            min(_MAX_SECTION_CHARS, _MAX_TOTAL_CHARS // max(1, len(top))),
        )

        # T5 expand=graph：命中 doc 的 wikilink 出边图 ≤3 跳。取数用 S0
        # 校验过的 kb.id（不触碰未绑定库）；每 doc 只调一次防 N+1；
        # pg 权威面 CTE 单次往返，json 面诚实降级空；异常整体隔离。
        graph_lines: list[str] = []
        if expand_mode == "graph":
            try:
                seen_docs: set[tuple[str, str]] = set()
                for kb, chunk, _score in top:
                    doc_key = (kb.id, chunk.doc_id)
                    if doc_key in seen_docs:
                        continue
                    seen_docs.add(doc_key)
                    for dst_id, dst_path, depth in svc.document_graph(
                        kb.id,
                        chunk.doc_id,
                        depth=3,
                    ):
                        label = dst_path or dst_id
                        indent = "  " * (depth - 1)
                        graph_lines.append(
                            f"{indent}- {label} (doc_id={dst_id}, "
                            f"depth={depth})",
                        )
                        if len(graph_lines) >= _MAX_GRAPH_LINES:
                            break
                    if len(graph_lines) >= _MAX_GRAPH_LINES:
                        break
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "[kb] graph expansion failed; degrade to snippets",
                    exc_info=True,
                )

        parts: list[str] = []
        rendered: set[tuple[str, str, int]] = set()
        for kb, chunk, score in top:
            heading = getattr(chunk, "heading_path", "") or ""
            # 键含 S0 校验过的 kb.id + section_key（审查 P2-1/P2-2：跨库不
            # 串号、同名 heading 不误并）
            skey = (kb.id, chunk.doc_id, _section_key(chunk))
            if heading and skey in sections:
                # 同小节多命中去重：整节只渲染一次（top 已按分降序，首次即最高分）
                if skey in rendered:
                    continue
                rendered.add(skey)
                sec_heading, blocks = sections[skey]
                body, shown, total_blocks = _join_blocks_cap(
                    blocks,
                    per_section,
                )
                # 块边界截断对 agent 可见（不静默丢证据，审查 P1-2）
                if shown < total_blocks:
                    body += f"\n…[小节共 {total_blocks} 块，已显示 {shown} 块]"
                heading = heading or sec_heading
            else:
                body = _clip(
                    chunk.text,
                    min(_MAX_SNIPPET_CHARS, per_section),
                )
            # D6：heading_path 非空即显示面包屑（与 expand 模式无关）
            crumb = f" #{heading}" if heading else ""
            parts.append(
                f"===== [{kb.name}] {chunk.title or chunk.doc_id}{crumb} "
                f"[score={score:.4f}] =====\n{body}",
            )
        if graph_lines:
            parts.append(
                "===== 相关文档链（wikilink ≤3 跳）=====\n"
                + "\n".join(graph_lines),
            )
        return _tool_chunk("\n\n".join(parts))

    return kb_search


def make_kb_read_tool(
    service: Optional[KbService] = None,
    agent_id: str = "",
) -> Callable[..., Any]:
    """Build the ``kb_read`` tool: fetch one document's full Markdown.

    仿只读契约（spec §7.4）：``kb_search`` 命中片段不够时，Agent 用
    doc_id 拉权威全文，支撑渐进式检索。T10-S0 绑定收敛（spec §8 决策点1）：
    doc 所属库必须 ∈ agent 绑定集才可读，未绑定/不存在合并 not-found。
    """
    svc = service or get_kb_service()

    async def kb_read(doc_id: str) -> ToolChunk:
        """Read the full Markdown text of one knowledge document.

        Use this after ``kb_search`` when a snippet is not enough and you
        need the complete authoritative document. Only documents in bases
        bound to you are readable.

        Args:
            doc_id (`str`):
                The document id, taken from a kb_search result's tracing
                line.

        Returns:
            `ToolResponse`:
                The document's full Markdown text, or an error message.
        """
        doc_id = (doc_id or "").strip()
        if not doc_id:
            return _tool_chunk("Error: doc_id cannot be empty", ok=False)

        meta = svc.get_document_meta(doc_id)
        if meta is None:
            return _tool_chunk(
                f"Error: document '{doc_id}' not found",
                ok=False,
            )

        # S0 绑定收敛：doc 所属库 ∈ agent 绑定集才可读（绑定即授权）；
        # 未绑定视同不可见，合并 not-found，不泄露存在性/绑定态。
        from .bindings import list_bound_space_ids

        bound_ids = set(await list_bound_space_ids(agent_id))
        if meta.kb_id not in bound_ids:
            return _tool_chunk(
                f"Error: document '{doc_id}' not found",
                ok=False,
            )

        content = svc.read_document(doc_id)
        if content is None:
            return _tool_chunk(
                f"Error: document '{doc_id}' not found",
                ok=False,
            )
        kb = svc.get_kb(meta.kb_id)
        kb_name = kb.name if kb is not None else meta.kb_id
        title = meta.title or doc_id
        return _tool_chunk(f"===== [{kb_name}] {title} =====\n{content}")

    return kb_read


def _format_object_card(card: dict) -> str:
    """渲染一张本体对象卡（kb_objects 工具输出；供 Agent 阅读）。"""
    lines = [f"[对象] {card['name']} ({card['type_id']}) id={card['id']}"]
    if card.get("aliases"):
        lines.append(f"别名: {', '.join(card['aliases'][:5])}")
    if card.get("state"):
        lines.append(f"状态: {card['state']}")
    attrs = card.get("attributes") or {}
    for key, value in list(attrs.items())[:6]:
        lines.append(f"{key}: {value}")
    rels = card.get("relations") or {}
    for rel in (rels.get("outbound") or [])[:3]:
        lines.append(f"—[{rel['type']}]→ {rel['to_id']} ({rel['to_type']})")
    for rel in (rels.get("inbound") or [])[:3]:
        lines.append(
            f"←[{rel['type']}]— {rel['from_id']} ({rel['from_type']})",
        )
    docs = card.get("linked_docs") or []
    if docs:
        lines.append("关联知识（可用 kb_read 深读）:")
        for doc in docs[:3]:
            lines.append(f"- {doc['doc_id']} [{doc['relation']}]")
    return "\n".join(lines)


def make_kb_objects_tool(
    service: Optional[KbService] = None,
    agent_id: str = "",
) -> Callable[..., Any]:
    """Build the ``kb_objects`` tool: ontology object cards (T5).

    绑定语义：对象本身是企业结构化资产（企业可见），但卡内的关联知识
    doc 引用经 Agent 绑定集收敛（grounding.object_card 的
    ``bound_space_ids``）——卡片可看，知识引用不越权（S0 同源收敛）。
    数据面走 ontology.grounding（独立 PG 平面），不依赖 kb svc；
    ``service`` 参数保留与 kb_search/kb_read 同构签名（测试注入用）。
    """
    del service

    async def kb_objects(
        name: str = "",
        type: str = "",
        object_id: str = "",
    ) -> ToolChunk:
        """Look up structured business objects (projects, contracts,
        customers, ...) from the company ontology.

        Use this when the question mentions a concrete entity name or
        code (e.g. ``PROJECT-10001``) or asks about an object's current
        state. Returns compact object cards with attributes, relations,
        current state, and linked knowledge doc ids you can deep-read
        with ``kb_read``.

        Args:
            name (`str`, optional):
                Object name or alias to ground (fuzzy match).
            type (`str`, optional):
                Optional type filter, e.g. ``l1.project``.
            object_id (`str`, optional):
                Exact object id (takes precedence over name).

        Returns:
            `ToolResponse`:
                Up to three object cards, or a no-match note.
        """
        from ..ontology.grounding import ground_objects, object_card

        object_id = (object_id or "").strip()
        name = (name or "").strip()
        if not object_id and not name:
            return _tool_chunk(
                "Error: provide name or object_id",
                ok=False,
            )

        from .bindings import list_bound_space_ids

        bound_ids = await list_bound_space_ids(agent_id)

        # 交互式工具查询 limit≤3：卡组装为 4 次小查询 × 3 对象，非
        # 列表页场景（规范 §2.4 禁 N+1 指列表接口批量路径）。
        cards: list[dict] = []
        if object_id:
            card = await object_card(
                object_id,
                bound_space_ids=list(bound_ids),
            )
            if card is not None:
                cards.append(card)
        else:
            targets = await ground_objects(name, type_id=type, limit=3)
            for obj in targets:
                card = await object_card(
                    obj.id,
                    bound_space_ids=list(bound_ids),
                )
                if card is not None:
                    cards.append(card)
        if not cards:
            return _tool_chunk("(no matching ontology objects)")
        return _tool_chunk("\n\n".join(_format_object_card(c) for c in cards))

    return kb_objects
