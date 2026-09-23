# -*- coding: utf-8 -*-
"""M6-5: L2 Milvus 引擎真机集成用例（URI 门控）。

运行方式：环境变量 ``QWENPAW_TEST_MILVUS_URI``（如
``http://127.0.0.1:19530``）未设时整文件 skip；环境用 Milvus 官方
standalone 即可（``docker compose --profile milvus up -d``，或开发机上
既有的等价三容器组）。

用例自清洗：数据全部写入独立空间 ``kb_it_milvus``，首尾按 ``space_id``
过滤删除；**不使用 ``drop_collection``**——``kb_chunks_v1`` 是共享
collection，测试不得整体清除。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.p0]

_URI = os.environ.get("QWENPAW_TEST_MILVUS_URI", "").strip()

#: 真机用例的固定空间/文档 ID（首尾清洗）
_IT_SPACE = "kb_it_milvus"
_IT_DOC = "doc_it_milvus"


def _require_uri() -> str:
    """取门控 URI；未配置时跳过（整文件 skip 语义）。"""
    if not _URI:
        pytest.skip(
            "QWENPAW_TEST_MILVUS_URI not set (milvus-gated tests)",
        )
    return _URI


def _dense(axis: int) -> list:
    """1024 维轴基向量（可分辨的稠密探针）。"""
    vector = [0.0] * 1024
    vector[axis] = 1.0
    return vector


def _purge(uri: str) -> None:
    """按空间清掉本用例的行（collection 不存在时为空操作）。"""
    from pymilvus import MilvusClient

    from qwenpaw.app.kb.milvus_engine import COLLECTION_NAME

    client = MilvusClient(uri=uri)
    if client.has_collection(COLLECTION_NAME):
        client.delete(
            COLLECTION_NAME,
            filter=f'space_id == "{_IT_SPACE}"',
        )


def test_kb_milvus_engine_roundtrip() -> None:
    """L2 真机往返：建 collection → 写入 → 中文 BM25 命中 → 向量路径 → 删除。

    真机才能证的语义：服务端 BM25 function（chinese analyzer）对中文
    短语可命中；dense + sparse 双路经 WeightedRanker 融合；partition
    key（space_id）过滤生效；``parent_seq`` 直读字段回填；``flush``
    落地“写入返回即可搜”的同步可见点。
    """

    async def _run() -> None:
        from qwenpaw.app.kb.chunker import ChunkSpec
        from qwenpaw.app.kb.milvus_engine import MilvusEngine

        uri = _require_uri()
        engine = MilvusEngine(uri=uri)
        _purge(uri)
        try:
            specs = [
                ChunkSpec(
                    seq=0,
                    heading_path="甲减 > 用药",
                    text="左甲状腺素的妊娠早期剂量调整需要监测 TSH。",
                    parent_seq=None,
                    token_count=20,
                ),
                ChunkSpec(
                    seq=1,
                    heading_path="甲减 > 监测",
                    text="TSH 目标在妊娠早期低于 2.5 mIU/L。",
                    parent_seq=0,
                    token_count=15,
                ),
                ChunkSpec(
                    seq=2,
                    heading_path="孕期 > 营养",
                    text="孕期补钙与维生素 D 的常规建议。",
                    parent_seq=None,
                    token_count=12,
                ),
            ]
            dense_a = _dense(0)
            dense_b = _dense(1)
            written = await engine.index_document(
                _IT_SPACE,
                _IT_DOC,
                specs,
                [dense_a, None, dense_b],
            )
            assert written == 3
            # 同步可见点：Bounded 一致性不 flush 则检索约秒级后才收敛
            await engine.flush()

            # 中文 BM25 命中（服务端 chinese analyzer 分词；默认 standard
            # analyzer 不切中文——真机实测中文查询恒空）
            hits = await engine.search([_IT_SPACE], "左甲状腺素", None, 5)
            assert hits, "Chinese phrase must hit via server-side BM25"
            assert "左甲状腺素" in hits[0].text
            assert hits[0].document_id == _IT_DOC

            # parent_seq 直读（子块指向节首块）
            tsh_hits = await engine.search([_IT_SPACE], "TSH", None, 5)
            assert tsh_hits
            child = next(h for h in tsh_hits if h.seq == 1)
            assert child.parent_seq == 0

            # 向量路径：dense 探针（查询词与库内文本无 BM25 交集）
            vec_hits = await engine.search(
                [_IT_SPACE],
                "探针XYZ",
                dense_a,
                5,
            )
            assert vec_hits, "dense probe must return vector-path hits"
            assert vec_hits[0].chunk_id.endswith("_0")

            # 删除后不可见（flush 加速收敛，短轮询兜底）
            await engine.delete_document(_IT_SPACE, _IT_DOC)
            await engine.flush()
            remaining = await engine.search(
                [_IT_SPACE],
                "左甲状腺素",
                None,
                5,
            )
            for _ in range(10):
                if not remaining:
                    break
                await asyncio.sleep(0.5)
                remaining = await engine.search(
                    [_IT_SPACE],
                    "左甲状腺素",
                    None,
                    5,
                )
            assert remaining == []
        finally:
            _purge(uri)

    asyncio.run(_run())
