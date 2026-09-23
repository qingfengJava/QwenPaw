# -*- coding: utf-8 -*-
"""Channel intent-dispatch gate (P5 closing batch: channel adapters wiring).

``ChannelManager`` gives every agent workspace a unified process pipeline
(``process=ws.stream_query``), so instead of touching the 18 built-in
channel adapters we wrap that single pipeline with a dispatch gate:

1. Extract the last inbound user text from the ``AgentRequest``;
2. Load the channel's candidate expert list (``dispatch_experts`` in the
   channel config) as published ``DispatchCandidate`` projections;
3. Call ``dispatch_expert_intent`` (LLM classification + sticky guard +
   confidence threshold, degrading to ``None`` on any failure);
4. On a hit for a *different* expert, stream the request through the
   target workspace (``manager.get_agent(expert_agent_id(id))``) —
   replies render back through the original channel unchanged;
5. Any failure / miss / low confidence falls through to the owning
   workspace's own ``stream_query`` — dispatch never blocks the message
   mainline (same degradation contract as the core classifier).
@author qingfeng
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Candidate projection cache TTL (seconds) — per-gate instance.
_CANDIDATE_CACHE_TTL_S = 60.0

#: Inbound text longer than this is truncated for classification (core
#: prompt already slices at 500 chars; avoid handing over huge payloads).
_MAX_DISPATCH_TEXT_LEN = 2000


def last_user_text(request: Any) -> str:
    """Extract the concatenated text of the last user message.

    ``AgentRequest.input`` is a list of ``Message``（role=user/assistant/…，
    content items carry ``.text``）。Non-text / missing input yields "".
    """
    inputs = getattr(request, "input", None) or []
    for message in reversed(inputs):
        # Role 是 str-enum：裸字符串 "user" 与 Role.USER 都归一到 "user"
        role = getattr(message, "role", None)
        role_value = str(getattr(role, "value", role) or "").lower()
        if role_value != "user":
            continue
        parts: List[str] = []
        for item in getattr(message, "content", None) or []:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text:
                parts.append(text)
        text = "".join(parts).strip()
        if text:
            return text[:_MAX_DISPATCH_TEXT_LEN]
    return ""


class _CandidateCache:
    """Tiny TTL cache: expert_id → DispatchCandidate (name/title/desc)."""

    def __init__(self) -> None:
        self._entries: Dict[str, tuple[float, Any]] = {}

    def get(self, expert_id: str) -> Optional[Any]:
        entry = self._entries.get(expert_id)
        if entry is None:
            return None
        stamp, candidate = entry
        if time.monotonic() - stamp > _CANDIDATE_CACHE_TTL_S:
            self._entries.pop(expert_id, None)
            return None
        return candidate

    def put(self, expert_id: str, candidate: Any) -> None:
        self._entries[expert_id] = (time.monotonic(), candidate)


async def _load_candidates(
    expert_ids: List[str],
    cache: _CandidateCache,
) -> List[Any]:
    """Project configured expert ids to DispatchCandidate (published only).

    未发布/不存在的候选直接剔除（与 dispatch API 面语义一致）；
    投影走 ExpertStore，单员工单查（候选名单通常 2~5 个，带 TTL 缓存）。
    """
    from ..experts.intent_dispatch import DispatchCandidate
    from ..experts.models import EXPERT_STATUS_PUBLISHED
    from ..experts.store import get_expert_store

    store = get_expert_store()
    out = []
    for expert_id in expert_ids:
        candidate = cache.get(expert_id)
        if candidate is None:
            try:
                record = await store.get_expert(expert_id)
            except Exception:  # noqa: BLE001 - 单候选失败不拖垮名单
                record = None
            if record is None or record.status != EXPERT_STATUS_PUBLISHED:
                continue
            candidate = DispatchCandidate(
                expert_id=record.id,
                name=record.name,
                title=record.title,
                description=record.description,
            )
            cache.put(expert_id, candidate)
        out.append(candidate)
    return out


def wrap_process_with_dispatch(
    process: Callable[[Any], AsyncGenerator[Any, None]],
    ws: Any,
    candidates_by_channel: Dict[str, List[str]],
) -> Callable[[Any], AsyncGenerator[Any, None]]:
    """Wrap one workspace's shared process handler with the dispatch gate.

    Args:
        process: the workspace's own ``stream_query`` (or an outer wrap).
        ws: the owning workspace (agent = default receiver / sticky owner).
        candidates_by_channel: channel_key → configured candidate expert
            ids（仅含非空名单的渠道；其余渠道零介入）。
    """
    cache = _CandidateCache()
    # 预清洗：剥空白项；空名单渠道不进入判定分支（零开销直通）
    configured_by_channel: Dict[str, List[str]] = {
        key: [eid for eid in ids if eid]
        for key, ids in (candidates_by_channel or {}).items()
        if ids
    }

    async def gated_process(request: Any) -> AsyncGenerator[Any, None]:
        # ---- 分发判定（一切异常都降级回默认路由）----
        target_ws = None
        try:
            channel = str(getattr(request, "channel", "") or "")
            configured = configured_by_channel.get(channel) or []
            text = last_user_text(request)
            if text and len(configured) >= 2:
                from ..experts.intent_dispatch import dispatch_expert_intent
                from ..experts.models import expert_agent_id

                candidates = await _load_candidates(configured, cache)
                if len(candidates) >= 2:
                    choice = await dispatch_expert_intent(
                        text,
                        candidates,
                        current_expert_id=ws.agent_id,
                        sticky=bool(getattr(request, "session_id", "")),
                    )
                    if choice and choice.get("expert_id"):
                        target_id = expert_agent_id(str(choice["expert_id"]))
                        if target_id != ws.agent_id:
                            manager = getattr(ws, "_manager", None)
                            if manager is not None:
                                target_ws = await manager.get_agent(target_id)
                                logger.info(
                                    "intent dispatch on channel=%s: %s -> %s "
                                    "(confidence=%.2f, reason=%s)",
                                    channel,
                                    ws.agent_id,
                                    target_id,
                                    float(choice.get("confidence") or 0.0),
                                    choice.get("reason", ""),
                                )
        except Exception:  # noqa: BLE001 - 分发故障绝不阻塞主链路
            target_ws = None
            logger.warning(
                "intent dispatch gate degraded to default routing "
                "(agent=%s)",
                getattr(ws, "agent_id", "?"),
                exc_info=True,
            )

        # ---- 命中转发：目标员工 workspace 流式透传 ----
        if target_ws is not None:
            try:
                async for item in target_ws.stream_query(request):
                    yield item
                return
            except Exception:  # noqa: BLE001 - 转发失败回落本员工
                logger.warning(
                    "dispatched target workspace failed; falling back to "
                    "owning agent",
                    exc_info=True,
                )

        # ---- 默认路由：本 workspace 原样处理 ----
        async for item in process(request):
            yield item

    return gated_process
