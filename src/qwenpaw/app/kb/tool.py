# -*- coding: utf-8 -*-
"""``kb_search`` agent tool (M4-5): retrieval over accessible bases.

The tool resolves the caller from the trusted-identity ContextVar, lists
only the bases that identity may read, and returns the fused top hits.
It is registered by :class:`AgentBuilder` only when at least one
knowledge base exists, so deployments without KBs see no prompt change.
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
    """Trusted caller identity + RBAC context for ACL filtering."""
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
) -> Callable[..., Any]:
    """Build the ``kb_search`` tool bound to a KB service."""
    svc = service or get_kb_service()

    async def kb_search(
        query: str,
        kb_id: str = "",
        max_results: int = 5,
    ) -> ToolChunk:
        """Search enterprise knowledge bases for relevant document snippets.

        Use this tool to answer questions about shared company/team
        documents: policies, runbooks, product specs, meeting notes that
        were ingested into a knowledge base. Only bases you have access
        to are searched. For the user's personal long-term memory, use
        ``memory_search`` instead.

        Args:
            query (`str`):
                The search query describing what to find.
            kb_id (`str`, optional):
                Restrict the search to one knowledge base; empty searches
                every base the caller can access.
            max_results (`int`, optional):
                Maximum snippets to return. Defaults to 5.

        Returns:
            `ToolResponse`:
                Ranked snippets with knowledge base and document titles.
        """
        query = (query or "").strip()
        if not query:
            return _tool_chunk("Error: query cannot be empty", ok=False)

        username, access = _current_identity()
        if kb_id:
            kb = svc.get_kb(kb_id)
            if kb is None:
                return _tool_chunk(
                    f"Error: knowledge base '{kb_id}' not found",
                    ok=False,
                )
            if not svc.can_access(kb, username, **access):
                return _tool_chunk(
                    "Error: you do not have access to this knowledge base",
                    ok=False,
                )
            kbs = [kb]
        else:
            kbs = svc.accessible_kbs(username, **access)
        if not kbs:
            return _tool_chunk("(no accessible knowledge bases)")

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
