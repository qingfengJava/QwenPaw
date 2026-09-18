# -*- coding: utf-8 -*-
"""L1 pgvector 引擎：``kb_chunks`` 上的单 SQL 混合检索（默认引擎）。

检索形态（spec §5）：向量 CTE 与全文 CTE 各自先取候选池 top50（内层
``ORDER BY ... LIMIT`` 让 HNSW / GIN 索引的 top-k 优化生效），再在同一 SQL
内以 RRF 融合（权重与 k 引用 :mod:`qwenpaw.app.kb.search` 的共享常量，
与内存融合同口径）——一次数据库往返完成「混检 + 融合」。

分词口径（与索引侧同源，T3 教训）：写入 ``tsv`` 用
``tokenize_mixed(embed_input(spec))``（标题路径 + 正文，标题里的专有名词可被
BM25 命中）；查询侧 ``' & '.join(tokenize_mixed(query))`` 组成 tsquery。
两边不是同一套 tokenizer 时，中文关键词会整库搜不到。

向量参数以字符串字面量（``[v1,v2,...]``）经 ``CAST(:qv AS vector)`` 绑定，
不引入 pgvector 的 Python 扩展包——列宽与写入口的一致性由 Task 4 的
维度守卫保证。

失败语义：**检索面 fail-soft**（异常仅 WARN 返回空列表）；**写入面异常向
调用方传播**（摄入状态机需要据此落 ``failed``，静默吞掉会让状态永远卡在
processing）。巡检链路的「永不报错」承诺只覆盖检索。

@author qingfeng
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from .chunker import ChunkSpec, embed_input
from .hits import KbSearchHit
from .pg_store import DEFAULT_TENANT_ID
from .search import (
    KEYWORD_WEIGHT,
    RRF_K,
    VECTOR_WEIGHT,
    tokenize_mixed,
)

logger = logging.getLogger(__name__)

#: 各分支进入融合的候选池大小（spec §5：单分支 top50）
_POOL_SIZE = 50

#: 向量分支 CTE：内层 top-k 扫描（HNSW 友好），外层对候选池编排名
_VEC_CTE = f"""
vec AS (
    SELECT id, row_number() OVER (ORDER BY distance) AS rank
    FROM (
        SELECT id, embedding <=> CAST(:qv AS vector) AS distance
        FROM kb_chunks
        WHERE tenant_id = :tenant AND space_id = ANY(:space_ids)
          AND embedding IS NOT NULL
        ORDER BY distance
        LIMIT {_POOL_SIZE}
    ) pool
)
"""

#: 全文分支 CTE：GIN 命中后按 ts_rank 取候选池
_KW_CTE = f"""
kw AS (
    SELECT id, row_number() OVER (ORDER BY score DESC) AS rank
    FROM (
        SELECT id, ts_rank(tsv, to_tsquery('simple', :tsq)) AS score
        FROM kb_chunks
        WHERE tenant_id = :tenant AND space_id = ANY(:space_ids)
          AND tsv @@ to_tsquery('simple', :tsq)
        ORDER BY score DESC
        LIMIT {_POOL_SIZE}
    ) pool
)
"""


def _score_term(alias: str, weight: float) -> str:
    """融合打分子式（与内存融合的 ``weight / (k + rank)`` 同形）。"""
    return f"COALESCE({weight:g} / ({RRF_K:g} + {alias}.rank), 0)"


def _build_search_sql(with_vector: bool, with_keyword: bool) -> str:
    """按可用分支组装检索 SQL（片段受控拼接，无用户输入）。

    向量缺失时仅全文分支、全文无 token 时仅向量分支——调用方保证二者
    至少一个为真；两个都为假是调用方的编程错误，此处仍返回合法 SQL
    （空检索），由调用方短路。
    """
    ctes: List[str] = []
    joins: List[str] = []
    terms: List[str] = []
    if with_vector:
        ctes.append(_VEC_CTE)
        joins.append("LEFT JOIN vec ON vec.id = c.id")
        terms.append(_score_term("vec", VECTOR_WEIGHT))
    if with_keyword:
        ctes.append(_KW_CTE)
        joins.append("LEFT JOIN kw ON kw.id = c.id")
        terms.append(_score_term("kw", KEYWORD_WEIGHT))
    score_expr = " + ".join(terms)
    return f"""
    WITH {", ".join(ctes)}
    SELECT c.id, c.space_id, c.document_id, c.seq, c.heading_path,
           c.content_text, c.parent_chunk_id,
           {score_expr} AS score
    FROM kb_chunks c
    {" ".join(joins)}
    WHERE {score_expr} > 0
    ORDER BY score DESC, c.id
    LIMIT :top_k
    """


#: 逐条写入切片（重建语义：调用方先删同文档旧行）
_INSERT_CHUNK_SQL = """
INSERT INTO kb_chunks (
    tenant_id, id, space_id, document_id, seq, heading_path,
    parent_chunk_id, token_count, content_text, tsv, embedding,
    model_name
) VALUES (
    :tenant, :chunk_id, :space_id, :document_id, :seq, :heading_path,
    :parent_chunk_id, :token_count, :content_text,
    to_tsvector('simple', :ts_text),
    CAST(:embedding AS vector),
    :model_name
)
"""

_DELETE_DOCUMENT_SQL = """
DELETE FROM kb_chunks
WHERE tenant_id = :tenant AND document_id = :document_id
"""


def _vector_literal(values: Sequence[float]) -> str:
    """pgvector 文本字面量（``[v1,v2,...]``；``repr`` 保证浮点往返精度）。"""
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def _parent_seq(parent_chunk_id: str) -> Optional[int]:
    """从 ``{document_id}_{seq}`` 反解父块 seq；空串或不可解析返回 ``None``。"""
    if not parent_chunk_id:
        return None
    try:
        return int(parent_chunk_id.rsplit("_", 1)[-1])
    except ValueError:
        return None


def _hit_from_row(row: Any) -> KbSearchHit:
    """SQL 行 → :class:`KbSearchHit`（``parent_chunk_id`` 反解 ``parent_seq``）。"""
    return KbSearchHit(
        space_id=str(row.space_id),
        document_id=str(row.document_id),
        chunk_id=str(row.id),
        seq=int(row.seq or 0),
        heading_path=str(row.heading_path or ""),
        text=str(row.content_text or ""),
        score=float(row.score or 0.0),
        parent_seq=_parent_seq(str(row.parent_chunk_id or "")),
    )


class PgVectorEngine:
    """pgvector 引擎（L1）：单 SQL 混合检索 + 切片重建写入。"""

    def __init__(self, engine: Any = None) -> None:
        self._engine = engine

    def _get_engine(self) -> Any:
        """惰性取共享连接池（json-only 部署永不触达）。"""
        if self._engine is None:
            from ...db.engine import create_pg_engine

            self._engine = create_pg_engine()
        return self._engine

    # ------------------------------------------------------------------
    # 检索面（fail-soft）
    # ------------------------------------------------------------------

    async def search(
        self,
        space_ids: Sequence[str],
        query: str,
        query_embedding: Optional[Sequence[float]] = None,
        top_k: int = 5,
    ) -> List[KbSearchHit]:
        """混合检索（向量 + 全文，SQL 内 RRF）；任何失败返回空列表。"""
        ids = [str(space_id) for space_id in space_ids if str(space_id)]
        query_text = (query or "").strip()
        if not ids or not query_text:
            return []
        tokens = tokenize_mixed(query_text)
        with_vector = query_embedding is not None
        with_keyword = bool(tokens)
        if not with_vector and not with_keyword:
            return []

        sql = _build_search_sql(with_vector, with_keyword)
        params: Dict[str, Any] = {
            "tenant": DEFAULT_TENANT_ID,
            "space_ids": ids,
            "top_k": max(1, top_k),
        }
        if with_vector:
            params["qv"] = _vector_literal(query_embedding)
        if with_keyword:
            params["tsq"] = " & ".join(tokens)
        try:
            from sqlalchemy import text

            async with self._get_engine().connect() as conn:
                rows = (await conn.execute(text(sql), params)).fetchall()
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg engine search failed; returning empty set",
                exc_info=True,
            )
            return []
        return [_hit_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # 写入面（异常向调用方传播：摄入状态机据此落 failed）
    # ------------------------------------------------------------------

    async def index_document(
        self,
        space_id: str,
        document_id: str,
        chunks: Sequence[ChunkSpec],
        embeddings: Optional[Sequence[Sequence[float]]] = None,
        *,
        title: str = "",
        model_name: str = "",
    ) -> int:
        """重建一份文档的切片索引（同 ``document_id`` 旧行先删）。

        Args:
            space_id: 知识库 ID。
            document_id: 文档 ID（``chunk_id`` 前缀与删除谓词）。
            chunks: 切片器产出（阅读序；``seq`` 为文档内序号）。
            embeddings: 与 *chunks* 严格同序的向量；缺省时该条 ``embedding``
                为 NULL（BM25 分支仍然命中）。
            title: 保留参数（PG 面标题落 ``kb_documents``，此处不冗余）。
            model_name: 产生向量的模型名（换模型重建依据）。

        Returns:
            写入的切片条数。
        """
        specs = list(chunks)
        vectors = list(embeddings) if embeddings is not None else []
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(_DELETE_DOCUMENT_SQL),
                {"tenant": DEFAULT_TENANT_ID, "document_id": document_id},
            )
            for index, spec in enumerate(specs):
                # 缺位与显式 None 同义：该条切片无向量（embedding 列写 NULL）
                raw = vectors[index] if index < len(vectors) else None
                vector = _vector_literal(raw) if raw is not None else None
                parent_chunk_id = (
                    f"{document_id}_{spec.parent_seq}"
                    if spec.parent_seq is not None
                    else ""
                )
                await conn.execute(
                    text(_INSERT_CHUNK_SQL),
                    {
                        "tenant": DEFAULT_TENANT_ID,
                        "chunk_id": f"{document_id}_{spec.seq}",
                        "space_id": space_id,
                        "document_id": document_id,
                        "seq": spec.seq,
                        "heading_path": spec.heading_path,
                        "parent_chunk_id": parent_chunk_id,
                        "token_count": spec.token_count,
                        "content_text": spec.text,
                        "ts_text": " ".join(
                            tokenize_mixed(embed_input(spec)),
                        ),
                        "embedding": vector,
                        "model_name": model_name,
                    },
                )
        return len(specs)

    async def delete_document(
        self,
        space_id: str,
        document_id: str,
    ) -> int:
        """删除一份文档的切片行，返回删除条数。"""
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(_DELETE_DOCUMENT_SQL),
                {"tenant": DEFAULT_TENANT_ID, "document_id": document_id},
            )
        return int(result.rowcount or 0)


__all__ = [
    "PgVectorEngine",
]
