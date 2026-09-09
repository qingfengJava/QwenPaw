# -*- coding: utf-8 -*-
"""One-time backfill: migrate legacy SQLite ``history.db`` rows to PostgreSQL.

SQLite 退役专项（Phase A→B）：``QWENPAW_STORAGE_BACKEND`` 默认切到 ``dual``
后，新对话轮次已实时影子写入 ``history_entries``；本工具把切换前残留在各
工作区 SQLite ``history.db`` 里的历史轮次一次性搬进 PG，使读切换（``pg``）
不丢数据。

幂等设计（参照 ``agents/context/scroll/sync.py`` 的 ``.synced.json`` 范式）：

- 每个工作区完成后写入 ``.pg_backfilled.json`` manifest，重复运行跳过；
- 带 ``dedup_key`` 的行走 ``ux_history_dedup`` 部分唯一索引
  ``ON CONFLICT DO NOTHING``，manifest 丢失也能安全重放；
- 无 ``dedup_key`` 的行（历史遗留）依赖 manifest 防重。

用法::

    python -m qwenpaw.db.backfill_history [--dry-run]

@author qingfeng
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

#: manifest 文件名（落在各工作区根目录）
MANIFEST_NAME = ".pg_backfilled.json"

#: 单批插入行数
_BATCH_SIZE = 500

_INSERT_SQL = """
INSERT INTO history_entries (tenant_id, session_id, agent_id, owner_id,
    kind, role, name, content, tool_call_id, tool_input, tool_state,
    headline, blocks, metadata, created_at, dedup_key)
VALUES (:tid, :session_id, :agent_id, :owner_id, :kind, :role, :name,
    :content, :tool_call_id,
    CAST(:tool_input AS JSONB), :tool_state, :headline,
    CAST(:blocks AS JSONB), CAST(:metadata AS JSONB),
    :created_at, :dedup_key)
ON CONFLICT (tenant_id, session_id, dedup_key) WHERE dedup_key IS NOT NULL
DO NOTHING
"""


def _iter_workspace_dirs() -> list[Path]:
    """Collect every agent workspace dir from the root config."""
    from ..config import load_config

    config = load_config()
    dirs: list[Path] = []
    for ref in config.agents.profiles.values():
        wd = getattr(ref, "workspace_dir", None)
        if wd:
            dirs.append(Path(wd).expanduser())
    return dirs


def _parse_ts(value: str | None) -> datetime | None:
    """SQLite ``created_at`` is an ISO text; parse defensively to UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _row_params(row: sqlite3.Row, tenant_id: str) -> dict:
    """Map one ``conversation_history`` row to the insert parameters."""
    return {
        "tid": tenant_id,
        "session_id": row["session_id"],
        "agent_id": row["agent_id"],
        "owner_id": row["owner_id"],
        "kind": row["kind"],
        "role": row["role"],
        "name": row["name"],
        "content": row["content"],
        "tool_call_id": row["tool_call_id"],
        # SQLite 侧 JSON 列以 TEXT 存放；空值原样传 None
        "tool_input": row["tool_input"],
        "tool_state": row["tool_state"],
        "headline": row["headline"],
        "blocks": row["blocks"],
        "metadata": row["metadata"],
        "created_at": _parse_ts(row["created_at"]),
        "dedup_key": row["dedup_key"],
    }


def _backfill_workspace(
    workspace_dir: Path,
    engine,
    tenant_id: str,
    dry_run: bool,
) -> int:
    """Migrate one workspace's history.db; returns migrated row count."""
    manifest = workspace_dir / MANIFEST_NAME
    if manifest.exists():
        return 0
    db_path = workspace_dir / "history.db"
    if not db_path.is_file():
        # 无 SQLite 的工作区也补 manifest，避免每次运行重复扫描
        if not dry_run:
            manifest.write_text(
                json.dumps({"rows": 0, "note": "no history.db"}),
                encoding="utf-8",
            )
        return 0

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT session_id, agent_id, owner_id, kind, role, name, "
            "content, tool_call_id, tool_input, tool_state, headline, "
            "blocks, metadata, created_at, dedup_key "
            "FROM conversation_history ORDER BY seq",
        ).fetchall()
    finally:
        conn.close()

    if dry_run:
        logger.info("[dry-run] %s: %d rows pending", db_path, len(rows))
        return 0

    migrated = 0

    async def _insert() -> None:
        nonlocal migrated
        from sqlalchemy import text

        for start in range(0, len(rows), _BATCH_SIZE):
            batch = [
                _row_params(row, tenant_id)
                for row in rows[start : start + _BATCH_SIZE]
            ]
            async with engine.begin() as pg_conn:
                result = await pg_conn.execute(
                    text(_INSERT_SQL),
                    batch,
                )
                migrated += result.rowcount or 0

    asyncio.run(_insert())

    manifest.write_text(
        json.dumps(
            {
                "rows": len(rows),
                "migrated": migrated,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info(
        "Backfilled %s: %d/%d rows into history_entries",
        workspace_dir,
        migrated,
        len(rows),
    )
    return migrated


def backfill_all(*, dry_run: bool = False) -> dict:
    """Migrate every agent workspace's SQLite history into PostgreSQL."""
    from ..app.enterprise import enterprise_engine

    if enterprise_engine() is None:
        raise SystemExit(
            "QWENPAW_PG_DSN is not configured — nothing to backfill. "
            "Configure PostgreSQL first (SQLite retirement requires it)."
        )
    from .engine import create_pg_engine
    from .base import DEFAULT_TENANT_ID

    tenant_id = DEFAULT_TENANT_ID
    engine = create_pg_engine()
    total = 0
    scanned = 0
    for workspace_dir in _iter_workspace_dirs():
        if not workspace_dir.is_dir():
            continue
        scanned += 1
        total += _backfill_workspace(
            workspace_dir,
            engine,
            tenant_id,
            dry_run,
        )
    summary = {"workspaces": scanned, "rows": total, "dry_run": dry_run}
    logger.info("Backfill summary: %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill legacy SQLite history.db into PostgreSQL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count pending rows without writing",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    backfill_all(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
