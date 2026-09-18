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
from typing import Any, List, Optional

from ...constant import SECRET_DIR
from ...db import write_gateway
from .chunker import ChunkSpec
from .file_engine import DEFAULT_KB_DATA_DIR, FileKbEngine
from .hits import KbSearchHit
from .models import (
    INGEST_READY,
    SCOPE_ENTERPRISE,
    SCOPE_PERSONAL,
    SCOPE_TEAM,
    SOURCE_MANUAL,
    VALID_SCOPES,
    VALID_SOURCES,
    KbChunk,
    KbDocument,
    KbDocumentMeta,
    KbRegistry,
    KbSpace,
    KnowledgeBase,
)

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
            created_at=doc.created_at,
        )

    def _hit_to_chunk(self, hit: KbSearchHit) -> KbChunk:
        """KbSearchHit → KbChunk（embedding 不回传，置 None）。"""
        return KbChunk(
            chunk_id=hit.chunk_id,
            kb_id=hit.space_id,
            doc_id=hit.document_id,
            seq=hit.seq,
            text=hit.text,
            title="",
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
        """摄入：切片 → upsert 文档行 → 引擎写索引 → 推进 ready → 回 meta。"""
        store = self._pg_store()
        if store is None or await store.get_space(kb_id) is None:
            return None
        pieces = chunk_text(text)
        if not pieces:
            return None
        # dual 影子写复用 json 主写的 doc_id（否则影子删除按 json doc_id 在 pg 找不到行）
        doc_id = doc_id or f"doc_{uuid.uuid4().hex[:12]}"
        doc_title = title or pieces[0][:40]
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
                "chunk_count": len(pieces),
                "via": "facade_ingest_text",
            },
            ingest_status=INGEST_READY,
        )
        await store.upsert_document(document)
        specs = [
            ChunkSpec(
                seq=index,
                heading_path="",
                text=piece,
                parent_seq=None,
                token_count=len(piece),
            )
            for index, piece in enumerate(pieces)
        ]
        await self._engine().index_document(
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
            chunk_count=len(pieces),
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

    def _pg_search(
        self,
        kb_id: str,
        query: str,
        query_embedding: Optional[List[float]],
        top_k: int,
    ) -> Optional[List[KbSearchHit]]:
        try:
            return self._run_async(
                self._engine().search([kb_id], query, query_embedding, top_k)
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
    ) -> bool:
        """Whether *username* may read *kb*."""
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
        return self._file_engine.search_sync(
            [kb_id],
            query,
            query_embedding=query_embedding,
            top_k=top_k,
        )


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
