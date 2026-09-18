# -*- coding: utf-8 -*-
"""L0 文件引擎：JSONL 存储的收编（无 PG 部署的回退面）。

M4-5 时代知识库的 chunk 存储是「每库一份 ``chunks.jsonl``」；本模块把这套
读写逻辑从 ``service.py`` **原样搬移**过来（KbService 的同名私有方法改为
薄委托），使「文件」与 pgvector / Milvus 一样成为检索引擎的一种实现。

语义边界（json 面不承载结构字段）：

- ``heading_path`` / ``parent_seq`` 是切片器的结构锚点，JSONL 现状格式
  没有这两列；本引擎读出的命中其 ``heading_path`` 为空串、``parent_seq``
  为 ``None``——需要结构字段（S2 扩展、溯源面包屑）的部署须切 pg/milvus。

写入语义：``index_document`` 是**重建**语义（同 ``document_id`` 的旧切片
先删后写，重复调用幂等），与 Task 6 摄入服务的「重切重嵌」对齐。

@author qingfeng
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from ...constant import SECRET_DIR
from .chunker import ChunkSpec
from .hits import KbSearchHit
from .models import KbChunk
from .search import search_chunks

logger = logging.getLogger(__name__)

#: 文件面存储根目录（json 后端与 L0 引擎共用）
DEFAULT_KB_DATA_DIR = SECRET_DIR / "kb_data"


def _chmod_best_effort(path: Path, mode: int) -> None:
    """尽力设置权限位（Windows 上多数场景为 no-op）。"""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


class FileKbEngine:
    """文件引擎（L0）：包裹现状 chunks.jsonl 读写，语义与 M4-5 逐字一致。"""

    def __init__(self, data_dir: Path | str = DEFAULT_KB_DATA_DIR) -> None:
        self._data_dir = Path(data_dir)
        #: 每库 chunk 缓存：space_id -> (mtime_ns, chunks)（搬移自 KbService）
        self._chunk_cache: dict[str, tuple[Optional[int], List[KbChunk]]] = {}

    # ------------------------------------------------------------------
    # JSONL 存储面（KbService 委托与引擎自有检索共用）
    # ------------------------------------------------------------------

    def chunks_path(self, space_id: str) -> Path:
        """该库的 ``chunks.jsonl`` 路径。"""
        return self._data_dir / space_id / "chunks.jsonl"

    def load_chunks(self, space_id: str) -> List[KbChunk]:
        """读某库全部切片（mtime 缓存，语义与 M4-5 一致）。"""
        path = self.chunks_path(space_id)
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        cached = self._chunk_cache.get(space_id)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        chunks: list[KbChunk] = []
        if mtime is not None:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            chunks.append(KbChunk.model_validate_json(line))
            except (OSError, ValueError) as exc:
                logger.error("Failed to read kb chunks %s: %s", path, exc)
        self._chunk_cache[space_id] = (mtime, chunks)
        return chunks

    def save_chunks(self, space_id: str, chunks: List[KbChunk]) -> None:
        """整库重写 ``chunks.jsonl`` 并刷新缓存。"""
        path = self.chunks_path(space_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(path.parent, 0o700)
        with open(path, "w", encoding="utf-8") as fh:
            for chunk in chunks:
                fh.write(chunk.model_dump_json() + "\n")
        _chmod_best_effort(path, 0o600)
        try:
            mtime: Optional[int] = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        self._chunk_cache[space_id] = (mtime, chunks)

    def drop_space(self, space_id: str) -> None:
        """删除该库的存储文件与缓存（删库时的实际清理面）。"""
        path = self.chunks_path(space_id)
        try:
            path.unlink(missing_ok=True)
            path.parent.rmdir()
        except OSError:
            pass
        self._chunk_cache.pop(space_id, None)

    # ------------------------------------------------------------------
    # 检索面
    # ------------------------------------------------------------------

    def search_sync(
        self,
        space_ids: Sequence[str],
        query: str,
        *,
        query_embedding: Optional[Sequence[float]] = None,
        top_k: int = 5,
    ) -> List[Tuple[KbChunk, float]]:
        """同步检索核心：合并各库切片做一次内存混合检索（BM25 + 可选向量）。

        多库传入时词频统计跨库共享（一次 BM25），单库调用与 M4-5 逐字一致；
        ``KbService.search``（legacy 同步面）与本引擎的 ``search`` 共用本方法，
        保证「文件检索逻辑只有一处」。

        Args:
            space_ids: 待检索的库 ID 列表。
            query: 查询原文。
            query_embedding: 查询向量，``None`` 时纯 BM25。
            top_k: 返回条数上限。

        Returns:
            ``[(chunk, fused_score)]``，按分数降序。
        """
        chunks: List[KbChunk] = []
        for space_id in space_ids:
            chunks.extend(self.load_chunks(space_id))
        return search_chunks(
            chunks,
            query,
            query_embedding=query_embedding,
            top_k=top_k,
        )

    async def search(
        self,
        space_ids: Sequence[str],
        query: str,
        query_embedding: Optional[Sequence[float]] = None,
        top_k: int = 5,
    ) -> List[KbSearchHit]:
        """协议面检索：文件检索天然同步，async 包装只为统一调用形状。"""
        pairs = self.search_sync(
            space_ids,
            query,
            query_embedding=query_embedding,
            top_k=top_k,
        )
        return [
            KbSearchHit(
                space_id=chunk.kb_id,
                document_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                seq=chunk.seq,
                heading_path="",
                text=chunk.text,
                score=score,
                parent_seq=None,
            )
            for chunk, score in pairs
        ]

    async def list_document_chunks(
        self,
        space_id: str,
        document_id: str,
    ) -> List[KbSearchHit]:
        """按文档列出切片（L0 面）；heading_path 恒空，S2 降级为单块。

        与 :meth:`search` 同一语义边界（json 面不承载结构锚点）：回传的
        命中 ``heading_path`` 为空串、``parent_seq`` 为 None，需小节回补的
        部署须切 pg/milvus。
        """
        return [
            KbSearchHit(
                space_id=chunk.kb_id,
                document_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                seq=chunk.seq,
                heading_path="",
                text=chunk.text,
                score=0.0,
                parent_seq=None,
            )
            for chunk in self.load_chunks(space_id)
            if chunk.doc_id == document_id
        ]

    # ------------------------------------------------------------------
    # 写入面
    # ------------------------------------------------------------------

    async def index_document(
        self,
        space_id: str,
        document_id: str,
        chunks: Sequence[ChunkSpec],
        embeddings: Optional[Sequence[Sequence[float]]] = None,
        *,
        title: str = "",
    ) -> int:
        """写入/重建一份文档的切片；同 ``document_id`` 旧切片先删（幂等）。

        ``seq`` 落**文档内序号**（``spec.seq``），与 0034 注释的 kb_chunks
        列语义及各引擎统一——跨引擎的 chunk 标识必须同形态可互读。

        Args:
            space_id: 知识库 ID。
            document_id: 文档 ID（``chunk_id`` 前缀与删除谓词）。
            chunks: 切片器产出的 :class:`ChunkSpec` 序列（阅读序）。
            embeddings: 与 *chunks* 严格同序的向量；缺省或短于 chunks 时该条
                切片不带向量（BM25 路径永远可用）。
            title: 文档标题（JSONL 现状格式的展示字段）。

        Returns:
            写入的切片条数。
        """
        vectors = list(embeddings) if embeddings is not None else []
        kept = [
            chunk
            for chunk in self.load_chunks(space_id)
            if chunk.doc_id != document_id
        ]
        appended: List[KbChunk] = []
        for index, spec in enumerate(chunks):
            # 缺位与显式 None 同义：该条切片无向量，BM25 路径永远可用
            raw = vectors[index] if index < len(vectors) else None
            vector = list(raw) if raw is not None else None
            appended.append(
                KbChunk(
                    chunk_id=f"{document_id}_{spec.seq}",
                    kb_id=space_id,
                    doc_id=document_id,
                    title=title,
                    seq=spec.seq,
                    text=spec.text,
                    embedding=vector,
                ),
            )
        self.save_chunks(space_id, kept + appended)
        return len(appended)

    async def delete_document(self, space_id: str, document_id: str) -> int:
        """删除一份文档的切片，返回删除条数。"""
        existing = self.load_chunks(space_id)
        kept = [chunk for chunk in existing if chunk.doc_id != document_id]
        removed = len(existing) - len(kept)
        if removed:
            self.save_chunks(space_id, kept)
        return removed


__all__ = [
    "DEFAULT_KB_DATA_DIR",
    "FileKbEngine",
]
