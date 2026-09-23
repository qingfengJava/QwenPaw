# -*- coding: utf-8 -*-
"""M6-5 + T2: 引擎工厂路由、按库分组与回退。

检索引擎三层实现（L0 FileKbEngine / L1 PgVectorEngine / L2 MilvusEngine）
共用同一套上层语义：

- 默认引擎（T2 升级）：``pymilvus`` 已装、未被
  ``QWENPAW_KB_DEFAULT_ENGINE=pgvector`` 禁用且服务可达（TTL 缓存探测）
  时落 Milvus（回退链 milvus → pgvector → file）；否则按存储后端三态——
  json 落 File，pg/dual 且 ``kb_chunks`` 表存在落 PgVector，探不到表
  回退 File（启动/检索不阻塞）；
- ``kb_spaces.engine`` 按库路由——auto 落默认引擎，``pgvector`` 显式钉
  住 pg 面（默认引擎已升 Milvus 时用专用单例），milvus 显式落
  MilvusEngine，**驱动缺失或服务不可达时告警回退默认引擎**（检索不中断）；
- 跨引擎的候选库按引擎分组检索后 RRF 二次融合（k=60 与单层检索一致），
  融合序必须确定（相同输入两次调用结果一致，不依赖 dict 遍历序）。

本文件锁定 monkeypatch 契约面：``eng.write_gateway.
resolve_storage_backend`` / ``eng._kb_chunks_table_exists`` /
``eng._milvus_preferred`` / ``eng._milvus_reachable``（均同步探针；
``_pymilvus_available`` 仅作为 ``_milvus_preferred`` 的底层实现存在）。

@author qingfeng
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

import pytest

from qwenpaw.app.kb import engine as eng
from qwenpaw.app.kb.models import KbSpace

pytestmark = pytest.mark.unit


def _pg_engine_stub() -> Any:
    """不经 __init__ 造一个 PgVectorEngine 实例（仅作路由断言的哨兵）。"""
    return eng.PgVectorEngine.__new__(eng.PgVectorEngine)


@pytest.fixture(autouse=True)
def _no_milvus_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """本文件默认锁定「无 Milvus」语义（历史 pg/file 路由不受真机影响）。

    本机装了 pymilvus 时 ``_milvus_preferred`` 真实现会返回 True，默认
    路由受可达性探测环境干扰；统一 mock 后，需要 Milvus 语义的用例在
    用例内再覆盖 mock（monkeypatch 同名 attr 后注册者生效）。
    """
    monkeypatch.setattr(eng, "_milvus_preferred", lambda: False)
    monkeypatch.setattr(eng, "_milvus_reachable", lambda: False)


# ---------------------------------------------------------------------------
# 默认引擎工厂：存储后端三态 × kb_chunks 表探测
# ---------------------------------------------------------------------------


def test_factory_json_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """json 后端：默认引擎是 FileKbEngine（现值收编，无 PG 依赖）。"""
    monkeypatch.setattr(
        eng.write_gateway,
        "resolve_storage_backend",
        lambda: eng.write_gateway.BACKEND_JSON,
    )

    assert isinstance(eng.get_kb_engine(), eng.FileKbEngine)


def test_factory_pg_backend_without_table_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg 后端但 kb_chunks 表缺失：回退 FileEngine，启动不阻塞。"""
    monkeypatch.setattr(
        eng.write_gateway,
        "resolve_storage_backend",
        lambda: eng.write_gateway.BACKEND_PG,
    )
    monkeypatch.setattr(eng, "_kb_chunks_table_exists", lambda: False)

    assert isinstance(eng.get_kb_engine(), eng.FileKbEngine)


def test_factory_pg_backend_with_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg 后端且 kb_chunks 表存在：默认引擎落 PgVectorEngine。"""
    monkeypatch.setattr(
        eng.write_gateway,
        "resolve_storage_backend",
        lambda: eng.write_gateway.BACKEND_PG,
    )
    monkeypatch.setattr(eng, "_kb_chunks_table_exists", lambda: True)

    assert isinstance(eng.get_kb_engine(), eng.PgVectorEngine)


def test_factory_dual_backend_with_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dual 后端（文件 primary + PG 影子）与 pg 同语义：表在即 PgVector。"""
    monkeypatch.setattr(
        eng.write_gateway,
        "resolve_storage_backend",
        lambda: eng.write_gateway.BACKEND_DUAL,
    )
    monkeypatch.setattr(eng, "_kb_chunks_table_exists", lambda: True)

    assert isinstance(eng.get_kb_engine(), eng.PgVectorEngine)


# ---------------------------------------------------------------------------
# 按库路由：kb_spaces.engine 字段
# ---------------------------------------------------------------------------


def test_resolve_engine_by_space_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto/pgvector 落默认引擎（无 milvus 语义）；milvus 可用落 Milvus。"""
    default = _pg_engine_stub()
    monkeypatch.setattr(eng, "get_kb_engine", lambda: default)
    # 覆盖 autouse：本用例需要 Milvus 可用语义（驱动已装 + 服务可达）
    monkeypatch.setattr(eng, "_milvus_preferred", lambda: True)
    monkeypatch.setattr(eng, "_milvus_reachable", lambda: True)

    milvus_space = KbSpace(id="s1", name="n", engine="milvus")
    assert isinstance(eng.resolve_engine_for(milvus_space), eng.MilvusEngine)

    auto_space = KbSpace(id="s2", name="n")
    assert eng.resolve_engine_for(auto_space) is default

    # milvus 可用语义下，显式 pgvector 钉住 pg 面专用单例（不落 default）
    explicit_pg = KbSpace(id="s3", name="n", engine="pgvector")
    resolved = eng.resolve_engine_for(explicit_pg)
    assert isinstance(resolved, eng.PgVectorEngine)
    assert resolved is eng._get_pgvector_engine()


def test_milvus_engine_missing_driver_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """库配了 milvus 但 Milvus 不可用（驱动缺失/服务不可达）：回退默认。"""
    fallback = _pg_engine_stub()
    monkeypatch.setattr(eng, "get_kb_engine", lambda: fallback)

    space = KbSpace(id="s1", name="n", engine="milvus")

    assert eng.resolve_engine_for(space) is fallback


# ---------------------------------------------------------------------------
# T2 路由升级：Milvus 优先 + 可达性探测 + env 钉回 + 显式 pgvector 单例
# ---------------------------------------------------------------------------


def test_factory_milvus_preferred_and_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Milvus 优先（T2 定稿）：驱动已装且服务可达 → 默认引擎即 Milvus。"""
    monkeypatch.setattr(eng, "_milvus_preferred", lambda: True)
    monkeypatch.setattr(eng, "_milvus_reachable", lambda: True)

    first = eng.get_kb_engine()
    second = eng.get_kb_engine()

    assert isinstance(first, eng.MilvusEngine)
    # identity 稳定：分组检索按实例分组，跨调用必须同一实例
    assert first is second


def test_factory_milvus_preferred_but_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """驱动已装但服务不可达：回退 pg/file 面（不因 milvus 挂而中断）。"""
    monkeypatch.setattr(eng, "_milvus_preferred", lambda: True)
    monkeypatch.setattr(eng, "_milvus_reachable", lambda: False)
    monkeypatch.setattr(
        eng.write_gateway,
        "resolve_storage_backend",
        lambda: eng.write_gateway.BACKEND_PG,
    )
    monkeypatch.setattr(eng, "_kb_chunks_table_exists", lambda: True)

    assert isinstance(eng.get_kb_engine(), eng.PgVectorEngine)


def test_env_pin_pgvector_disables_milvus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QWENPAW_KB_DEFAULT_ENGINE=pgvector：显式禁用 Milvus 优先。"""
    monkeypatch.setenv(eng.ENV_DEFAULT_ENGINE, "pgvector")
    # 恢复真实现（autouse mock 了 _milvus_preferred），env 分支才生效
    monkeypatch.setattr(eng, "_milvus_preferred", eng._milvus_preferred)
    monkeypatch.setattr(eng, "_pymilvus_available", lambda: True)
    monkeypatch.setattr(
        eng.write_gateway,
        "resolve_storage_backend",
        lambda: eng.write_gateway.BACKEND_PG,
    )
    monkeypatch.setattr(eng, "_kb_chunks_table_exists", lambda: True)

    assert eng._milvus_preferred() is False
    assert isinstance(eng.get_kb_engine(), eng.PgVectorEngine)


def test_explicit_pgvector_pins_pg_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式 pgvector 在默认引擎已升 Milvus 时仍钉住 pg 面（专用单例）。"""
    monkeypatch.setattr(eng, "_milvus_preferred", lambda: True)
    monkeypatch.setattr(eng, "_milvus_reachable", lambda: True)

    space = KbSpace(id="s1", name="n", engine="pgvector")

    first = eng.resolve_engine_for(space)
    second = eng.resolve_engine_for(space)
    assert isinstance(first, eng.PgVectorEngine)
    # 单例 identity：跨调用同一实例（分组检索依赖）
    assert first is second
    # 与默认 Milvus 引擎不是同一实例
    assert first is not eng.get_kb_engine()


def test_milvus_space_unreachable_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式 milvus 库在服务不可达时回退默认引擎（告警不中断）。"""
    monkeypatch.setattr(eng, "_milvus_preferred", lambda: True)
    monkeypatch.setattr(eng, "_milvus_reachable", lambda: False)
    fallback = _pg_engine_stub()
    monkeypatch.setattr(eng, "get_kb_engine", lambda: fallback)

    space = KbSpace(id="s1", name="n", engine="milvus")

    assert eng.resolve_engine_for(space) is fallback


# ---------------------------------------------------------------------------
# 跨引擎分组检索 + RRF 二次融合
# ---------------------------------------------------------------------------


class _FakeEngine:
    """替身引擎：记录调用并按预置命中返回。"""

    def __init__(self, hits: List[eng.KbSearchHit]) -> None:
        self._hits = hits
        self.calls: List[tuple] = []

    async def index_document(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("分组检索不应触碰写入面")

    async def delete_document(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("分组检索不应触碰写入面")

    async def search(
        self,
        space_ids: Sequence[str],
        query: str,
        query_embedding: Optional[Sequence[float]],
        top_k: int,
    ) -> List[eng.KbSearchHit]:
        self.calls.append((tuple(space_ids), query, top_k))
        return [hit for hit in self._hits if hit.space_id in space_ids]


def _hit(space_id: str, chunk_id: str, score: float) -> eng.KbSearchHit:
    """造一条最小命中。"""
    return eng.KbSearchHit(
        space_id=space_id,
        document_id=f"d_{space_id}",
        chunk_id=chunk_id,
        seq=0,
        heading_path="",
        text=f"文本 {chunk_id}",
        score=score,
        parent_seq=0,
    )


@pytest.mark.asyncio
async def test_hybrid_search_multi_groups_by_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两个 space 分属不同引擎：各自只收到所属 space 的检索请求。"""
    pg_engine = _FakeEngine([_hit("s1", "c1", 0.9), _hit("s1", "c2", 0.5)])
    file_engine = _FakeEngine([_hit("s2", "c3", 0.8)])
    monkeypatch.setattr(
        eng,
        "resolve_engine_for",
        lambda space: pg_engine if space.engine == "pgvector" else file_engine,
    )
    spaces = [
        KbSpace(id="s1", name="n", engine="pgvector"),
        KbSpace(id="s2", name="n", engine="auto"),
    ]

    result = await eng.hybrid_search_multi(spaces, "问题", None, 5)

    assert pg_engine.calls == [(("s1",), "问题", 5)]
    assert file_engine.calls == [(("s2",), "问题", 5)]
    assert sorted(hit.chunk_id for hit in result) == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_hybrid_search_multi_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同分同序的融合结果必须确定（不得依赖 dict 遍历序抖动）。"""
    pg_engine = _FakeEngine([_hit("s1", "c1", 0.9)])
    file_engine = _FakeEngine([_hit("s2", "c2", 0.9)])
    monkeypatch.setattr(
        eng,
        "resolve_engine_for",
        lambda space: pg_engine if space.engine == "pgvector" else file_engine,
    )
    spaces = [
        KbSpace(id="s1", name="n", engine="pgvector"),
        KbSpace(id="s2", name="n", engine="auto"),
    ]

    first = await eng.hybrid_search_multi(spaces, "问题", None, 5)
    second = await eng.hybrid_search_multi(spaces, "问题", None, 5)

    assert [hit.chunk_id for hit in first] == [hit.chunk_id for hit in second]


@pytest.mark.asyncio
async def test_hybrid_search_multi_engine_error_is_fail_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单组引擎抛错不得让整次检索失败：该组退化空贡献，其余组结果保留。"""

    class _BoomEngine(_FakeEngine):
        async def search(
            self,
            space_ids: Sequence[str],
            query: str,
            query_embedding: Optional[Sequence[float]],
            top_k: int,
        ) -> List[eng.KbSearchHit]:
            raise RuntimeError("engine down")

    pg_engine = _BoomEngine([])
    file_engine = _FakeEngine([_hit("s2", "c3", 0.8)])
    monkeypatch.setattr(
        eng,
        "resolve_engine_for",
        lambda space: pg_engine if space.engine == "pgvector" else file_engine,
    )
    spaces = [
        KbSpace(id="s1", name="n", engine="pgvector"),
        KbSpace(id="s2", name="n", engine="auto"),
    ]

    result = await eng.hybrid_search_multi(spaces, "问题", None, 5)

    assert [hit.chunk_id for hit in result] == ["c3"]
