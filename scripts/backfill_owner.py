# -*- coding: utf-8 -*-
"""One-shot M1 backfill: assign legacy data to a owning account.

Pre-M1 deployments stored chats, session files and scroll history rows
without an enterprise owner.  After multi-user isolation lands, every row
must belong to exactly one account.  This script:

1. ``chats.json`` — fills ``owner_id`` (and rewrites ``user_id`` to the
   owning account) on rows that predate M1.
2. ``sessions/*.json`` — copies session files whose filename embeds a
   legacy user id to the owner-keyed filename (originals are kept).
3. ``history.db`` — backfills ``owner_id`` on rows where it is NULL,
   keyed by the session's owning chat.

Mapping rules (deterministic, in order):

- a legacy ``user_id`` equal to a registered username maps to itself;
- a ``(channel, user_id)`` pair present in ``identity_bindings`` maps to
  the bound username;
- everything else maps to ``--to`` (default: the first admin account).

Default is a dry run printing the full mapping manifest; pass ``--apply``
to write.  Re-running is safe (idempotent).

Usage::

    python scripts/backfill_owner.py                # dry run
    python scripts/backfill_owner.py --apply        # write changes
    python scripts/backfill_owner.py --to alice --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
from pathlib import Path

# Make ``src`` importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qwenpaw.app.chats.session import session_relative_paths  # noqa: E402
from qwenpaw.app.users.store import get_user_store  # noqa: E402
from qwenpaw.config.utils import load_config  # noqa: E402

logger = logging.getLogger("backfill_owner")


def _resolve_owner(
    user_id: str,
    channel: str,
    *,
    usernames: set[str],
    bindings: dict[str, str],
    default_owner: str,
) -> str:
    """Map one legacy user id to its owning account (see module docstring)."""
    if user_id in usernames:
        return user_id
    bound = bindings.get(f"{channel}:{user_id}")
    if bound:
        return bound
    return default_owner


def _iter_workspaces() -> list[tuple[str, Path]]:
    """Yield ``(agent_id, workspace_dir)`` for every configured agent."""
    config = load_config()
    seen: set[str] = set()
    result: list[tuple[str, Path]] = []
    for agent_id, ref in (config.agents.profiles or {}).items():
        raw = getattr(ref, "workspace_dir", "") or ""
        if not raw:
            continue
        path = Path(raw).expanduser()
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        result.append((agent_id, path))
    return result


def _backfill_chats(
    workspace: Path,
    *,
    usernames: set[str],
    bindings: dict[str, str],
    default_owner: str,
    apply: bool,
    report: list[str],
) -> dict[tuple[str, str, str], str]:
    """Backfill chats.json; return ``(session, user, channel) -> owner``."""
    chats_path = workspace / "chats.json"
    mapping: dict[tuple[str, str, str], str] = {}
    if not chats_path.is_file():
        return mapping
    try:
        data = json.loads(chats_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.append(f"!! {chats_path}: unreadable ({exc}) — skipped")
        return mapping

    chats = data.get("chats") or []
    changed = 0
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        session_id = str(chat.get("session_id") or "")
        user_id = str(chat.get("user_id") or "")
        channel = str(chat.get("channel") or "")
        owner = chat.get("owner_id") or None
        if owner is None:
            owner = _resolve_owner(
                user_id,
                channel,
                usernames=usernames,
                bindings=bindings,
                default_owner=default_owner,
            )
            chat["owner_id"] = owner
            changed += 1
        mapping[(session_id, user_id, channel)] = owner
        # The session user_id dimension becomes the owning account too,
        # so runtime/session files stay on one identity key.
        if user_id and user_id != owner:
            chat["user_id"] = owner
            changed += 1
    if changed:
        report.append(
            f"chats.json: {changed} field(s) to backfill in {workspace}"
        )
        if apply:
            backup = chats_path.with_suffix(".json.pre-owner-backfill.bak")
            if not backup.exists():
                shutil.copy2(chats_path, backup)
            tmp = chats_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
                newline="\n",
            )
            tmp.replace(chats_path)
    return mapping


def _backfill_session_files(
    workspace: Path,
    mapping: dict[tuple[str, str, str], str],
    *,
    apply: bool,
    report: list[str],
) -> None:
    """Copy session files to owner-keyed filenames (originals kept)."""
    sessions_dir = workspace / "sessions"
    if not sessions_dir.is_dir():
        return
    copied = 0
    for (session_id, user_id, channel), owner in mapping.items():
        if not session_id or not owner or user_id == owner:
            continue
        old_candidates = session_relative_paths(session_id, user_id, channel)
        new_candidates = session_relative_paths(session_id, owner, channel)
        for old_rel in old_candidates - new_candidates:
            old_path = sessions_dir / old_rel
            if not old_path.is_file():
                continue
            # Pick the new path with the same channel layout.
            new_rel = next(
                (c for c in new_candidates if c.split("/")[0] ==
                 old_rel.split("/")[0] or len(new_candidates) == 1),
                sorted(new_candidates)[0],
            )
            new_path = sessions_dir / new_rel
            if new_path.exists():
                continue
            report.append(f"session file: {old_path.name} -> {new_rel}")
            if apply:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_path, new_path)
                copied += 1
    if copied:
        report.append(f"sessions: copied {copied} file(s) in {workspace}")


def _backfill_history(
    workspace: Path,
    mapping: dict[tuple[str, str, str], str],
    *,
    default_owner: str,
    apply: bool,
    report: list[str],
) -> None:
    """Backfill owner_id on scroll history rows (NULL = pre-M1)."""
    db_path = workspace / "history.db"
    if not db_path.is_file():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(conversation_history)")
        }
        if "owner_id" not in cols:
            report.append(f"history.db: no owner_id column in {db_path}")
            return
        # Session -> owner from the (already backfilled) chat mapping.
        session_owner: dict[str, str] = {}
        for (session_id, _user, _channel), owner in mapping.items():
            session_owner.setdefault(session_id, owner)

        total_null = conn.execute(
            "SELECT COUNT(*) FROM conversation_history WHERE owner_id IS NULL",
        ).fetchone()[0]
        if not total_null:
            return
        per_owner: dict[str, int] = {}
        for session_id, owner in session_owner.items():
            n = conn.execute(
                "SELECT COUNT(*) FROM conversation_history "
                "WHERE owner_id IS NULL AND session_id = ?",
                (session_id,),
            ).fetchone()[0]
            if n:
                per_owner[owner] = per_owner.get(owner, 0) + n
                if apply:
                    conn.execute(
                        "UPDATE conversation_history SET owner_id = ? "
                        "WHERE owner_id IS NULL AND session_id = ?",
                        (owner, session_id),
                    )
        # Rows whose session has no chat (cron:/heartbeat/etc.) go to the
        # default owner.
        assigned = sum(per_owner.values())
        remainder = total_null - assigned
        if remainder:
            per_owner[default_owner] = per_owner.get(default_owner, 0) + remainder
            if apply:
                conn.execute(
                    "UPDATE conversation_history SET owner_id = ? "
                    "WHERE owner_id IS NULL",
                    (default_owner,),
                )
        if apply:
            conn.commit()
        breakdown = ", ".join(f"{o}: {n}" for o, n in sorted(per_owner.items()))
        report.append(
            f"history.db: {total_null} NULL-owner row(s) -> {breakdown} "
            f"in {workspace}"
        )
    finally:
        conn.close()


def main() -> int:
    """Entry point: dry-run by default, ``--apply`` to write."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write changes (default: dry run, prints the mapping manifest)",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="fallback owner for unmapped rows (default: first admin)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    store = get_user_store()
    users = store.list_users()
    if not users:
        print("No registered users found — nothing to backfill.")
        return 0
    admins = [u for u in users if u.role == "admin"]
    default_owner = args.to or (admins[0].username if admins else users[0].username)
    usernames = {u.username for u in users}
    bindings = dict(store._load().identity_bindings)  # noqa: SLF001

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] default owner: {default_owner}")
    print(f"[{mode}] users: {sorted(usernames)}")
    if bindings:
        print(f"[{mode}] identity bindings: {len(bindings)}")

    report: list[str] = []
    workspaces = _iter_workspaces()
    if not workspaces:
        print("No agent workspaces found.")
        return 0
    for agent_id, workspace in workspaces:
        report.append(f"--- agent={agent_id} dir={workspace}")
        mapping = _backfill_chats(
            workspace,
            usernames=usernames,
            bindings=bindings,
            default_owner=default_owner,
            apply=args.apply,
            report=report,
        )
        _backfill_session_files(workspace, mapping, apply=args.apply, report=report)
        _backfill_history(
            workspace,
            mapping,
            default_owner=default_owner,
            apply=args.apply,
            report=report,
        )

    print("\n".join(report))
    if not args.apply:
        print("\nDry run only — re-run with --apply to write these changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
