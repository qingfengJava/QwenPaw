# -*- coding: utf-8 -*-
"""Shadow store for agent identity documents (``agent_documents`` table).

Phase A of the workspace-storage migration: the workspace file remains the
primary read/write surface (the system-prompt contributors read it
synchronously on the hot path), while every successful write of an identity
file (``PROFILE.md`` / ``AGENTS.md`` / ``SOUL.md`` / ``agent.json``) mirrors
a fire-and-forget shadow row into PostgreSQL — the same dual-write pattern
as ``app/chats/dual_session_store.py``. Shadow failures are counted and
logged; they never block or fail the primary write.

The store is a ``None`` singleton when ``QWENPAW_PG_DSN`` is not configured:
local deployments without PostgreSQL keep the file-only behavior unchanged.

@author qingfeng
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: workspace 文件名 → doc_type 的映射（档案文件的固定白名单）
DOC_TYPE_BY_FILENAME = {
    "PROFILE.md": "profile",
    "AGENTS.md": "agents",
    "SOUL.md": "soul",
    "agent.json": "agent_json",
}

#: 判定草稿实例的 agent_id 后缀（与 expert preview 的命名约定一致）
_DRAFT_SUFFIX = "__draft"

#: 合法 doc_type 集合（白名单值视图，promote 入口校验用）
VALID_DOC_TYPES = frozenset(DOC_TYPE_BY_FILENAME.values())

#: 每 (tenant, agent, doc_type, environment) 保留的版本快照数（发布时惰性清理）
REVISION_RETENTION = 20


def environment_for_agent(agent_id: str) -> str:
    """Map an agent id to its document environment (draft|production)."""
    return "draft" if agent_id.endswith(_DRAFT_SUFFIX) else "production"


def content_hash(content: str) -> str:
    """SHA-256 hex digest used as the idempotent upsert predicate."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def annotate_draft_status(
    drafts: list[dict],
    shared_docs: list[dict],
) -> list[dict]:
    """为个人草稿行标注 ``unapplied``（与共享行内容分叉即待应用）。

    ``drafts`` 为 :meth:`AgentDocsStore.list_personal_drafts` 的行，
    ``shared_docs`` 为 :meth:`AgentDocsStore.list_documents` 的共享行。
    "草稿行存在"不等于"有未应用变更"（apply 后草稿行保留作为工作副本，
    内容与共享一致）——必须用内容 hash 比对，避免错误的「未应用」
    信号（与 SOP promote 幂等的教训同源）。共享行缺失时视为待应用
    （无物可比，确实尚未固化到共享面）。
    """
    shared_hash_by_doc = {
        str(row.get("doc_type")): str(row.get("content_hash") or "")
        for row in shared_docs
    }
    annotated: list[dict] = []
    for draft in drafts:
        shared_hash = shared_hash_by_doc.get(str(draft.get("doc_type")))
        annotated.append(
            {
                **draft,
                "unapplied": shared_hash is None
                or shared_hash != str(draft.get("content_hash") or ""),
            },
        )
    return annotated


class AgentDocsStore:
    """Async accessor for the ``agent_documents`` table.

    Owns the shared pooled engine from ``QWENPAW_PG_DSN`` (same factory as
    the other PG stores); all statements are parameterized and idempotent.
    """

    def __init__(self, engine: Any = None, tenant_id: str = "default") -> None:
        if engine is None:
            from ...db.engine import create_pg_engine

            engine = create_pg_engine()
        self._engine = engine
        self._tenant_id = tenant_id

    # -- write path --------------------------------------------------------

    async def upsert_document(
        self,
        agent_id: str,
        doc_type: str,
        content: str,
        *,
        environment: str | None = None,
        updated_by: str | None = None,
        owner_user_id: str | None = None,
    ) -> bool:
        """Upsert one document; bump ``version`` only on content change.

        内容变化时在同事务快照一个不可变 revision（复用发布路径的保留
        窗口清理），使文件覆盖写也可回滚；内容未变的幂等重放不产生版本
        与快照。

        ``owner_user_id`` 非空时写该用户的个人草稿行（environment 固定
        ``draft``，不写 revision 快照——快照链仅属于共享发布闸门，apply
        时经 :meth:`promote` 在共享链落版本）；None 时写共享行（原行为）。

        Returns True when a row was written (insert or content change),
        False when an identical version already existed (idempotent replay).
        """
        from datetime import datetime, timezone

        from sqlalchemy import text

        # 个人草稿行固定 draft 环境；共享行随 agent_id/显式参数分流
        if owner_user_id:
            env = "draft"
        else:
            env = environment or environment_for_agent(agent_id)
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO agent_documents (tenant_id, agent_id, "
                    "doc_type, environment, owner_user_id, content, "
                    "content_hash, version, updated_by, created_at, "
                    "updated_at) "
                    "VALUES (:tid, :aid, :dtype, :env, :owner, "
                    "CAST(:content AS TEXT), "
                    ":chash, 1, :uby, :now, :now) "
                    "ON CONFLICT (tenant_id, agent_id, doc_type, "
                    "environment, (COALESCE(owner_user_id, ''))) "
                    "DO UPDATE SET content = EXCLUDED.content, "
                    "content_hash = EXCLUDED.content_hash, "
                    "version = agent_documents.version + 1, "
                    "updated_by = EXCLUDED.updated_by, "
                    "updated_at = EXCLUDED.updated_at "
                    "WHERE agent_documents.content_hash "
                    "IS DISTINCT FROM EXCLUDED.content_hash "
                    "RETURNING version"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "dtype": doc_type,
                    "env": env,
                    "owner": owner_user_id,
                    "content": content,
                    "chash": content_hash(content),
                    "uby": updated_by,
                    "now": now,
                },
            )
            row = result.mappings().first()
            if row is None:
                # 内容未变（WHERE 拦截）→ RETURNING 空集，属幂等重放
                return False
            # 个人草稿不写发布链快照（apply=promote 时才在共享链落版本）
            if owner_user_id is None:
                # version 递增即快照（复用发布路径的保留窗口清理），覆盖可回滚
                await self._snapshot_revision(
                    conn,
                    agent_id=agent_id,
                    doc_type=doc_type,
                    environment=env,
                    version=int(row["version"]),
                    content=content,
                    updated_by=updated_by,
                    now=now,
                )
            return True

    async def upsert_documents(
        self,
        agent_id: str,
        documents: dict[str, str],
        *,
        environment: str | None = None,
        updated_by: str | None = None,
    ) -> int:
        """Upsert a batch of documents in one transaction.

        每个内容变化的文档在同事务内快照一个 revision（复用保留窗口清理），
        使批量覆盖写也可回滚。``documents`` maps doc_type → content. Returns
        the number of rows actually written (inserts + content changes).
        """
        from datetime import datetime, timezone

        from sqlalchemy import text

        env = environment or environment_for_agent(agent_id)
        now = datetime.now(timezone.utc)
        written = 0
        async with self._engine.begin() as conn:
            for doc_type, content in documents.items():
                result = await conn.execute(
                    text(
                        "INSERT INTO agent_documents (tenant_id, agent_id, "
                        "doc_type, environment, content, content_hash, "
                        "version, updated_by, created_at, updated_at) "
                        "VALUES (:tid, :aid, :dtype, :env, "
                        "CAST(:content AS TEXT), :chash, 1, :uby, :now, :now) "
                        "ON CONFLICT (tenant_id, agent_id, doc_type, "
                        "environment, (COALESCE(owner_user_id, ''))) "
                        "DO UPDATE SET "
                        "content = EXCLUDED.content, "
                        "content_hash = EXCLUDED.content_hash, "
                        "version = agent_documents.version + 1, "
                        "updated_by = EXCLUDED.updated_by, "
                        "updated_at = EXCLUDED.updated_at "
                        "WHERE agent_documents.content_hash "
                        "IS DISTINCT FROM EXCLUDED.content_hash "
                        "RETURNING version"
                    ),
                    {
                        "tid": self._tenant_id,
                        "aid": agent_id,
                        "dtype": doc_type,
                        "env": env,
                        "content": content,
                        "chash": content_hash(content),
                        "uby": updated_by,
                        "now": now,
                    },
                )
                row = result.mappings().first()
                if row is None:
                    # 内容未变：幂等重放，不计数、不写快照
                    continue
                written += 1
                # version 递增即快照（同事务，复用保留窗口清理）
                await self._snapshot_revision(
                    conn,
                    agent_id=agent_id,
                    doc_type=doc_type,
                    environment=env,
                    version=int(row["version"]),
                    content=content,
                    updated_by=updated_by,
                    now=now,
                )
        return written

    async def _snapshot_revision(
        self,
        conn: Any,
        *,
        agent_id: str,
        doc_type: str,
        environment: str,
        version: int,
        content: str,
        updated_by: str | None,
        now: Any,
    ) -> None:
        """在调用方事务内快照一个不可变版本并惰性清理超出保留窗口的旧版本。

        所有 version 递增路径（影子 upsert / 权威 promote / 回填种子）共用本
        助手，保证「全量变更快照」口径一致、覆盖可回滚。版本号冲突时让位
        （DO NOTHING）绝不阻断主写入；随后仅保留最近 ``REVISION_RETENTION``
        个版本，控制快照表体量。
        """
        from sqlalchemy import text

        # 不可变版本快照（同版本号冲突时让位，不阻断主流程）
        await conn.execute(
            text(
                "INSERT INTO agent_document_revisions (tenant_id, "
                "agent_id, doc_type, environment, version, content, "
                "content_hash, published_by, published_at) "
                "VALUES (:tid, :aid, :dtype, :env, :ver, "
                "CAST(:content AS TEXT), :chash, :uby, :now) "
                "ON CONFLICT (tenant_id, agent_id, doc_type, "
                "environment, version) DO NOTHING"
            ),
            {
                "tid": self._tenant_id,
                "aid": agent_id,
                "dtype": doc_type,
                "env": environment,
                "ver": version,
                "content": content,
                "chash": content_hash(content),
                "uby": updated_by,
                "now": now,
            },
        )
        # 保留窗口惰性清理：仅保留最近 REVISION_RETENTION 个版本
        await conn.execute(
            text(
                "DELETE FROM agent_document_revisions "
                "WHERE tenant_id = :tid AND agent_id = :aid "
                "AND doc_type = :dtype AND environment = :env "
                "AND version < (SELECT COALESCE(MIN(version), 0) FROM ( "
                "SELECT version FROM agent_document_revisions "
                "WHERE tenant_id = :tid AND agent_id = :aid "
                "AND doc_type = :dtype AND environment = :env "
                "ORDER BY version DESC LIMIT :keep) recent)"
            ),
            {
                "tid": self._tenant_id,
                "aid": agent_id,
                "dtype": doc_type,
                "env": environment,
                "keep": REVISION_RETENTION,
            },
        )

    # -- read path (Phase B seed) ------------------------------------------

    async def get_document(
        self,
        agent_id: str,
        doc_type: str,
        *,
        environment: str | None = None,
        owner_user_id: str | None = None,
    ) -> Optional[dict]:
        """Return one document row (content/version/...) or None.

        ``owner_user_id`` None → 共享行（``owner_user_id IS NULL``，绝不
        读到他人个人草稿）；非空 → 该用户的个人草稿行（environment 默认
        ``draft``）。
        """
        from sqlalchemy import text

        # 个人草稿行固定 draft 环境；共享行随 agent_id/显式参数分流
        if owner_user_id:
            env = environment or "draft"
        else:
            env = environment or environment_for_agent(agent_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT agent_id, doc_type, environment, owner_user_id, "
                    "content, content_hash, version, updated_by, created_at, "
                    "updated_at FROM agent_documents "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND doc_type = :dtype AND environment = :env "
                    "AND owner_user_id IS NOT DISTINCT FROM :owner"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "dtype": doc_type,
                    "env": env,
                    "owner": owner_user_id,
                },
            )
            row = result.mappings().first()
        if row is None:
            return None
        # text() 结果无类型上下文：时间列原样返回（ISO 字符串）
        return {key: str(value) for key, value in dict(row).items()}

    async def list_documents(
        self,
        agent_id: str,
        *,
        environment: str | None = None,
        owner_user_id: str | None = None,
    ) -> list[dict]:
        """List all documents of one agent (optionally per environment).

        默认仅共享行（owner IS NULL）；``owner_user_id`` 非空时列该用户
        的个人草稿行（environment 默认 ``draft``）。
        """
        from sqlalchemy import text

        # 个人草稿行固定 draft 环境；共享行随 agent_id/显式参数分流
        if owner_user_id:
            env = environment or "draft"
        else:
            env = environment or environment_for_agent(agent_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT agent_id, doc_type, environment, owner_user_id, "
                    "content, content_hash, version, updated_by, created_at, "
                    "updated_at FROM agent_documents "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND environment = :env "
                    "AND owner_user_id IS NOT DISTINCT FROM :owner "
                    "ORDER BY doc_type"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "env": env,
                    "owner": owner_user_id,
                },
            )
            rows = result.mappings().all()
        return [
            {key: str(value) for key, value in dict(row).items()}
            for row in rows
        ]

    async def list_personal_drafts(
        self,
        agent_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> list[dict]:
        """List personal draft rows of one agent (S2 个人草稿平面)。

        仅返回草稿行（``owner_user_id IS NOT NULL`` + environment=draft）；
        ``owner_user_id`` 非空时限定单个用户（「我的草稿」），None 时列
        全部用户（admin 待应用列表）。按 ``updated_at`` 降序。
        """
        from sqlalchemy import text

        owner_clause = "AND owner_user_id = :owner" if owner_user_id else ""
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT agent_id, doc_type, environment, owner_user_id, "
                    "version, content_hash, updated_by, created_at, "
                    "updated_at FROM agent_documents "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND environment = 'draft' "
                    "AND owner_user_id IS NOT NULL "
                    f"{owner_clause} "
                    "ORDER BY updated_at DESC"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "owner": owner_user_id,
                },
            )
            rows = result.mappings().all()
        return [
            {key: str(value) for key, value in dict(row).items()}
            for row in rows
        ]

    async def promote(
        self,
        agent_id: str,
        doc_type: str,
        content: str,
        *,
        environment: str = "production",
        updated_by: str | None = None,
    ) -> Optional[int]:
        """Authoritatively publish one document + snapshot a revision.

        Single transaction: upsert the authoritative row (version bumps
        only on content change), insert an immutable revision snapshot,
        then lazily trim revisions beyond ``REVISION_RETENTION``.

        Returns the new version number, or ``None`` when the content was
        unchanged (idempotent replay — no revision is written).
        """
        from datetime import datetime, timezone

        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        async with self._engine.begin() as conn:
            # 幂等 upsert：内容未变时 WHERE 拦截 → RETURNING 空集
            result = await conn.execute(
                text(
                    "INSERT INTO agent_documents (tenant_id, agent_id, "
                    "doc_type, environment, content, content_hash, version, "
                    "updated_by, created_at, updated_at) "
                    "VALUES (:tid, :aid, :dtype, :env, "
                    "CAST(:content AS TEXT), "
                    ":chash, 1, :uby, :now, :now) "
                    "ON CONFLICT (tenant_id, agent_id, doc_type, "
                    "environment, (COALESCE(owner_user_id, ''))) "
                    "DO UPDATE SET content = EXCLUDED.content, "
                    "content_hash = EXCLUDED.content_hash, "
                    "version = agent_documents.version + 1, "
                    "updated_by = EXCLUDED.updated_by, "
                    "updated_at = EXCLUDED.updated_at "
                    "WHERE agent_documents.content_hash "
                    "IS DISTINCT FROM EXCLUDED.content_hash "
                    "RETURNING version"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "dtype": doc_type,
                    "env": environment,
                    "content": content,
                    "chash": content_hash(content),
                    "uby": updated_by,
                    "now": now,
                },
            )
            row = result.mappings().first()
            if row is None:
                # 内容未变：不写 revision（幂等重放）
                return None
            version = int(row["version"])
            # version 递增即快照 + 保留窗口惰性清理（与 upsert 路径共用助手）
            await self._snapshot_revision(
                conn,
                agent_id=agent_id,
                doc_type=doc_type,
                environment=environment,
                version=version,
                content=content,
                updated_by=updated_by,
                now=now,
            )
        return version

    async def get_revision(
        self,
        agent_id: str,
        doc_type: str,
        version: int,
        *,
        environment: str = "production",
    ) -> Optional[dict]:
        """Return one revision snapshot (with content) or None."""
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT agent_id, doc_type, environment, version, "
                    "content, content_hash, published_by, published_at "
                    "FROM agent_document_revisions "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND doc_type = :dtype AND environment = :env "
                    "AND version = :ver"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "dtype": doc_type,
                    "env": environment,
                    "ver": version,
                },
            )
            row = result.mappings().first()
        if row is None:
            return None
        result = {key: str(value) for key, value in dict(row).items()}
        # text() 无类型上下文：version 显式回 int（API/前端语义）
        result["version"] = int(result["version"])
        return result

    async def list_revisions(
        self,
        agent_id: str,
        doc_type: str,
        *,
        environment: str = "production",
        limit: int = 50,
    ) -> list[dict]:
        """List revision snapshots of one document (newest first)."""
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT version, content_hash, published_by, "
                    "published_at FROM agent_document_revisions "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND doc_type = :dtype AND environment = :env "
                    "ORDER BY version DESC LIMIT :lim"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "dtype": doc_type,
                    "env": environment,
                    "lim": limit,
                },
            )
            rows = result.mappings().all()
        results = []
        for row in rows:
            item = {key: str(value) for key, value in dict(row).items()}
            # version 显式回 int（API/前端语义）
            item["version"] = int(item["version"])
            results.append(item)
        return results


_store: Optional[AgentDocsStore] = None

#: fire-and-forget 影子写任务的存活集合（防任务被 GC，同 dual_session_store）
_shadow_tasks: set[asyncio.Task] = set()
#: 同步上下文兜底提交的存活 future 集合（防 GC）
_shadow_futures: set[Any] = set()
#: 影子写失败计数（观测指标；主链路不受影响）
shadow_write_failures = 0

#: 同步上下文兜底用的单例后台事件循环（daemon 线程，惰性启动）
_background_loop: Optional[asyncio.AbstractEventLoop] = None
_background_loop_lock = threading.Lock()


def get_agent_docs_store() -> Optional[AgentDocsStore]:
    """Return the shared store; ``None`` when PostgreSQL is not configured."""
    global _store  # pylint: disable=global-statement
    if _store is not None:
        return _store
    from ...db.engine import get_pg_dsn

    if not get_pg_dsn():
        return None
    _store = AgentDocsStore()
    return _store


def _get_background_loop() -> asyncio.AbstractEventLoop:
    """Return the shared daemon background loop (lazy-start, thread-safe).

    CLI 等同步上下文没有 running loop，影子写经此后台循环提交，
    保证「任何进程内的档案写入都能落到 PG」不因调用方式静默丢失。
    """
    global _background_loop  # pylint: disable=global-statement
    loop = _background_loop
    if loop is not None and loop.is_running():
        return loop
    with _background_loop_lock:
        if _background_loop is not None and _background_loop.is_running():
            return _background_loop

        def _run() -> None:
            global _background_loop  # pylint: disable=global-statement
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            _background_loop = new_loop
            new_loop.run_forever()

        threading.Thread(
            target=_run,
            daemon=True,
            name="agent-docs-shadow",
        ).start()
        while _background_loop is None or not _background_loop.is_running():
            time.sleep(0.005)
        return _background_loop


def shadow_write_document(
    agent_id: str,
    filename: str,
    content: str,
    *,
    updated_by: str | None = None,
) -> None:
    """Mirror one identity-file write into PG; fire-and-forget, never raises.

    ``filename`` is the workspace file name (e.g. ``PROFILE.md``); unknown
    names are silently ignored so non-identity files never reach the table.
    """
    doc_type = DOC_TYPE_BY_FILENAME.get(filename)
    if doc_type is None:
        return
    store = get_agent_docs_store()
    if store is None:
        return

    async def _run() -> None:
        global shadow_write_failures  # pylint: disable=global-statement
        try:
            await store.upsert_document(
                agent_id,
                doc_type,
                content,
                updated_by=updated_by,
            )
        except Exception as exc:  # noqa: BLE001 - 影子写绝不影响主链路
            shadow_write_failures += 1
            logger.warning(
                "Agent docs shadow write failed (primary unaffected): "
                "agent=%s doc=%s: %s",
                agent_id,
                doc_type,
                exc,
            )

    try:
        task = asyncio.get_running_loop().create_task(_run())
        _shadow_tasks.add(task)
        task.add_done_callback(_shadow_tasks.discard)
    except RuntimeError:
        # 无事件循环（CLI 等同步上下文）：经共享后台循环兜底提交，
        # 保证影子写不因调用方式静默丢失；兜底本身失败只计数告警。
        try:
            future = asyncio.run_coroutine_threadsafe(
                _run(),
                _get_background_loop(),
            )
            _shadow_futures.add(future)
            future.add_done_callback(_shadow_futures.discard)
        except Exception as exc:  # noqa: BLE001 - 影子写绝不影响主链路
            shadow_write_failures += 1
            logger.warning(
                "Agent docs shadow write sync-fallback failed (primary "
                "unaffected): agent=%s doc=%s: %s",
                agent_id,
                doc_type,
                exc,
            )


async def promote_documents(
    agent_id: str,
    documents: dict[str, str],
    *,
    environment: str = "production",
    updated_by: str | None = None,
) -> bool:
    """Authoritatively promote documents to PG + snapshot revisions.

    这是发布/回滚等「生产闸门」动作的统一入口：逐文档调
    ``AgentDocsStore.promote``（幂等，内容未变不产生新版本）。

    Returns:
        True 当 PG 可用且全部执行完成（含幂等重放）；False 当 PG
        未配置（调用方决定降级行为）。单个文档异常向上抛出。
    """
    store = get_agent_docs_store()
    if store is None:
        return False
    for doc_type, content in documents.items():
        # 非白名单类型拒绝入库（与文件名白名单同一防线）
        if doc_type not in VALID_DOC_TYPES:
            continue
        await store.promote(
            agent_id,
            doc_type,
            content,
            environment=environment,
            updated_by=updated_by,
        )
    return True
