# -*- coding: utf-8 -*-
"""Lightweight hybrid retrieval for knowledge bases (M4-5).

BM25 keyword scoring plus optional cosine-similarity vector scoring,
fused with Reciprocal Rank Fusion (the same shape ReMe uses:
``weight / (60 + rank)``).  Pure Python — the M4 knowledge corpus is
small (hundreds of chunks per kb), and the pg vector path can later
replace the scoring internals without changing callers.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List, Optional, Sequence, Tuple

from .models import KbChunk

# BM25 hyperparameters (standard defaults).
_K1 = 1.5
_B = 0.75
#: RRF 融合常数（M6-5 转正为共享导出：引擎层跨引擎二次融合与 PgVector 的
#: SQL 内融合均引用本值，任何地方不得再写一个 60 字面量）
RRF_K = 60.0
#: 单层融合权重（同上转正：PgVector 引擎的 SQL 与内存融合共用同一权重）
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def tokenize_mixed(text: str) -> List[str]:
    """Lower-cased word tokens; CJK runs are split into bigrams so
    Chinese content is searchable without a segmenter.

    M6-3 提升为共享导出：切片端（Task 3）与检索端必须用同一套词表，否则
    写入 ``tsv`` 的 token 与查询 token 对不上，中文关键词会整库搜不到。
    """
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group(0)
        if any("一" <= ch <= "鿿" for ch in token):
            # CJK 无词边界，退化为相邻双字 bigram（输出与旧实现逐字等价）
            tokens.extend(
                token[i] + token[i + 1] for i in range(len(token) - 1)
            )
            if len(token) == 1:
                tokens.append(token)
        else:
            tokens.append(token)
    return tokens


def _bm25_scores(
    query_tokens: List[str],
    docs: List[List[str]],
) -> List[float]:
    """Classic BM25 over an in-memory corpus."""
    n_docs = len(docs)
    if n_docs == 0:
        return []
    avg_len = sum(len(d) for d in docs) / max(n_docs, 1)
    avg_len = avg_len or 1.0
    doc_freqs: Counter[str] = Counter()
    doc_terms = [Counter(d) for d in docs]
    for terms in doc_terms:
        for term in terms:
            doc_freqs[term] += 1
    scores: list[float] = []
    for terms in doc_terms:
        doc_len = sum(terms.values())
        score = 0.0
        for token in query_tokens:
            tf = terms.get(token, 0)
            if tf == 0:
                continue
            df = doc_freqs.get(token, 0)
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            denom = tf + _K1 * (1 - _B + _B * doc_len / avg_len)
            score += idf * (tf * (_K1 + 1)) / denom
        scores.append(score)
    return scores


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def search_chunks(
    chunks: Iterable[KbChunk],
    query: str,
    *,
    query_embedding: Optional[Sequence[float]] = None,
    top_k: int = 5,
) -> List[Tuple[KbChunk, float]]:
    """Rank *chunks* for *query*; returns ``[(chunk, fused_score)]``.

    BM25 always runs; the vector branch activates when both the query
    and at least one chunk carry embeddings.  Single-branch rankings
    use that branch's order directly.
    """
    items = [c for c in chunks if c.text.strip()]
    if not items or not query.strip():
        return []

    query_tokens = tokenize_mixed(query)
    doc_tokens = [tokenize_mixed(c.text) for c in items]
    keyword_scores = _bm25_scores(query_tokens, doc_tokens)
    # Rank indices by keyword score descending.
    kw_ranked = sorted(
        range(len(items)),
        key=lambda i: keyword_scores[i],
        reverse=True,
    )
    kw_rank = {idx: rank for rank, idx in enumerate(kw_ranked)}

    vec_rank: dict[int, int] = {}
    if query_embedding is not None:
        vec_scores = [
            (_cosine(query_embedding, c.embedding) if c.embedding else 0.0)
            for c in items
        ]
        vec_ranked = sorted(
            range(len(items)),
            key=lambda i: vec_scores[i],
            reverse=True,
        )
        vec_rank = {idx: rank for rank, idx in enumerate(vec_ranked)}

    fused: list[tuple[int, float]] = []
    for idx in range(len(items)):
        score = 0.0
        if vec_rank:
            score += VECTOR_WEIGHT / (RRF_K + vec_rank[idx])
            # Only keyword *hits* contribute on the fused path.
            if keyword_scores[idx] > 0:
                score += KEYWORD_WEIGHT / (RRF_K + kw_rank[idx])
        else:
            if keyword_scores[idx] <= 0:
                continue  # pure-BM25 path: non-hits are excluded
            score = keyword_scores[idx]
        fused.append((idx, score))

    fused.sort(key=lambda pair: pair[1], reverse=True)
    return [(items[idx], score) for idx, score in fused[: max(1, top_k)]]


__all__ = [
    "KEYWORD_WEIGHT",
    "RRF_K",
    "VECTOR_WEIGHT",
    "search_chunks",
    "tokenize_mixed",
]
