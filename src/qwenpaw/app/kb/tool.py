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


def _tool_chunk(text: str, *, ok: bool = True) -> ToolChunk:
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS if ok else ToolResultState.ERROR,
        content=[TextBlock(type="text", text=text)],
    )


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
        hits: list[tuple[Any, Any, float]] = []
        for kb in kbs:
            for chunk, score in svc.search(kb.id, query, top_k=cap):
                hits.append((kb, chunk, score))
        if not hits:
            return _tool_chunk("(no matching knowledge snippets)")
        hits.sort(key=lambda item: item[2], reverse=True)

        parts: list[str] = []
        for kb, chunk, score in hits[:cap]:
            snippet = chunk.text
            if len(snippet) > _MAX_SNIPPET_CHARS:
                snippet = snippet[:_MAX_SNIPPET_CHARS] + "…"
            parts.append(
                f"===== [{kb.name}] {chunk.title or chunk.doc_id} "
                f"[score={score:.4f}] =====\n{snippet}",
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
