# -*- coding: utf-8 -*-
"""KB PG 存储平面（空间 / 文档 / 版本三表）。

四层架构（spec §4）中「Markdown 文档权威源」在 PostgreSQL 上的落地：本模块
只负责结构化存取，不做切片与检索（分属 Task 3 / Task 5）。

三态后端语义与其余 PG 平面完全同源，判定统一收敛在
``db.write_gateway``：

- ``json``：个人部署无 PG，本平面所有写方法零动作、读方法返回空；
- ``dual``：文件仍为 primary，本平面经 :func:`write_gateway.submit_shadow_write`
  接收 fire-and-forget 影子写，失败仅告警；
- ``pg``：本平面为权威读写路径。

迁移（alembic 0034）尚未执行时 :meth:`KbPgStore.ensure_ready` 返回 ``False``，
``KbService`` 门面据此回退文件平面，绝不因表缺失抛异常。

幂等契约：文档写入以 ``content_hash`` 为唯一判据，SQL 层
``IS DISTINCT FROM`` 护栏拦截无变化重放——内容未变时既不刷新
``updated_at``，也不追加版本快照，因此重复摄入零副作用。

@author qingfeng
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, List, Optional

from ...db import write_gateway
from .models import (
    KbDocument,
    KbSpace,
)

logger = logging.getLogger(__name__)

#: 多租户预留，现阶段固定 default（与其余 PG 平面同源）
DEFAULT_TENANT_ID = "default"

#: 每个文档保留的版本快照数（惰性清理，同 agent_docs 保留窗口策略）
VERSION_RETENTION = 20

#: 表就绪探测涉及的六张表（缺一不可走 PG 权威读）
_KB_TABLES = (
    "kb_spaces",
    "kb_documents",
    "kb_document_versions",
    "kb_chunks",
    "kb_links",
    "agent_kb_bindings",
)

_store: Optional["KbPgStore"] = None
_store_lock = threading.Lock()


def content_hash(content: str) -> str:
    """SHA-256 hex digest，作为幂等写入与版本判定的唯一依据。"""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def kb_pg_plane_available() -> bool:
    """True when the KB plane should touch PG (dual/pg backend + DSN set).

    仅做静态三态判定（判定逻辑本身沉在写网关，本层不复制）；表是否真的
    建好需 ``await store.ensure_ready()``——探测是异步操作，不能塞进
    同步判定里阻塞事件循环。
    """
    return write_gateway.pg_write_available()


def _json_dumps(value: Any) -> str:
    """Serialize a JSONB payload (dict/list) to a compact JSON string."""
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_loads(raw: Any, default: Any) -> Any:
    """Decode a JSONB column that may arrive as ``str`` or already ``dict``."""
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("kb pg jsonb decode failed, fallback to default")
        return default


def _row_value(row: Any, key: str) -> Any:
    """Read one column from a mapping row, tolerating absent keys."""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):  # pragma: no cover - 行契约稳定
        return None


def _as_datetime(raw: Any) -> Optional[datetime]:
    """Coerce a timestamptz column into a datetime (``None`` when absent)."""
    return raw if isinstance(raw, datetime) else None


def space_from_row(row: Any) -> KbSpace:
    """Build a :class:`KbSpace` from one ``kb_spaces`` mapping row."""
    return KbSpace(
        id=str(_row_value(row, "id") or ""),
        name=str(_row_value(row, "name") or ""),
        description=str(_row_value(row, "description") or ""),
        scope=str(_row_value(row, "scope") or "personal"),
        owner_id=str(_row_value(row, "owner_id") or ""),
        team_id=str(_row_value(row, "team_id") or ""),
        grants=_json_loads(_row_value(row, "grants"), {}),
        embedding_model=str(_row_value(row, "embedding_model") or ""),
        engine=str(_row_value(row, "engine") or "auto"),
        created_at=_as_datetime(_row_value(row, "created_at")),
        updated_at=_as_datetime(_row_value(row, "updated_at")),
    )


def document_from_row(row: Any, *, with_content: bool = True) -> KbDocument:
    """Build a :class:`KbDocument` from one ``kb_documents`` mapping row.

    ``with_content=False`` 用于列表场景（正文未查询，字段保持默认空串）。
    """
    return KbDocument(
        id=str(_row_value(row, "id") or ""),
        space_id=str(_row_value(row, "space_id") or ""),
        path=str(_row_value(row, "path") or ""),
        title=str(_row_value(row, "title") or ""),
        content_md=(
            str(_row_value(row, "content_md") or "") if with_content else ""
        ),
        content_hash=str(_row_value(row, "content_hash") or ""),
        source=str(_row_value(row, "source") or "manual"),
        source_meta=_json_loads(_row_value(row, "source_meta"), {}),
        ingest_status=str(_row_value(row, "ingest_status") or "ready"),
        error=str(_row_value(row, "error") or ""),
        is_delete=bool(_row_value(row, "is_delete")),
        updated_by=str(_row_value(row, "updated_by") or ""),
        created_at=_as_datetime(_row_value(row, "created_at")),
        updated_at=_as_datetime(_row_value(row, "updated_at")),
    )


class KbPgStore:
    """Async accessor for the KB PG tables (alembic 0034).

    Engine 懒取：三态判定为 json 时永不触碰 ``create_pg_engine()``，保证
    无 PG 的个人部署连数据库连接池都不会建立。
    """

    def __init__(
        self,
        engine: Any = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        self._engine = engine
        self._tenant_id = tenant_id
        self._tables_ready: Optional[bool] = None

    # ------------------------------------------------------------------
    # engine / readiness
    # ------------------------------------------------------------------

    def _get_engine(self) -> Any:
        """Lazily materialize the shared pooled engine from the PG DSN."""
        if self._engine is None:
            from ...db.engine import create_pg_engine

            self._engine = create_pg_engine()
        return self._engine

    async def _probe_tables_async(self) -> bool:
        """Single round-trip ``to_regclass`` probe over all six KB tables."""
        from sqlalchemy import text

        columns = ", ".join(
            f"to_regclass('public.{name}')" for name in _KB_TABLES
        )
        async with self._get_engine().connect() as conn:
            row = (await conn.execute(text(f"SELECT {columns}"))).fetchone()
        return bool(row) and all(value is not None for value in row)

    async def ensure_ready(self) -> bool:
        """True when PG is reachable and the KB tables exist (cached).

        探测结果进程级缓存：表一旦建好不会在运行期消失，无需重复往返。
        """
        if not kb_pg_plane_available():
            return False
        if self._tables_ready is None:
            try:
                self._tables_ready = await self._probe_tables_async()
            except Exception:  # pylint: disable=broad-except
                logger.warning("kb pg tables not ready", exc_info=True)
                return False
        return self._tables_ready

    # ------------------------------------------------------------------
    # space ops
    # ------------------------------------------------------------------

    async def upsert_space(self, space: KbSpace) -> bool:
        """Insert or refresh one knowledge space; True when a row was written.

        空间元数据无内容哈希概念，重复写入只保证 ``updated_at`` 前进。
        """
        if not kb_pg_plane_available():
            return False
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO kb_spaces (tenant_id, id, name, "
                    "description, scope, owner_id, team_id, grants, "
                    "embedding_model, engine, created_at, updated_at) "
                    "VALUES (:tid, :space_id, :name, :description, :scope, "
                    ":owner_id, :team_id, CAST(:grants AS JSONB), "
                    ":embedding_model, :engine, :now, :now) "
                    "ON CONFLICT (tenant_id, id) DO UPDATE SET "
                    "name = EXCLUDED.name, "
                    "description = EXCLUDED.description, "
                    "scope = EXCLUDED.scope, "
                    "owner_id = EXCLUDED.owner_id, "
                    "team_id = EXCLUDED.team_id, "
                    "grants = EXCLUDED.grants, "
                    "embedding_model = EXCLUDED.embedding_model, "
                    "engine = EXCLUDED.engine, "
                    "updated_at = EXCLUDED.updated_at",
                ),
                {
                    "tid": self._tenant_id,
                    "space_id": space.id,
                    "name": space.name,
                    "description": space.description,
                    "scope": space.scope,
                    "owner_id": space.owner_id,
                    "team_id": space.team_id,
                    "grants": _json_dumps(space.grants),
                    "embedding_model": space.embedding_model,
                    "engine": space.engine,
                    "now": now,
                },
            )
        return True

    async def get_space(self, space_id: str) -> Optional[KbSpace]:
        """Load one space by id, or ``None`` on the json backend."""
        if not kb_pg_plane_available():
            return None
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _SPACE_COLUMNS + " FROM kb_spaces "
                    "WHERE tenant_id = :tid AND id = :space_id"
                ),
                {"tid": self._tenant_id, "space_id": space_id},
            )
            row = result.mappings().first()
        return space_from_row(row) if row is not None else None

    async def list_spaces(self) -> List[KbSpace]:
        """All spaces ordered by creation time (scope ACL 由门面上层收敛)."""
        if not kb_pg_plane_available():
            return []
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _SPACE_COLUMNS
                    + " FROM kb_spaces WHERE tenant_id = :tid "
                    + "ORDER BY created_at ASC"
                ),
                {"tid": self._tenant_id},
            )
            rows = result.mappings().all()
        return [space_from_row(row) for row in rows]

    async def delete_space(self, space_id: str) -> bool:
        """Hard-delete one space row; True when it existed.

        空间删除是管理动作，文档与切片由调用方（Task 6/11）先行清理，
        本层不做级联，避免隐式批量删除。
        """
        if not kb_pg_plane_available():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM kb_spaces "
                    "WHERE tenant_id = :tid AND id = :space_id",
                ),
                {"tid": self._tenant_id, "space_id": space_id},
            )
        return bool(result.rowcount)

    # ------------------------------------------------------------------
    # document ops（hash 护栏：内容未变零副作用）
    # ------------------------------------------------------------------

    async def upsert_document(self, document: KbDocument) -> bool:
        """Upsert one document; snapshot a version only on content change.

        Returns ``True`` when a row was inserted or the content actually
        changed, ``False`` when an identical hash already existed（幂等重放
        不抖动 ``updated_at``、不追加版本、不打扰下游索引重建）。

        Raises:
            ValueError: ``path`` 为空。``uq_kb_documents_path`` 是部分唯一
                索引，空串会让同库第二篇无路径文档直接撞唯一键。
        """
        if not document.path.strip():
            raise ValueError(
                "kb document path must not be empty (it backs the "
                "per-space unique index)",
            )
        if not kb_pg_plane_available():
            return False
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        markdown = document.content_md or ""
        digest = document.content_hash or content_hash(markdown)
        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO kb_documents (tenant_id, id, space_id, "
                    "path, title, content_md, content_hash, source, "
                    "source_meta, ingest_status, error, is_delete, "
                    "updated_by, created_at, updated_at) "
                    "VALUES (:tid, :doc_id, :space_id, :path, :title, "
                    "CAST(:content_md AS TEXT), :chash, :source, "
                    "CAST(:source_meta AS JSONB), :ingest_status, :error, "
                    ":is_delete, :updated_by, :now, :now) "
                    "ON CONFLICT (tenant_id, id) DO UPDATE SET "
                    "space_id = EXCLUDED.space_id, "
                    "path = EXCLUDED.path, "
                    "title = EXCLUDED.title, "
                    "content_md = EXCLUDED.content_md, "
                    "content_hash = EXCLUDED.content_hash, "
                    "source = EXCLUDED.source, "
                    "source_meta = EXCLUDED.source_meta, "
                    "ingest_status = EXCLUDED.ingest_status, "
                    "error = EXCLUDED.error, "
                    "is_delete = EXCLUDED.is_delete, "
                    "updated_by = EXCLUDED.updated_by, "
                    "updated_at = EXCLUDED.updated_at "
                    "WHERE kb_documents.content_hash IS DISTINCT FROM "
                    "EXCLUDED.content_hash "
                    "RETURNING id",
                ),
                {
                    "tid": self._tenant_id,
                    "doc_id": document.id,
                    "space_id": document.space_id,
                    "path": document.path,
                    "title": document.title,
                    "content_md": markdown,
                    "chash": digest,
                    "source": document.source,
                    "source_meta": _json_dumps(document.source_meta),
                    "ingest_status": document.ingest_status,
                    "error": document.error,
                    "is_delete": document.is_delete,
                    "updated_by": document.updated_by,
                    "now": now,
                },
            )
            if result.mappings().first() is None:
                # WHERE 拦截 → 内容未变的幂等重放，零副作用返回
                return False
            await self._snapshot_version(
                conn,
                document_id=document.id,
                content_md=markdown,
                content_hash_value=digest,
                created_by=document.updated_by,
            )
        return True

    async def _snapshot_version(
        self,
        conn: Any,
        *,
        document_id: str,
        content_md: str,
        content_hash_value: str,
        created_by: str,
    ) -> int:
        """Append one immutable revision inside the caller's transaction.

        写入当前版本号 = 历史最大版本 + 1，随后按保留窗口清理最旧的快照，
        使「版本抖动」与「存储膨胀」同时可控。
        """
        from sqlalchemy import text

        next_version = int(
            (
                await conn.execute(
                    text(
                        "SELECT COALESCE(MAX(version), 0) + 1 AS "
                        "next_version FROM kb_document_versions "
                        "WHERE tenant_id = :tid AND document_id = :doc_id",
                    ),
                    {"tid": self._tenant_id, "doc_id": document_id},
                )
            )
            .mappings()
            .first()["next_version"],
        )
        await conn.execute(
            text(
                "INSERT INTO kb_document_versions (tenant_id, document_id, "
                "version, content_md, content_hash, created_by) "
                "VALUES (:tid, :doc_id, :version, "
                "CAST(:content_md AS TEXT), :chash, :created_by) "
                "ON CONFLICT (tenant_id, document_id, version) DO NOTHING",
            ),
            {
                "tid": self._tenant_id,
                "doc_id": document_id,
                "version": next_version,
                "content_md": content_md,
                "chash": content_hash_value,
                "created_by": created_by,
            },
        )
        cutoff = next_version - VERSION_RETENTION
        if cutoff > 0:
            await conn.execute(
                text(
                    "DELETE FROM kb_document_versions "
                    "WHERE tenant_id = :tid AND document_id = :doc_id "
                    "AND version <= :cutoff",
                ),
                {
                    "tid": self._tenant_id,
                    "doc_id": document_id,
                    "cutoff": cutoff,
                },
            )
        return next_version

    async def add_document_version(
        self,
        document_id: str,
        content_md: str,
        *,
        created_by: str = "",
    ) -> int:
        """Append one revision outside a document write; returns its version.

        供 Task 6 的「摄入失败后仅补版本」等场景显式调用；日常内容变更
        应走 :meth:`upsert_document`，由 hash 护栏自动决定是否抖动版本。
        """
        if not kb_pg_plane_available():
            return 0
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            return await self._snapshot_version(
                conn,
                document_id=document_id,
                content_md=content_md,
                content_hash_value=content_hash(content_md),
                created_by=created_by,
            )

    async def get_document(self, doc_id: str) -> Optional[KbDocument]:
        """Load one document (full content) by id."""
        if not kb_pg_plane_available():
            return None
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _DOCUMENT_COLUMNS
                    + " FROM kb_documents "
                    + "WHERE tenant_id = :tid AND id = :doc_id"
                ),
                {"tid": self._tenant_id, "doc_id": doc_id},
            )
            row = result.mappings().first()
        return document_from_row(row) if row is not None else None

    async def list_documents(
        self,
        space_id: str,
        *,
        include_deleted: bool = False,
    ) -> List[KbDocument]:
        """List a space's documents without正文（目录树/列表场景）。

        默认过滤逻辑删除行：``uq_kb_documents_path`` 只对未删除文档生效，
        回收站内容混入会让目录树出现重复路径。
        """
        if not kb_pg_plane_available():
            return []
        from sqlalchemy import text

        where = "WHERE tenant_id = :tid AND space_id = :space_id"
        if not include_deleted:
            where += " AND is_delete = FALSE"
        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _DOCUMENT_LIST_COLUMNS
                    + " FROM kb_documents "
                    + where
                    + " ORDER BY path ASC"
                ),
                {"tid": self._tenant_id, "space_id": space_id},
            )
            rows = result.mappings().all()
        return [document_from_row(row, with_content=False) for row in rows]

    async def delete_document(self, doc_id: str) -> bool:
        """Soft-delete one document（逻辑删除，保证可追溯与可恢复）。"""
        if not kb_pg_plane_available():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE kb_documents SET is_delete = TRUE, "
                    "updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :doc_id "
                    "AND is_delete = FALSE",
                ),
                {"tid": self._tenant_id, "doc_id": doc_id},
            )
        return bool(result.rowcount)

    async def update_ingest_status(
        self,
        doc_id: str,
        ingest_status: str,
        *,
        error: str = "",
    ) -> bool:
        """Advance one document's ingest state machine (Task 6 异步摄入)."""
        if not kb_pg_plane_available():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE kb_documents SET ingest_status = :status, "
                    "error = :error, updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :doc_id",
                ),
                {
                    "tid": self._tenant_id,
                    "doc_id": doc_id,
                    "status": ingest_status,
                    "error": error,
                },
            )
        return bool(result.rowcount)

    # ------------------------------------------------------------------
    # fire-and-forget shadow writes（同步调用方不阻塞）
    # ------------------------------------------------------------------

    def schedule_upsert_space(self, space: KbSpace) -> None:
        """Mirror one space write into PG; never blocks or raises."""
        write_gateway.submit_shadow_write(
            lambda: self.upsert_space(space),
            domain="kb_space",
        )

    def schedule_upsert_document(self, document: KbDocument) -> None:
        """Mirror one document write into PG; never blocks or raises."""
        write_gateway.submit_shadow_write(
            lambda: self.upsert_document(document),
            domain="kb_document",
        )


# 列清单常量化，避免读写两侧手写不一致
_SPACE_COLUMNS = (
    "SELECT id, name, description, scope, owner_id, team_id, grants, "
    "embedding_model, engine, created_at, updated_at"
)

_DOCUMENT_COLUMNS = (
    "SELECT id, space_id, path, title, content_md, content_hash, "
    "source, source_meta, ingest_status, error, is_delete, updated_by, "
    "created_at, updated_at"
)

#: 列表场景不取 ``content_md``（长文本），其余字段与详情一致
_DOCUMENT_LIST_COLUMNS = (
    "SELECT id, space_id, path, title, content_hash, "
    "source, source_meta, ingest_status, error, is_delete, updated_by, "
    "created_at, updated_at"
)


def get_kb_pg_store(engine: Any = None) -> Optional[KbPgStore]:
    """Return the shared store; ``None`` when PG is not configured at all."""
    global _store  # pylint: disable=global-statement
    if _store is not None:
        return _store
    if not kb_pg_plane_available():
        return None
    with _store_lock:
        if _store is None:
            _store = KbPgStore(engine=engine)
        return _store


async def get_ready_kb_pg_store() -> Optional[KbPgStore]:
    """Factory gated on table readiness; ``None`` means「回退 json 平面」."""
    store = get_kb_pg_store()
    if store is None:
        return None
    if not await store.ensure_ready():
        return None
    return store


def reset_store_for_tests() -> None:
    """Drop the cached singleton (tests切换环境变量后必须调用)."""
    global _store  # pylint: disable=global-statement
    with _store_lock:
        _store = None
