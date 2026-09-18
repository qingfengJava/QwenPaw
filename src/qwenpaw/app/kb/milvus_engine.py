# -*- coding: utf-8 -*-
"""L2 Milvus 引擎：双路（稠密 + BM25 稀疏）混合检索，按库显式启用。

启用条件：库的 ``kb_spaces.engine='milvus'`` 且 ``pymilvus`` 可选依赖已装
（驱动缺失时由 :func:`qwenpaw.app.kb.engine.resolve_engine_for` 告警回退默认
引擎，本模块不做二次判定）。适用判据（spec §5）：单库 > 50 万 chunk 或
检索 P95 > 300ms。

Collection 契约（``kb_chunks_v1``）：

- 主键 ``chunk_id``（VARCHAR，与 PG 面同形态 ``{document_id}_{seq}``，
  不用 plan 草图的 INT64——双引擎的 chunk 标识必须可互读）；
- ``space_id`` 为 partition key（S0 ACL 收敛结果直传 filter 表达式，
  分区键过滤高效且不破坏混合检索）；
- ``content_text`` 经内置 BM25 function 生成稀疏向量（服务端分词，
  analyzer 用 ``chinese``：默认 standard analyzer 不切主流中文，中文
  查询恒空——真机实测；chinese/jieba 切分中文且保留英数 token，兼容
  中英混排正文），``dense`` 为 1024 维稠密向量（与 pgvector 列宽一致）；
- ``parent_seq`` 直接落列（读回免反解，无父块存 :data:`_NO_PARENT`）。

执行模型：pymilvus 客户端是同步阻塞的，所有操作经 ``asyncio.to_thread``
离线到线程池执行，不阻塞事件循环（这是与 PG/文件引擎并列参与
``asyncio.gather`` 并行的前提）。

失败语义：检索面 fail-soft（异常仅 WARN 返回空列表）；写入面异常向调用方
传播（与 pg 引擎同一约定，摄入状态机据此落 ``failed``）。

可见性语义：Milvus Bounded 一致性下写入返回后约秒级收敛可见；:meth:`MilvusEngine.flush`
提供确定性可见点（写入批次收口后调用，返回即可搜）。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Sequence

from .chunker import ChunkSpec
from .embedding import EMBEDDING_DIM
from .hits import KbSearchHit
from .search import KEYWORD_WEIGHT, VECTOR_WEIGHT

logger = logging.getLogger(__name__)

#: 默认连接地址（Milvus standalone gRPC 端口）
DEFAULT_MILVUS_URI = "http://127.0.0.1:19530"

#: collection 名（schema 变更时升版本号重键）
COLLECTION_NAME = "kb_chunks_v1"

#: 各分支候选池（与 pg 引擎一致：单分支 top50 进融合）
_POOL_SIZE = 50

#: INT64 列没有 NULL：无父块的哨兵值
_NO_PARENT = -1

#: 读回的输出字段（含 parent_seq，免去 id 反解；chunk_id 显式请求，
#: 与 Hit.id 属性互为双保险）
_OUTPUT_FIELDS = [
    "chunk_id",
    "space_id",
    "document_id",
    "seq",
    "heading_path",
    "content_text",
    "parent_seq",
]


class MilvusEngine:
    """Milvus 引擎（L2）：混合检索 + 文档级重建写入。"""

    def __init__(
        self,
        uri: str = "",
        dim: int = EMBEDDING_DIM,
    ) -> None:
        self._uri = (
            uri or os.environ.get("QWENPAW_MILVUS_URI", DEFAULT_MILVUS_URI)
        ).strip()
        self._dim = dim
        self._client: Any = None
        self._collection_ready = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 客户端与 schema（惰性；驱动缺失/连接失败返回 None 降级）
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """惰性建 MilvusClient；任何失败仅 WARN 返回 ``None``。"""
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                from pymilvus import MilvusClient

                self._client = MilvusClient(uri=self._uri)
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "[kb] milvus client unavailable: uri=%s",
                    self._uri,
                    exc_info=True,
                )
                return None
        return self._client

    def _ensure_collection(self, client: Any) -> None:
        """幂等建 collection（schema + BM25 function + 双索引）。"""
        if self._collection_ready:
            return
        with self._lock:
            if self._collection_ready:
                return
            if client.has_collection(COLLECTION_NAME):
                # 已存在：直接装载（load 幂等）。
                # 注意：Milvus 不支持原地改 schema（如 analyzer 变更），
                # 契约变更时需手动 drop_collection 后由本方法重建。
                client.load_collection(COLLECTION_NAME)
                self._collection_ready = True
                return
            from pymilvus import DataType, Function, FunctionType

            schema = client.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            schema.add_field(
                "chunk_id",
                DataType.VARCHAR,
                is_primary=True,
                max_length=64,
            )
            schema.add_field(
                "space_id",
                DataType.VARCHAR,
                max_length=64,
                is_partition_key=True,
            )
            schema.add_field(
                "document_id",
                DataType.VARCHAR,
                max_length=64,
            )
            schema.add_field("seq", DataType.INT64)
            schema.add_field(
                "heading_path",
                DataType.VARCHAR,
                max_length=512,
            )
            schema.add_field(
                "content_text",
                DataType.VARCHAR,
                max_length=65535,
                # BM25 function 的输入字段必须开启 analyzer（Milvus 2.5 硬性要求，
                # 否则 create_collection 直接报 "input field must set
                # enable_analyzer to true"）
                enable_analyzer=True,
                # 默认 standard analyzer 不切分中文（中文查询恒空，真机实测）；
                # chinese（jieba）切分中文并保留英数 token，兼容中英混排正文
                analyzer_params={"type": "chinese"},
            )
            schema.add_field("parent_seq", DataType.INT64)
            schema.add_field(
                "dense",
                DataType.FLOAT_VECTOR,
                dim=self._dim,
            )
            schema.add_field(
                "sparse",
                DataType.SPARSE_FLOAT_VECTOR,
            )
            # 服务端 BM25：content_text → 稀疏向量（写入方只给正文）
            schema.add_function(
                Function(
                    name="content_bm25",
                    function_type=FunctionType.BM25,
                    input_field_names=["content_text"],
                    output_field_names=["sparse"],
                ),
            )
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name="dense",
                index_type="AUTOINDEX",
                metric_type="COSINE",
            )
            index_params.add_index(
                field_name="sparse",
                index_type="AUTOINDEX",
                metric_type="BM25",
            )
            client.create_collection(
                COLLECTION_NAME,
                schema=schema,
                index_params=index_params,
            )
            self._collection_ready = True

    # ------------------------------------------------------------------
    # 检索面（fail-soft）
    # ------------------------------------------------------------------

    def _search_sync(
        self,
        space_ids: Sequence[str],
        query: str,
        query_embedding: Optional[Sequence[float]],
        top_k: int,
    ) -> List[KbSearchHit]:
        """同步实现：双 AnnSearchRequest + WeightedRanker（0.7/0.3）。"""
        from pymilvus import AnnSearchRequest, WeightedRanker

        client = self._get_client()
        if client is None:
            return []
        self._ensure_collection(client)

        requests: List[Any] = []
        if query_embedding is not None:
            requests.append(
                AnnSearchRequest(
                    data=[list(query_embedding)],
                    anns_field="dense",
                    param={"metric_type": "COSINE"},
                    limit=_POOL_SIZE,
                ),
            )
        if query.strip():
            requests.append(
                AnnSearchRequest(
                    data=[query],
                    anns_field="sparse",
                    param={"metric_type": "BM25"},
                    limit=_POOL_SIZE,
                ),
            )
        if not requests:
            return []

        escaped = ",".join(f'"{sid}"' for sid in space_ids)
        # 双路用与单层一致的 0.7/0.3 权重；单路时权重数必须与请求数对齐
        if len(requests) == 2:
            ranker = WeightedRanker(VECTOR_WEIGHT, KEYWORD_WEIGHT)
        else:
            ranker = WeightedRanker(1.0)
        results = client.hybrid_search(
            COLLECTION_NAME,
            reqs=requests,
            ranker=ranker,
            limit=max(1, top_k),
            filter=f"space_id in [{escaped}]",
            output_fields=list(_OUTPUT_FIELDS),
        )
        hits: List[KbSearchHit] = []
        for hit in results[0] if results else []:
            entity = hit.get("entity") or {}
            parent_seq = entity.get("parent_seq", _NO_PARENT)
            # pymilvus 的 Hit 不是 dict：hit.get("id"/"pk") 恒为 None，
            # 主键经 hit.id 属性暴露（真机实测），entity 回填作双保险
            chunk_id = str(
                getattr(hit, "id", "") or entity.get("chunk_id") or "",
            )
            hits.append(
                KbSearchHit(
                    space_id=str(entity.get("space_id", "")),
                    document_id=str(entity.get("document_id", "")),
                    chunk_id=chunk_id,
                    seq=int(entity.get("seq") or 0),
                    heading_path=str(entity.get("heading_path") or ""),
                    text=str(entity.get("content_text") or ""),
                    score=float(hit.get("distance") or 0.0),
                    parent_seq=(
                        None if parent_seq == _NO_PARENT else int(parent_seq)
                    ),
                ),
            )
        return hits

    async def search(
        self,
        space_ids: Sequence[str],
        query: str,
        query_embedding: Optional[Sequence[float]] = None,
        top_k: int = 5,
    ) -> List[KbSearchHit]:
        """混合检索（dense + BM25，WeightedRanker 融合）；失败返回空列表。"""
        ids = [str(space_id) for space_id in space_ids if str(space_id)]
        query_text = (query or "").strip()
        if not ids or (not query_text and query_embedding is None):
            return []
        try:
            return await asyncio.to_thread(
                self._search_sync,
                ids,
                query_text,
                query_embedding,
                top_k,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] milvus search failed; returning empty set",
                exc_info=True,
            )
            return []

    # ------------------------------------------------------------------
    # 写入面（异常向调用方传播）
    # ------------------------------------------------------------------

    def _rows(
        self,
        space_id: str,
        document_id: str,
        chunks: Sequence[ChunkSpec],
        embeddings: Optional[Sequence[Sequence[float]]],
    ) -> List[Dict[str, Any]]:
        """组装 upsert 行；缺向量的切片以零向量占位（BM25 路仍可召回）。"""
        vectors = list(embeddings) if embeddings is not None else []
        zero = [0.0] * self._dim
        rows: List[Dict[str, Any]] = []
        for index, spec in enumerate(chunks):
            # 缺位与显式 None 同义：该条切片无向量，以零向量占位
            raw = vectors[index] if index < len(vectors) else None
            dense = list(raw) if raw is not None else list(zero)
            rows.append(
                {
                    "chunk_id": f"{document_id}_{spec.seq}",
                    "space_id": space_id,
                    "document_id": document_id,
                    "seq": spec.seq,
                    "heading_path": spec.heading_path,
                    "content_text": spec.text,
                    "parent_seq": (
                        _NO_PARENT
                        if spec.parent_seq is None
                        else spec.parent_seq
                    ),
                    "dense": dense,
                },
            )
        return rows

    def _index_sync(
        self,
        space_id: str,
        document_id: str,
        chunks: Sequence[ChunkSpec],
        embeddings: Optional[Sequence[Sequence[float]]],
    ) -> int:
        """同步实现：删旧行 + upsert 新行（重建语义，幂等）。"""
        client = self._get_client()
        if client is None:
            raise RuntimeError("milvus client unavailable")
        self._ensure_collection(client)
        client.delete(
            COLLECTION_NAME,
            filter=f'document_id == "{document_id}"',
        )
        rows = self._rows(space_id, document_id, chunks, embeddings)
        if rows:
            client.upsert(COLLECTION_NAME, data=rows)
        return len(rows)

    async def index_document(
        self,
        space_id: str,
        document_id: str,
        chunks: Sequence[ChunkSpec],
        embeddings: Optional[Sequence[Sequence[float]]] = None,
        *,
        title: str = "",
    ) -> int:
        """重建一份文档的索引（同 ``document_id`` 旧行先删）。"""
        # title 由知识组织层权威承担；显式弃用（保持三引擎统一调用形状）
        del title
        return await asyncio.to_thread(
            self._index_sync,
            space_id,
            document_id,
            list(chunks),
            embeddings,
        )

    def _delete_sync(self, document_id: str) -> None:
        """同步实现：按文档删除（Milvus delete 无可靠 rowcount）。"""
        client = self._get_client()
        if client is None:
            raise RuntimeError("milvus client unavailable")
        self._ensure_collection(client)
        client.delete(
            COLLECTION_NAME,
            filter=f'document_id == "{document_id}"',
        )

    async def delete_document(
        self,
        space_id: str,
        document_id: str,
    ) -> int:
        """删除一份文档的行；Milvus 不返回可靠 rowcount，返回 0 表示已下发。"""
        await asyncio.to_thread(self._delete_sync, document_id)
        return 0

    async def flush(self) -> None:
        """同步可见点：写入批次收口后调用，返回即可搜。

        Bounded 一致性下写入约秒级才收敛可见；flush 提供确定性可见点
        （真机实测：flush 前立即查 0 行、flush 后立即查命中）。异常向
        调用方传播（与写入面约定一致），由编排层决定降级策略。
        """
        client = self._get_client()
        if client is None:
            raise RuntimeError("milvus client unavailable")
        self._ensure_collection(client)
        await asyncio.to_thread(client.flush, COLLECTION_NAME)


__all__ = [
    "COLLECTION_NAME",
    "DEFAULT_MILVUS_URI",
    "MilvusEngine",
]
