# -*- coding: utf-8 -*-
"""M6-4: embedding 复用管线——配置缺失降级 / 维度守卫 / 批量顺序对齐。

知识库不引入第二套 embedding 栈：凭证与模型一律复用 ReMe 的
``reme_light_memory_config.embedding_model_config``（落在 active_agent 上），
向量宽度必须与 0034 的 ``kb_chunks.embedding vector(1024)`` 对齐，否则写库
直接 DataError。任何不可用路径都返回 ``None``，让调用方降级 BM25-only。

@author qingfeng
"""

from __future__ import annotations

import types
from typing import Any, List, Optional, Sequence

import pytest

from qwenpaw.app.kb import embedding as kb_emb
from qwenpaw.config.config import EmbeddingModelConfig

pytestmark = pytest.mark.unit


def _config(**overrides: Any) -> EmbeddingModelConfig:
    """构造一份可用的 embedding 配置（默认 1024 维 + openai 后端）。"""
    values: dict[str, Any] = {
        "backend": "openai",
        "api_key": "sk-test",
        "base_url": "https://dashscope.example.com/compatible-mode/v1",
        "model_name": "text-embedding-v4",
        "dimensions": kb_emb.EMBEDDING_DIM,
        "max_batch_size": 10,
    }
    values.update(overrides)
    return EmbeddingModelConfig(**values)


def _vector(value: float) -> List[float]:
    """按当前维度约束造一条向量。"""
    return [value] * kb_emb.EMBEDDING_DIM


def _agent_config(embedding: EmbeddingModelConfig) -> Any:
    """造出只到 ``embedding_model_config`` 那一层的假 agent 配置。"""
    return types.SimpleNamespace(
        running=types.SimpleNamespace(
            reme_light_memory_config=types.SimpleNamespace(
                embedding_model_config=embedding,
            ),
        ),
    )


def _agent_ref_cfg() -> Any:
    """造出带 ``agents.active_agent`` 的假根配置。"""

    class _Agents:
        active_agent = "default"

    return types.SimpleNamespace(agents=_Agents())


class _BatchRecorder:
    """替身传输层：记录每批的条数与配置，并按输入文本回显可辨识向量。"""

    def __init__(self) -> None:
        self.batch_sizes: List[int] = []
        self.configs: List[EmbeddingModelConfig] = []

    async def __call__(
        self,
        config: EmbeddingModelConfig,
        texts: Sequence[str],
    ) -> Optional[List[List[float]]]:
        self.batch_sizes.append(len(texts))
        self.configs.append(config)
        return [_vector(float(text)) for text in texts]


# ---------------------------------------------------------------------------
# 配置解析（唯一权威源 = active_agent 的 reme 配置）
# ---------------------------------------------------------------------------


def test_resolve_config_reads_active_agent_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未指定 agent 时用 active_agent 的 embedding 配置，不新建 KB 专用配置面。"""

    class _Agents:
        active_agent = "worker-a"

    class _Cfg:
        agents = _Agents()

    seen: List[str] = []

    def _fake_load_agent_config(agent_id: str) -> Any:
        seen.append(agent_id)
        return _agent_config(_config(model_name="from-agent"))

    monkeypatch.setattr(kb_emb, "load_config", lambda: _Cfg())
    monkeypatch.setattr(kb_emb, "load_agent_config", _fake_load_agent_config)

    resolved = kb_emb._resolve_config()

    assert seen == ["worker-a"]
    assert resolved is not None
    assert resolved.model_name == "from-agent"


def test_resolve_config_honours_explicit_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式 agent_id 优先：Task 9/10 在某个 agent 运行内检索时用其自身凭证。"""

    def _fake_load_agent_config(agent_id: str) -> Any:
        return _agent_config(_config(model_name=f"model-of-{agent_id}"))

    monkeypatch.setattr(
        kb_emb, "load_config", lambda: pytest.fail("不该读全局")
    )
    monkeypatch.setattr(kb_emb, "load_agent_config", _fake_load_agent_config)

    resolved = kb_emb._resolve_config(agent_id="worker-b")

    assert resolved is not None
    assert resolved.model_name == "model-of-worker-b"


def test_resolve_config_missing_agent_profile_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """agent 配置读不出来时返回 None（fail-soft），不把异常抛给检索链路。"""

    def _boom(_agent_id: str) -> Any:
        raise RuntimeError("agent.json 缺失")

    monkeypatch.setattr(kb_emb, "load_config", lambda: _agent_ref_cfg())
    monkeypatch.setattr(kb_emb, "load_agent_config", _boom)

    assert kb_emb._resolve_config() is None


def test_resolve_config_unreadable_global_config_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """根配置目录不可读（load_config 抛错）时降级 None，不进 agent 读取。"""

    def _boom() -> Any:
        raise RuntimeError("config 目录不可读")

    monkeypatch.setattr(kb_emb, "load_config", _boom)
    monkeypatch.setattr(
        kb_emb,
        "load_agent_config",
        lambda _aid: pytest.fail("读根配置失败后不应再读 agent 配置"),
    )

    assert kb_emb._resolve_config() is None


def test_resolve_config_requires_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无模型名或无 api_key 都算未配置（与 ReMe 的启用判定同一套规则）。"""
    monkeypatch.setattr(kb_emb, "load_config", lambda: _agent_ref_cfg())

    monkeypatch.setattr(
        kb_emb,
        "load_agent_config",
        lambda _aid: _agent_config(_config(model_name="")),
    )
    assert kb_emb._resolve_config() is None

    monkeypatch.setattr(
        kb_emb,
        "load_agent_config",
        lambda _aid: _agent_config(_config(api_key="  ")),
    )
    assert kb_emb._resolve_config() is None


def test_resolve_config_space_model_overrides_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``kb_spaces.embedding_model`` 只覆盖模型名，不动维度与凭证。"""
    monkeypatch.setattr(kb_emb, "load_config", lambda: _agent_ref_cfg())
    monkeypatch.setattr(
        kb_emb,
        "load_agent_config",
        lambda _aid: _agent_config(_config(model_name="text-embedding-v4")),
    )

    resolved = kb_emb._resolve_config(model="text-embedding-v3")

    assert resolved is not None
    assert resolved.model_name == "text-embedding-v3"
    assert resolved.dimensions == kb_emb.EMBEDDING_DIM


# ---------------------------------------------------------------------------
# embed_texts 的降级与批量语义
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_unconfigured_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置 embedding 模型：embed_texts 返回 None（BM25-only 降级信号）。"""
    monkeypatch.setattr(kb_emb, "_resolve_config", lambda **_kw: None)
    assert await kb_emb.embed_texts(["a"]) is None


@pytest.mark.asyncio
async def test_embed_empty_input_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空输入返回 [] 而非 None：「无需工作」与「不可用」必须可区分。"""
    monkeypatch.setattr(kb_emb, "_resolve_config", lambda **_kw: None)
    assert await kb_emb.embed_texts([]) == []


@pytest.mark.asyncio
async def test_embed_dimension_mismatch_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置维度与向量列宽不符时不下发请求（写库必炸，宁可直接降级）。"""
    recorder = _BatchRecorder()
    monkeypatch.setattr(
        kb_emb,
        "_resolve_config",
        lambda **_kw: _config(dimensions=768),
    )
    monkeypatch.setattr(kb_emb, "_call_model", recorder)

    assert await kb_emb.embed_texts(["甲"]) is None
    assert recorder.batch_sizes == []


@pytest.mark.asyncio
async def test_embed_batch_order_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第 i 条输入必须对应第 i 条向量（Task 6 按 index 回填 chunk）。"""
    recorder = _BatchRecorder()
    monkeypatch.setattr(kb_emb, "_resolve_config", lambda **_kw: _config())
    monkeypatch.setattr(kb_emb, "_call_model", recorder)

    out = await kb_emb.embed_texts([str(i) for i in range(6)])

    assert out is not None
    assert [vec[0] for vec in out] == [float(i) for i in range(6)]


@pytest.mark.parametrize(
    ("max_batch_size", "expected_sizes"),
    [
        (1, [1] * 25),
        (2, [2] * 12 + [1]),
        (3, [3] * 8 + [1]),
        (7, [7, 7, 7, 4]),
        (10, [10, 10, 5]),
        (25, [25]),
    ],
)
@pytest.mark.asyncio
async def test_embed_splits_batches_by_max_batch_size(
    monkeypatch: pytest.MonkeyPatch,
    max_batch_size: int,
    expected_sizes: List[int],
) -> None:
    """25 条按配置的 max_batch_size 切批；参数化覆盖非默认值，切分一旦被
    硬编码（如 10）变异必须被抓，跨批拼接仍严格对齐。"""
    recorder = _BatchRecorder()
    monkeypatch.setattr(
        kb_emb,
        "_resolve_config",
        lambda **_kw: _config(max_batch_size=max_batch_size),
    )
    monkeypatch.setattr(kb_emb, "_call_model", recorder)

    out = await kb_emb.embed_texts([str(i) for i in range(25)])

    assert recorder.batch_sizes == expected_sizes
    assert out is not None
    assert [vec[0] for vec in out] == [float(i) for i in range(25)]


@pytest.mark.asyncio
async def test_embed_batch_failure_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """任一批失败即整体 None：不做「半库有向量」的部分成功。"""
    calls: List[int] = []

    async def _flaky(
        _config_obj: EmbeddingModelConfig,
        texts: Sequence[str],
    ) -> Optional[List[List[float]]]:
        calls.append(len(texts))
        if len(calls) == 2:
            return None
        return [_vector(float(text)) for text in texts]

    monkeypatch.setattr(kb_emb, "_resolve_config", lambda **_kw: _config())
    monkeypatch.setattr(kb_emb, "_call_model", _flaky)

    assert await kb_emb.embed_texts([str(i) for i in range(25)]) is None
    assert calls == [10, 10]


@pytest.mark.asyncio
async def test_embed_rejects_wrong_vector_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """provider 少给维度时同样降级，不让半截向量进库。

    维度校验发生在传输层（唯一的向量生产者），因此这里用真
    :func:`_call_model` + 假模型，而不是 stub 传输层后期待上层拦截。
    """

    class _ShortModel:
        async def __call__(self, inputs: Sequence[str]) -> Any:
            return types.SimpleNamespace(
                embeddings=[[0.1, 0.2] for _ in inputs],
            )

    monkeypatch.setattr(
        kb_emb,
        "create_embedding_model",
        lambda *_args, **_kwargs: _ShortModel(),
    )

    assert await kb_emb._call_model(_config(), ["甲", "乙"]) is None


@pytest.mark.asyncio
async def test_embed_rejects_count_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """返回条数与入参不等长时必须降级（否则 index 回填会整体错位）。"""

    async def _lopsided(
        _config_obj: EmbeddingModelConfig,
        texts: Sequence[str],
    ) -> List[List[float]]:
        return [_vector(float(text)) for text in texts[:-1]]

    monkeypatch.setattr(kb_emb, "_resolve_config", lambda **_kw: _config())
    monkeypatch.setattr(kb_emb, "_call_model", _lopsided)

    assert await kb_emb.embed_texts(["0", "1", "2"]) is None


@pytest.mark.asyncio
async def test_embed_query_uses_same_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """embed_query 取首条向量，与批量端共用同一套降级语义。"""
    recorder = _BatchRecorder()
    monkeypatch.setattr(kb_emb, "_resolve_config", lambda **_kw: _config())
    monkeypatch.setattr(kb_emb, "_call_model", recorder)

    vector = await kb_emb.embed_query("7")

    assert vector is not None
    assert vector == _vector(7.0)
    assert recorder.batch_sizes == [1]


@pytest.mark.asyncio
async def test_embed_query_none_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """链路不可用时 embed_query 透传 None（查询端据此只跑 BM25）。"""
    monkeypatch.setattr(kb_emb, "_resolve_config", lambda **_kw: None)
    assert await kb_emb.embed_query("甲减") is None


@pytest.mark.asyncio
async def test_embed_query_rejects_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空查询不发起网络请求，返回 None。"""
    recorder = _BatchRecorder()
    monkeypatch.setattr(kb_emb, "_resolve_config", lambda **_kw: _config())
    monkeypatch.setattr(kb_emb, "_call_model", recorder)

    assert await kb_emb.embed_query("   ") is None
    assert recorder.batch_sizes == []


# ---------------------------------------------------------------------------
# 真实传输层（_call_model）必须 fail-soft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_model_transport_error_is_fail_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工厂/网络抛任何异常都只 WARN 并返回 None，不冒泡到检索链路。"""

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("credential rejected")

    monkeypatch.setattr(kb_emb, "create_embedding_model", _boom)

    assert await kb_emb._call_model(_config(), ["甲"]) is None


@pytest.mark.asyncio
async def test_call_model_reads_embeddings_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AgentScope 响应形态是 ``response.embeddings``，按批顺序原样取出。"""

    class _FakeModel:
        def __init__(self) -> None:
            self.payloads: List[Sequence[str]] = []

        async def __call__(self, inputs: Sequence[str]) -> Any:
            self.payloads.append(list(inputs))
            return types.SimpleNamespace(
                embeddings=[_vector(float(text)) for text in inputs],
            )

    fake = _FakeModel()
    monkeypatch.setattr(
        kb_emb,
        "create_embedding_model",
        lambda *_args, **_kwargs: fake,
    )

    out = await kb_emb._call_model(_config(), ["3", "4"])

    assert fake.payloads == [["3", "4"]]
    assert out is not None
    assert [vec[0] for vec in out] == [3.0, 4.0]


@pytest.mark.asyncio
async def test_call_model_rejects_non_finite_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NaN/inf 会让 pgvector 写入或相似度计算静默出错，必须当失败处理。"""
    import math

    class _FakeModel:
        async def __call__(self, inputs: Sequence[str]) -> Any:
            bad = _vector(0.0)
            bad[0] = math.nan
            return types.SimpleNamespace(
                embeddings=[bad for _ in inputs],
            )

    monkeypatch.setattr(
        kb_emb,
        "create_embedding_model",
        lambda *_args, **_kwargs: _FakeModel(),
    )

    assert await kb_emb._call_model(_config(), ["甲"]) is None


@pytest.mark.asyncio
async def test_call_model_non_sequence_embeddings_is_fail_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """响应形状不受控：embeddings 为非序列（如 int）时 len() 会 TypeError，
    必须降级为 None 而不是把异常抛给检索链路。"""

    class _BadShapeModel:
        async def __call__(self, inputs: Sequence[str]) -> Any:
            return types.SimpleNamespace(embeddings=3)

    monkeypatch.setattr(
        kb_emb,
        "create_embedding_model",
        lambda *_args, **_kwargs: _BadShapeModel(),
    )

    assert await kb_emb._call_model(_config(), ["甲", "乙"]) is None


@pytest.mark.asyncio
async def test_call_model_none_entries_is_fail_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """embeddings=[None,...] 时 list(None) 会 TypeError，同样必须降级。"""

    class _NoneEntryModel:
        async def __call__(self, inputs: Sequence[str]) -> Any:
            return types.SimpleNamespace(
                embeddings=[None for _ in inputs],
            )

    monkeypatch.setattr(
        kb_emb,
        "create_embedding_model",
        lambda *_args, **_kwargs: _NoneEntryModel(),
    )

    assert await kb_emb._call_model(_config(), ["甲"]) is None
