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

表缺失语义：迁移（alembic 0034）尚未执行时 :meth:`KbPgStore.ensure_ready`
返回 ``False``，**所有读写方法在入口处自行短路**，绝不把 ``UndefinedTable``
抛给调用方；``KbService`` 门面据此回退文件平面。探测正结果永久缓存，负结果
按 :data:`NOT_READY_RETRY_SECONDS` 冷却重试，保证「应用先起、迁移后跑」时
PG 平面能在同进程内自动恢复。

两条写入入口职责严格分离（幂等契约的地基）：

- :meth:`KbPgStore.upsert_document` —— 只写**内容族**列，以 ``content_hash``
  为唯一判据；内容未变时 SQL 层 ``IS DISTINCT FROM`` 护栏拦截整条 UPDATE，
  既不刷新 ``updated_at`` 也不追加版本快照，因此重复摄入零副作用；INSERT 与
  UPDATE 两臂对称地把 ``ingest_status`` 落 ``pending``、``error`` 落空串，
  保证“刚写入的内容总是未摄入”，杜绝「正文已改（或文档新建）、切片仍是空的
  却被标成 ready」的静默脏读。
- :meth:`KbPgStore.update_document_meta` —— 只写**元数据族**列（重命名、
  移动、回收站恢复），不触碰正文与版本链。两者互不越权，改名不会被内容
  护栏静默吞掉，正文写入也不会意外复活已删除文档。

@author qingfeng
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, Tuple

from ...db import write_gateway
from .models import (
    INGEST_PENDING,
    KbBinding,
    KbDocument,
    KbDocumentVersion,
    KbSpace,
)

logger = logging.getLogger(__name__)

#: 多租户预留，现阶段固定 default（与其余 PG 平面同源）
DEFAULT_TENANT_ID = "default"

#: 每个文档保留的版本快照数（惰性清理，同 agent_docs 保留窗口策略）
VERSION_RETENTION = 20

#: 表未就绪判定的冷却窗口：错过窗口后允许重新探测，避免迁移补跑后
#: 进程仍一路在文件平面上写到重启
NOT_READY_RETRY_SECONDS = 60.0

#: 表就绪探测涉及的六张表（缺一不可走 PG 平面）
_KB_TABLES = (
    "kb_spaces",
    "kb_documents",
    "kb_document_versions",
    "kb_chunks",
    "kb_links",
    "agent_kb_bindings",
)

# 列清单常量化且前置，读写两侧共用同一份字面量，杜绝手写漂移
_SPACE_COLUMNS = (
    "SELECT id, name, description, scope, owner_id, team_id, grants, "
    "embedding_model, engine, created_at, updated_at"
)

_DOCUMENT_COLUMNS = (
    "SELECT id, space_id, path, title, content_md, content_hash, "
    "source, source_meta, ingest_status, error, is_delete, updated_by, "
    "created_at, updated_at"
)

#: 列表与路径定位场景不取 ``content_md``（长文本），其余字段同详情
_DOCUMENT_LIST_COLUMNS = (
    "SELECT id, space_id, path, title, content_hash, "
    "source, source_meta, ingest_status, error, is_delete, updated_by, "
    "created_at, updated_at"
)

#: 绑定行投影（T7：agent_kb_bindings 全列，读写共用同一份字面量）
_BINDING_COLUMNS = "SELECT agent_id, space_id, granted_by, remark, created_at"

#: 版本快照投影（T2 派生入口 list_document_versions 的读端）
_VERSION_COLUMNS = (
    "SELECT document_id, version, content_md, content_hash, "
    "created_by, created_at"
)

#: 元数据写入白名单：列名 → SET 片段（仅键名可枚举，值一律走绑定参数）
_META_ASSIGNMENTS = {
    "space_id": "space_id = :space_id",
    "path": "path = :path",
    "title": "title = :title",
    "source": "source = :source",
    "source_meta": "source_meta = CAST(:source_meta AS JSONB)",
    "is_delete": "is_delete = :is_delete",
    "updated_by": "updated_by = :updated_by",
}

_store: Optional["KbPgStore"] = None
_store_lock = threading.Lock()


def content_hash(content: str) -> str:
    """SHA-256 hex digest，幂等写入与版本判定的唯一依据。"""
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def kb_pg_plane_available() -> bool:
    """True when the KB plane may touch PG (dual/pg backend + DSN set).

    仅做静态三态判定（判定逻辑本身沉在写网关，本层不复制、不自行判 DSN）；
    表是否真的建好需 :meth:`KbPgStore.ensure_ready`——探测必须 await，
    不能塞进同步判定里阻塞事件循环。
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
    except (KeyError, IndexError, TypeError):
        return None


def _stamp_kwargs(row: Any, key: str) -> dict:
    """Build constructor kwargs for one NOT NULL timestamptz column.

    ``created_at`` / ``updated_at`` 在 0034 两侧都是 NOT NULL，且本模块的
    列清单常量显式包含它们。缺列或类型意外只会是投影写错这种**编程错误**，
    因此在此处早失败：拿 ``now()`` 伪造一个看起来合法的时间戳，会让 Task 8
    的目录树排序与后续排查都建立在假数据上。
    """
    value = _row_value(row, key)
    if not isinstance(value, datetime):
        raise KeyError(
            f"kb pg row is missing datetime column {key!r}; "
            "check the SELECT column list against alembic 0034",
        )
    return {key: value}


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
        **_stamp_kwargs(row, "created_at"),
        **_stamp_kwargs(row, "updated_at"),
    )


def document_from_row(row: Any, *, with_content: bool = True) -> KbDocument:
    """Build a :class:`KbDocument` from one ``kb_documents`` mapping row.

    ``with_content=False`` 用于列表/路径定位场景（正文未查询）。
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
        **_stamp_kwargs(row, "created_at"),
        **_stamp_kwargs(row, "updated_at"),
    )


def binding_from_row(row: Any) -> KbBinding:
    """Build a :class:`KbBinding` from one ``agent_kb_bindings`` row."""
    return KbBinding(
        agent_id=str(_row_value(row, "agent_id") or ""),
        space_id=str(_row_value(row, "space_id") or ""),
        granted_by=str(_row_value(row, "granted_by") or ""),
        remark=str(_row_value(row, "remark") or ""),
        **_stamp_kwargs(row, "created_at"),
    )


def version_from_row(row: Any) -> KbDocumentVersion:
    """Build a :class:`KbDocumentVersion` from one versions row."""
    raw_version = _row_value(row, "version")
    if not isinstance(raw_version, int):
        # 版本号是主键的一部分，缺列/类型意外只能是投影写错这类编程错误，
        # 在此处早失败而不是静默落 0 伪装成合法快照
        raise KeyError(
            "kb pg row is missing int column 'version'; check the "
            "SELECT column list against alembic 0034",
        )
    return KbDocumentVersion(
        document_id=str(_row_value(row, "document_id") or ""),
        version=raw_version,
        content_md=str(_row_value(row, "content_md") or ""),
        content_hash=str(_row_value(row, "content_hash") or ""),
        created_by=str(_row_value(row, "created_by") or ""),
        **_stamp_kwargs(row, "created_at"),
    )


class KbPgStore:
    """Async accessor for the KB PG tables (alembic 0034).

    Engine 懒取：三态判定为 json 时永不触碰 ``create_pg_engine()``，保证
    无 PG 的个人部署连连接池都不会建立。

    数据不变式（``path`` 非空）与后端无关，因此在三态短路**之前**校验：
    json 后端同样拒绝空 path，避免只在 PG 平面暴露的脏数据。
    """

    def __init__(
        self,
        engine: Any = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        self._engine = engine
        self._tenant_id = tenant_id
        self._tables_ready: Optional[bool] = None
        self._tables_checked_at: float = 0.0

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
        """True when PG is reachable and every KB table exists.

        正结果永久缓存（表不会在运行期消失）；负结果只缓存
        :data:`NOT_READY_RETRY_SECONDS`，迁移补跑后同进程自动恢复；
        探测异常不写缓存（网络抖动不应把平面永久降级）。
        """
        if not kb_pg_plane_available():
            return False
        if self._tables_ready is True:
            return True
        cooled = (
            time.monotonic() - self._tables_checked_at
        ) < NOT_READY_RETRY_SECONDS
        if self._tables_ready is False and cooled:
            return False
        self._tables_checked_at = time.monotonic()
        try:
            self._tables_ready = await self._probe_tables_async()
        except Exception:  # pylint: disable=broad-except
            logger.warning("kb pg tables probe failed", exc_info=True)
            return False
        if not self._tables_ready:
            logger.warning(
                "kb pg tables missing, falling back to file plane; "
                "re-check after `alembic upgrade head`",
            )
        return self._tables_ready

    # ------------------------------------------------------------------
    # space ops
    # ------------------------------------------------------------------

    async def upsert_space(self, space: KbSpace) -> bool:
        """Insert or refresh one knowledge space; True when it was written.

        空间元数据无内容哈希概念，重复写入只保证 ``updated_at`` 前进。
        """
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        async with self._get_engine().begin() as conn:
            result = await conn.execute(
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
            return bool(result.rowcount)

    async def get_space(self, space_id: str) -> Optional[KbSpace]:
        """Load one space by id, or ``None`` when absent/unavailable."""
        if not await self.ensure_ready():
            return None
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _SPACE_COLUMNS
                    + " FROM kb_spaces "
                    + "WHERE tenant_id = :tid AND id = :space_id",
                ),
                {"tid": self._tenant_id, "space_id": space_id},
            )
            row = result.mappings().first()
        return space_from_row(row) if row is not None else None

    async def list_spaces(self) -> List[KbSpace]:
        """All spaces by creation time（scope ACL 由门面上层收敛）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _SPACE_COLUMNS
                    + " FROM kb_spaces WHERE tenant_id = :tid "
                    + "ORDER BY created_at ASC",
                ),
                {"tid": self._tenant_id},
            )
            rows = result.mappings().all()
        return [space_from_row(row) for row in rows]

    async def delete_space(self, space_id: str) -> bool:
        """Delete an **empty** space; refuse while it still owns live docs.

        0034 无外键，空间行删掉不会级联。若在此处放过还有活文档的空间，
        其下的文档、版本快照、切片（含 HNSW/GIN 索引体积）、链接边与
        agent 绑定会全部变成可达孤儿，其中孤儿切片还存在被 Task 5 召回的
        现实路径。因此把「调用方须先清理」从注释升级为代码守卫。

        守卫只看活文档：已进回收站（``is_delete``）的文档会随空间一起失去
        可达路径（S0 按已授权空间集合收敛，空间不存在即不会被检索命中），
        残留行由 Task 11 的清理端点物理回收；若连回收站也当守卫，空间将
        在「用户已清空回收站但未物理删除」的常见流程里彻底删不掉。
        """
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            occupied = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM kb_documents "
                        "WHERE tenant_id = :tid AND space_id = :space_id "
                        "AND is_delete = FALSE "
                        "LIMIT 1",
                    ),
                    {"tid": self._tenant_id, "space_id": space_id},
                )
            ).first()
            if occupied is not None:
                # 仍有未删除文档：删除会直接造出可达孤儿，一律拒绝
                logger.info(
                    "kb space %s still owns documents, refuse delete",
                    space_id,
                )
                return False
            result = await conn.execute(
                text(
                    "DELETE FROM kb_spaces "
                    "WHERE tenant_id = :tid AND id = :space_id",
                ),
                {"tid": self._tenant_id, "space_id": space_id},
            )
            if result.rowcount:
                # 同事务回收该库的全部绑定行：0034 无外键，不回收会在
                # 绑定列表造出指向已删空间的脏读（T2 派生登记项）
                await conn.execute(
                    text(
                        "DELETE FROM agent_kb_bindings "
                        "WHERE tenant_id = :tid AND space_id = :space_id",
                    ),
                    {"tid": self._tenant_id, "space_id": space_id},
                )
            return bool(result.rowcount)

    # ------------------------------------------------------------------
    # document ops（内容写：hash 护栏 + 版本链，与元数据写严格分途）
    # ------------------------------------------------------------------

    async def upsert_document(self, document: KbDocument) -> bool:
        """Upsert one document; snapshot a version only on content change.

        Returns ``True`` when a row was inserted or the content actually
        changed, ``False`` when an identical hash already existed（幂等重放
        零副作用）。

        ``content_hash`` 一律由存储层按 ``content_md`` 重算，不信任入参：
        该值既是幂等判据又是落库列，一旦被上游算错就会造成永久性丢写。

        摄入状态在**两条路径上对称**：新行与变更行一律落 ``pending`` 并清空
        ``error``（“刚写入的内容总是未摄入”是不变式，否则新文档会以
        ready 状态带着零切片入库，dual 下重建扫描永远看不见它）；
        ``processing``/``ready``/``failed`` 只能由 :meth:`update_ingest_status`
        推进。本方法也不改 ``is_delete``（复活走 :meth:`update_document_meta`）。

        Raises:
            ValueError: ``path`` 为空——``uq_kb_documents_path`` 是部分唯一
                索引，空串会让同库第二篇无路径文档直接撞键。
        """
        if not document.path.strip():
            raise ValueError(
                "kb document path must not be empty (it backs the "
                "per-space unique index)",
            )
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        markdown = document.content_md or ""
        digest = content_hash(markdown)
        if document.content_hash and document.content_hash != digest:
            logger.warning(
                "kb pg caller-supplied content_hash mismatches body, "
                "recomputed from content_md: doc_id=%s",
                document.id,
            )
        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO kb_documents (tenant_id, id, space_id, "
                    "path, title, content_md, content_hash, source, "
                    "source_meta, ingest_status, error, is_delete, "
                    "updated_by, created_at, updated_at) "
                    "VALUES (:tid, :doc_id, :space_id, :path, :title, "
                    "CAST(:content_md AS TEXT), :chash, :source, "
                    "CAST(:source_meta AS JSONB), :reset_status, '', "
                    ":is_delete, :updated_by, :now, :now) "
                    "ON CONFLICT (tenant_id, id) DO UPDATE SET "
                    "space_id = EXCLUDED.space_id, "
                    "path = EXCLUDED.path, "
                    "title = EXCLUDED.title, "
                    "content_md = EXCLUDED.content_md, "
                    "content_hash = EXCLUDED.content_hash, "
                    "source = EXCLUDED.source, "
                    "source_meta = EXCLUDED.source_meta, "
                    "ingest_status = :reset_status, "
                    "error = '', "
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
                    "is_delete": document.is_delete,
                    "updated_by": document.updated_by,
                    "reset_status": INGEST_PENDING,
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

    async def update_document_meta(
        self,
        doc_id: str,
        **fields: Any,
    ) -> bool:
        """Write metadata only（重命名 / 移动 / 回收站恢复），不触碰正文。

        允许键见 :data:`_META_ASSIGNMENTS`；正文与版本链由
        :meth:`upsert_document` 独占，因此本方法不受内容哈希护栏影响，
        改名一定生效。

        Raises:
            ValueError: 键不在白名单，或把 ``path`` 改成空串。
        """
        unknown = [key for key in fields if key not in _META_ASSIGNMENTS]
        if unknown:
            raise ValueError(
                f"unsupported kb document meta field(s): {unknown}",
            )
        if not fields:
            return False
        if "path" in fields and not str(fields["path"] or "").strip():
            raise ValueError(
                "kb document path must not be empty (it backs the "
                "per-space unique index)",
            )
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        assignments = [
            fragment
            for key, fragment in _META_ASSIGNMENTS.items()
            if key in fields
        ]
        params: dict[str, Any] = {"tid": self._tenant_id, "doc_id": doc_id}
        for key, value in fields.items():
            params[key] = _json_dumps(value) if key == "source_meta" else value
        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE kb_documents SET "
                    + ", ".join(assignments)
                    + ", updated_at = now() "
                    + "WHERE tenant_id = :tid AND id = :doc_id",
                ),
                params,
            )
            # 目标路径已被同库其他文档占用时由 uq_kb_documents_path 抛
            # IntegrityError，交由门面翻译成「路径已存在」的用户可读错误
            return bool(result.rowcount)

    async def _lock_document(self, conn: Any, doc_id: str) -> None:
        """Take the row lock so same-document version numbers stay serial.

        Raises:
            ValueError: 文档不存在（版本快照必须挂在真实主体上，0034 无外键
                拦不住孤儿快照）。
        """
        from sqlalchemy import text

        locked = await conn.execute(
            text(
                "SELECT 1 FROM kb_documents "
                "WHERE tenant_id = :tid AND id = :doc_id FOR UPDATE",
            ),
            {"tid": self._tenant_id, "doc_id": doc_id},
        )
        if locked.fetchone() is None:
            raise ValueError(
                f"kb document {doc_id} not found; cannot snapshot a version",
            )

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

        先锁文档行把同一文档的并发写入串行化，再取 ``MAX(version)+1``，
        否则两个事务会拿到同号，而 ``ON CONFLICT DO NOTHING`` 会把后到者
        的真实快照直接吞掉（版本链断裂且无人知晓）。此处用普通 INSERT：
        真撞号就抛 ``IntegrityError`` 让事务回滚，宁可失败也不静默丢历史。
        """
        from sqlalchemy import text

        await self._lock_document(conn, document_id)
        next_version = int(
            (
                await conn.execute(
                    text(
                        "SELECT COALESCE(MAX(version), 0) + 1 AS "
                        "next_version FROM kb_document_versions "
                        "WHERE tenant_id = :tid "
                        "AND document_id = :doc_id",
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
                "CAST(:content_md AS TEXT), :chash, :created_by)",
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

        供 Task 6「正文未变但需留痕」等场景显式调用；日常内容变更应走
        :meth:`upsert_document`，由 hash 护栏自动决定是否抖动版本。
        """
        if not await self.ensure_ready():
            return 0
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
        if not await self.ensure_ready():
            return None
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _DOCUMENT_COLUMNS
                    + " FROM kb_documents "
                    + "WHERE tenant_id = :tid AND id = :doc_id",
                ),
                {"tid": self._tenant_id, "doc_id": doc_id},
            )
            row = result.mappings().first()
        return document_from_row(row) if row is not None else None

    async def get_document_by_path(
        self,
        space_id: str,
        path: str,
        *,
        include_deleted: bool = False,
    ) -> Optional[KbDocument]:
        """Locate one document by its per-space path (no 正文).

        ``path`` 才是业务唯一键（``uq_kb_documents_path``），wikilink 解析
        与「先查后写」都必须按它定位，因此这里提供原子入口，避免调用方
        自己 list 后过滤留下竞态窗口。
        """
        if not path.strip():
            raise ValueError(
                "kb document path must not be empty (it backs the "
                "per-space unique index)",
            )
        if not await self.ensure_ready():
            return None
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
                    + " AND path = :path",
                ),
                {
                    "tid": self._tenant_id,
                    "space_id": space_id,
                    "path": path,
                },
            )
            row = result.mappings().first()
        return (
            document_from_row(row, with_content=False)
            if row is not None
            else None
        )

    async def list_documents(
        self,
        space_id: str,
        *,
        include_deleted: bool = False,
    ) -> List[KbDocument]:
        """List a space's documents without 正文（目录树/列表场景）。

        默认过滤逻辑删除行：``uq_kb_documents_path`` 只对未删除文档生效，
        回收站内容混入会让目录树出现重复路径。
        """
        if not await self.ensure_ready():
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
                    + " ORDER BY path ASC",
                ),
                {"tid": self._tenant_id, "space_id": space_id},
            )
            rows = result.mappings().all()
        return [document_from_row(row, with_content=False) for row in rows]

    async def delete_document(self, doc_id: str) -> bool:
        """Soft-delete one document（逻辑删除，保证可追溯与可恢复）。"""
        if not await self.ensure_ready():
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
        if not await self.ensure_ready():
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
    # link ops（wikilink 出边：重建语义 = 删本源旧边 + 插新边）
    # ------------------------------------------------------------------

    async def replace_document_links(
        self,
        space_id: str,
        src_document_id: str,
        edges: Sequence[Tuple[str, str, str]],
    ) -> int:
        """Replace one document's outgoing wikilink edges (single txn).

        入参 ``edges`` 已在摄入侧解析完毕（``dst_path`` / 归一化后的
        ``dst_document_id`` / ``context_snippet`` 三元组，悬挂目标落空串，
        见 Task 6）：本方法只负责「删本源旧边 + 插新边」的原子替换。
        空列表等价于「清除本源全部出边」——正文删掉 wikilink 的收敛路径。

        ``link_id`` 前缀携带插入序号（零填充 6 位）：「保序」由此端到端
        成立（读回 ``ORDER BY id`` 即插入序，见 :meth:`list_document_links`）。
        平面未就绪时返回 0（全平面三态短路口径）：0 不区分「无出边」与
        「平面不可用」，完成态路径不依赖本返回值。

        Returns:
            写入的边条数。
        """
        if not await self.ensure_ready():
            return 0
        from sqlalchemy import text

        rows = list(edges)
        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM kb_links "
                    "WHERE tenant_id = :tid "
                    "AND src_document_id = :src",
                ),
                {"tid": self._tenant_id, "src": src_document_id},
            )
            for seq, (dst_path, dst_document_id, context) in enumerate(
                rows,
            ):
                await conn.execute(
                    text(
                        "INSERT INTO kb_links (tenant_id, id, space_id, "
                        "src_document_id, dst_path, dst_document_id, "
                        "context_snippet, created_at) "
                        "VALUES (:tid, :link_id, :space_id, :src, "
                        ":dst_path, :dst_document_id, :context, now())",
                    ),
                    {
                        "tid": self._tenant_id,
                        "link_id": f"lnk_{seq:06d}_{uuid.uuid4().hex[:12]}",
                        "space_id": space_id,
                        "src": src_document_id,
                        "dst_path": dst_path,
                        "dst_document_id": dst_document_id,
                        "context": context,
                    },
                )
        return len(rows)

    async def list_document_links(
        self,
        src_document_id: str,
    ) -> List[Tuple[str, str, str]]:
        """List one document's outgoing edges in insertion order.

        返回 ``(dst_path, dst_document_id, context_snippet)`` 列表，顺序 =
        首次出现序（文档内保序契约的读端；依赖 ``link_id`` 的零填充序号
        前缀，见 :meth:`replace_document_links`）。
        """
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT dst_path, dst_document_id, context_snippet "
                    "FROM kb_links "
                    "WHERE tenant_id = :tid "
                    "AND src_document_id = :src ORDER BY id ASC",
                ),
                {"tid": self._tenant_id, "src": src_document_id},
            )
            rows = result.mappings().all()
        return [
            (
                str(_row_value(row, "dst_path") or ""),
                str(_row_value(row, "dst_document_id") or ""),
                str(_row_value(row, "context_snippet") or ""),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # binding ops（T7：授权关系是交互式强一致数据，不走影子写）
    # ------------------------------------------------------------------

    async def insert_binding(
        self,
        agent_id: str,
        space_id: str,
        *,
        granted_by: str = "",
        remark: str = "",
    ) -> bool:
        """Bind one agent to a space; ``True`` when the relation holds.

        ``ON CONFLICT DO NOTHING``：重复绑定幂等成立（返回 ``True``），
        不产生重复行也不刷新既有行的授权人与备注；平面不可用返回
        ``False``。调用方须先经 ``can_manage_space`` 管理权校验。
        """
        if not agent_id.strip() or not space_id.strip():
            raise ValueError("kb binding requires non-empty agent/space id")
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO agent_kb_bindings "
                    "(tenant_id, agent_id, space_id, granted_by, remark, "
                    " created_at) VALUES (:tid, :agent_id, :space_id, "
                    ":granted_by, :remark, :now) "
                    "ON CONFLICT (tenant_id, agent_id, space_id) DO NOTHING",
                ),
                {
                    "tid": self._tenant_id,
                    "agent_id": agent_id,
                    "space_id": space_id,
                    "granted_by": granted_by,
                    "remark": remark,
                    "now": datetime.now(timezone.utc),
                },
            )
            return True

    async def delete_binding(self, agent_id: str, space_id: str) -> bool:
        """Remove one binding; ``True`` only when a row was deleted."""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM agent_kb_bindings "
                    "WHERE tenant_id = :tid AND agent_id = :agent_id "
                    "AND space_id = :space_id",
                ),
                {
                    "tid": self._tenant_id,
                    "agent_id": agent_id,
                    "space_id": space_id,
                },
            )
            return bool(result.rowcount)

    async def list_agent_bindings(self, agent_id: str) -> List[KbBinding]:
        """All spaces bound to one agent（确定性读序：绑定时间升序）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _BINDING_COLUMNS
                    + " FROM agent_kb_bindings "
                    + "WHERE tenant_id = :tid AND agent_id = :agent_id "
                    + "ORDER BY created_at ASC, space_id ASC",
                ),
                {"tid": self._tenant_id, "agent_id": agent_id},
            )
            rows = result.mappings().all()
        return [binding_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # version read model（T2 派生入口：版本链读端）
    # ------------------------------------------------------------------

    async def list_document_versions(
        self,
        document_id: str,
    ) -> List[KbDocumentVersion]:
        """One document's snapshots, newest first（version DESC）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        async with self._get_engine().connect() as conn:
            result = await conn.execute(
                text(
                    _VERSION_COLUMNS
                    + " FROM kb_document_versions "
                    + "WHERE tenant_id = :tid AND document_id = :doc_id "
                    + "ORDER BY version DESC",
                ),
                {"tid": self._tenant_id, "doc_id": document_id},
            )
            rows = result.mappings().all()
        return [version_from_row(row) for row in rows]

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


def get_kb_pg_store(engine: Any = None) -> Optional[KbPgStore]:
    """Return the shared store; ``None`` when PG is not configured at all.

    表未建时本工厂仍返回实例——所有方法自带 :meth:`KbPgStore.ensure_ready`
    短路，因此不会抛异常；需要「拿一个确定可用的实例」请用
    :func:`get_ready_kb_pg_store`。
    """
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
    """Drop the cached singleton（测试切换环境变量后必须调用）."""
    global _store  # pylint: disable=global-statement
    with _store_lock:
        _store = None
