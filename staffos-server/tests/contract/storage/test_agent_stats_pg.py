# -*- coding: utf-8 -*-
"""Contract: AgentStatsService reads pg-backed chats and session states.

The pg storage backend keeps chat specs in the ``chats`` table and session
states in ``session_states`` — the workspace's ``chats.json`` / ``sessions/``
files stay empty. The statistics service must therefore resolve both planes
through the storage factory, scoped by ``agent_id``. Runs only when
``QWENPAW_TEST_PG_DSN`` points at a throwaway database; skipped otherwise
(never aim it at a real deployment database: the fixture truncates tables).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from qwenpaw.agent_stats.service import AgentStatsService
from qwenpaw.app.chats.factory import (
    STORAGE_BACKEND_ENV,
    build_chat_repository,
    get_session_store_class,
)
from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.token_usage.turn_usage import TURN_USAGE_META_KEY


@pytest.fixture
def pg_backend_env(monkeypatch: pytest.MonkeyPatch, pg_dsn: str) -> str:
    """Point the storage factory at the throwaway test database."""
    monkeypatch.setenv(STORAGE_BACKEND_ENV, "pg")
    monkeypatch.setenv("QWENPAW_PG_DSN", pg_dsn)
    return pg_dsn


def _assistant_with_usage(
    *,
    created_at: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> dict:
    return {
        "role": "assistant",
        "created_at": created_at,
        "content": [{"type": "text", "text": "hi"}],
        "metadata": {
            TURN_USAGE_META_KEY: {
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            },
        },
    }


async def test_pg_summary_counts_chats_and_session_messages(
    pg_backend_env: str,
    tmp_path,
) -> None:
    """chats/session rows of one agent feed the summary; files stay empty."""
    agent_id = "expert_builtin_analyst"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # Deliberately NO chats.json / sessions/ on disk: pg is the only plane.

    created = datetime(2026, 7, 23, 9, 0, 0, tzinfo=timezone.utc)
    repo = build_chat_repository(
        workspace / "chats.json",
        agent_id=agent_id,
    )
    await repo.upsert_chat(
        ChatSpec(
            id="c1",
            session_id="console:u1",
            user_id="u1",
            channel="console",
            created_at=created,
            updated_at=created,
        ),
    )

    store = get_session_store_class()(
        save_dir=str(workspace / "sessions"),
        agent_id=agent_id,
    )
    await store.update_session_state(
        "console:u1",
        "agent.state.context",
        [
            {
                "role": "user",
                "created_at": "2026-07-23T09:00:00Z",
                "content": [{"type": "text", "text": "hi"}],
            },
            _assistant_with_usage(
                created_at="2026-07-23T09:00:01Z",
                prompt_tokens=111,
                completion_tokens=22,
            ),
        ],
        user_id="u1",
        channel="console",
    )

    summary = await AgentStatsService().get_summary(
        workspace_dir=workspace,
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 23),
        include_token_overlay=False,
        agent_id=agent_id,
    )

    assert summary.by_date[0].chats == 1
    assert summary.total_messages == 2
    assert summary.total_active_sessions == 1
    assert summary.agent_prompt_tokens == 111
    assert summary.agent_completion_tokens == 22
    assert summary.agent_llm_calls == 1


async def test_pg_summary_is_scoped_to_agent(
    pg_backend_env: str,
    tmp_path,
) -> None:
    """Another agent's rows must not leak into this agent's summary."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    created = datetime(2026, 7, 23, 9, 0, 0, tzinfo=timezone.utc)
    repo = build_chat_repository(
        workspace / "chats.json",
        agent_id="agent_a",
    )
    await repo.upsert_chat(
        ChatSpec(
            id="c1",
            session_id="console:u1",
            user_id="u1",
            channel="console",
            created_at=created,
            updated_at=created,
        ),
    )

    summary = await AgentStatsService().get_summary(
        workspace_dir=workspace,
        start_date=date(2026, 7, 23),
        end_date=date(2026, 7, 23),
        include_token_overlay=False,
        agent_id="agent_b",
    )

    assert summary.by_date[0].chats == 0
