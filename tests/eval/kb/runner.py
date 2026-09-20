# -*- coding: utf-8 -*-
"""KB 检索评测 runner（T8）：Recall@5 / MRR 计算与阈值判定。

评测口径：对每组 QA 对取 svc.search top5 命中，去重后的文档 id 序列中
期望文档首次出现位次即该条的 rank（0 基）；Recall@5 = 命中条数占比，
MRR = mean(1 / (rank + 1))。

@author qingfeng
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .corpus import DOCUMENTS
from .evalset import QA_PAIRS

#: 评测阈值（词面锚点设计下应远高于此；低于即回归）
RECALL_THRESHOLD = 0.9
MRR_THRESHOLD = 0.7


@dataclass
class EvalReport:
    """一次评测的聚合结果与逐条明细。"""

    recall_at_5: float = 0.0
    mrr: float = 0.0
    total: int = 0
    misses: List[dict] = field(default_factory=list)

    def summary(self) -> str:
        """人读摘要（misses 详单供回归排查）。"""
        lines = [
            f"KB eval: {self.total} pairs, "
            f"Recall@5={self.recall_at_5:.3f}, MRR={self.mrr:.3f}",
        ]
        for miss in self.misses:
            lines.append(
                f"  MISS q={miss['q']!r} expected_doc={miss['doc']} "
                f"got={miss['got']}",
            )
        return "\n".join(lines)


def evaluate(svc, kb_id: str, *, top_k: int = 5) -> EvalReport:
    """Run the full evalset against one kb and aggregate metrics."""
    report = EvalReport(total=len(QA_PAIRS))
    hit_count = 0
    rr_sum = 0.0
    for pair in QA_PAIRS:
        query = str(pair["q"])
        expected_idx = int(pair["doc"])  # type: ignore[arg-type]
        hits = svc.search(kb_id, query, top_k=top_k)
        # 命中文档去重保序（同一文档多切片只记首个位次）
        ranked_docs: List[str] = []
        for chunk, _score in hits:
            if chunk.doc_id not in ranked_docs:
                ranked_docs.append(chunk.doc_id)
        expected_doc_id = document_id(svc, kb_id, expected_idx)
        rank = None
        if expected_doc_id is not None:
            try:
                rank = ranked_docs.index(expected_doc_id)
            except ValueError:
                rank = None
        if rank is not None:
            hit_count += 1
            rr_sum += 1.0 / (rank + 1)
        else:
            report.misses.append(
                {"q": query, "doc": expected_idx, "got": ranked_docs[:5]},
            )
    report.recall_at_5 = hit_count / report.total if report.total else 0.0
    report.mrr = rr_sum / report.total if report.total else 0.0
    return report


def document_id(svc, kb_id: str, doc_index: int):
    """按语料下标取真实 doc_id（摄入时按 path=eval/doc{i}.md 对齐）。"""
    for doc in svc.pg_list_documents(kb_id):
        if str(getattr(doc, "path", "")).endswith(f"eval/doc{doc_index}.md"):
            return doc.id
    return None
