# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from ..constant import WORKING_DIR
from ..utils.io_utils import read_json, run_sync_io, write_json_atomic

logger = logging.getLogger(__name__)

_INBOX_PATH = WORKING_DIR / "inbox_events.json"
_LOCK = asyncio.Lock()
_MAX_EVENTS = 5000


# ---------------------------------------------------------------------------
# PG 权威平面（QWENPAW_STORAGE_BACKEND=dual/pg 时启用）
#
# 架构契约（与 app/crons/repo/pg_repo.py 同一范式）：
# - PG 是唯一权威源；inbox_events.json 仅作为首次启用的一次性
#   backfill 种子（lifespan 启动钩子显式触发，见 initialize()）；
# - 运行期读路径纯读，永不隐式回填——否则运行期“表空”会把投影
#   文件回灌权威，已读/删除状态被“复活”（crons 平面已踩过的
#   自激振荡缺陷，绝不重犯）；
# - 读失败降级读文件（只读无分叉风险），写失败仅告警（投影文件
#   已清空，降级写文件只会制造无读方的孤儿数据）。
# ---------------------------------------------------------------------------


def _pg_plane_available() -> bool:
    """True when dual/pg backend is active with a configured DSN.

    M2 收敛：判定统一下沉到 ``db.write_gateway``（此前在 provider/
    inbox 各自复制一份同语义实现），本函数保留私有名供既有测试
    monkeypatch 与域内分派头使用。
    """
    from ..db import write_gateway

    try:
        return write_gateway.pg_write_available()
    except Exception:  # noqa: BLE001 - 依赖缺失一律按文件平面
        return False


def _row_to_event(row) -> dict[str, Any]:
    """One inbox_events row -> event dict（json 文件协议字段不变）。"""
    payload = row["payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    return {
        "id": row["event_id"],
        "agent_id": row["agent_id"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "event_type": row["event_type"],
        "status": row["status"],
        "severity": row["severity"],
        "title": row["title"],
        "body": row["body"],
        "payload": payload if isinstance(payload, dict) else {},
        "read": bool(row["is_read"]),
        "created_at": float(row["created_at"] or 0.0),
    }


def _pg_filter_clauses(
    *,
    source_type: str | None = None,
    source_types: set[str] | None = None,
    status: str | None = None,
    agent_id: str | None = None,
    unread_only: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    """Build WHERE clauses shared by the list/query PG readers."""
    from ..db.base import DEFAULT_TENANT_ID

    clauses = ["tenant_id = :tenant_id"]
    params: dict[str, Any] = {"tenant_id": DEFAULT_TENANT_ID}
    if source_type:
        clauses.append("source_type = :source_type")
        params["source_type"] = source_type
    if source_types:
        clauses.append("source_type = ANY(:source_types)")
        params["source_types"] = sorted(source_types)
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if agent_id:
        clauses.append("agent_id = :agent_id")
        params["agent_id"] = agent_id
    if unread_only:
        clauses.append("is_read = FALSE")
    return clauses, params


_EVENT_COLS = (
    "event_id, agent_id, source_type, source_id, event_type, "
    "status, severity, title, body, payload, is_read, created_at"
)

_INSERT_EVENT_SQL = """
INSERT INTO inbox_events (
    tenant_id, event_id, agent_id, source_type, source_id,
    event_type, status, severity, title, body, payload,
    is_read, created_at
) VALUES (
    :tenant_id, :event_id, :agent_id, :source_type, :source_id,
    :event_type, :status, :severity, :title, :body,
    CAST(:payload AS JSONB), :is_read, :created_at
)
ON CONFLICT (tenant_id, event_id) DO NOTHING
"""

_PRUNE_EVENTS_SQL = """
DELETE FROM inbox_events
WHERE tenant_id = :tenant_id
  AND id NOT IN (
      SELECT id FROM inbox_events
      WHERE tenant_id = :tenant_id
      ORDER BY id DESC
      LIMIT :max_events
  )
"""

_DELETE_EVENT_SQL = """
DELETE FROM inbox_events
WHERE tenant_id = :tenant_id AND event_id = :event_id
RETURNING payload->>'run_id' AS run_id
"""

_COUNT_RUN_REFS_SQL = """
SELECT count(*) FROM inbox_events
WHERE tenant_id = :tenant_id AND payload->>'run_id' = :run_id
"""


def _load_events() -> list[dict[str, Any]]:
    if not _INBOX_PATH.exists():
        return []
    try:
        data = read_json(_INBOX_PATH)
    except (ValueError, OSError) as exc:
        # Corrupted or unreadable inbox file — treat as empty rather than
        # crashing every subsequent read. The next append_event will
        # atomically replace the file with a valid payload. Log the
        # error so permission/disk-full issues are not silently lost.
        logger.warning(
            "Failed to load inbox events from %s: %s",
            _INBOX_PATH,
            exc,
        )
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _save_events(events: list[dict[str, Any]]) -> None:
    write_json_atomic(
        _INBOX_PATH,
        events,
        sort_keys=True,
    )


async def append_event(
    *,
    agent_id: str | None,
    source_type: str,
    source_id: str | None,
    event_type: str,
    status: str,
    title: str,
    body: str,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "id": str(uuid.uuid4()),
        "agent_id": agent_id or "default",
        "source_type": source_type,
        "source_id": source_id or "",
        "event_type": event_type,
        "status": status,
        "severity": severity,
        "title": title,
        "body": body,
        "payload": payload or {},
        "read": False,
        "created_at": time.time(),
    }
    if _pg_plane_available():
        try:
            await _pg_append_event(event)
        except Exception:  # noqa: BLE001 - 写失败仅告警，绝不阻塞业务
            logger.warning(
                "inbox PG append failed; event not persisted",
                exc_info=True,
            )
        return event
    async with _LOCK:
        events = await run_sync_io(_load_events)
        events.insert(0, event)
        del events[_MAX_EVENTS:]
        await run_sync_io(_save_events, events)
    return event


async def list_events(
    *,
    limit: int = 50,
    offset: int = 0,
    source_type: str | None = None,
    status: str | None = None,
    agent_id: str | None = None,
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    if _pg_plane_available():
        try:
            return await _pg_list_events(
                limit=limit,
                offset=offset,
                source_type=source_type,
                status=status,
                agent_id=agent_id,
                unread_only=unread_only,
            )
        except Exception:  # noqa: BLE001 - 读失败降级文件平面
            logger.warning(
                "inbox PG read failed; falling back to file",
                exc_info=True,
            )
    async with _LOCK:
        events = await run_sync_io(_load_events)
    if source_type:
        events = [
            event
            for event in events
            if event.get("source_type") == source_type
        ]
    if status:
        events = [event for event in events if event.get("status") == status]
    if agent_id:
        events = [
            event for event in events if event.get("agent_id") == agent_id
        ]
    if unread_only:
        events = [event for event in events if not bool(event.get("read"))]
    return events[offset : offset + max(limit, 0)]


async def query_events(
    *,
    limit: int = 50,
    offset: int = 0,
    source_types: set[str] | None = None,
    status: str | None = None,
    agent_id: str | None = None,
    unread_only: bool = False,
) -> tuple[list[dict[str, Any]], int, int]:
    """Return a filtered page with exact total and unread counts."""
    if _pg_plane_available():
        try:
            return await _pg_query_events(
                limit=limit,
                offset=offset,
                source_types=source_types,
                status=status,
                agent_id=agent_id,
                unread_only=unread_only,
            )
        except Exception:  # noqa: BLE001 - 读失败降级文件平面
            logger.warning(
                "inbox PG query failed; falling back to file",
                exc_info=True,
            )
    async with _LOCK:
        events = await run_sync_io(_load_events)
    if source_types:
        events = [
            event
            for event in events
            if event.get("source_type") in source_types
        ]
    if status:
        events = [event for event in events if event.get("status") == status]
    if agent_id:
        events = [
            event for event in events if event.get("agent_id") == agent_id
        ]
    unread_count = sum(not bool(event.get("read")) for event in events)
    if unread_only:
        events = [event for event in events if not bool(event.get("read"))]
    total = len(events)
    page = events[offset : offset + max(limit, 0)]
    return page, total, unread_count


async def mark_read(event_ids: list[str]) -> int:
    if not event_ids:
        return 0
    if _pg_plane_available():
        try:
            return await _pg_mark_read(event_ids)
        except Exception:  # noqa: BLE001 - 写失败仅告警
            logger.warning(
                "inbox PG mark-read failed",
                exc_info=True,
            )
            return 0
    event_id_set = set(event_ids)
    updated = 0
    async with _LOCK:
        events = await run_sync_io(_load_events)
        for event in events:
            if event.get("id") in event_id_set and not bool(event.get("read")):
                event["read"] = True
                updated += 1
        await run_sync_io(_save_events, events)
    return updated


async def mark_all_read() -> int:
    if _pg_plane_available():
        try:
            return await _pg_mark_all_read()
        except Exception:  # noqa: BLE001 - 写失败仅告警
            logger.warning(
                "inbox PG mark-all-read failed",
                exc_info=True,
            )
            return 0
    updated = 0
    async with _LOCK:
        events = await run_sync_io(_load_events)
        for event in events:
            if not bool(event.get("read")):
                event["read"] = True
                updated += 1
        await run_sync_io(_save_events, events)
    return updated


async def mark_read_by_acl_sender(agent_id: str, sender_address: str) -> int:
    """Mark matching unread ACL-pending events for one agent as read.

    Called when the user approves / denies / dismisses an ACL pending sender
    so the corresponding notification is cleared from the unread count.
    """
    needle = (sender_address or "").lower().strip()
    if not agent_id or not needle:
        return 0
    if _pg_plane_available():
        try:
            return await _pg_mark_read_by_acl_sender(agent_id, needle)
        except Exception:  # noqa: BLE001 - 写失败仅告警
            logger.warning(
                "inbox PG acl mark-read failed",
                exc_info=True,
            )
            return 0
    updated = 0
    async with _LOCK:
        events = await run_sync_io(_load_events)
        for event in events:
            if bool(event.get("read")):
                continue
            if event.get("agent_id") != agent_id:
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("acl_status") != "pending":
                continue
            event_sender = payload.get("acl_sender_address")
            if not isinstance(event_sender, str):
                continue
            if event_sender.lower().strip() == needle:
                event["read"] = True
                updated += 1
        if updated:
            await run_sync_io(_save_events, events)
    return updated


async def delete_event(event_id: str) -> tuple[bool, str | None, bool]:
    if not event_id:
        return False, None, False
    if _pg_plane_available():
        try:
            return await _pg_delete_event(event_id)
        except Exception:  # noqa: BLE001 - 写失败仅告警
            logger.warning(
                "inbox PG delete failed",
                exc_info=True,
            )
            return False, None, False
    deleted = False
    deleted_run_id: str | None = None
    run_id_still_referenced = False
    async with _LOCK:
        events = await run_sync_io(_load_events)
        kept_events = []
        for event in events:
            if not deleted and event.get("id") == event_id:
                payload = event.get("payload") or {}
                if isinstance(payload, dict) and isinstance(
                    payload.get("run_id"),
                    str,
                ):
                    deleted_run_id = payload.get("run_id")
                deleted = True
                continue
            kept_events.append(event)
        if deleted and deleted_run_id:
            for event in kept_events:
                payload = event.get("payload") or {}
                if (
                    isinstance(payload, dict)
                    and payload.get("run_id") == deleted_run_id
                ):
                    run_id_still_referenced = True
                    break
        if deleted:
            await run_sync_io(_save_events, kept_events)
    return deleted, deleted_run_id, run_id_still_referenced


# ---------------------------------------------------------------------------
# PG 平面实现（dual/pg 后端的权威读写；json 分支仅作降级读源）
# ---------------------------------------------------------------------------


async def _pg_append_event(event: dict[str, Any]) -> None:
    """Insert one event then prune beyond the retention window."""
    from sqlalchemy import text

    from ..db.base import DEFAULT_TENANT_ID
    from ..db.engine import create_pg_engine

    engine = create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(_INSERT_EVENT_SQL),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "event_id": event["id"],
                "agent_id": event["agent_id"],
                "source_type": event["source_type"],
                "source_id": event["source_id"],
                "event_type": event["event_type"],
                "status": event["status"],
                "severity": event["severity"],
                "title": event["title"],
                "body": event["body"],
                "payload": json.dumps(
                    event["payload"],
                    ensure_ascii=False,
                ),
                "is_read": bool(event["read"]),
                "created_at": float(event["created_at"]),
            },
        )
        await conn.execute(
            text(_PRUNE_EVENTS_SQL),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "max_events": _MAX_EVENTS,
            },
        )


async def _pg_list_events(
    *,
    limit: int,
    offset: int,
    source_type: str | None,
    status: str | None,
    agent_id: str | None,
    unread_only: bool,
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    clauses, params = _pg_filter_clauses(
        source_type=source_type,
        status=status,
        agent_id=agent_id,
        unread_only=unread_only,
    )
    params["limit"] = max(limit, 0)
    params["offset"] = max(offset, 0)
    engine = create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT "
                + _EVENT_COLS
                + " FROM inbox_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        )
        rows = [dict(r) for r in result.mappings()]
    return [_row_to_event(row) for row in rows]


async def _pg_query_events(
    *,
    limit: int,
    offset: int,
    source_types: set[str] | None,
    status: str | None,
    agent_id: str | None,
    unread_only: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    """Filtered page + exact total/unread counts (two reads, one conn)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    clauses, params = _pg_filter_clauses(
        source_types=source_types,
        status=status,
        agent_id=agent_id,
        unread_only=unread_only,
    )
    where = " AND ".join(clauses)
    engine = create_pg_engine()
    async with engine.connect() as conn:
        count_result = await conn.execute(
            text(
                "SELECT count(*) AS total, "
                "count(*) FILTER (WHERE NOT is_read) AS unread "
                "FROM inbox_events WHERE " + where
            ),
            params,
        )
        counts = count_result.mappings().first()
        page_params = dict(params)
        page_params["limit"] = max(limit, 0)
        page_params["offset"] = max(offset, 0)
        page_result = await conn.execute(
            text(
                "SELECT "
                + _EVENT_COLS
                + " FROM inbox_events WHERE "
                + where
                + " ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            page_params,
        )
        rows = [dict(r) for r in page_result.mappings()]
    total = int(counts["total"]) if counts else 0
    unread = int(counts["unread"]) if counts else 0
    return [_row_to_event(row) for row in rows], total, unread


async def _pg_mark_read(event_ids: list[str]) -> int:
    from sqlalchemy import text

    from ..db.base import DEFAULT_TENANT_ID
    from ..db.engine import create_pg_engine

    engine = create_pg_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE inbox_events SET is_read = TRUE, "
                "updated_at = now() WHERE tenant_id = :tenant_id "
                "AND is_read = FALSE AND event_id = ANY(:event_ids)"
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "event_ids": list(event_ids),
            },
        )
        return result.rowcount or 0


async def _pg_mark_all_read() -> int:
    from sqlalchemy import text

    from ..db.base import DEFAULT_TENANT_ID
    from ..db.engine import create_pg_engine

    engine = create_pg_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE inbox_events SET is_read = TRUE, "
                "updated_at = now() WHERE tenant_id = :tenant_id "
                "AND is_read = FALSE"
            ),
            {"tenant_id": DEFAULT_TENANT_ID},
        )
        return result.rowcount or 0


async def _pg_mark_read_by_acl_sender(agent_id: str, needle: str) -> int:
    """Clear unread ACL-pending events for one sender (approval flow)."""
    from sqlalchemy import text

    from ..db.base import DEFAULT_TENANT_ID
    from ..db.engine import create_pg_engine

    engine = create_pg_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE inbox_events SET is_read = TRUE, "
                "updated_at = now() WHERE tenant_id = :tenant_id "
                "AND is_read = FALSE AND agent_id = :agent_id "
                "AND payload->>'acl_status' = 'pending' "
                "AND lower(payload->>'acl_sender_address') = :needle"
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "needle": needle,
            },
        )
        return result.rowcount or 0


async def _pg_delete_event(event_id: str) -> tuple[bool, str | None, bool]:
    """Delete one event; report its run_id and remaining references."""
    from sqlalchemy import text

    from ..db.base import DEFAULT_TENANT_ID
    from ..db.engine import create_pg_engine

    engine = create_pg_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(_DELETE_EVENT_SQL),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "event_id": event_id,
            },
        )
        row = result.mappings().first()
        if row is None:
            return False, None, False
        run_id = row["run_id"]
        referenced = False
        if run_id:
            count_result = await conn.execute(
                text(_COUNT_RUN_REFS_SQL),
                {
                    "tenant_id": DEFAULT_TENANT_ID,
                    "run_id": run_id,
                },
            )
            referenced = int(count_result.scalar() or 0) > 0
    return True, run_id, referenced


async def initialize() -> None:
    """One-time startup migration hook: seed PG from the legacy file.

    必须由 lifespan 显式调用且先于任何运行期读写。backfill 绝不
    挂在读路径：运行期“表空”是删除/修剪后的合法状态，若在读路径
    隐式回填，投影文件会把旧数据回灌权威，已读/删除状态被“复活”
    （crons 平面已验证过的自激振荡缺陷，绝不重犯）。
    """
    if not _pg_plane_available():
        return
    from sqlalchemy import text

    from ..db.base import DEFAULT_TENANT_ID
    from ..db.engine import create_pg_engine

    engine = create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT count(*) FROM inbox_events "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": DEFAULT_TENANT_ID},
        )
        existing = int(result.scalar() or 0)
    if existing:
        return
    await _migrate_json_file_to_pg(engine)


async def _migrate_json_file_to_pg(engine: Any) -> None:
    """Seed PG from the legacy json file once, then clear the file.

    “文件→库”方向只允许发生这一次：成功后重写种子文件为空平面，
    即便未来有人误把回填挂到读路径，也没有旧数据可供“复活”。
    导入为 DO NOTHING 幂等，中途失败保留文件下次启动重试。
    """
    from sqlalchemy import text

    from ..db.base import DEFAULT_TENANT_ID

    legacy = await run_sync_io(_load_events)
    if not legacy:
        return
    async with engine.begin() as conn:
        await conn.execute(
            text(_INSERT_EVENT_SQL),
            [
                {
                    "tenant_id": DEFAULT_TENANT_ID,
                    "event_id": str(item.get("id") or uuid.uuid4()),
                    "agent_id": str(
                        item.get("agent_id") or "default",
                    ),
                    "source_type": str(item.get("source_type") or ""),
                    "source_id": str(item.get("source_id") or ""),
                    "event_type": str(item.get("event_type") or ""),
                    "status": str(item.get("status") or ""),
                    "severity": str(item.get("severity") or "info"),
                    "title": str(item.get("title") or ""),
                    "body": str(item.get("body") or ""),
                    "payload": json.dumps(
                        item.get("payload")
                        if isinstance(item.get("payload"), dict)
                        else {},
                        ensure_ascii=False,
                    ),
                    "is_read": bool(item.get("read")),
                    "created_at": float(item.get("created_at") or 0.0),
                }
                for item in legacy
            ],
        )
    # 关键收尾：把种子文件重写为空平面（防“复活”的最终防线）
    await run_sync_io(_save_events, [])
    logger.warning(
        "inbox backfill done: imported=%d from %s "
        "(PG is now authoritative; seed file cleared)",
        len(legacy),
        _INBOX_PATH,
    )
