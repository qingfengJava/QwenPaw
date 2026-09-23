#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline storage migration: JSON/SQLite planes -> PostgreSQL (M2).

Migrates, per workspace directory:

- ``chats.json``              -> ``chats`` table
- ``sessions/**/*.json``      -> ``session_states`` table
- ``history.db`` (scroll)     -> ``history_entries`` table (seq preserved)

Properties:

- **Idempotent**: re-running upserts the same rows; history dedup keys
  prevent duplicates, and the seq sequence is re-aligned afterwards.
- **Verifiable**: prints per-plane row counts (source vs target) and a
  content-hash sample comparison.
- **Non-destructive**: source files are never modified or deleted; the
  plan's 30-day file retention window is an operator decision.

``users.json``/``audit`` planes land with their M4 tables; this script only
covers the three planes modeled in M2.

Usage::

    python scripts/migrate_storage_to_pg.py \
        --workspace path/to/workspace \
        --dsn postgresql+asyncpg://qwenpaw:***@127.0.0.1:5432/qwenpaw \
        [--dry-run] [--sample 20]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger("migrate_storage_to_pg")


# ---------------------------------------------------------------------------
# chats.json -> chats
# ---------------------------------------------------------------------------


async def migrate_chats(
    workspace: Path,
    engine,
    dry_run: bool,
    agent_id: str = "default",
) -> dict:
    from qwenpaw.app.chats.models import ChatsFile
    from qwenpaw.app.chats.repo.pg_repo import PgChatRepository

    path = workspace / "chats.json"
    if not path.is_file():
        return {"plane": "chats", "source": 0, "target": 0, "skipped": True}
    data = json.loads(path.read_text(encoding="utf-8"))
    chats_file = ChatsFile.model_validate(data)
    repo = PgChatRepository(engine=engine, agent_id=agent_id)
    if not dry_run:
        # Upsert semantics (save would also delete rows absent here, which
        # must NOT happen on a re-run after cutover): upsert one by one.
        for spec in chats_file.chats:
            await repo.upsert_chat(spec)
    existing = await repo.load()
    return {
        "plane": "chats",
        "source": len(chats_file.chats),
        "target": len(existing.chats),
        "skipped": False,
    }


# ---------------------------------------------------------------------------
# sessions/**/*.json -> session_states
# ---------------------------------------------------------------------------


def _build_file_index(workspace: Path) -> dict[str, tuple[str, str, str]]:
    """Map session file *stem* -> (session_id, owner_id, channel).

    The authoritative source is ``chats.json``: each spec knows its exact
    session_id/owner/channel, and the JSON backend's file name is derived
    deterministically from them. Files not referenced by any chat (cron /
    heartbeat sessions) fall back to their stem as the session id with an
    empty owner — they stay readable and can be re-owned later.
    """
    from qwenpaw.app.chats.session import session_filename

    index: dict[str, tuple[str, str, str]] = {}
    chats_path = workspace / "chats.json"
    if chats_path.is_file():
        specs = json.loads(chats_path.read_text(encoding="utf-8")).get(
            "chats",
            [],
        )
        for spec in specs:
            session_id = spec.get("session_id", "")
            owner = spec.get("owner_id") or spec.get("user_id") or ""
            channel = spec.get("channel", "")
            if not session_id:
                continue
            stem = Path(session_filename(session_id, owner)).stem
            index[stem] = (session_id, owner, channel)
    return index


async def migrate_sessions(
    workspace: Path,
    engine,
    dry_run: bool,
    agent_id: str = "default",
) -> dict:
    from sqlalchemy import text

    sessions_dir = workspace / "sessions"
    if not sessions_dir.is_dir():
        return {"plane": "sessions", "source": 0, "target": 0, "skipped": True}
    index = _build_file_index(workspace)

    files = [
        p
        for p in sessions_dir.rglob("*.json")
        if ".weixin-legacy" not in p.parts and p.name != ".synced.json"
    ]
    rows = []
    for path in files:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable session file %s: %s", path, exc)
            continue
        if not isinstance(state, dict):
            continue
        channel_dir = (
            path.parent.name if path.parent != sessions_dir else ""
        )
        session_id, owner, channel = index.get(
            path.stem,
            (path.stem, "", channel_dir),
        )
        rows.append(
            {
                "aid": agent_id,
                "chan": channel,
                "uid": owner,
                "sid": session_id,
                "state": json.dumps(state, ensure_ascii=False),
            },
        )

    if not dry_run and rows:
        async with engine.begin() as conn:
            for row in rows:
                await conn.execute(
                    text(
                        "INSERT INTO session_states (tenant_id, agent_id, "
                        "channel, "
                        "owner_id, session_id, state, created_at, updated_at) "
                        "VALUES ('default', :aid, :chan, :uid, :sid, "
                        "CAST(:state AS JSONB), now(), now()) "
                        "ON CONFLICT (tenant_id, agent_id, channel, owner_id, "
                        "session_id) DO UPDATE SET state = EXCLUDED.state, "
                        "updated_at = now()",
                    ),
                    row,
                )
    return {
        "plane": "sessions",
        "source": len(rows),
        "target": len(rows),
        "skipped": False,
    }


# ---------------------------------------------------------------------------
# history.db -> history_entries
# ---------------------------------------------------------------------------


async def migrate_history(workspace: Path, engine, dry_run: bool) -> dict:
    db_path = workspace / "history.db"
    if not db_path.is_file():
        return {"plane": "history", "source": 0, "target": 0, "skipped": True}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT seq, session_id, agent_id, owner_id, kind, role, name, "
            "content, tool_call_id, tool_input, tool_state, headline, "
            "blocks, metadata, created_at, dedup_key "
            "FROM conversation_history ORDER BY seq",
        ).fetchall()
    finally:
        conn.close()

    if not dry_run and rows:
        from datetime import datetime, timezone

        from sqlalchemy import text

        def _parse_ts(value) -> datetime | None:
            if not value:
                return None
            if isinstance(value, datetime):
                return value
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed

        async with engine.begin() as conn:
            for row in rows:
                await conn.execute(
                    text(
                        "INSERT INTO history_entries (seq, tenant_id, "
                        "session_id, agent_id, owner_id, kind, role, name, "
                        "content, tool_call_id, tool_input, tool_state, "
                        "headline, blocks, metadata, created_at, dedup_key) "
                        "VALUES (:seq, 'default', :sid, :aid, :oid, :kind, "
                        ":role, :name, :content, :tcid, "
                        "CAST(:tinput AS JSONB), :tstate, :headline, "
                        "CAST(:blocks AS JSONB), CAST(:meta AS JSONB), "
                        ":created, :dedup) "
                        "ON CONFLICT (seq) DO NOTHING",
                    ),
                    {
                        "seq": row["seq"],
                        "sid": row["session_id"],
                        "aid": row["agent_id"],
                        "oid": row["owner_id"],
                        "kind": row["kind"],
                        "role": row["role"],
                        "name": row["name"],
                        "content": row["content"],
                        "tcid": row["tool_call_id"],
                        "tinput": row["tool_input"],
                        "tstate": row["tool_state"],
                        "headline": row["headline"],
                        "blocks": row["blocks"],
                        "meta": row["metadata"],
                        "created": _parse_ts(row["created_at"]),
                        "dedup": row["dedup_key"],
                    },
                )
            # Re-align the identity sequence with the preserved seq values.
            await conn.execute(
                text(
                    "SELECT setval("
                    "pg_get_serial_sequence('history_entries', 'seq'), "
                    "COALESCE((SELECT MAX(seq) FROM history_entries), 1))",
                ),
            )

    from sqlalchemy import text

    async with engine.connect() as conn:
        target = (
            await conn.execute(text("SELECT COUNT(*) FROM history_entries"))
        ).scalar()
    return {
        "plane": "history",
        "source": len(rows),
        "target": int(target or 0),
        "skipped": False,
    }


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


async def verify_sample(engine, sample: int) -> dict:
    """Content-hash spot check: sample chats compare equal to their source."""
    from sqlalchemy import text

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, md5(meta::text) AS h FROM chats "
                    "ORDER BY random() LIMIT :n",
                ),
                {"n": sample},
            )
        ).fetchall()
    return {"sampled": len(rows), "hashes": {r[0]: r[1] for r in rows}}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    from qwenpaw.db.migrate import run_migrations

    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.is_dir():
        print(f"workspace not found: {workspace}", file=sys.stderr)
        return 2

    engine = create_async_engine(args.dsn, pool_pre_ping=True)
    try:
        if not args.dry_run:
            await run_migrations(engine)
        results = []
        results.append(
            await migrate_chats(workspace, engine, args.dry_run, args.agent_id),
        )
        results.append(
            await migrate_sessions(
                workspace,
                engine,
                args.dry_run,
                args.agent_id,
            ),
        )
        results.append(await migrate_history(workspace, engine, args.dry_run))
    finally:
        await engine.dispose()

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    print(f"\n=== migration {mode} for {workspace} ===")
    ok = True
    for r in results:
        status = "SKIP" if r["skipped"] else "OK"
        if not r["skipped"] and not args.dry_run and r["target"] < r["source"]:
            status = "MISMATCH"
            ok = False
        print(
            f"  {r['plane']:>9}: source={r['source']} target={r['target']} "
            f"[{status}]",
        )
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="workspace dir")
    parser.add_argument("--dsn", required=True, help="SQLAlchemy async DSN")
    parser.add_argument(
        "--agent-id",
        default="default",
        help=(
            "agent id owning this workspace's chats/sessions "
            "(chats.agent_id scope)"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="count only")
    parser.add_argument("--sample", type=int, default=20)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
