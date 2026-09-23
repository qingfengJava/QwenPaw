# -*- coding: utf-8 -*-
"""Row-Level Security policies for user-data tables.

RLS is the database-level *backstop* for owner isolation; the application
layer stays the primary enforcer (M1 trusted-identity chain). During the
gray rollout every policy is PERMISSIVE:

- When the connection does not set ``app.current_owner`` the policy passes
  everything (application-level filtering governs, current behavior).
- When it is set (``SET LOCAL app.current_owner = 'alice'``) rows tagged
  with another owner become invisible, and legacy ``NULL`` owners stay
  visible so pre-M1 data does not vanish mid-migration.

Operational roles must be created with ``BYPASSRLS`` (or own the tables)
for backups/migrations to see all rows.
"""
from __future__ import annotations

# Tables carrying per-user data; RLS-enabled by the initial migration.
RLS_TABLES: tuple[str, ...] = (
    "chats",
    "session_states",
    "history_entries",
)

#: Session GUC read by every owner-isolation policy.
OWNER_GUC = "app.current_owner"


def policy_statements(table: str) -> tuple[str, ...]:
    """Return the idempotent ENABLE+POLICY DDL statements for one table.

    One string per statement: asyncpg prepared statements reject multi-
    statement strings, so callers execute these one by one.
    """
    predicate = (
        f"current_setting('{OWNER_GUC}', true) IS NULL "
        f"OR current_setting('{OWNER_GUC}', true) = '' "
        "OR owner_id IS NULL "
        f"OR owner_id = current_setting('{OWNER_GUC}', true)"
    )
    return (
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        # FORCE applies RLS to the table owner as well; otherwise the owner
        # role would silently bypass the backstop. Superusers still bypass —
        # operational roles must therefore be BYPASSRLS (or superuser), and
        # the application role must be neither.
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"DROP POLICY IF EXISTS owner_isolation ON {table}",
        (
            f"CREATE POLICY owner_isolation ON {table} "
            "AS PERMISSIVE FOR ALL "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        ),
    )


def set_owner_context_sql() -> str:
    """Return the SET LOCAL statement binding the GUC to a parameter.

    Usage::

        await conn.execute(
            text(set_owner_context_sql()),
            {"owner": owner_id},
        )

    ``SET LOCAL`` scopes the setting to the current transaction so pooled
    connections never leak one user's context into another user's query.
    """
    # set_config(name, value, is_local): NULL-safe, parameterized.
    return "SELECT set_config('app.current_owner', :owner, true)"
