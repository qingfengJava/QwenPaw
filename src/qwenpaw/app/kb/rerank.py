# -*- coding: utf-8 -*-
"""知识库检索精排（管线 S3）：复用仓库唯一现成的 rerank 通道。

不为知识库另写一套 rerank HTTP 客户端：``agents.memory.reme_reranker``
已实现 OpenAI 兼容的 ``POST {base_url}/rerank``（``{model, query, documents}``
→ ``results[{index, relevance_score}]``），DashScope ``qwen3-rerank`` 的
兼容端点与之同形，SiliconFlow 等第三方服务亦然。本模块只做两件事：
**解析配置**（含凭证与 embedding 同源）与**按 index 重排截断**。

降级语义：精排是增益项而非必需项——未启用、单条命中、超时、HTTP 错误、
返回索引非法，全部保持调用方传入的顺序（RRF 序）返回，检索永不因精排失败而报错。

命中类型刻意不 import Task 5 的 ``KbSearchHit``（反向依赖会成环），改为结构化
协议 :class:`_Rerankable`：**任何带 ``text: str`` 的对象都可被精排**，返回的
仍是原对象（不复制、不改写字段），调用方可继续读取 ``score`` 等字段。

@author qingfeng
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Protocol, Sequence

from qwenpaw.agents.memory.reme_reranker import call_reranker_api
from qwenpaw.config.config import RerankerConfig

from .embedding import resolve_memory_config

logger = logging.getLogger(__name__)


class _Rerankable(Protocol):
    """精排契约：只需要命中携带正文。"""

    text: str


def _inherit_credentials(
    config: RerankerConfig,
    embedding: Any,
) -> Dict[str, str]:
    """返回需要从 embedding 继承的凭证补丁（无缺口时为空字典）。

    兑现 spec 的「精排凭证与 embedding 同源」：reranker 未填 api_key/base_url
    时沿用 embedding 的值，而不是再造一套环境变量配置面。
    """
    if embedding is None:
        return {}
    updates: Dict[str, str] = {}
    if not config.api_key.strip() and embedding.api_key.strip():
        updates["api_key"] = embedding.api_key
    if not config.base_url.strip() and embedding.base_url.strip():
        updates["base_url"] = embedding.base_url
    return updates


def _resolve_rerank_config(agent_id: str = "") -> Optional[RerankerConfig]:
    """解析精排配置；未启用或缺模型名时返回 ``None``（零网络调用）。

    ``enabled`` 是硬开关：关闭时不继承凭证、不发请求，避免「配了 embedding
    就被动打外网」这种隐性行为。
    """
    memory = resolve_memory_config(agent_id)
    if memory is None:
        return None
    config = getattr(memory, "reranker_config", None)
    if config is None or not config.enabled or not config.model_name.strip():
        return None
    updates = _inherit_credentials(
        config,
        getattr(memory, "embedding_model_config", None),
    )
    if not updates:
        return config
    return config.model_copy(update=updates)


def _valid_order(order: Sequence[int], size: int) -> bool:
    """精排返回的索引序必须是 ``range(size)`` 的一个排列，否则放弃重排。"""
    return len(order) == size and set(order) == set(range(size))


async def rerank_hits(
    query: str,
    hits: Sequence[_Rerankable],
    top_n: int = 5,
    agent_id: str = "",
) -> List[_Rerankable]:
    """按语义相关性重排命中并截断到 *top_n*；不可用时保持原序。

    调用方应**超量取回**候选（例如 RRF top 20）再交给本函数，否则精排只能
    在已截断的小集合内换位，收益有限。

    注意：下发给精排服务的是完整切片正文，不做二次截断——切片端已按
    ``target_tokens`` 控制长度，再截 500 字符会静默丢内容。

    Args:
        query: 用户查询原文。
        hits: 候选命中（顺序即降级时的最终顺序）。
        top_n: 最终返回条数，非正数收敛为 1（不允许静默清空结果）。
        agent_id: 凭证归属 agent，空串表示当前生效 agent。

    Returns:
        重排（或原序）后的命中列表，长度为 ``min(top_n, len(hits))``。

    @author qingfeng
    """
    cap = max(1, top_n)
    items = list(hits)
    if len(items) <= 1:
        return items[:cap]
    config = _resolve_rerank_config(agent_id=agent_id)
    if config is None:
        return items[:cap]
    if not query.strip():
        logger.warning("[kb] rerank skipped: empty query")
        return items[:cap]
    order = await call_reranker_api(
        query,
        [item.text for item in items],
        config,
    )
    if not order or not _valid_order(order, len(items)):
        logger.warning(
            "[kb] rerank returned unusable order; keeping RRF order",
        )
        return items[:cap]
    return [items[index] for index in order[:cap]]


__all__ = [
    "rerank_hits",
]
