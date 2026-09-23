# -*- coding: utf-8 -*-
"""LLM Wiki 知识层（T3，0046）：知识生命周期 + 冲突候选 + LLM 建议。

三层架构中的「LLM Wiki Knowledge」落地原则：**文档（content_md）是知识
的唯一权威源**，LLM 产物（摘要/分类/别名建议）永远只是候选——经人工
确认后才经 :meth:`KbPgStore.update_document_meta` 落库，本模块不提供
「LLM 直写知识」的任何路径。

三个职责：

1. **生命周期状态机**：动作到目标状态的映射见 :data:`REVIEW_TRANSITIONS`；
   每次流转追加一条 ``kb_reviews`` 流水（审计不可变），文档行经元数据
   白名单更新（与摄入路径严格分离，摄入永不重置生命周期列）。
2. **冲突候选（规则判定）**：同库内标题归一相同的不同文档 →
   ``kb_conflicts`` 候选（duplicate_title），无序对查重防重复建候选；
   LLM 辅助判定为后续增强，本期规则判定即可闭环。
3. **LLM 结构化建议（候选生成器）**：``suggest_wiki_meta`` 用既有
   provider 配置平面的 chat 模型生成摘要/域/类型候选 JSON，**只返回给
   调用方供表单预填**，不触碰任何表。

有效期语义：``valid_from/valid_to`` 为 NULL 表示无界；检索面过滤在
pg_engine SQL（CTE EXISTS）与门面文件面分支（:func:`is_effective`）
两侧落地。

@author qingfeng
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import (
    CONFLICT_OPEN,
    DOC_TYPE_DOC,
    KNOWLEDGE_ARCHIVED,
    KNOWLEDGE_DRAFT,
    KNOWLEDGE_IN_REVIEW,
    KNOWLEDGE_PUBLISHED,
    REVIEW_APPROVE,
    REVIEW_ARCHIVE,
    REVIEW_REJECT,
    REVIEW_SUBMIT,
    VALID_DOC_TYPES,
    VALID_REVIEW_ACTIONS,
    KbConflict,
    KbDocument,
    KbReview,
)

logger = logging.getLogger(__name__)

#: 动作 → (目标状态, 是否写 reviewed_by)。当前状态不设白名单：
#: submit 允许对 published 重送审、approve 允许对 draft 快速发布，
#: 严格流转约束交给前端表单与审计流水（拒绝滥用靠 review 记录追溯）。
REVIEW_TRANSITIONS: Dict[str, Dict[str, Any]] = {
    REVIEW_SUBMIT: {
        "target": KNOWLEDGE_IN_REVIEW,
        "stamp_reviewer": False,
    },
    REVIEW_APPROVE: {
        "target": KNOWLEDGE_PUBLISHED,
        "stamp_reviewer": True,
    },
    REVIEW_REJECT: {
        "target": KNOWLEDGE_DRAFT,
        "stamp_reviewer": False,
    },
    REVIEW_ARCHIVE: {
        "target": KNOWLEDGE_ARCHIVED,
        "stamp_reviewer": False,
    },
}

#: LLM 建议的正文采样上限（摘要不需要全文，token 成本可控）
_SUGGEST_CONTENT_LIMIT = 8000

#: LLM 建议单次调用的等待上限（秒）
_SUGGEST_TIMEOUT_SECONDS = 30.0


def normalize_title(title: str) -> str:
    """冲突归一键：去首尾空白 + 小写（中文不受影响，英文大小写不敏感）。"""
    return (title or "").strip().lower()


async def review_document(
    store: Any,
    space_id: str,
    doc_id: str,
    action: str,
    reviewer: str,
    comment: str = "",
) -> Optional[KbDocument]:
    """:func:`review_document` 的真实现（async；命名区分防误同步调用）。"""
    action = (action or "").strip().lower()
    if action not in VALID_REVIEW_ACTIONS:
        raise ValueError(
            f"review action 取值非法：{action!r}，"
            f"仅允许 {sorted(VALID_REVIEW_ACTIONS)}",
        )
    transition = REVIEW_TRANSITIONS[action]
    doc = await store.get_document(doc_id)
    if doc is None or doc.space_id != space_id or doc.is_delete:
        return None
    fields: Dict[str, Any] = {
        "knowledge_status": transition["target"],
        "review_note": comment or "",
        "reviewed_by": reviewer if transition["stamp_reviewer"] else "",
    }
    # reviewed_by 传空串会覆盖旧审核人：reject/archive 不该抹掉
    # 最近一次 approve 的记录，故非盖章动作不提交该键
    if not transition["stamp_reviewer"]:
        fields.pop("reviewed_by")
    updated = await store.update_document_meta(doc_id, **fields)
    if not updated:
        logger.warning(
            "[kb] review meta update affected no rows: doc=%s action=%s",
            doc_id,
            action,
        )
    await store.create_review(
        KbReview(
            id=f"rev_{uuid.uuid4().hex[:12]}",
            space_id=space_id,
            document_id=doc_id,
            action=action,
            reviewer=reviewer,
            comment=comment or "",
        ),
    )
    latest = await store.get_document(doc_id)
    return latest if latest is not None else doc


async def detect_conflicts(
    store: Any,
    space_id: str,
    doc_id: str,
) -> List[KbConflict]:
    """为一份文档跑规则冲突检测，返回**本次新建**的冲突候选。

    规则（duplicate_title）：同库内标题归一相同的不同未删文档。无序对
    （a,b）/（b,a）经 :meth:`find_open_conflict` 查重，已存在 open 候选
    不重复建；优先级由双文档 confidence 最低值归档（<0.5→4，否则 3）。
    平面不可用返回空列表（与 store 读方法同一 fail-soft 口径）。
    """
    doc = await store.get_document(doc_id)
    if doc is None or doc.space_id != space_id or doc.is_delete:
        return []
    siblings = await store.list_documents(space_id)
    key = normalize_title(doc.title)
    if not key:
        return []
    created: List[KbConflict] = []
    for sibling in siblings:
        if sibling.id == doc.id or sibling.is_delete:
            continue
        if normalize_title(sibling.title) != key:
            continue
        existing = await store.find_open_conflict(space_id, doc.id, sibling.id)
        if existing is not None:
            continue
        lowest = min(doc.confidence, sibling.confidence)
        conflict = KbConflict(
            id=f"cfl_{uuid.uuid4().hex[:12]}",
            space_id=space_id,
            document_id_a=doc.id,
            document_id_b=sibling.id,
            conflict_type="duplicate_title",
            affected_scope=f"space:{space_id}",
            priority=4 if lowest < 0.5 else 3,
            resolution_status=CONFLICT_OPEN,
        )
        if await store.upsert_conflict(conflict):
            created.append(conflict)
    return created


def is_effective(
    doc: Any,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """文档当前是否「可检索」：published 且在有效期内（文件面过滤用）。

    ``valid_from/valid_to`` 为 NULL 表示无界；非 KbDocument（如
    KbDocumentMeta）只要带 knowledge_status/valid_from/valid_to 属性
    即可参与判定，缺属性按 published/无界处理（json 面降级语义）。
    """
    status = str(getattr(doc, "knowledge_status", "") or KNOWLEDGE_PUBLISHED)
    if status != KNOWLEDGE_PUBLISHED:
        return False
    moment = now or datetime.now(timezone.utc)
    valid_from = getattr(doc, "valid_from", None)
    valid_to = getattr(doc, "valid_to", None)
    if valid_from is not None and moment < valid_from:
        return False
    if valid_to is not None and moment >= valid_to:
        return False
    return True


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型响应中提取第一个 JSON 对象（容忍 ```json 围栏与前后闲话）。"""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        text = text[start:end + 1]
    try:
        loaded = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


async def suggest_wiki_meta(
    content_md: str,
    agent_id: str = "",
    *,
    timeout_seconds: float = _SUGGEST_TIMEOUT_SECONDS,
) -> Optional[Dict[str, Any]]:
    """LLM 结构化建议（候选生成器）：摘要/知识域/文档类型。

    走既有 provider 配置平面的 chat 模型（与 agent 运行同源，不引入
    第二 LLM 接入栈）。**只返回候选**（调用方确认后经元数据编辑接口
    落库），失败/超时/模型未配置一律返回 ``None``（路由映射 503），
    绝不抛出也绝不落库。

    Returns:
        候选 dict：``{"summary", "domain", "doc_type", "aliases"}``；
        ``domain`` 不受枚举约束（自由文本），``doc_type`` 白名单外落
        ``doc``，非法 JSON 返回 ``None``。
    """
    markdown = (content_md or "").strip()
    if not markdown:
        return None
    try:
        from agentscope.message import UserMsg

        from ...agents.model_factory import (
            create_model_and_formatter_async,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning("[kb] wiki suggest: model stack unavailable")
        return None
    try:
        model, _formatter = await create_model_and_formatter_async(
            agent_id or None,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "[kb] wiki suggest: no chat model configured; agent=%s",
            agent_id,
            exc_info=True,
        )
        return None
    sample = markdown[:_SUGGEST_CONTENT_LIMIT]
    prompt = (
        "你是企业知识库的编目助手。请阅读以下文档内容，输出严格的 JSON"
        "（不要任何多余文字），字段：\n"
        '- "summary"：不超过 120 字的内容摘要；\n'
        '- "domain"：知识域，从 企业基础/业务域/流程SOP/专业知识/案例/QA '
        "中选择最贴切的一个；\n"
        '- "doc_type"：文档类型，从 doc/process/case/qa/terminology/entity '
        "中选择一个；\n"
        '- "aliases"：这篇文档的常见别名/同义词数组（0~5 项，可为空）。\n\n'
        f"文档标题与正文：\n{sample}"
    )
    try:
        response = await asyncio_wait_for(
            model([UserMsg(name="user", content=prompt)]),
            timeout_seconds,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "[kb] wiki suggest failed (timeout/model error)",
            exc_info=True,
        )
        return None
    text = ""
    get_text = getattr(response, "get_text_content", None)
    if callable(get_text):
        text = get_text() or ""
    candidate = _extract_json_object(text)
    if candidate is None:
        logger.warning("[kb] wiki suggest returned non-JSON response")
        return None
    doc_type = str(candidate.get("doc_type") or DOC_TYPE_DOC).strip().lower()
    if doc_type not in VALID_DOC_TYPES:
        doc_type = DOC_TYPE_DOC
    aliases = candidate.get("aliases")
    if not isinstance(aliases, list):
        aliases = []
    return {
        "summary": str(candidate.get("summary") or "").strip(),
        "domain": str(candidate.get("domain") or "").strip(),
        "doc_type": doc_type,
        "aliases": [
            str(item).strip() for item in aliases if str(item).strip()
        ],
    }


def asyncio_wait_for(awaitable: Any, timeout: float) -> Any:
    """:func:`asyncio.wait_for` 的薄包装（便于测试 monkeypatch 超时）。"""
    import asyncio

    return asyncio.wait_for(awaitable, timeout)


__all__ = [
    "REVIEW_TRANSITIONS",
    "detect_conflicts",
    "is_effective",
    "normalize_title",
    "review_document",
    "suggest_wiki_meta",
]
