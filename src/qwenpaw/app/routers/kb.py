# -*- coding: utf-8 -*-
"""Employee-facing knowledge base API (M4-5).

Employees list/search the bases they can access (ACL-filtered) and
manage documents in their own personal bases.  Cross-scope
administration lives under ``/api/admin/kb``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field

from ..kb.ingest import (
    ParserUnavailable,
    UnsupportedFormat,
    parse_upload,
)
from ..kb.models import (
    INGEST_FAILED,
    SCOPE_PERSONAL,
    SOURCE_MANUAL,
    SOURCE_UPLOAD,
    KbDocument,
    KnowledgeBase,
)
from ..kb.service import KbService, get_kb_service
from ...db import write_gateway
from ..utils import read_upload_bounded

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


class KbView(BaseModel):
    id: str
    name: str
    scope: str
    owner_id: str = ""
    team_id: str = ""
    description: str = ""


class CreateKbBody(BaseModel):
    name: str
    description: str = ""


class IngestBody(BaseModel):
    text: str
    title: str = ""
    source: str = ""


class SearchBody(BaseModel):
    query: str
    kb_id: Optional[str] = None  # None = search every accessible base
    top_k: int = Field(default=5, ge=1, le=50)


class SearchHit(BaseModel):
    kb_id: str
    kb_name: str
    doc_id: str
    title: str
    text: str
    score: float


class SearchResponse(BaseModel):
    hits: List[SearchHit] = Field(default_factory=list)


def _caller(request: Request) -> str:
    # 无认证部署（QWENPAW_AUTH_ENABLED!=true）中间件不绑定身份：
    # 回退 "local" 让个人库链路可用（xian/projects.py 同款先例）。
    return getattr(request.state, "user", None) or "local"


def _access_kwargs(username: str) -> dict:
    from ..rbac.deps import _resolve_flat_role
    from ..rbac.store import get_rbac_store

    flat_role = _resolve_flat_role(username) if username else ""
    store = get_rbac_store()
    return {
        "flat_role": flat_role,
        "user_roles": store.roles_for_user(username, flat_role),
        "user_teams": store.teams_for_user(username),
    }


def _view(kb: KnowledgeBase) -> KbView:
    return KbView(
        id=kb.id,
        name=kb.name,
        scope=kb.scope,
        owner_id=kb.owner_id,
        team_id=kb.team_id,
        description=kb.description,
    )


@router.get("", response_model=List[KbView])
async def list_accessible(request: Request) -> List[KbView]:
    """List every knowledge base the caller may read."""
    username = _caller(request)
    service = get_kb_service()
    kbs = service.accessible_kbs(username, **_access_kwargs(username))
    views = [_view(kb) for kb in kbs]
    return _apply_kb_data_scope(views, username)


def _apply_kb_data_scope(
    views: List[KbView],
    username: str,
) -> List[KbView]:
    """在既有 ACL 之上叠加 RBAC 数据范围过滤（resource=``kb``）。

    ``accessible_kbs`` 已按 scope（personal/team/enterprise）+ grants 做了
    严格的可见性收敛；本层只在其上补一道数据范围。KB 模型（``kb_spaces``
    / ``KnowledgeBase``）**无 department 维度**，故 ``dept`` /
    ``dept_and_child`` / ``custom`` 范围在此不适用（交由既有 ACL 承载），
    仅 ``self`` 范围按 ``owner_id`` 收敛为「只看本人拥有的库」。

    ``all`` 范围 / PG 不可用 / 任何异常都回落到未过滤列表（优雅降级）。

    TODO(rbac-data-scope): 若后续 ``kb_spaces`` 增加 ``department_id`` 列，
    在此接入 ``dept`` / ``dept_and_child`` 维度过滤。
    """
    if not username:
        return views
    try:
        from ..rbac.data_scope import SCOPE_SELF, DataScopeFilter

        scope = DataScopeFilter.resolve_scope(username, "kb")
        if getattr(scope, "scope_type", "") != SCOPE_SELF:
            # 非 self 范围：KB 无部门维度，既有 ACL 已足够，不再二次过滤
            return views
        return DataScopeFilter.apply_to_list(
            views,
            scope,
            username,
            user_dept_id=None,
            dept_id_field="owner_id",
            owner_field="owner_id",
        )
    except Exception:  # pylint: disable=broad-except
        logger.debug("kb data-scope filter skipped", exc_info=True)
        return views


@router.post("", status_code=201, response_model=KbView)
async def create_personal_kb(
    body: CreateKbBody,
    request: Request,
) -> KbView:
    """Create a personal knowledge base owned by the caller."""
    username = _caller(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    kb = get_kb_service().create_kb(
        body.name,
        scope=SCOPE_PERSONAL,
        owner_id=username,
        description=body.description,
    )
    if kb is None:
        raise HTTPException(status_code=400, detail="invalid kb payload")
    return _view(kb)


def _get_accessible_kb(kb_id: str, username: str) -> KnowledgeBase:
    service = get_kb_service()
    kb = service.get_kb(kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="kb not found")
    if not service.can_access(kb, username, **_access_kwargs(username)):
        raise HTTPException(status_code=403, detail="no access to this kb")
    return kb


@router.post("/{kb_id}/documents", status_code=201)
async def ingest_document(
    kb_id: str,
    body: IngestBody,
    request: Request,
) -> dict:
    """Ingest text into a kb. Personal bases: owner only; other scopes
    require the kb:write permission (team/enterprise administration)."""
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    if kb.scope == SCOPE_PERSONAL and kb.owner_id != username:
        raise HTTPException(status_code=403, detail="owner only")
    if kb.scope != SCOPE_PERSONAL:
        from ..rbac import PERM_KB_WRITE
        from ..rbac.deps import _resolve_flat_role
        from ..rbac.store import get_rbac_store

        flat_role = _resolve_flat_role(username) if username else ""
        if not get_rbac_store().user_has_permission(
            username,
            PERM_KB_WRITE,
            flat_role=flat_role,
        ):
            raise HTTPException(status_code=403, detail="kb:write required")
    doc = get_kb_service().ingest_text(
        kb_id,
        body.text,
        title=body.title,
        source=body.source,
    )
    if doc is None:
        raise HTTPException(status_code=400, detail="empty document")
    return {
        "doc_id": doc.doc_id,
        "kb_id": doc.kb_id,
        "chunk_count": doc.chunk_count,
    }


@router.delete("/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: str,
    doc_id: str,
    request: Request,
) -> None:
    """Remove one document. Same permission rule as ingestion."""
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    # 收敛复用 _ensure_kb_manage：docstring 声称与 ingest 同规则，
    # 但旧实现漏了非 personal 的 kb:write 校验（team/enterprise 库
    # 任何可读用户均可删文档）——补齐属修 bug，行为收紧。
    _ensure_kb_manage(kb, username)
    service = get_kb_service()
    # 归属校验（P2-N1，对齐 detail/PUT/chunks 先判归属模式）：doc_id
    # 全局唯一，跨库误删防线——doc 必须属于本库，否则 404 不落删
    if write_gateway.resolve_storage_backend() == write_gateway.BACKEND_PG:
        _ensure_pg_ready(service)
        doc, _ = service.pg_document_detail(kb.id, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
    else:
        # json/dual 读 json 主面：硬删后 registry 无此文档 → 404
        meta = service.get_document_meta(doc_id)
        if meta is None or meta.kb_id != kb.id:
            raise HTTPException(status_code=404, detail="document not found")
    if not service.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="document not found")


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchBody, request: Request) -> SearchResponse:
    """Hybrid search across one or all accessible knowledge bases."""
    username = _caller(request)
    service = get_kb_service()
    if body.kb_id:
        kbs = [_get_accessible_kb(body.kb_id, username)]
    else:
        kbs = service.accessible_kbs(username, **_access_kwargs(username))
    hits: list[SearchHit] = []
    for kb in kbs:
        for chunk, score in service.search(
            kb.id,
            body.query,
            top_k=body.top_k,
        ):
            hits.append(
                SearchHit(
                    kb_id=kb.id,
                    kb_name=kb.name,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    text=chunk.text,
                    score=score,
                ),
            )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return SearchResponse(hits=hits[: body.top_k])


# ------------------------------------------------------------------
# T11: 文档面端点（目录树 / 详情 / 编辑 / 上传 / 切片预览）
# ------------------------------------------------------------------


class UpdateDocBody(BaseModel):
    """PUT 编辑请求体（content_md upsert，自动版本+1）。"""

    content_md: str


def _ensure_kb_manage(kb: KnowledgeBase, username: str) -> None:
    """文档写权校验（与既有 ingest/delete 端点同规则，提取复用）。"""
    if kb.scope == SCOPE_PERSONAL and kb.owner_id != username:
        raise HTTPException(status_code=403, detail="owner only")
    if kb.scope != SCOPE_PERSONAL:
        from ..rbac import PERM_KB_WRITE
        from ..rbac.deps import _resolve_flat_role
        from ..rbac.store import get_rbac_store

        flat_role = _resolve_flat_role(username) if username else ""
        if not get_rbac_store().user_has_permission(
            username,
            PERM_KB_WRITE,
            flat_role=flat_role,
        ):
            raise HTTPException(status_code=403, detail="kb:write required")


def _ensure_pg_ready(service: KbService) -> None:
    """pg 权威平面守门（T11 文档面）：不可用 → 503 显式提示，不静默降级。"""
    if not service.pg_ready():
        raise HTTPException(
            status_code=503,
            detail="knowledge base PG plane unavailable (pg backend required)",
        )


def _build_tree(docs: List[KbDocument]) -> List[dict]:
    """按 ``path`` 聚合目录树（文档节点携带 doc_id/title/ingest_status）。

    节点用 dict 按 path 前缀索引（O(n) 建树），避免逐层线性扫 children
    的 O(n²)。
    """
    roots: List[dict] = []
    index: Dict[str, dict] = {}
    for doc in docs:
        parts = [p for p in (doc.path or "").split("/") if p]
        if not parts:
            continue
        children = roots
        prefix = ""
        for i, part in enumerate(parts):
            prefix = f"{prefix}/{part}" if prefix else part
            node = index.get(prefix)
            if node is None:
                node = {
                    "name": part,
                    "path": prefix,
                    "doc_id": None,
                    "title": "",
                    "ingest_status": "",
                    "children": [],
                }
                index[prefix] = node
                children.append(node)
            if i == len(parts) - 1:
                node["doc_id"] = doc.id
                node["title"] = doc.title
                node["ingest_status"] = doc.ingest_status
            children = node["children"]
    return roots


@router.get("/{kb_id}/tree")
def get_document_tree(kb_id: str, request: Request) -> dict:
    """Path 聚合目录树（pg 权威面；文档节点携带摄入状态）。"""
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    service = get_kb_service()
    _ensure_pg_ready(service)
    docs = service.pg_list_documents(kb.id)
    return {"kb_id": kb.id, "nodes": _build_tree(docs)}


@router.get("/{kb_id}/documents/{doc_id}")
def get_document_detail(
    kb_id: str,
    doc_id: str,
    request: Request,
) -> dict:
    """文档详情：content_md 权威全文 + 当前版本 + 摄入状态。"""
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    service = get_kb_service()
    _ensure_pg_ready(service)
    doc, version = service.pg_document_detail(kb.id, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {
        "doc_id": doc.id,
        "kb_id": doc.space_id,
        "title": doc.title,
        "path": doc.path,
        "source": doc.source,
        "ingest_status": doc.ingest_status,
        "version": version,
        "content_md": doc.content_md,
        "updated_by": doc.updated_by,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }


@router.put("/{kb_id}/documents/{doc_id}")
def update_document(
    kb_id: str,
    doc_id: str,
    body: UpdateDocBody,
    request: Request,
) -> dict:
    """MD 编辑 = content_md upsert 自动版本+1 + 重切片重索引。

    经 :meth:`KbService.pg_ingest_document` 复用 T6 版本化重摄入：hash
    护栏变更时 ``MAX(version)+1`` 快照，状态机推进并重切片重索引
    （同内容幂等短路）。
    """
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    _ensure_kb_manage(kb, username)
    service = get_kb_service()
    _ensure_pg_ready(service)
    doc, _ = service.pg_document_detail(kb.id, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    try:
        result = service.pg_ingest_document(
            space_id=kb.id,
            title=doc.title,
            path=doc.path,
            content_md=body.content_md,
            source=doc.source or SOURCE_MANUAL,
        )
    except ValueError as exc:
        # 值级拒绝（如空白 content_md）：400，与基础设施故障 500 区分
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None or result.status == INGEST_FAILED:
        raise HTTPException(
            status_code=500,
            detail="document ingest failed (see server logs)",
        )
    _, version = service.pg_document_detail(kb.id, result.doc_id)
    if version <= 0:
        # 写入已提交但读回失败：显式报错，绝不假成功返回 version=0
        raise HTTPException(
            status_code=503,
            detail=(
                "document ingested but version readback failed "
                "(pg plane unstable); retry shortly"
            ),
        )
    return {
        "doc_id": result.doc_id,
        "version": version,
        "ingest_status": result.status,
        "chunk_count": result.chunk_count,
    }


@router.post("/{kb_id}/documents/upload", status_code=201)
def upload_document(
    kb_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    """multipart 上传：白名单解析 → T6 版本化摄入（同步推进状态机）。"""
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    _ensure_kb_manage(kb, username)
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    service = get_kb_service()
    # fail fast：503 门控在读文件体之前，避免无谓 IO
    _ensure_pg_ready(service)
    # 分块限读（P2-2）：超限立即中止，不把大文件整体读进内存
    data = read_upload_bounded(file.file)
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        content_md = parse_upload(file.filename, data)
    except UnsupportedFormat as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ParserUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stem = Path(file.filename).stem or "document"
    path = f"{stem}.md"
    try:
        result = service.pg_ingest_document(
            space_id=kb.id,
            title=stem,
            path=path,
            content_md=content_md,
            source=SOURCE_UPLOAD,
            source_meta={"filename": file.filename},
            uploaded_from=data,
        )
    except ValueError as exc:
        # 值级拒绝：400，与基础设施故障 500 区分
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None or result.status == INGEST_FAILED:
        raise HTTPException(
            status_code=500,
            detail="document ingest failed (see server logs)",
        )
    return {
        "doc_id": result.doc_id,
        "path": path,
        "ingest_status": result.status,
        "chunk_count": result.chunk_count,
    }


@router.get("/{kb_id}/documents/{doc_id}/chunks")
def get_document_chunks(
    kb_id: str,
    doc_id: str,
    request: Request,
) -> List[dict]:
    """chunk 预览（数据源 ``svc.document_chunks``，seq 升序含 heading_path）。"""
    username = _caller(request)
    kb = _get_accessible_kb(kb_id, username)
    service = get_kb_service()
    if write_gateway.resolve_storage_backend() == write_gateway.BACKEND_PG:
        # 与详情端点契约一致：pg 面软删（is_delete）文档 → 404，
        # 而非返回遗留 chunks；pg 后端但平面不可达 → 503 显式
        _ensure_pg_ready(service)
        doc, _ = service.pg_document_detail(kb.id, doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
    else:
        # json/dual 读 json 主面：硬删后 registry 无此文档 → 404
        meta = service.get_document_meta(doc_id)
        if meta is None or meta.kb_id != kb.id:
            raise HTTPException(status_code=404, detail="document not found")
    return [
        {
            "chunk_id": chunk.chunk_id,
            "seq": chunk.seq,
            "text": chunk.text,
            "heading_path": chunk.heading_path,
            "parent_seq": chunk.parent_seq,
        }
        for chunk in service.document_chunks(kb.id, doc_id)
    ]
