# -*- coding: utf-8 -*-
"""Backfill ``chats``/``session_states`` agent ownership (one-off, idempotent).

The PG ``chats``/``session_states`` tables gained their ``agent_id`` scope
column in migration 0016. Rows written before that column existed all carry
the ``default`` placeholder regardless of which employee's workspace the
write came from, so every digital employee saw every chat in its panel.

This script re-assigns ownership with a three-level fallback:

1. **json** — each agent workspace's ``chats.json`` is authoritative for
   the chats it still lists;
2. **history** — ``history_entries.session_id → agent_id`` majority vote
   (the scroll history table has carried ``agent_id`` from day one);
3. **default** — undeterminable rows stay with ``default``.

Usage::

    python -m qwenpaw.db.backfill_chat_agent [--dry-run]

@author qingfeng
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ID = "default"


# ---------------------------------------------------------------------------
# workspace -> agent mapping
# ---------------------------------------------------------------------------


def _agent_workspace_pairs() -> list[tuple[str, Path]]:
    """Return (agent_id, workspace_dir) pairs for every known agent.

    Primary source is the loaded config (each profile carries its
    ``workspace_dir``); a directory-name heuristic covers leftover expert
    workspaces that no longer appear in the config.
    """
    pairs: list[tuple[str, Path]] = []
    seen_dirs: set[Path] = set()

    from ..config import load_config

    try:
        config = load_config()
    except Exception:  # noqa: BLE001 - config may be unreadable in repairs
        config = None
    if config is not None:
        for agent_id, ref in config.agents.profiles.items():
            try:
                ws_dir = Path(ref.workspace_dir).expanduser().resolve()
            except Exception:  # noqa: BLE001 - malformed profile
                continue
            if ws_dir.is_dir() and ws_dir not in seen_dirs:
                pairs.append((agent_id, ws_dir))
                seen_dirs.add(ws_dir)

    # Heuristic sweep over the workspaces root: orphan agent dirs, the
    # ``experts/`` tree and its ``.drafts/`` sub-tree.
    home = Path.home() / ".copaw" / "workspaces"
    if not home.is_dir():
        return pairs

    candidates: list[Path] = []
    for child in sorted(home.iterdir()):
        if child.is_dir() and child.name != "experts" and not child.name.startswith("."):
            candidates.append(child)
        if child.name == "experts":
            for sub in sorted(child.iterdir()):
                if not sub.is_dir() or sub.name == ".drafts":
                    continue
                candidates.append(sub)
                drafts = sub / ".drafts"
                if drafts.is_dir():
                    candidates.extend(
                        d for d in sorted(drafts.iterdir()) if d.is_dir()
                    )
    for ws_dir in candidates:
        ws_dir = ws_dir.resolve()
        if ws_dir in seen_dirs:
            continue
        agent_id = _infer_agent_id(ws_dir)
        if agent_id:
            pairs.append((agent_id, ws_dir))
            seen_dirs.add(ws_dir)
    return pairs


def _infer_agent_id(workspace_dir: Path) -> str | None:
    """Guess the agent id from a workspace directory layout."""
    name = workspace_dir.name
    parent = workspace_dir.parent.name
    if parent == ".drafts":
        # experts/<id>/.drafts/<expert_id> -> expert_<expert_id>__draft
        return f"expert_{name}__draft"
    if parent == "experts":
        return f"expert_{name}"
    if name.startswith("."):
        return None
    return name


# ---------------------------------------------------------------------------
# json ownership map
# ---------------------------------------------------------------------------


def _json_chat_ownership(pairs: list[tuple[str, Path]]) -> dict[str, str]:
    """chat_id -> agent_id from every workspace's chats.json."""
    ownership: dict[str, str] = {}
    for agent_id, ws_dir in pairs:
        chats_path = ws_dir / "chats.json"
        if not chats_path.is_file():
            continue
        try:
            data = json.loads(chats_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping unreadable %s: %s", chats_path, exc)
            continue
        for spec in data.get("chats", []):
            chat_id = spec.get("id")
            if chat_id:
                ownership.setdefault(chat_id, agent_id)
    return ownership


async def _history_agent_votes(engine, session_id: str) -> str | None:
    """Majority agent_id for a session from history_entries (or None)."""
    from sqlalchemy import text

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT agent_id FROM history_entries "
                    "WHERE tenant_id = 'default' AND session_id = :sid "
                    "GROUP BY agent_id ORDER BY count(*) DESC LIMIT 1",
                ),
                {"sid": session_id},
            )
        ).first()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# backfill passes
# ---------------------------------------------------------------------------


async def backfill_chats(engine, ownership: dict[str, str], dry_run: bool) -> dict:
    """Re-scope every chats row via json -> history -> default."""
    from sqlalchemy import text

    stats = {"json": 0, "history": 0, "default": 0, "total": 0}
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, session_id FROM chats "
                    "WHERE tenant_id = 'default'",
                ),
            )
        ).fetchall()
    updates: list[tuple[str, str]] = []
    for chat_id, session_id in rows:
        stats["total"] += 1
        agent_id = ownership.get(chat_id)
        if agent_id:
            stats["json"] += 1
        else:
            agent_id = await _history_agent_votes(engine, session_id)
            if agent_id:
                stats["history"] += 1
            else:
                agent_id = DEFAULT_AGENT_ID
                stats["default"] += 1
        updates.append((chat_id, agent_id))

    if not dry_run:
        async with engine.begin() as conn:
            for chat_id, agent_id in updates:
                await conn.execute(
                    text(
                        "UPDATE chats SET agent_id = :aid "
                        "WHERE tenant_id = 'default' AND id = :cid",
                    ),
                    {"aid": agent_id, "cid": chat_id},
                )
    return stats


async def backfill_session_states(engine, dry_run: bool) -> dict:
    """Re-scope session_states rows via history votes -> default."""
    from sqlalchemy import text

    stats = {"history": 0, "default": 0, "total": 0}
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT channel, owner_id, session_id "
                    "FROM session_states WHERE tenant_id = 'default'",
                ),
            )
        ).fetchall()
    updates: list[tuple[str, str, str, str]] = []
    for channel, owner_id, session_id in rows:
        stats["total"] += 1
        agent_id = await _history_agent_votes(engine, session_id)
        if agent_id:
            stats["history"] += 1
        else:
            agent_id = DEFAULT_AGENT_ID
            stats["default"] += 1
        updates.append((channel, owner_id, session_id, agent_id))

    if not dry_run:
        async with engine.begin() as conn:
            for channel, owner_id, session_id, agent_id in updates:
                await conn.execute(
                    text(
                        "UPDATE session_states SET agent_id = :aid "
                        "WHERE tenant_id = 'default' AND channel = :chan "
                        "AND owner_id = :uid AND session_id = :sid",
                    ),
                    {
                        "aid": agent_id,
                        "chan": channel,
                        "uid": owner_id,
                        "sid": session_id,
                    },
                )
    return stats


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def _run(dry_run: bool) -> int:
    from .engine import create_pg_engine

    engine = create_pg_engine()
    try:
        pairs = _agent_workspace_pairs()
        print(f"workspaces discovered: {len(pairs)}")
        for agent_id, ws_dir in pairs:
            print(f"  {agent_id} -> {ws_dir}")

        ownership = _json_chat_ownership(pairs)
        print(f"chats.json ownership entries: {len(ownership)}")

        chat_stats = await backfill_chats(engine, ownership, dry_run)
        state_stats = await backfill_session_states(engine, dry_run)
    finally:
        await engine.dispose()

    mode = "DRY-RUN" if dry_run else "APPLIED"
    print(f"\n=== chats backfill {mode} ===")
    print(f"  total={chat_stats['total']} json={chat_stats['json']} "
          f"history={chat_stats['history']} default={chat_stats['default']}")
    print("=== session_states backfill ===")
    print(f"  total={state_stats['total']} "
          f"history={state_stats['history']} default={state_stats['default']}")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the assignment plan without writing",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
