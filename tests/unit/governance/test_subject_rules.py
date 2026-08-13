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


def _fresh_audit_log(tmp_path: Path) -> AuditLog:
    existing = AuditLog._instance
    if existing is not None:
        existing.close()
    return AuditLog.get_instance(tmp_path)


def test_audit_schema_has_actor_column(tmp_path: Path) -> None:
    log = _fresh_audit_log(tmp_path)
    try:
        cols = {
            row[1]
            for row in log._conn.execute(
                "PRAGMA table_info(audit_events)",
            ).fetchall()
        }
        assert "actor_id" in cols
    finally:
        log.close()


def test_legacy_table_backfilled_with_actor_column(tmp_path: Path) -> None:
    db = tmp_path / "audit.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE audit_events ("
        "ts INTEGER NOT NULL, workspace_dir TEXT NOT NULL, "
        "agent_id TEXT NOT NULL, session_id TEXT NOT NULL, "
        "tool_name TEXT NOT NULL, target TEXT NOT NULL, "
        "decision TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', "
        "extra TEXT NOT NULL DEFAULT '{}')",
    )
    conn.commit()
    AuditLog._migrate_legacy_schema(conn)
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(audit_events)").fetchall()
    }
    conn.close()
    assert "actor_id" in cols
    # Idempotent: a second run is a no-op.
    conn = sqlite3.connect(str(db))
    AuditLog._migrate_legacy_schema(conn)
    conn.close()


def test_record_persists_actor_id(tmp_path: Path) -> None:
    log = _fresh_audit_log(tmp_path)
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
