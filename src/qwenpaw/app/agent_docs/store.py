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


_store: Optional[AgentDocsStore] = None

#: fire-and-forget 影子写任务的存活集合（防任务被 GC，同 dual_session_store）
_shadow_tasks: set[asyncio.Task] = set()
#: 影子写失败计数（观测指标；主链路不受影响）
shadow_write_failures = 0


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
    except RuntimeError:
        # 无事件循环（同步上下文）：影子写只服务异步主链路，静默跳过
        return
    _shadow_tasks.add(task)
    task.add_done_callback(_shadow_tasks.discard)
