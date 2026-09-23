# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for M4 subject-scoped governance rules and audit actor_id."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from qwenpaw.governance.audit import AuditLog
from qwenpaw.governance.policy import (
    GovernanceAction,
    GovernanceDecision,
    GovernanceRule,
    ToolCallSpec,
)


def _spec(user_id: str = "", roles=(), teams=()) -> ToolCallSpec:
    return ToolCallSpec(
        tool_name="Bash",
        target="rm -rf /tmp/x",
        agent_id="a1",
        session_id="s1",
        user_id=user_id,
        user_roles=roles,
        user_teams=teams,
    )


def _rule(subject: str = "") -> GovernanceRule:
    return GovernanceRule(
        match="Bash(rm *)",
        action=GovernanceAction.DENY,
        reason="no rm",
        subject=subject,
    )


# ---------------------------------------------------------------------------
# subject matching on GovernanceRule
# ---------------------------------------------------------------------------


def test_global_rule_matches_any_caller() -> None:
    rule = _rule(subject="")
    assert rule.matches_tool_call(_spec()) is True
    assert rule.matches_tool_call(_spec(user_id="alice")) is True


def test_user_subject_matches_only_that_user() -> None:
    rule = _rule(subject="user:alice")
    assert rule.matches_tool_call(_spec(user_id="alice")) is True
    assert rule.matches_tool_call(_spec(user_id="bob")) is False
    # Anonymous caller never matches a user-scoped rule.
    assert rule.matches_tool_call(_spec()) is False


def test_role_subject_matches_member_role() -> None:
    rule = _rule(subject="role:employee")
    assert rule.matches_tool_call(_spec(roles=("employee",))) is True
    assert rule.matches_tool_call(_spec(roles=("platform_admin",))) is False
    assert rule.matches_tool_call(_spec()) is False


def test_team_subject_matches_member_team() -> None:
    rule = _rule(subject="team:core")
    assert rule.matches_tool_call(_spec(teams=("core",))) is True
    assert rule.matches_tool_call(_spec(teams=("edge",))) is False


def test_malformed_subject_never_matches() -> None:
    for bad in ("user", ":alice", "group:core", ":"):
        assert _rule(subject=bad).matches_tool_call(
            _spec(user_id="alice", roles=("employee",), teams=("core",)),
        ) is False


def test_subject_denies_role_end_to_end() -> None:
    """"Disable tool X for role Y" as a policy: DENY + subject=role:..."""
    rule = GovernanceRule(
        match="Bash(*)",
        action=GovernanceAction.DENY,
        reason="employees may not run shell",
        subject="role:employee",
    )
    employee_call = _spec(user_id="eve", roles=("employee",))
    admin_call = _spec(user_id="root", roles=("platform_admin",))
    assert rule.matches_tool_call(employee_call) is True
    assert rule.matches_tool_call(admin_call) is False


# ---------------------------------------------------------------------------
# audit actor_id
# ---------------------------------------------------------------------------


def _fresh_audit_log(tmp_path: Path, monkeypatch=None) -> AuditLog:
    existing = AuditLog._instance
    if existing is not None:
        existing.close()
    if monkeypatch is not None:
        # 单元测试强制 JSONL 后端，与宿主机 PG 环境解耦
        from qwenpaw.governance.audit_store import JsonlAuditStore

        monkeypatch.setattr(
            "qwenpaw.governance.audit.create_audit_backend",
            lambda d: JsonlAuditStore(tmp_path / "audit.jsonl"),
        )
    return AuditLog.get_instance(tmp_path)


def test_audit_row_carries_actor_id(tmp_path: Path, monkeypatch) -> None:
    """JSONL 后端落盘的行包含 actor_id 字段（M4 语义保持）。"""
    import json

    log = _fresh_audit_log(tmp_path, monkeypatch)
    try:
        spec = _spec(user_id="alice")
        decision = GovernanceDecision(
            action=GovernanceAction.ALLOW,
            reason="ok",
        )
        log.record("/ws", spec, decision)
        log.flush()
        jsonl = tmp_path / "audit.jsonl"
        row = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[0])
        assert row["actor_id"] == "alice"
    finally:
        log.close()


def test_legacy_sqlite_rows_imported_into_backend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """遗留 SQLite audit.db 被一次性导入后端并写入 marker（幂等）。"""
    import sqlite3

    from qwenpaw.governance.audit import _backfill_legacy_sqlite
    from qwenpaw.governance.audit_store import JsonlAuditStore

    db = tmp_path / "audit.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE audit_events ("
        "ts INTEGER NOT NULL, workspace_dir TEXT NOT NULL, "
        "agent_id TEXT NOT NULL, session_id TEXT NOT NULL, "
        "tool_name TEXT NOT NULL, target TEXT NOT NULL, "
        "decision TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', "
        "extra TEXT NOT NULL DEFAULT '{}', "
        "actor_id TEXT NOT NULL DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO audit_events VALUES (1, '/ws', 'a', 's', 'Bash', "
        "'git status', 'allow', 'ok', '{}', 'bob')"
    )
    conn.commit()
    conn.close()

    backend = JsonlAuditStore(tmp_path / "audit.jsonl")
    _backfill_legacy_sqlite(backend, db)
    rows, total = backend.query()
    assert total == 1
    assert rows[0]["actor_id"] == "bob"
    assert (tmp_path / "audit.db.pg_backfilled").exists()

    # 幂等：marker 存在时重复导入是 no-op
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO audit_events VALUES (2, '/ws', 'a', 's', 'Bash', "
        "'git log', 'allow', 'ok', '{}', 'bob')"
    )
    conn.commit()
    conn.close()
    _backfill_legacy_sqlite(backend, db)
    _, total_again = backend.query()
    assert total_again == 1


def test_record_persists_actor_id(tmp_path: Path, monkeypatch) -> None:
    log = _fresh_audit_log(tmp_path, monkeypatch)
    try:
        spec = _spec(user_id="alice")
        decision = GovernanceDecision(
            action=GovernanceAction.ALLOW,
            reason="ok",
        )
        log.record("/ws", spec, decision)
        log.flush()
        rows, total = log.query()
        assert total == 1
        assert rows[0].actor_id == "alice"
    finally:
        log.close()
