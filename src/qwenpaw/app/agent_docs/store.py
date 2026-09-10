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
    ) -> bool:
        """Upsert one document; bump ``version`` only on content change.

        Returns True when a row was written (insert or content change),
        False when an identical version already existed (idempotent replay).
        """
        from datetime import datetime, timezone

        from sqlalchemy import text

        env = environment or environment_for_agent(agent_id)
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO agent_documents (tenant_id, agent_id, "
                    "doc_type, environment, content, content_hash, version, "
                    "updated_by, created_at, updated_at) "
                    "VALUES (:tid, :aid, :dtype, :env, CAST(:content AS TEXT), "
                    ":chash, 1, :uby, :now, :now) "
                    "ON CONFLICT (tenant_id, agent_id, doc_type, environment) "
                    "DO UPDATE SET content = EXCLUDED.content, "
                    "content_hash = EXCLUDED.content_hash, "
                    "version = agent_documents.version + 1, "
                    "updated_by = EXCLUDED.updated_by, "
                    "updated_at = EXCLUDED.updated_at "
                    "WHERE agent_documents.content_hash "
                    "IS DISTINCT FROM EXCLUDED.content_hash"
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
            # rowcount 为 0 说明内容未变（WHERE 拦截），属幂等重放
            return (result.rowcount or 0) > 0

    async def upsert_documents(
        self,
        agent_id: str,
        documents: dict[str, str],
        *,
        environment: str | None = None,
        updated_by: str | None = None,
    ) -> int:
        """Upsert a batch of documents in one transaction.

        ``documents`` maps doc_type → content. Returns the number of rows
        actually written (inserts + content changes).
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
                        "environment) DO UPDATE SET "
                        "content = EXCLUDED.content, "
                        "content_hash = EXCLUDED.content_hash, "
                        "version = agent_documents.version + 1, "
                        "updated_by = EXCLUDED.updated_by, "
                        "updated_at = EXCLUDED.updated_at "
                        "WHERE agent_documents.content_hash "
                        "IS DISTINCT FROM EXCLUDED.content_hash"
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
                written += result.rowcount or 0
        return written

    # -- read path (Phase B seed) ------------------------------------------

    async def get_document(
        self,
        agent_id: str,
        doc_type: str,
        *,
        environment: str | None = None,
    ) -> Optional[dict]:
        """Return one document row (content/version/...) or None."""
        from sqlalchemy import text

        env = environment or environment_for_agent(agent_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT agent_id, doc_type, environment, content, "
                    "content_hash, version, updated_by, created_at, "
                    "updated_at FROM agent_documents "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND doc_type = :dtype AND environment = :env"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "dtype": doc_type,
                    "env": env,
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
    ) -> list[dict]:
        """List all documents of one agent (optionally per environment)."""
        from sqlalchemy import text

        env = environment or environment_for_agent(agent_id)
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT agent_id, doc_type, environment, content, "
                    "content_hash, version, updated_by, created_at, "
                    "updated_at FROM agent_documents "
                    "WHERE tenant_id = :tid AND agent_id = :aid "
                    "AND environment = :env ORDER BY doc_type"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "env": env,
                },
            )
            rows = result.mappings().all()
        return [
            {key: str(value) for key, value in dict(row).items()}
            for row in rows
        ]

    # -- publish plane (Phase B authoritative writes) ----------------------

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
                    "VALUES (:tid, :aid, :dtype, :env, CAST(:content AS TEXT), "
                    ":chash, 1, :uby, :now, :now) "
                    "ON CONFLICT (tenant_id, agent_id, doc_type, environment) "
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
