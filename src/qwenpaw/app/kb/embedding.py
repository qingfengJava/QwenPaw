# -*- coding: utf-8 -*-
"""知识库 embedding 管线：复用 ReMe 的模型工厂与凭证，缺失即降级 BM25。

设计约束（spec §2「embedding 接入」）：知识库**不引入第二套 embedding 栈**。
配置权威源是 agent 的 ``reme_light_memory_config.embedding_model_config``，
本模块只负责「挑哪个 agent 的配置 + 维度守卫 + 批量对齐 + fail-soft」。

向量宽度是硬约束：``kb_chunks.embedding`` 在 0034 里是 ``vector(1024)``，
任何非 1024 维向量写入都会 ``DataError``，因此维度不符时直接返回 ``None``
让调用方降级，而不是「先试再说」。

返回值语义（Task 5/6 依赖，勿改）：

- ``None``：向量能力不可用（未配置 / 维度不符 / 调用失败），调用方走 BM25-only；
- ``[]``：入参为空，属「无需工作」，与「不可用」必须可区分；
- 非空列表：顺序与入参严格一一对应（摄入端按 index 回填 chunk）。

@author qingfeng
"""

from __future__ import annotations

import logging
import math
from typing import Any, List, Optional, Sequence

from qwenpaw.agents.memory.embedding_model import create_embedding_model
from qwenpaw.agents.memory.reme_config import is_embedding_enabled
from qwenpaw.config.config import EmbeddingModelConfig, load_agent_config
from qwenpaw.config.utils import load_config

logger = logging.getLogger(__name__)

#: 向量列宽固定 1024（与 alembic 0034 的 ``vector(1024)`` 必须一致）
EMBEDDING_DIM = 1024


def resolve_memory_config(agent_id: str = "") -> Any:
    """返回目标 agent 的 ``reme_light_memory_config``，读不出时返回 ``None``。

    解析顺序：显式 ``agent_id`` 优先，未传则落 ``Config.agents.active_agent``
    （仓库既有的「当前生效 agent」指针）。两个 loader 都带缓存，故同步调用
    对事件循环的影响可忽略；精排（:mod:`qwenpaw.app.kb.rerank`）共用本函数，
    保证「向量用谁的凭证」与「精排用谁的凭证」永远一致。

    Args:
        agent_id: 目标 agent ID，空串表示使用当前生效 agent。

    Returns:
        agent 的记忆配置对象，或 ``None``（配置缺失/损坏，调用方须 fail-soft）。

    @author qingfeng
    """
    target = (agent_id or "").strip()
    if not target:
        try:
            target = str(load_config().agents.active_agent or "").strip()
        except Exception:  # 配置目录不可读等环境问题同样降级
            logger.warning(
                "[kb] cannot read global config; vector search disabled",
                exc_info=True,
            )
            return None
    if not target:
        return None
    try:
        agent_config = load_agent_config(target)
    except Exception:
        logger.warning(
            "[kb] cannot read agent config: agent=%s",
            target,
            exc_info=True,
        )
        return None
    return getattr(agent_config.running, "reme_light_memory_config", None)


def _resolve_config(
    model: str = "",
    agent_id: str = "",
) -> Optional[EmbeddingModelConfig]:
    """解析本次调用该用的 embedding 配置；不可用时返回 ``None``。

    ``model`` 对应 ``kb_spaces.embedding_model``（空=全局默认）：只覆盖模型名，
    维度与凭证沿用 agent 配置——换模型不换维度是本项目的前提（列宽固定），
    若该模型实际输出维度不同，会在 :func:`_call_model` 的维度守卫处降级。
    """
    memory = resolve_memory_config(agent_id)
    if memory is None:
        return None
    config = getattr(memory, "embedding_model_config", None)
    if config is None or not is_embedding_enabled(config):
        return None
    override = (model or "").strip()
    if override and override != config.model_name:
        config = config.model_copy(update={"model_name": override})
    return config


async def _call_model(
    config: EmbeddingModelConfig,
    texts: Sequence[str],
) -> Optional[List[List[float]]]:
    """下发**单批** embedding 请求；失败或维度不符返回 ``None``。

    这里集中所有异常捕获：provider SDK 的异常类型过多，逐类捕获反而漏。
    非有限数（NaN/inf）同样视为失败——它们会让 pgvector 距离计算静默出错。
    """
    try:
        model = create_embedding_model(config)
        response = await model(list(texts))
    except Exception:
        logger.warning(
            "[kb] embedding request failed: model=%s batch=%d",
            config.model_name,
            len(texts),
            exc_info=True,
        )
        return None

    embeddings = getattr(response, "embeddings", None)
    if embeddings is None or len(embeddings) != len(texts):
        logger.warning(
            "[kb] embedding count mismatch: want=%d got=%s",
            len(texts),
            0 if embeddings is None else len(embeddings),
        )
        return None
    vectors = [list(embedding) for embedding in embeddings]
    if not all(_is_valid_vector(vector) for vector in vectors):
        logger.warning(
            "[kb] embedding rejected: expected %d finite dims",
            EMBEDDING_DIM,
        )
        return None
    return vectors


def _is_valid_vector(vector: Sequence[Any]) -> bool:
    """单条向量是否可直接入库（宽度与列型一致且全为有限数）。"""
    if len(vector) != EMBEDDING_DIM:
        return False
    return all(
        isinstance(value, (int, float)) and math.isfinite(value)
        for value in vector
    )


async def embed_texts(
    texts: Sequence[str],
    model: str = "",
    agent_id: str = "",
) -> Optional[List[List[float]]]:
    """为一批文本生成向量；不可用时返回 ``None``（调用方降级 BM25）。

    按 ``max_batch_size`` 切批以适配 provider 单请求条数上限；任一批失败即
    整体返回 ``None``，不做「部分成功」——半库有向量半库没有会让检索质量
    无法解释，也会让重建任务的状态机难以收敛。

    Args:
        texts: 待向量化文本，返回顺序与此严格对齐。
        model: 库级模型覆盖（``kb_spaces.embedding_model``），空=全局默认。
        agent_id: 凭证归属 agent，空串表示当前生效 agent。

    Returns:
        ``None`` 表示向量能力不可用；``[]`` 表示无需工作；否则为等长向量列表。

    @author qingfeng
    """
    items = list(texts)
    if not items:
        return []
    config = _resolve_config(model=model, agent_id=agent_id)
    if config is None:
        return None
    if config.dimensions != EMBEDDING_DIM:
        logger.warning(
            "[kb] configured dimensions (%d) != column width %d; "
            "vector search disabled",
            config.dimensions,
            EMBEDDING_DIM,
        )
        return None
    batch_size = max(1, config.max_batch_size)
    vectors: List[List[float]] = []
    for start in range(0, len(items), batch_size):
        stop = start + batch_size
        batch = items[start:stop]
        result = await _call_model(config, batch)
        if result is None or len(result) != len(batch):
            return None
        vectors.extend(result)
    return vectors


async def embed_query(
    query: str,
    model: str = "",
    agent_id: str = "",
) -> Optional[List[float]]:
    """为单次查询生成向量；语义与 :func:`embed_texts` 一致（fail-soft）。"""
    if not (query or "").strip():
        return None
    vectors = await embed_texts([query], model=model, agent_id=agent_id)
    if not vectors:
        return None
    return vectors[0]


__all__ = [
    "EMBEDDING_DIM",
    "embed_query",
    "embed_texts",
    "resolve_memory_config",
]
