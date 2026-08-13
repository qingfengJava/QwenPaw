# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the M1 owner backfill script (dry-run + apply)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "scripts"),
)

import backfill_owner as bo  # noqa: E402


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "sessions" / "console").mkdir(parents=True)
    return ws


def _write_chats(ws: Path, chats: list[dict]) -> None:
    (ws / "chats.json").write_text(
        json.dumps({"version": 1, "chats": chats}),
        encoding="utf-8",
    )


def _chat(session_id: str, user_id: str, channel: str = "console") -> dict:
    return {
        "id": f"id-{session_id}",
        "session_id": session_id,
        "user_id": user_id,
        "channel": channel,
    }


def _make_history(ws: Path, rows: list[tuple[str, str]]) -> None:
    """rows: (session_id, content); owner_id starts NULL."""
    conn = sqlite3.connect(str(ws / "history.db"))
    with conn:
        conn.execute(
            "CREATE TABLE conversation_history ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,"
            " agent_id TEXT, owner_id TEXT, kind TEXT NOT NULL, role TEXT,"
            " name TEXT, content TEXT, tool_call_id TEXT, tool_input TEXT,"
            " tool_state TEXT, headline TEXT, blocks TEXT, metadata TEXT,"
            " created_at TEXT, dedup_key TEXT)",
        )
        for sid, content in rows:
            conn.execute(
                "INSERT INTO conversation_history (session_id, kind, content)"
                " VALUES (?, 'model_turn', ?)",
                (sid, content),
            )
    conn.close()


def test_dry_run_writes_nothing(workspace: Path):
    _write_chats(workspace, [_chat("console:legacy", "legacy-user")])
    report: list[str] = []
    mapping = bo._backfill_chats(
        workspace,
        usernames={"alice"},
        bindings={},
        default_owner="alice",
        apply=False,
        report=report,
    )
    assert mapping[("console:legacy", "legacy-user", "console")] == "alice"
    on_disk = json.loads((workspace / "chats.json").read_text("utf-8"))
    assert "owner_id" not in on_disk["chats"][0]
    assert report  # manifest mentions the planned change


def test_apply_backfills_owner_and_rewrites_user(workspace: Path):
    _write_chats(workspace, [_chat("console:legacy", "legacy-user")])
    mapping = bo._backfill_chats(
        workspace,
        usernames={"alice"},
        bindings={},
        default_owner="alice",
        apply=True,
        report=[],
    )
    on_disk = json.loads((workspace / "chats.json").read_text("utf-8"))
    chat = on_disk["chats"][0]
    assert chat["owner_id"] == "alice"
    assert chat["user_id"] == "alice"
    assert mapping[("console:legacy", "legacy-user", "console")] == "alice"


def test_registered_username_maps_to_itself(workspace: Path):
    _write_chats(workspace, [_chat("console:bob", "bob")])
    bo._backfill_chats(
        workspace,
        usernames={"alice", "bob"},
        bindings={},
        default_owner="alice",
        apply=True,
        report=[],
    )
    chat = json.loads((workspace / "chats.json").read_text("utf-8"))["chats"][0]
    assert chat["owner_id"] == "bob"


def test_identity_binding_wins_over_default(workspace: Path):
    _write_chats(
        workspace,
        [_chat("dingtalk:u100", "u100", channel="dingtalk")],
    )
    bo._backfill_chats(
        workspace,
        usernames={"alice"},
        bindings={"dingtalk:u100": "alice"},
        default_owner="alice",
        apply=True,
        report=[],
    )
    chat = json.loads((workspace / "chats.json").read_text("utf-8"))["chats"][0]
    assert chat["owner_id"] == "alice"


def test_session_files_copied_to_owner_keyed_name(workspace: Path):
    sessions = workspace / "sessions" / "console"
    old = sessions / "legacy-user_console--legacy.json"
    old.write_text('{"agent": {}}', encoding="utf-8")
    mapping = {("console:legacy", "legacy-user", "console"): "alice"}
    bo._backfill_session_files(workspace, mapping, apply=True, report=[])
    new = sessions / "alice_console--legacy.json"
    assert new.is_file()
    assert old.is_file()  # original kept
    # Idempotent: second run does nothing.
    report: list[str] = []
    bo._backfill_session_files(workspace, mapping, apply=True, report=report)
    assert not [line for line in report if "session file" in line]


def test_history_rows_backfilled_by_session(workspace: Path):
    _make_history(
        workspace,
        [("console:legacy", "old row"), ("cron:job1", "cron row")],
    )
    mapping = {("console:legacy", "legacy-user", "console"): "alice"}
    bo._backfill_history(
        workspace,
        mapping,
        default_owner="alice",
        apply=True,
        report=[],
    )
    conn = sqlite3.connect(str(workspace / "history.db"))
    remaining = conn.execute(
        "SELECT COUNT(*) FROM conversation_history WHERE owner_id IS NULL",
    ).fetchone()[0]
    owners = {
        row[0]
        for row in conn.execute(
            "SELECT owner_id FROM conversation_history",
        )
    }
    conn.close()
    assert remaining == 0
    assert owners == {"alice"}


def test_history_backfill_is_idempotent(workspace: Path):
    _make_history(workspace, [("console:legacy", "old row")])
    mapping = {("console:legacy", "legacy-user", "console"): "alice"}
    bo._backfill_history(
        workspace,
        mapping,
        default_owner="alice",
        apply=True,
        report=[],
    )
    report: list[str] = []
    bo._backfill_history(
        workspace,
        mapping,
        default_owner="alice",
        apply=True,
        report=report,
    )
    assert not report
