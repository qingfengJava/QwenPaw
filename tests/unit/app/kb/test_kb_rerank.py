# -*- coding: utf-8 -*-
"""M6-4: 检索精排（S3）——凭证缺失/失败原序返回，正常路径按 index 重排。

KB 不新写 rerank HTTP 客户端：仓库唯一现成通道是
``agents.memory.reme_reranker.call_reranker_api``（OpenAI 兼容 ``/rerank``，
qwen3-rerank 与 SiliconFlow 同形）。本模块只做「配置解析 + 命中重排」，
凭证按 spec「与 embedding 同源」在 reranker 未填时继承 embedding 配置。

@author qingfeng
"""

from __future__ import annotations

import types
from typing import Any, List, Optional, Sequence

import pytest

from qwenpaw.app.kb import rerank as kb_rr
from qwenpaw.config.config import (
    EmbeddingModelConfig,
    RerankerConfig,
)

pytestmark = pytest.mark.unit

#: embedding 默认端点（精排凭证继承的断言目标）
_EMBED_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class _Hit:
    """结构化命中替身：只需 ``text`` 即满足精排契约。"""

    def __init__(self, ref: str, text: str) -> None:
        self.ref = ref
        self.text = text

    def __repr__(self) -> str:  # pragma: no cover - 仅失败时便于读断言
        return f"_Hit({self.ref})"


def _hits(count: int) -> List[_Hit]:
    """造 *count* 条可辨识命中。"""
    return [_Hit(f"h{i}", f"文本{i}" * 30) for i in range(count)]


def _refs(result: Sequence[Any]) -> List[str]:
    return [hit.ref for hit in result]


class _ApiRecorder:
    """替身 rerank 客户端：记录入参并按预置序返回。"""

    def __init__(self, order: Optional[List[int]]) -> None:
        self.order = order
        self.queries: List[str] = []
        self.documents: List[List[str]] = []
        self.calls = 0

    async def __call__(
        self,
        query: str,
        documents: Sequence[str],
        _config: RerankerConfig,
    ) -> Optional[List[int]]:
        self.calls += 1
        self.queries.append(query)
        self.documents.append(list(documents))
        return self.order


def _reranker(**overrides: Any) -> RerankerConfig:
    """一份默认启用的精排配置。"""
    values: dict[str, Any] = {
        "enabled": True,
        "api_key": "sk-rerank",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_name": "BAAI/bge-reranker-v2-m3",
    }
    values.update(overrides)
    return RerankerConfig(**values)


def _embedding_config(**overrides: Any) -> EmbeddingModelConfig:
    values: dict[str, Any] = {
        "backend": "openai",
        "api_key": "sk-embed",
        "base_url": _EMBED_BASE_URL,
        "model_name": "text-embedding-v4",
        "dimensions": 1024,
    }
    values.update(overrides)
    return EmbeddingModelConfig(**values)


def _agent_config(
    reranker: RerankerConfig,
    embedding: Optional[EmbeddingModelConfig],
) -> Any:
    """造出含 reme 精排/embedding 两段的记忆配置对象。"""
    return types.SimpleNamespace(
        reranker_config=reranker,
        embedding_model_config=embedding,
    )


# ---------------------------------------------------------------------------
# fail-soft：任何不可用路径都保持原序、长度不变
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerank_unconfigured_returns_original_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置精排模型：原序返回（RRF 序即最终序）。"""
    monkeypatch.setattr(kb_rr, "_resolve_rerank_config", lambda **_kw: None)
    items = _hits(4)

    result = await kb_rr.rerank_hits("问题", items)

    assert _refs(result) == _refs(items)


@pytest.mark.asyncio
async def test_rerank_caps_even_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """降级也要截 top_n：调用方是超量取候选，不得回退成全量。"""
    monkeypatch.setattr(kb_rr, "_resolve_rerank_config", lambda **_kw: None)

    result = await kb_rr.rerank_hits("问题", _hits(20), top_n=5)

    assert _refs(result) == [f"h{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_rerank_never_calls_api_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未启用即零网络调用（不能只靠「返回 None」间接短路）。"""
    recorder = _ApiRecorder([0])
    monkeypatch.setattr(kb_rr, "_resolve_rerank_config", lambda **_kw: None)
    monkeypatch.setattr(kb_rr, "call_reranker_api", recorder)

    await kb_rr.rerank_hits("问题", _hits(5))

    assert recorder.calls == 0


@pytest.mark.asyncio
async def test_rerank_skips_single_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只有一条命中时无需精排，也不应发起请求。"""
    recorder = _ApiRecorder([0])
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    monkeypatch.setattr(kb_rr, "call_reranker_api", recorder)
    single = _hits(1)

    result = await kb_rr.rerank_hits("问题", single)

    assert recorder.calls == 0
    assert result == single


@pytest.mark.asyncio
async def test_rerank_api_none_keeps_original_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """客户端返回 None（超时/HTTP 错误）时原序返回。"""
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    monkeypatch.setattr(kb_rr, "call_reranker_api", _ApiRecorder(None))
    items = _hits(3)

    result = await kb_rr.rerank_hits("问题", items)

    assert _refs(result) == ["h0", "h1", "h2"]


@pytest.mark.asyncio
async def test_rerank_invalid_indices_keep_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非法序（越界 / 重复 / 条数不符）一律放弃重排，宁保原序。"""
    items = _hits(3)
    for bad in ([0, 1, 9], [1, 1, 0], [0, 1], []):
        monkeypatch.setattr(
            kb_rr,
            "_resolve_rerank_config",
            lambda **_kw: _reranker(),
        )
        recorder = _ApiRecorder(list(bad))
        monkeypatch.setattr(kb_rr, "call_reranker_api", recorder)

        result = await kb_rr.rerank_hits("问题", items)

        assert _refs(result) == ["h0", "h1", "h2"], bad


@pytest.mark.asyncio
async def test_rerank_untyped_or_unhashable_indices_keep_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """响应元素类型不受控：不可 hash（list/dict）或非 int（str/float）索引
    必须原序返回。

    ``set(order)`` 遇不可 hash 元素抛 ``TypeError``；float 能骗过集合相等
    却在 ``items[index]`` 取值时抛错——两者都会击穿「精排永不抛错」。
    """
    items = _hits(3)
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    for bad in (
        [0, [1], 2],
        [{"i": 0}, 1, 2],
        ["0", "1", "2"],
        [0.0, 1.0, 2.0],
    ):
        recorder = _ApiRecorder(list(bad))
        monkeypatch.setattr(kb_rr, "call_reranker_api", recorder)

        result = await kb_rr.rerank_hits("问题", items)

        assert _refs(result) == ["h0", "h1", "h2"], bad


@pytest.mark.asyncio
async def test_rerank_skips_empty_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空查询不打精排服务（没意义且浪费额度），直接原序截断。"""
    recorder = _ApiRecorder([0, 1])
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    monkeypatch.setattr(kb_rr, "call_reranker_api", recorder)

    result = await kb_rr.rerank_hits("   ", _hits(2))

    assert recorder.calls == 0
    assert _refs(result) == ["h0", "h1"]


# ---------------------------------------------------------------------------
# 正常路径：按 index 重排 + 截断 top_n
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerank_reorders_and_caps_top_n(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """按精排 index 重排后截 top_n，且返回对象仍是原命中（不复制）。"""
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    monkeypatch.setattr(kb_rr, "call_reranker_api", _ApiRecorder([2, 0, 3, 1]))
    items = _hits(4)

    result = await kb_rr.rerank_hits("问题", items, top_n=2)

    assert _refs(result) == ["h2", "h0"]
    assert result[0] is items[2]


@pytest.mark.asyncio
async def test_rerank_top_n_larger_than_hits_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_n 大于命中数时返回全部重排结果。"""
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    monkeypatch.setattr(kb_rr, "call_reranker_api", _ApiRecorder([1, 0, 2]))

    result = await kb_rr.rerank_hits("问题", _hits(3), top_n=10)

    assert _refs(result) == ["h1", "h0", "h2"]


@pytest.mark.asyncio
async def test_rerank_non_positive_top_n_is_clamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """top_n<=0 收敛为 1，不允许「一条都不返回」的静默清空。"""
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    monkeypatch.setattr(kb_rr, "call_reranker_api", _ApiRecorder([1, 0]))

    result = await kb_rr.rerank_hits("问题", _hits(2), top_n=0)

    assert _refs(result) == ["h1"]


@pytest.mark.asyncio
async def test_rerank_sends_full_chunk_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文档正文必须原样下发（切片已按 token 预算控制，不得再截断丢内容）。"""
    recorder = _ApiRecorder([0, 1])
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    monkeypatch.setattr(kb_rr, "call_reranker_api", recorder)
    items = _hits(2)

    await kb_rr.rerank_hits("问题", items)

    assert recorder.queries == ["问题"]
    assert recorder.documents[0] == [hit.text for hit in items]


@pytest.mark.asyncio
async def test_rerank_empty_hits_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空命中集直接返回，不抛错也不发请求。"""
    recorder = _ApiRecorder([])
    monkeypatch.setattr(
        kb_rr,
        "_resolve_rerank_config",
        lambda **_kw: _reranker(),
    )
    monkeypatch.setattr(kb_rr, "call_reranker_api", recorder)

    assert await kb_rr.rerank_hits("问题", []) == []
    assert recorder.calls == 0


# ---------------------------------------------------------------------------
# 配置解析与凭证同源（R7）
# ---------------------------------------------------------------------------


def test_resolve_rerank_config_requires_enabled_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``enabled=False`` 或缺模型名时返回 None：硬开关，零网络调用。"""
    monkeypatch.setattr(
        kb_rr,
        "resolve_memory_config",
        lambda _aid="": _agent_config(
            _reranker(enabled=False),
            _embedding_config(),
        ),
    )
    assert kb_rr._resolve_rerank_config() is None

    monkeypatch.setattr(
        kb_rr,
        "resolve_memory_config",
        lambda _aid="": _agent_config(
            _reranker(model_name=""),
            _embedding_config(),
        ),
    )
    assert kb_rr._resolve_rerank_config() is None


def test_rerank_credentials_inherit_from_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reranker 未填 api_key/base_url 时继承 embedding 凭证（spec 同源要求）。"""
    monkeypatch.setattr(
        kb_rr,
        "resolve_memory_config",
        lambda _aid="": _agent_config(
            _reranker(api_key="", base_url=""),
            _embedding_config(),
        ),
    )

    resolved = kb_rr._resolve_rerank_config()

    assert resolved is not None
    assert resolved.api_key == "sk-embed"
    assert resolved.base_url == _EMBED_BASE_URL


def test_rerank_keeps_explicit_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式配了精排凭证时不得被 embedding 覆盖。"""
    monkeypatch.setattr(
        kb_rr,
        "resolve_memory_config",
        lambda _aid="": _agent_config(_reranker(), _embedding_config()),
    )

    resolved = kb_rr._resolve_rerank_config()

    assert resolved is not None
    assert resolved.api_key == "sk-rerank"
    assert resolved.base_url == "https://api.siliconflow.cn/v1"


def test_rerank_partial_base_url_only_inherits_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """只缺其中一个字段时只继承那一个，不得把另一项置空。"""
    monkeypatch.setattr(
        kb_rr,
        "resolve_memory_config",
        lambda _aid="": _agent_config(
            _reranker(api_key=""),
            _embedding_config(),
        ),
    )

    resolved = kb_rr._resolve_rerank_config()

    assert resolved is not None
    assert resolved.api_key == "sk-embed"
    assert resolved.base_url == "https://api.siliconflow.cn/v1"


def test_resolve_rerank_config_without_memory_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """memory 配置读不出时返回 None（fail-soft），不冒泡到检索链路。"""
    monkeypatch.setattr(
        kb_rr,
        "resolve_memory_config",
        lambda _aid="": None,
    )

    assert kb_rr._resolve_rerank_config() is None


def test_resolve_rerank_config_without_embedding_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """agent 只配了精排没配 embedding：精排仍可用（不要求同源存在）。"""
    monkeypatch.setattr(
        kb_rr,
        "resolve_memory_config",
        lambda _aid="": _agent_config(_reranker(), None),
    )

    resolved = kb_rr._resolve_rerank_config()

    assert resolved is not None
    assert resolved.api_key == "sk-rerank"
