# -*- coding: utf-8 -*-
"""Knowledge base service (M4-5): registry, ingestion, retrieval, ACL.

Storage layout under ``SECRET_DIR`` (file-backed, matching the M4
management-plane pattern)::

    kb_registry.json            # KnowledgeBase + document registry
    kb_data/<kb_id>/chunks.jsonl

ACL resolution order for one user on one kb:

1. platform admins (flat ``admin``) see everything;
2. ``personal`` scope: the owner only;
3. ``team`` scope: members of ``team_id``;
4. ``enterprise`` scope: every authenticated user;
5. explicit grants (roles/users/teams) extend any scope.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...constant import SECRET_DIR
from ...db import write_gateway
from .chunker import embed_input, split_markdown
from .embedding import embed_query_cached, embed_texts
from .file_engine import DEFAULT_KB_DATA_DIR, FileKbEngine
from .hits import KbSearchHit
from .ingest import IngestResult, ingest_space_document
from .models import (
    INGEST_READY,
    SCOPE_ENTERPRISE,
    SCOPE_ORG,
    SCOPE_PERSONAL,
    SCOPE_TEAM,
    SOURCE_MANUAL,
    VALID_SCOPES,
    VALID_SOURCES,
    KbChunk,
    KbConflict,
    KbDocument,
    KbDocumentMeta,
    KbRegistry,
    KbReview,
    KbSpace,
    KnowledgeBase,
)
from .wiki import detect_conflicts, is_effective, review_document

logger = logging.getLogger(__name__)

REGISTRY_FILE = SECRET_DIR / "kb_registry.json"
#: 文件面存储根目录（读写已收编进 L0 引擎；此别名兼容旧引用）
DATA_DIR = DEFAULT_KB_DATA_DIR

# Chunking: split on blank lines, pack paragraphs into ~800-char chunks
# with a small overlap so sentences crossing boundaries stay intact.
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 100


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def chunk_text(text: str) -> List[str]:
    """Split *text* into paragraph-packed chunks of ~800 chars."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if not current:
            current = para
        elif len(current) + len(para) + 2 <= _CHUNK_SIZE:
            current = f"{current}\n\n{para}"
        else:
            chunks.append(current)
            overlap = current[-_CHUNK_OVERLAP:] if _CHUNK_OVERLAP else ""
            current = f"{overlap}{para}" if overlap else para
    if current:
        chunks.append(current)
    # Hard-split any chunk still beyond 4x the target (no blank lines).
    result: list[str] = []
    for chunk in chunks:
        while len(chunk) > _CHUNK_SIZE * 4:
            result.append(chunk[: _CHUNK_SIZE * 4])
            tail_start = _CHUNK_SIZE * 4 - _CHUNK_OVERLAP
            chunk = chunk[tail_start:]
        result.append(chunk)
    return [c for c in result if c.strip()]


# ---------------------------------------------------------------------------
# sync→async 桥接（镜像 app/users/store_pg.py 的专用后台 loop 先例）
#
# KbService 门面全同步（消费方 admin 路由 / tool / workforce 均同步调用），
# 而 pg 平面（KbPgStore / 检索引擎）全异步。pg 后端下用一个进程级专用后台
# 事件循环线程把协程桥接回同步（run_coroutine_threadsafe），不引入同步驱动
# 依赖。仅在 pg 后端触发；json / dual 读走文件面，无桥接开销。kb 局部自持，
# 不复用 engine._run_blocking（那是探测专用 5s 口径）、不动 db/ 共享设施。
# ---------------------------------------------------------------------------

#: 桥接读超时（秒）：pg 读回退文件面前的等待上限
_BRIDGE_READ_TIMEOUT = 10.0
#: 桥接写超时（秒）：摄入含切片写入，给足余量
_BRIDGE_WRITE_TIMEOUT = 60.0

_bridge_loop: Optional[asyncio.AbstractEventLoop] = None
_bridge_loop_lock = threading.Lock()


def _ensure_bridge_loop() -> asyncio.AbstractEventLoop:
    """惰性启动专用后台事件循环线程（进程一个，daemon）。"""
    global _bridge_loop  # noqa: PLW0603
    with _bridge_loop_lock:
        if _bridge_loop is not None and _bridge_loop.is_running():
            return _bridge_loop
        loop = asyncio.new_event_loop()

        def _run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        threading.Thread(
            target=_run_loop,
            name="qwenpaw-kb-facade",
            daemon=True,
        ).start()
        _bridge_loop = loop
        return loop


def _run_coro_blocking(coro: Any, *, timeout: float) -> Any:
    """在后台 loop 上阻塞执行协程并取回结果。"""
    loop = _ensure_bridge_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)


class KbService:
    """Knowledge base registry + per-kb chunk store."""

    def __init__(
        self,
        registry_path: Path | str = REGISTRY_FILE,
        data_dir: Path | str = DATA_DIR,
    ) -> None:
        self._registry_path = Path(registry_path)
        self._data_dir = Path(data_dir)
        self._lock = threading.Lock()
        self._cache_valid = False
        self._cache_key: Optional[int] = None
        self._cache_data: Optional[KbRegistry] = None
        # chunk 读写收编进 L0 文件引擎（含其 mtime 缓存）；本类为薄委托
        self._file_engine = FileKbEngine(data_dir=self._data_dir)

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self) -> KbRegistry:
        try:
            cache_key: Optional[int] = self._registry_path.stat().st_mtime_ns
        except OSError:
            cache_key = None
        if self._cache_valid and cache_key == self._cache_key:
            return self._cache_data  # type: ignore[return-value]
        data = KbRegistry()
        if self._registry_path.is_file():
            try:
                with open(
                    self._registry_path,
                    "r",
                    encoding="utf-8",
                ) as fh:
                    data = KbRegistry.model_validate(json.load(fh))
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.error(
                    "Failed to load kb registry %s: %s",
                    self._registry_path,
                    exc,
                )
        self._cache_valid = True
        self._cache_key, self._cache_data = cache_key, data
        return data

    def _save(self, data: KbRegistry) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(self._registry_path.parent, 0o700)
        with open(self._registry_path, "w", encoding="utf-8") as fh:
            json.dump(
                data.model_dump(mode="json"),
                fh,
                indent=2,
                ensure_ascii=False,
            )
        _chmod_best_effort(self._registry_path, 0o600)
        try:
            self._cache_key = self._registry_path.stat().st_mtime_ns
        except OSError:
            self._cache_key = None
        self._cache_data = data
        self._cache_valid = True

    def _chunks_path(self, kb_id: str) -> Path:
        """该库的 chunks.jsonl 路径（委托 L0 引擎，逻辑单一来源）。"""
        return self._file_engine.chunks_path(kb_id)

    def _load_chunks(self, kb_id: str) -> List[KbChunk]:
        """读某库全部切片（委托 L0 引擎；mtime 缓存语义不变）。"""
        return self._file_engine.load_chunks(kb_id)

    def _save_chunks(self, kb_id: str, chunks: List[KbChunk]) -> None:
        """整库重写切片文件（委托 L0 引擎）。"""
        self._file_engine.save_chunks(kb_id, chunks)

    # ------------------------------------------------------------------
    # backend dispatch seams（T8 门面统一；均可被测试 monkeypatch）
    # ------------------------------------------------------------------

    def _backend(self) -> str:
        """当前存储后端（json/dual/pg）。"""
        return write_gateway.resolve_storage_backend()

    def _pg_store(self) -> Any:
        """pg 访问器（惰性导入避环）；未配置返回 None。"""
        from .pg_store import get_kb_pg_store

        return get_kb_pg_store()

    def _engine(self) -> Any:
        """默认检索引擎（惰性导入避环；已按 backend+探测路由）。"""
        from .engine import get_kb_engine

        return get_kb_engine()

    def _run_async(self, coro: Any, *, write: bool = False) -> Any:
        """同步门面 → 异步 pg 平面的桥接（仅 pg 后端触发）。"""
        timeout = _BRIDGE_WRITE_TIMEOUT if write else _BRIDGE_READ_TIMEOUT
        return _run_coro_blocking(coro, timeout=timeout)

    def _shadow(self, op: Any) -> None:
        """dual 态影子写（fire-and-forget，失败仅告警不影响 json 主写）。"""
        write_gateway.submit_shadow_write(op, domain="kb")

    # ------------------------------------------------------------------
    # 模型转换（json 读写模型 ↔ pg 权威模型；models.py 已预告门面转换）
    # ------------------------------------------------------------------

    def _kb_to_space(self, kb: KnowledgeBase) -> KbSpace:
        """KnowledgeBase → KbSpace（grants 三列表收进 grants dict）。"""
        return KbSpace(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            scope=kb.scope,
            owner_id=kb.owner_id,
            team_id=kb.team_id,
            org_id=kb.org_id or "default",
            grants={
                "roles": list(kb.grants_roles),
                "users": list(kb.grants_users),
                "teams": list(kb.grants_teams),
            },
            created_at=kb.created_at,
        )

    def _space_to_kb(self, space: KbSpace) -> KnowledgeBase:
        """KbSpace → KnowledgeBase（grants dict 摊平回三列表）。"""
        grants = space.grants or {}
        return KnowledgeBase(
            id=space.id,
            name=space.name,
            scope=space.scope,
            owner_id=space.owner_id,
            team_id=space.team_id,
            org_id=space.org_id or "default",
            description=space.description,
            grants_roles=list(grants.get("roles", [])),
            grants_users=list(grants.get("users", [])),
            grants_teams=list(grants.get("teams", [])),
            created_at=space.created_at,
        )

    def _doc_to_meta(self, doc: KbDocument) -> KbDocumentMeta:
        """KbDocument → KbDocumentMeta（chunk_count 从 source_meta 回读）。"""
        meta = doc.source_meta or {}
        return KbDocumentMeta(
            doc_id=doc.id,
            kb_id=doc.space_id,
            title=doc.title,
            source=str(meta.get("source", doc.source)),
            chunk_count=int(meta.get("chunk_count", 0)),
            knowledge_status=doc.knowledge_status,
            valid_from=doc.valid_from,
            valid_to=doc.valid_to,
            created_at=doc.created_at,
        )

    def _hit_to_chunk(self, hit: KbSearchHit) -> KbChunk:
        """KbSearchHit → KbChunk（embedding 不回传，置 None）。

        S2 expand=section 依赖结构锚点：heading_path/parent_seq 随命中回传
        （L0/json 面命中本就为空，pg/milvus 面为真值）。
        """
        return KbChunk(
            chunk_id=hit.chunk_id,
            kb_id=hit.space_id,
            doc_id=hit.document_id,
            seq=hit.seq,
            text=hit.text,
            title="",
            heading_path=hit.heading_path,
            parent_seq=hit.parent_seq,
            embedding=None,
        )

    # ------------------------------------------------------------------
    # pg 平面异步核（供 _run_async 桥接 / dual 影子写复用）
    # ------------------------------------------------------------------

    async def _pg_delete_kb_async(self, kb_id: str) -> bool:
        """删库：先逐文档软删 + 清切片，再删空间（delete_space 拒删非空库）。"""
        store = self._pg_store()
        if store is None or await store.get_space(kb_id) is None:
            return False
        engine = self._engine()
        for doc in await store.list_documents(kb_id):
            await engine.delete_document(kb_id, doc.id)
            await store.delete_document(doc.id)
        return bool(await store.delete_space(kb_id))

    async def _pg_delete_document_async(self, doc_id: str) -> bool:
        """删文档：清切片 + 软删文档行。"""
        store = self._pg_store()
        if store is None:
            return False
        doc = await store.get_document(doc_id)
        if doc is None:
            return False
        await self._engine().delete_document(doc.space_id, doc_id)
        return bool(await store.delete_document(doc_id))

    async def _pg_update_grants_async(
        self,
        kb_id: str,
        *,
        roles: Optional[List[str]],
        users: Optional[List[str]],
        teams: Optional[List[str]],
    ) -> Optional[KnowledgeBase]:
        """改授权：读空间 → 合并 grants → upsert。"""
        store = self._pg_store()
        if store is None:
            return None
        space = await store.get_space(kb_id)
        if space is None:
            return None
        grants = dict(space.grants or {})
        if roles is not None:
            grants["roles"] = list(roles)
        if users is not None:
            grants["users"] = list(users)
        if teams is not None:
            grants["teams"] = list(teams)
        space.grants = grants
        await store.upsert_space(space)
        return self._space_to_kb(space)

    async def _pg_ingest_async(
        self,
        kb_id: str,
        text: str,
        *,
        title: str,
        source: str,
        embeddings: Optional[List[List[float]]],
        doc_id: Optional[str] = None,
    ) -> Optional[KbDocumentMeta]:
        """摄入：结构化切片 → 向量 → upsert 文档行 → 索引 → ready → 回 meta。

        与权威摄入 :func:`ingest_space_document` 同一切片器
        （``split_markdown``：heading_path/parent_seq 随行，S2 结构扩展
        可用）与同一向量管线（``embed_texts(embed_input(spec))``，缺失
        降级 BM25-only），消除「文本/admin 摄入双标」的存量偏差。
        """
        store = self._pg_store()
        space = await store.get_space(kb_id) if store is not None else None
        if store is None or space is None:
            return None
        specs = split_markdown(text)
        if not specs:
            return None
        # dual 影子写复用 json 主写的 doc_id（否则影子删除按 json doc_id 在 pg 找不到行）
        doc_id = doc_id or f"doc_{uuid.uuid4().hex[:12]}"
        doc_title = title or specs[0].text[:40]
        pg_source = source if source in VALID_SOURCES else SOURCE_MANUAL
        document = KbDocument(
            id=doc_id,
            space_id=kb_id,
            path=f"{doc_id}.md",
            title=doc_title,
            content_md=text,
            source=pg_source,
            source_meta={
                "source": source,
                "chunk_count": len(specs),
                "via": "facade_ingest_text",
            },
            ingest_status=INGEST_READY,
        )
        await store.upsert_document(document)
        # 显式传入优先（向后兼容既有调用方）；缺省按库模型生成向量，
        # embedding 不可用返回 None → 全空走 BM25-only，摄入不失败
        if embeddings is None:
            embeddings = await embed_texts(
                [embed_input(spec) for spec in specs],
                model=str(getattr(space, "embedding_model", "") or ""),
            )
        from .engine import resolve_engine_for

        await resolve_engine_for(space).index_document(
            kb_id,
            doc_id,
            specs,
            embeddings,
            title=doc_title,
        )
        # upsert_document 一律落 pending（pg_store 不变式：刚写入=未摄入），
        # 切片写完后显式推进 ready，否则文档永久卡 pending（对齐 T6 ingest）
        await store.update_ingest_status(doc_id, INGEST_READY)
        return KbDocumentMeta(
            doc_id=doc_id,
            kb_id=kb_id,
            title=doc_title,
            source=source,
            chunk_count=len(specs),
        )

    # ------------------------------------------------------------------
    # pg 平面同步包装（fail-soft：异常/不可用 → 回退或按契约返 None/False）
    # ------------------------------------------------------------------

    def _pg_available(self) -> bool:
        """pg 平面是否就绪（表存在 + 可达）。

        用于区分「pg 不可用」（→ 回退文件面）与「pg 就绪但结果为空」
        （→ 权威空结果，绝不回退，否则已删空间会被 30 天保留的 json 复活）。
        pg_store 的 fail-soft 对二者都返回 None/[]，故必须用 ensure_ready 门控。
        """
        try:
            store = self._pg_store()
            if store is None:
                return False
            return bool(self._run_async(store.ensure_ready()))
        except Exception:  # pylint: disable=broad-except
            logger.warning("[kb] pg readiness probe failed", exc_info=True)
            return False

    def _pg_upsert_space(self, kb: KnowledgeBase) -> bool:
        try:
            store = self._pg_store()
            if store is None:
                return False
            return bool(
                self._run_async(
                    store.upsert_space(self._kb_to_space(kb)),
                    write=True,
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg create_kb failed; kb=%s", kb.id, exc_info=True
            )
            return False

    def _pg_get_space(self, kb_id: str) -> Optional[KbSpace]:
        try:
            store = self._pg_store()
            if store is None:
                return None
            return self._run_async(store.get_space(kb_id))
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg get_kb failed; kb=%s", kb_id, exc_info=True
            )
            return None

    def _pg_list_spaces(self) -> List[KbSpace]:
        try:
            store = self._pg_store()
            if store is None:
                return []
            return list(self._run_async(store.list_spaces()) or [])
        except Exception:  # pylint: disable=broad-except
            logger.warning("[kb] pg list_kbs failed", exc_info=True)
            return []

    def _pg_update_grants(
        self,
        kb_id: str,
        *,
        roles: Optional[List[str]],
        users: Optional[List[str]],
        teams: Optional[List[str]],
    ) -> Optional[KnowledgeBase]:
        try:
            return self._run_async(
                self._pg_update_grants_async(
                    kb_id, roles=roles, users=users, teams=teams
                ),
                write=True,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg update_grants failed; kb=%s", kb_id, exc_info=True
            )
            return None

    def _pg_delete_kb(self, kb_id: str) -> bool:
        try:
            return bool(
                self._run_async(self._pg_delete_kb_async(kb_id), write=True)
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg delete_kb failed; kb=%s", kb_id, exc_info=True
            )
            return False

    def _pg_delete_document(self, doc_id: str) -> bool:
        try:
            return bool(
                self._run_async(
                    self._pg_delete_document_async(doc_id), write=True
                )
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg delete_document failed; doc=%s",
                doc_id,
                exc_info=True,
            )
            return False

    def _pg_ingest(
        self,
        kb_id: str,
        text: str,
        *,
        title: str,
        source: str,
        embeddings: Optional[List[List[float]]],
    ) -> Optional[KbDocumentMeta]:
        try:
            return self._run_async(
                self._pg_ingest_async(
                    kb_id,
                    text,
                    title=title,
                    source=source,
                    embeddings=embeddings,
                ),
                write=True,
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg ingest_text failed; kb=%s", kb_id, exc_info=True
            )
            return None

    def _pg_list_documents(self, kb_id: str) -> List[KbDocumentMeta]:
        try:
            store = self._pg_store()
            if store is None:
                return []
            docs = self._run_async(store.list_documents(kb_id)) or []
            return [self._doc_to_meta(doc) for doc in docs]
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg list_documents failed; kb=%s", kb_id, exc_info=True
            )
            return []

    def _pg_get_document(self, doc_id: str) -> Optional[KbDocument]:
        """pg 权威读单文档（含 content_md）；不可用/异常/未命中返 None。"""
        try:
            store = self._pg_store()
            if store is None:
                return None
            return self._run_async(store.get_document(doc_id))
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg get_document failed; doc=%s", doc_id, exc_info=True
            )
            return None

    # ------------------------------------------------------------------
    # T11 文档面 pg 权威门面（供员工面同步 def 路由复用；与既有 admin
    # 路由同模式：路由线程 → 桥接循环，保证 KB 面协程单循环收敛）
    # ------------------------------------------------------------------

    def pg_ready(self) -> bool:
        """pg 权威面是否就绪（backend==pg 且 pg 可达；T11 文档面 503 门控）。

        仅探测 pg 可达不够：dual 后端下 T11 写端点走 pg 权威面，而三态
        读面（chunks/search）仍读 json 主面——读写分裂会让写入后的
        chunk 预览 404、检索不命中。故 backend 非 pg 一律不就绪（路由
        层 503 显式提示）：纯 json 部署无 pg 数据面，dual 部署请走既有
        ``ingest_text`` 写路径（json 主写）+ 三态读面。
        """
        if self._backend() != write_gateway.BACKEND_PG:
            return False
        return self._pg_available()

    def pg_list_documents(self, kb_id: str) -> List[KbDocument]:
        """目录树数据源：pg 权威面文档清单（path 升序，不含正文）。

        调用方先用 :meth:`pg_ready` 门控（503），本方法空列表即权威空。
        """
        try:
            store = self._pg_store()
            if store is None:
                return []
            return list(self._run_async(store.list_documents(kb_id)) or [])
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg tree list failed; kb=%s", kb_id, exc_info=True
            )
            return []

    async def _pg_document_detail_async(
        self,
        kb_id: str,
        doc_id: str,
    ) -> Tuple[Optional[KbDocument], int]:
        """详情取数协程：文档 + 当前版本（未命中/异库/已删除 → (None, 0)）。"""
        store = self._pg_store()
        doc = await store.get_document(doc_id)
        if doc is None or doc.space_id != kb_id or doc.is_delete:
            return None, 0
        versions = await store.list_document_versions(doc.id)
        version = versions[0].version if versions else 1
        return doc, version

    def pg_document_detail(
        self,
        kb_id: str,
        doc_id: str,
    ) -> Tuple[Optional[KbDocument], int]:
        """文档详情数据源：(doc, 当前版本)；未命中 → (None, 0)。

        pg 不可用/异常同样收敛为 (None, 0)——调用方必须先经
        :meth:`pg_ready` 门控（503），避免把基础设施故障误报为 404。
        """
        try:
            store = self._pg_store()
            if store is None:
                return None, 0
            return self._run_async(
                self._pg_document_detail_async(kb_id, doc_id),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg document detail failed; kb=%s doc=%s",
                kb_id,
                doc_id,
                exc_info=True,
            )
            return None, 0

    def pg_ingest_document(
        self,
        *,
        space_id: str,
        title: str,
        path: str,
        content_md: str,
        source: str,
        source_meta: Optional[Dict[str, Any]] = None,
        uploaded_from: Optional[bytes] = None,
    ) -> Optional[IngestResult]:
        """pg 权威面版本化摄入（T6 ``ingest_space_document`` 同步门面）。

        PUT 编辑与 multipart 上传共用：hash 护栏变更自动 ``MAX(version)+1``
        快照 + 重切片重索引；同 path 同内容幂等短路。

        Returns:
            :class:`IngestResult`（含 ``status=failed`` 的失败收敛）；
            桥接异常返 None（调用方 500）。值级拒绝（如空白 content_md，
            ``ingest_space_document`` 抛 ``ValueError``）原样重抛——调用方
            映射 400，与基础设施故障（None → 500）区分。
        """
        try:
            return self._run_async(
                ingest_space_document(
                    space_id=space_id,
                    title=title,
                    path=path,
                    content_md=content_md,
                    source=source,
                    source_meta=source_meta,
                    uploaded_from=uploaded_from,
                    store=self._pg_store(),
                ),
                write=True,
            )
        except ValueError:
            # 值级拒绝（空白 content_md 等）：非基础设施故障，不吞
            raise
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg ingest document failed; kb=%s",
                space_id,
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # T3 wiki 面 pg 权威门面（生命周期/冲突/分类；供同步 def 路由复用，
    # 桥接模式与 T11 文档面一致；写失败返 None/False，值级拒绝透传）
    # ------------------------------------------------------------------

    def pg_review_document(
        self,
        kb_id: str,
        doc_id: str,
        action: str,
        reviewer: str,
        comment: str = "",
    ) -> Optional[KbDocument]:
        """生命周期流转（submit/approve/reject/archive）+ 流水追加。"""
        try:
            return self._run_async(
                review_document(
                    self._pg_store(),
                    kb_id,
                    doc_id,
                    action,
                    reviewer,
                    comment,
                ),
                write=True,
            )
        except ValueError:
            # 非法 action：值级拒绝，路由映射 400
            raise
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg review failed; kb=%s doc=%s action=%s",
                kb_id,
                doc_id,
                action,
                exc_info=True,
            )
            return None

    def pg_list_reviews(
        self,
        kb_id: str,
        doc_id: str,
        *,
        limit: int = 50,
    ) -> List[KbReview]:
        """一份文档的审核流水（新→旧；pg 不可用返回空列表）。"""
        try:
            store = self._pg_store()
            if store is None:
                return []
            return list(
                self._run_async(store.list_reviews(kb_id, doc_id, limit=limit))
                or [],
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg list reviews failed; kb=%s doc=%s",
                kb_id,
                doc_id,
                exc_info=True,
            )
            return []

    def pg_update_knowledge_meta(
        self,
        doc_id: str,
        **fields: Any,
    ) -> bool:
        """分类/有效期编辑（domain/doc_type/confidence/valid_*；白名单内）。"""
        try:
            store = self._pg_store()
            if store is None:
                return False
            return bool(
                self._run_async(
                    store.update_document_meta(doc_id, **fields),
                    write=True,
                ),
            )
        except ValueError:
            # 白名单外的键：值级拒绝，路由映射 400
            raise
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg update knowledge meta failed; doc=%s",
                doc_id,
                exc_info=True,
            )
            return False

    def pg_detect_conflicts(self, kb_id: str, doc_id: str) -> List[KbConflict]:
        """规则冲突检测，返回本次新建的冲突候选（幂等查重）。"""
        try:
            store = self._pg_store()
            if store is None:
                return []
            return list(
                self._run_async(
                    detect_conflicts(store, kb_id, doc_id),
                    write=True,
                )
                or [],
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg detect conflicts failed; kb=%s doc=%s",
                kb_id,
                doc_id,
                exc_info=True,
            )
            return []

    def pg_list_conflicts(
        self,
        kb_id: str,
        *,
        status: str = "",
    ) -> List[KbConflict]:
        """库内冲突清单（status 空串 = 全态）。"""
        try:
            store = self._pg_store()
            if store is None:
                return []
            return list(
                self._run_async(
                    store.list_conflicts(kb_id, status=status),
                )
                or [],
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg list conflicts failed; kb=%s",
                kb_id,
                exc_info=True,
            )
            return []

    def pg_resolve_conflict(self, conflict_id: str, resolved_by: str) -> bool:
        """解决一个 open 冲突（已解决行返回 False）。"""
        try:
            store = self._pg_store()
            if store is None:
                return False
            return bool(
                self._run_async(
                    store.resolve_conflict(conflict_id, resolved_by),
                    write=True,
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg resolve conflict failed; id=%s",
                conflict_id,
                exc_info=True,
            )
            return False

    def _pg_search(
        self,
        kb_id: str,
        query: str,
        query_embedding: Optional[List[float]],
        top_k: int,
    ) -> Optional[List[KbSearchHit]]:
        """pg 面检索：库级引擎路由 + 查询向量按需解析（S1 混检激活点）。

        space 就绪时按 ``kb_spaces.engine`` 路由引擎（与摄入同一解析函数，
        milvus 库检索不再错落默认引擎）；``query_embedding`` 缺省时按库的
        ``embedding_model`` 经缓存调用 ``embed_query_cached`` 生成——失败
        返 ``None`` 自然降级 BM25-only。space 不可达时保留旧行为（默认
        引擎 + 不解析向量），保证 pg 抖动不新增故障面。
        """
        try:
            engine = self._engine()
            space = self._pg_get_space(kb_id)
            if space is not None:
                from .engine import resolve_engine_for

                engine = resolve_engine_for(space)
                if query_embedding is None and (query or "").strip():
                    query_embedding = self._run_async(
                        embed_query_cached(
                            query,
                            model=str(
                                getattr(space, "embedding_model", "") or ""
                            ),
                        ),
                    )
            return list(
                self._run_async(
                    engine.search([kb_id], query, query_embedding, top_k),
                ),
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg search failed; kb=%s", kb_id, exc_info=True
            )
            return None

    # ------------------------------------------------------------------
    # knowledge base CRUD
    # ------------------------------------------------------------------

    def create_kb(
        self,
        name: str,
        *,
        scope: str = SCOPE_PERSONAL,
        owner_id: str = "",
        team_id: str = "",
        org_id: str = "default",
        description: str = "",
    ) -> Optional[KnowledgeBase]:
        name = name.strip()
        if not name or scope not in VALID_SCOPES:
            return None
        if scope == SCOPE_PERSONAL and not owner_id:
            return None
        if scope == SCOPE_TEAM and not team_id:
            return None
        kb = KnowledgeBase(
            id=f"kb_{uuid.uuid4().hex[:12]}",
            name=name,
            scope=scope,
            owner_id=owner_id,
            team_id=team_id,
            org_id=(org_id or "default").strip() or "default",
            description=description.strip(),
        )
        backend = self._backend()
        # pg 后端：PG 权威写，成功返 kb、失败返 None（不裂写 json）
        if backend == write_gateway.BACKEND_PG:
            return kb if self._pg_upsert_space(kb) else None
        # json / dual：json primary 写
        with self._lock:
            data = self._load()
            data.knowledge_bases[kb.id] = kb
            self._save(data)
        # dual：json 主写成功后影子写 pg（fire-and-forget）
        if backend == write_gateway.BACKEND_DUAL:
            space = self._kb_to_space(kb)
            self._shadow(lambda: self._pg_store().upsert_space(space))
        return kb

    def get_kb(self, kb_id: str) -> Optional[KnowledgeBase]:
        if self._backend() == write_gateway.BACKEND_PG:
            if self._pg_available():
                # pg 就绪即权威：命中转换返回，未命中返 None（不回退，防已删复活）
                space = self._pg_get_space(kb_id)
                return self._space_to_kb(space) if space is not None else None
            # pg 不可用 → fail-soft 回退文件面
        return self._load().knowledge_bases.get(kb_id)

    def update_grants(
        self,
        kb_id: str,
        *,
        roles: Optional[List[str]] = None,
        users: Optional[List[str]] = None,
        teams: Optional[List[str]] = None,
    ) -> Optional[KnowledgeBase]:
        """Replace a kb's explicit grant lists (admin API)."""
        backend = self._backend()
        if backend == write_gateway.BACKEND_PG:
            return self._pg_update_grants(
                kb_id, roles=roles, users=users, teams=teams
            )
        with self._lock:
            data = self._load()
            kb = data.knowledge_bases.get(kb_id)
            if kb is None:
                return None
            if roles is not None:
                kb.grants_roles = list(roles)
            if users is not None:
                kb.grants_users = list(users)
            if teams is not None:
                kb.grants_teams = list(teams)
            self._save(data)
        if backend == write_gateway.BACKEND_DUAL:
            # 影子写走 read-modify-write（仅改 grants），避免 _kb_to_space 的
            # 默认 embedding_model/engine 覆盖 pg 已配置值
            self._shadow(
                lambda: self._pg_update_grants_async(
                    kb_id, roles=roles, users=users, teams=teams
                )
            )
        return kb

    def list_kbs(self) -> List[KnowledgeBase]:
        if self._backend() == write_gateway.BACKEND_PG:
            if self._pg_available():
                # pg 就绪即权威：空结果也直接返回（不回退，防已删库复活）
                return [self._space_to_kb(s) for s in self._pg_list_spaces()]
            # pg 不可用 → fail-soft 回退文件面
        return list(self._load().knowledge_bases.values())

    def delete_kb(self, kb_id: str) -> bool:
        backend = self._backend()
        if backend == write_gateway.BACKEND_PG:
            return self._pg_delete_kb(kb_id)
        with self._lock:
            data = self._load()
            if kb_id not in data.knowledge_bases:
                return False
            del data.knowledge_bases[kb_id]
            for doc_id in [
                d for d, doc in data.documents.items() if doc.kb_id == kb_id
            ]:
                del data.documents[doc_id]
            self._save(data)
        self._file_engine.drop_space(kb_id)
        # dual：json 主删成功后影子删 pg（delete_space 同事务回收绑定）
        if backend == write_gateway.BACKEND_DUAL:
            self._shadow(lambda: self._pg_delete_kb_async(kb_id))
        return True

    # ------------------------------------------------------------------
    # ACL
    # ------------------------------------------------------------------

    def can_access(
        self,
        kb: KnowledgeBase,
        username: str,
        *,
        flat_role: str = "",
        user_roles: Optional[List[str]] = None,
        user_teams: Optional[List[str]] = None,
        user_org: str = "",
    ) -> bool:
        """Whether *username* may read *kb*.

        判定顺序：admin → grants(users/roles/teams) → scope 语义。
        ``user_org`` 为调用者所属组织 id（org 即租户边界；空串按
        default 租户收敛，单租户部署与 enterprise 等价）。
        """
        if flat_role == "admin":
            return True
        if username and username in kb.grants_users:
            return True
        roles = user_roles or []
        if any(role in kb.grants_roles for role in roles):
            return True
        teams = user_teams or []
        if any(team in kb.grants_teams for team in teams):
            return True
        if kb.scope == SCOPE_PERSONAL:
            return bool(username) and username == kb.owner_id
        if kb.scope == SCOPE_TEAM:
            return bool(kb.team_id) and kb.team_id in teams
        if kb.scope == SCOPE_ORG:
            caller_org = user_org or "default"
            return bool(username) and caller_org == (kb.org_id or "default")
        if kb.scope == SCOPE_ENTERPRISE:
            return bool(username)
        return False

    def accessible_kbs(
        self,
        username: str,
        *,
        flat_role: str = "",
        user_roles: Optional[List[str]] = None,
        user_teams: Optional[List[str]] = None,
        user_org: str = "",
    ) -> List[KnowledgeBase]:
        """All knowledge bases visible to *username*."""
        return [
            kb
            for kb in self.list_kbs()
            if self.can_access(
                kb,
                username,
                flat_role=flat_role,
                user_roles=user_roles,
                user_teams=user_teams,
                user_org=user_org,
            )
        ]

    # ------------------------------------------------------------------
    # ingestion
    # ------------------------------------------------------------------

    def ingest_text(
        self,
        kb_id: str,
        text: str,
        *,
        title: str = "",
        source: str = "",
        embeddings: Optional[List[List[float]]] = None,
    ) -> Optional[KbDocumentMeta]:
        """Chunk *text* and append it to the kb's store.

        *embeddings* (one vector per chunk, same order) is optional —
        callers compute it when an embedding model is configured.
        """
        backend = self._backend()
        if backend == write_gateway.BACKEND_PG:
            return self._pg_ingest(
                kb_id,
                text,
                title=title,
                source=source,
                embeddings=embeddings,
            )
        if self.get_kb(kb_id) is None or not text.strip():
            return None
        pieces = chunk_text(text)
        if not pieces:
            return None
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        with self._lock:
            chunks = list(self._load_chunks(kb_id))
            base_seq = len(chunks)
            for index, piece in enumerate(pieces):
                embedding = None
                if embeddings and index < len(embeddings):
                    embedding = embeddings[index]
                chunks.append(
                    KbChunk(
                        chunk_id=f"{doc_id}_{index}",
                        kb_id=kb_id,
                        doc_id=doc_id,
                        title=title,
                        seq=base_seq + index,
                        text=piece,
                        embedding=embedding,
                    ),
                )
            self._save_chunks(kb_id, chunks)
            data = self._load()
            doc = KbDocumentMeta(
                doc_id=doc_id,
                kb_id=kb_id,
                title=title or pieces[0][:40],
                source=source,
                chunk_count=len(pieces),
            )
            data.documents[doc_id] = doc
            self._save(data)
        # dual：json 主写成功后影子摄入 pg（fire-and-forget；复用 json doc_id，
        # 否则影子 delete_document 按 json doc_id 在 pg 找不到行 → 孤儿残留）
        if backend == write_gateway.BACKEND_DUAL:
            self._shadow(
                lambda: self._pg_ingest_async(
                    kb_id,
                    text,
                    title=title,
                    source=source,
                    embeddings=embeddings,
                    doc_id=doc_id,
                )
            )
        return doc

    def delete_document(self, doc_id: str) -> bool:
        backend = self._backend()
        if backend == write_gateway.BACKEND_PG:
            return self._pg_delete_document(doc_id)
        with self._lock:
            data = self._load()
            doc = data.documents.get(doc_id)
            if doc is None:
                return False
            del data.documents[doc_id]
            chunks = [
                c for c in self._load_chunks(doc.kb_id) if c.doc_id != doc_id
            ]
            self._save_chunks(doc.kb_id, chunks)
            self._save(data)
        if backend == write_gateway.BACKEND_DUAL:
            self._shadow(lambda: self._pg_delete_document_async(doc_id))
        return True

    def list_documents(self, kb_id: str) -> List[KbDocumentMeta]:
        if self._backend() == write_gateway.BACKEND_PG:
            return self._pg_list_documents(kb_id)
        return [
            doc
            for doc in self._load().documents.values()
            if doc.kb_id == kb_id
        ]

    def get_document_meta(self, doc_id: str) -> Optional[KbDocumentMeta]:
        """按 doc_id 取文档元数据（三态门面；kb_read 据此解析所属库做 ACL）。

        pg 就绪即权威：命中转换返回、未命中返 None（不回退，防已删文档被
        30 天保留的 json 复活）；pg 不可用 fail-soft 回退文件面 registry。
        """
        if self._backend() == write_gateway.BACKEND_PG:
            if self._pg_available():
                doc = self._pg_get_document(doc_id)
                return self._doc_to_meta(doc) if doc is not None else None
            # pg 不可用 → fail-soft 回退文件面
        return self._load().documents.get(doc_id)

    def read_document(self, doc_id: str) -> Optional[str]:
        """取一篇文档的权威 Markdown 全文（三态门面，kb_read 工具数据源）。

        pg 后端取 ``kb_documents.content_md``（权威源全文，逐字精确）；
        json/dual 后端从切片按 seq 拼接重建（遗留 JSONL 无独立 MD 源，
        best-effort）。注意：chunk_text 为检索连续性在切片间保留 ~100
        字符 overlap，故多切片文档重建时边界处会有少量文本重复（已知
        限制，仅为遗留 json 后端；pg 后端取权威 content_md 无此问题）。
        未命中或无切片返 None。
        """
        if self._backend() == write_gateway.BACKEND_PG:
            if self._pg_available():
                doc = self._pg_get_document(doc_id)
                return doc.content_md if doc is not None else None
            # pg 不可用 → fail-soft 回退文件面
        with self._lock:
            meta = self._load().documents.get(doc_id)
            if meta is None:
                return None
            chunks = [
                c for c in self._load_chunks(meta.kb_id) if c.doc_id == doc_id
            ]
        if not chunks:
            return None
        chunks.sort(key=lambda c: c.seq)
        return "\n\n".join(c.text for c in chunks)

    # ------------------------------------------------------------------
    # retrieval
    # ------------------------------------------------------------------

    def search(
        self,
        kb_id: str,
        query: str,
        *,
        top_k: int = 5,
        query_embedding: Optional[List[float]] = None,
    ) -> List[tuple[KbChunk, float]]:
        """Rank chunks of one kb（三态门面：pg 走引擎，json/dual 走 L0 文件面）。

        pg 后端经引擎层（get_kb_engine 已按 backend+探测路由）桥接检索，命中
        KbSearchHit 转回 (KbChunk, score)；json/dual 读走文件面（dual 读仍 json，
        spec §4.3）。pg 不可用 fail-soft 回退文件面。同步签名保留给既有调用方。
        ACL is the caller's responsibility (see :meth:`accessible_kbs`).
        """
        if self._backend() == write_gateway.BACKEND_PG:
            hits = self._pg_search(kb_id, query, query_embedding, top_k)
            if hits is not None:
                return [(self._hit_to_chunk(h), h.score) for h in hits]
            # pg 不可用 → fail-soft 回退文件面
        results = self._file_engine.search_sync(
            [kb_id],
            query,
            query_embedding=query_embedding,
            top_k=top_k,
        )
        # T3 知识生命周期过滤（文件面降级口径）：registry 无状态信息的
        # 文档放行（宁误出不错杀），有状态的一律 published+有效期内才可检
        documents = self._load().documents
        return [
            (chunk, score)
            for chunk, score in results
            if self._meta_retrievable(documents.get(chunk.doc_id))
        ]

    @staticmethod
    def _meta_retrievable(meta: Optional[KbDocumentMeta]) -> bool:
        """json 面 registry 条目是否可检索（缺条目/缺状态 = 放行降级）。"""
        if meta is None:
            return True
        return is_effective(meta)

    def document_chunks(self, kb_id: str, doc_id: str) -> List[KbChunk]:
        """一份文档的全部切片（seq 升序，带 heading_path/parent_seq）。

        S2 ``expand=section`` 的兄弟块来源，亦是 T11 ``GET .../documents/
        {docId}/chunks`` 预览的数据源（共享基建）。工具层按 doc_id 去重后
        每 doc 只调一次，杜绝 per-hit N+1（项目规范 §2.4）。

        三态分派：pg 面经引擎 ``list_document_chunks`` 查 kb_chunks（权威）；
        json/L0 面过滤已载 chunk（heading_path 恒空，S2 自然降级为单块）。
        pg 不可用 fail-soft 回退文件面，绝不抛给调用方。
        """
        if self._backend() == write_gateway.BACKEND_PG:
            hits = self._pg_list_document_chunks(kb_id, doc_id)
            if hits is not None:
                chunks = [self._hit_to_chunk(h) for h in hits]
                chunks.sort(key=lambda c: c.seq)
                return chunks
            # pg 不可用 → fail-soft 回退文件面
        with self._lock:
            chunks = [
                c for c in self._load_chunks(kb_id) if c.doc_id == doc_id
            ]
        chunks.sort(key=lambda c: c.seq)
        return chunks

    def document_graph(
        self,
        kb_id: str,
        doc_id: str,
        depth: int = 3,
    ) -> List[tuple]:
        """Wikilink 出边图 ≤depth 跳（T5 ``expand=graph`` 底座）。

        pg 权威面：``kb_links`` WITH RECURSIVE CTE 单次往返；json/L0
        面无 links 存储 → 诚实降级空列表（工具层标注「无相关链」，
        不伪装）。fail-soft：任何异常返回空列表，绝不抛给检索面。
        """
        try:
            rows = self._run_async(
                self._pg_store().list_document_graph(
                    doc_id,
                    space_id=kb_id,
                    max_depth=depth,
                ),
            )
            return list(rows or [])
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] document_graph failed; kb=%s doc=%s",
                kb_id,
                doc_id,
                exc_info=True,
            )
            return []

    def _pg_list_document_chunks(
        self,
        kb_id: str,
        doc_id: str,
    ) -> Optional[List[KbSearchHit]]:
        """pg 面按文档取全部切片（与 ``search`` 同级的检索增强取数）。

        返回：None = 引擎未实现 ``list_document_chunks``（如 milvus 面本
        切片未实现，见 brief D7）或桥接/引擎解析本身报错 → 回退文件面；
        ``[]`` = 引擎就绪但无切片（权威空）。注：``PgVectorEngine`` 内部
        broad-except 已把连接/SQL 失败收敛为 ``[]``（非 None），故 pg 拖动
        不会误回退文件面。

        回退策略与 :meth:`search` 一致（同为检索面）：document_chunks 只为
        search 已命中的 doc 做小节扩展，若 pg 不可用则 search 也已回退文件面，
        两者同源——故不另加 ``_pg_available`` 门控（区别于 read_document/
        get_document_meta 的“pg 就绪即权威”读语义）。
        """
        try:
            engine = self._engine()
            # 库级路由与 _pg_search 同源：milvus 库的 S2 兄弟块取数/T11
            # 预览不再错落默认引擎（引擎未实现该能力时仍按 None 回退文件面）
            space = self._pg_get_space(kb_id)
            if space is not None:
                from .engine import resolve_engine_for

                engine = resolve_engine_for(space)
            lister = getattr(engine, "list_document_chunks", None)
            if lister is None:
                return None
            return list(self._run_async(lister(kb_id, doc_id)) or [])
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "[kb] pg list_document_chunks failed; kb=%s doc=%s",
                kb_id,
                doc_id,
                exc_info=True,
            )
            return None


_default_service: Optional[KbService] = None


def get_kb_service() -> KbService:
    """Return the process-wide default KB service (lazy singleton)."""
    global _default_service  # noqa: PLW0603
    if _default_service is None:
        _default_service = KbService()
    return _default_service


def reset_kb_service() -> None:
    """Drop the singleton (tests)."""
    global _default_service  # noqa: PLW0603
    _default_service = None
