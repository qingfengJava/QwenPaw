# -*- coding: utf-8 -*-
"""Fix bootstrap-guidance-polluted user messages in PG storage.

Background: BootstrapHook used to prepend the BOOTSTRAP.md guidance to
the first user message of a session. Agentscope deep-copies those input
messages into ``state.context``, so the guidance was persisted with the
session snapshot and echoed back to users after refresh. The hook now
appends the guidance to the transient system prompt instead; this
script cleans up history that was already polluted.

Scope:
- session_states.agent.state.context — strips the guidance prefix from
  user messages whose first text block starts with it.
- history_entries — same strip for the ``content`` / ``headline`` /
  ``blocks`` columns of polluted user-role rows.

Idempotent: only text exactly starting with the guidance prefix is
rewritten; everything else is left untouched. ``history_entries.tsv``
is a generated column over ``content`` and rebuilds itself on UPDATE.
Run with ``--apply`` to perform updates; default is a dry-run report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qwenpaw.agents.prompt import build_bootstrap_guidance

GUIDANCES = [build_bootstrap_guidance("zh"), build_bootstrap_guidance("en")]
# prepend_to_message_content appended "\n\n" after the guidance text.
PREFIXES = [g + "\n\n" for g in GUIDANCES]


def strip_prefix(text: str) -> tuple[str, bool]:
    """Strip the bootstrap guidance prefix; return (new_text, changed)."""
    for prefix in PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):], True
    return text, False


def clean_msg_content(content):
    """Return (new_content, changed) for a user message content value."""
    changed_any = False
    if isinstance(content, list):
        new_blocks = []
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                new_text, changed = strip_prefix(block["text"])
                if changed:
                    block = {**block, "text": new_text}
                    changed_any = True
            new_blocks.append(block)
        return new_blocks, changed_any
    if isinstance(content, str):
        new_text, changed = strip_prefix(content)
        return new_text, changed
    return content, False


def clean_context(context) -> tuple[bool, int]:
    """Clean polluted user messages in a context list; return (changed, n)."""
    changed_any = False
    fixed = 0
    for msg in context:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        new_content, changed = clean_msg_content(msg.get("content"))
        if changed:
            msg["content"] = new_content
            changed_any = True
            fixed += 1
    return changed_any, fixed


async def clean_session_states(conn, apply: bool) -> None:
    rows = await conn.fetch("SELECT session_id, state FROM session_states")
    fixed_sessions = 0
    for row in rows:
        raw = row["state"]
        state = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        context = state.get("agent", {}).get("state", {}).get("context")
        if not isinstance(context, list):
            continue
        changed, fixed = clean_context(context)
        if not changed:
            continue
        fixed_sessions += 1
        print(f"[session_states] session={row['session_id']} fixed={fixed}")
        if apply:
            await conn.execute(
                "UPDATE session_states SET state = $1 WHERE session_id = $2",
                json.dumps(state, ensure_ascii=False),
                row["session_id"],
            )
    print(
        f"session_states: {fixed_sessions} session(s) polluted"
        + (" — updated" if apply else " (dry-run)")
    )


async def clean_history_entries(conn, apply: bool) -> None:
    exists = await conn.fetchval(
        "SELECT to_regclass('history_entries') IS NOT NULL",
    )
    if not exists:
        print("history_entries: table absent — skipped")
        return
    rows = await conn.fetch(
        "SELECT seq, content, headline, blocks FROM history_entries "
        "WHERE role = 'user' ORDER BY seq",
    )
    fixed_rows = 0
    for row in rows:
        new_content, c_changed = strip_prefix(row["content"] or "")
        new_headline, h_changed = strip_prefix(row["headline"] or "")
        new_blocks, b_changed = None, False
        if row["blocks"]:
            blocks = (
                json.loads(row["blocks"])
                if isinstance(row["blocks"], (str, bytes))
                else row["blocks"]
            )
            if isinstance(blocks, list):
                new_blocks, b_changed = clean_msg_content(blocks)
        if not (c_changed or h_changed or b_changed):
            continue
        fixed_rows += 1
        print(
            f"[history_entries] seq={row['seq']} stripped guidance prefix "
            f"(content={c_changed} headline={h_changed} blocks={b_changed})"
        )
        if apply:
            await conn.execute(
                "UPDATE history_entries SET content = $1, headline = $2, "
                "blocks = $3 WHERE seq = $4",
                new_content,
                new_headline,
                json.dumps(new_blocks, ensure_ascii=False) if b_changed else row["blocks"],
                row["seq"],
            )
    print(
        f"history_entries: {fixed_rows} row(s) polluted"
        + (" — updated" if apply else " (dry-run)")
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strip leaked bootstrap guidance from stored user messages",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform the UPDATE statements (default: dry-run)",
    )
    args = parser.parse_args()

    import asyncpg

    conn = await asyncpg.connect(
        host="127.0.0.1",
        port=5432,
        user="qwenpaw",
        password="qwenpaw_test",
        database="qwenpaw",
    )
    try:
        await clean_session_states(conn, args.apply)
        await clean_history_entries(conn, args.apply)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
