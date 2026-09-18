# -*- coding: utf-8 -*-
"""检索引擎抽象层（L0/L1/L2 统一面）：工厂、按库路由与跨引擎融合。

三层引擎（spec §2「索引层」）：

- L0 :class:`FileKbEngine`——JSONL 现状收编，json 后端 / PG 未就绪时的回退面；
- L1 :class:`PgVectorEngine`——pgvector + tsvector 单 SQL 混合（默认引擎）；
- L2 :class:`MilvusEngine`——pymilvus 双路混合（库配 ``engine=milvus`` 启用）。

依赖方向（环防护）：本模块顶层反向依赖三个实现模块（工厂构造 + 重导出），
三个实现模块只依赖 ``hits.py`` 的 :class:`KbSearchHit` 与各自的数据面，
**禁止 import 本模块**。实现类「仅 duck-type 协议」：不继承、不 import
:class:`KbRetrievalEngine`——协议只服务静态检查与文档。

路由语义（spec §5）：

- ``kb_spaces.engine``：``auto`` / ``pgvector`` → 默认引擎；``milvus`` →
  Milvus，``pymilvus`` 驱动缺失时告警回退默认引擎（检索永不因引擎切换失败）；
- 默认引擎工厂：json → File；pg/dual 且 ``kb_chunks`` 表就绪 → PgVector；
  否则 File。判定结果**随探测结果动态缓存实例**（同一种引擎跨调用保持
  identity 稳定——``hybrid_search_multi`` 按实例分组依赖这一点）。

跨引擎融合（``hybrid_search_multi``）：不同引擎的 score 量纲不可比
（BM25 原值 / SQL 内 RRF / WeightedRanker 分数），因此组间只按**排名**做
RRF 二次融合（k 与单层一致，见 :data:`qwenpaw.app.kb.search.RRF_K`），
tie-break 取 ``chunk_id`` 升序，保证同输入结果确定。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import importlib.util
import logging
import threading
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from ...db import write_gateway
from .chunker import ChunkSpec
from .file_engine import FileKbEngine
from .hits import KbSearchHit
from .milvus_engine import MilvusEngine
from .models import ENGINE_MILVUS, KbSpace
from .pg_engine import PgVectorEngine
from .search import RRF_K

logger = logging.getLogger(__name__)

#: 表探测的同步等待上限（秒）：探测悬挂不得拖垮检索链路
PROBE_TIMEOUT_SECONDS = 5


class KbRetrievalEngine(Protocol):
    """检索引擎协议（duck-type：实现类不继承本协议）。"""

    async def index_document(
        self,
        space_id: str,
        document_id: str,
        chunks: Sequence[ChunkSpec],
        embeddings: Optional[Sequence[Sequence[float]]] = None,
        **kwargs: Any,
    ) -> int:
        """重建一份文档的切片索引，返回写入条数。"""
        ...

    async def delete_document(
        self,
        space_id: str,
        document_id: str,
    ) -> int:
        """删除一份文档的切片，返回删除条数。"""
        ...

    async def search(
        self,
        space_ids: Sequence[str],
        query: str,
        query_embedding: Optional[Sequence[float]] = None,
        top_k: int = 5,
    ) -> List[KbSearchHit]:
        """在给定空间集合内检索（S0 收敛结果直传），返回命中列表。"""
        ...


# ---------------------------------------------------------------------------
# 探测（同步面与 async 世界之间的唯一桥）
# ---------------------------------------------------------------------------


def _run_blocking(coro: Any) -> Any:
    """在同步函数里执行协程：循环外 ``asyncio.run``；循环内独立线程执行。

    ``get_kb_engine()`` 是同步 API（legacy 同步检索面也在用），而表探测
    本质是 async IO——本函数是模块内唯一的建线程点。探测结果的缓存
    （正永久 / 负 TTL）沉在 :class:`KbPgStore` 内，稳态调用零网络往返。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(asyncio.run, coro)
    try:
        return future.result(timeout=PROBE_TIMEOUT_SECONDS)
    finally:
        # 不等待悬挂线程（超时也要让调用方立即拿到降级结果）
        pool.shutdown(wait=False)


def _kb_chunks_table_exists() -> bool:
    """同步探针：``kb_chunks`` 表是否就绪（三态 + 六表探测，复用 PG 存储层）。

    这是工厂路由的「表存在性」判定面；探测失败一律按未就绪处理（回退
    文件引擎），绝不阻塞启动与检索。
    """
    try:
        from .pg_store import get_kb_pg_store

        store = get_kb_pg_store()
        if store is None:
            return False
        return bool(_run_blocking(store.ensure_ready()))
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "[kb] kb_chunks readiness probe failed; using file engine",
            exc_info=True,
        )
        return False


def _pymilvus_available() -> bool:
    """pymilvus 可选依赖判定（只查 spec 不 import，导入副作用留给真使用点）。"""
    return importlib.util.find_spec("pymilvus") is not None


# ---------------------------------------------------------------------------
# 默认引擎工厂与按库路由
# ---------------------------------------------------------------------------

_default_engine: Optional[Any] = None
_default_engine_kind = ""
_default_engine_lock = threading.Lock()

_milvus_engine: Optional[MilvusEngine] = None
_milvus_engine_lock = threading.Lock()


def _desired_engine_kind() -> str:
    """当前应使用的默认引擎类别：``"pg"`` 或 ``"file"``。"""
    backend = write_gateway.resolve_storage_backend()
    if (
        backend
        in (
            write_gateway.BACKEND_PG,
            write_gateway.BACKEND_DUAL,
        )
        and _kb_chunks_table_exists()
    ):
        return "pg"
    return "file"


def get_kb_engine() -> Any:
    """默认引擎工厂：json→File；pg/dual 且表就绪→PgVector；否则 File。

    每次调用重算「应使用哪类引擎」（探测有缓存，成本为内存判定），类别
    变化时重建实例、不变时复用缓存实例——保证分组检索的实例 identity
    稳定，同时兼容测试对后端/探测面的 monkeypatch。
    """
    global _default_engine, _default_engine_kind  # noqa: PLW0603
    kind = _desired_engine_kind()
    with _default_engine_lock:
        if _default_engine is None or _default_engine_kind != kind:
            _default_engine = (
                PgVectorEngine() if kind == "pg" else FileKbEngine()
            )
            _default_engine_kind = kind
        return _default_engine


def _get_milvus_engine() -> MilvusEngine:
    """Milvus 引擎单例（identity 稳定，分组检索依赖）。"""
    global _milvus_engine  # noqa: PLW0603
    if _milvus_engine is None:
        with _milvus_engine_lock:
            if _milvus_engine is None:
                _milvus_engine = MilvusEngine()
    return _milvus_engine


def resolve_engine_for(space: KbSpace) -> Any:
    """按库路由引擎：``auto``/``pgvector`` → 默认；``milvus`` → Milvus。

    库配了 milvus 但驱动未装时**告警回退默认引擎**——按库开关的失效
    不得让该库检索中断。
    """
    if getattr(space, "engine", "") == ENGINE_MILVUS:
        if _pymilvus_available():
            return _get_milvus_engine()
        logger.warning(
            "[kb] pymilvus not installed; space=%s falls back to "
            "the default engine",
            getattr(space, "id", ""),
        )
    return get_kb_engine()


# ---------------------------------------------------------------------------
# 跨引擎分组检索 + RRF 二次融合
# ---------------------------------------------------------------------------


async def hybrid_search_multi(
    spaces: Sequence[KbSpace],
    query: str,
    query_embedding: Optional[Sequence[float]] = None,
    top_k: int = 5,
) -> List[KbSearchHit]:
    """跨引擎检索：按引擎分组并行检索 → 排名级 RRF 二次融合 → 截 top_k。

    S0 收敛由调用方完成（本函数不碰 ACL）；单组引擎失败仅告警跳过该组，
    其余组结果保留（引擎层任何异常不得让检索链路报错）。

    Args:
        spaces: 已收敛的候选库列表（含 ``engine`` 路由字段）。
        query: 查询原文。
        query_embedding: 查询向量，``None`` 时各引擎内部走 BM25-only。
        top_k: 最终返回条数（非正数收敛为 1，照 rerank 同口径）。

    Returns:
        融合后的命中列表，长度 ≤ ``max(1, top_k)``。
    """
    cap = max(1, top_k)
    groups: Dict[int, Tuple[Any, List[str]]] = {}
    for space in spaces:
        engine = resolve_engine_for(space)
        entry = groups.get(id(engine))
        if entry is None:
            groups[id(engine)] = (engine, [space.id])
        else:
            entry[1].append(space.id)

    async def _search(engine: Any, space_ids: List[str]) -> List[KbSearchHit]:
        """单组检索（异常由 gather 收集，不在此处吞掉）。"""
        return await engine.search(space_ids, query, query_embedding, cap)

    results = await asyncio.gather(
        *(_search(engine, ids) for engine, ids in groups.values()),
        return_exceptions=True,
    )

    fused: Dict[str, Tuple[float, KbSearchHit]] = {}
    for result in results:
        if isinstance(result, BaseException):
            logger.warning(
                "[kb] engine group search failed; group skipped",
                exc_info=result,
            )
            continue
        for rank, hit in enumerate(result):
            rank_score = 1.0 / (RRF_K + rank)
            best = fused.get(hit.chunk_id)
            if best is None or rank_score > best[0]:
                fused[hit.chunk_id] = (rank_score, hit)
    ordered = sorted(
        fused.values(),
        key=lambda item: (-item[0], item[1].chunk_id),
    )
    return [hit for _score, hit in ordered[:cap]]


__all__ = [
    "FileKbEngine",
    "KbRetrievalEngine",
    "KbSearchHit",
    "MilvusEngine",
    "PgVectorEngine",
    "get_kb_engine",
    "hybrid_search_multi",
    "resolve_engine_for",
]
