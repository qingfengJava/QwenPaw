# -*- coding: utf-8 -*-
"""PostgreSQL session store (M2).

Implements ``BaseSessionStore`` over the ``session_states`` table, keyed by
``(tenant_id, agent_id, channel, owner_id, session_id)`` — the JSON backend
encoded the agent part into the workspace directory layout. State lives in
one JSONB document so module payloads stay schemaless, exactly like the
file era.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Sequence, Union

from ...db.base import DEFAULT_TENANT_ID
from ...exceptions import AgentStateError, ConfigurationException
from .session_store import BaseSessionStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class PgSessionStore(BaseSessionStore):
    """Session state persistence backed by the ``session_states`` table.

    ``save_dir`` is accepted (and ignored) so the workspace service manager's
    ``init_args`` contract — shaped for the JSON backend — keeps working when
    the pg backend is selected; ``engine`` defaults to the shared pool from
    ``QWENPAW_PG_DSN``.
    """

    def __init__(
        self,
        engine: "AsyncEngine | None" = None,
        tenant_id: str = DEFAULT_TENANT_ID,
        save_dir: str | None = None,
        agent_id: str = "default",
    ) -> None:
        if engine is None:
            from ...db.engine import create_pg_engine

            engine = create_pg_engine()
        _ = save_dir
        self._engine = engine
        self._tenant_id = tenant_id
        # 归属智能体：同用户同 session_id 在不同员工下互不覆盖
        self._agent_id = agent_id or "default"

    # -- helpers ----------------------------------------------------------

    def _key(
        self,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> dict:
        return {
            "tid": self._tenant_id,
            "aid": self._agent_id,
            "chan": channel or "",
            "uid": user_id or "",
            "sid": session_id,
        }

    async def _select_state(
        self,
        conn,
        key: dict,
        for_update: bool = False,
    ) -> dict | None:
        import json

        from sqlalchemy import text

        lock = " FOR UPDATE" if for_update else ""
        result = await conn.execute(
            text(
                "SELECT state FROM session_states "
                "WHERE tenant_id = :tid AND agent_id = :aid "
                "AND channel = :chan "
                "AND owner_id = :uid AND session_id = :sid" + lock,
            ),
            key,
        )
        row = result.first()
        if row is None:
            return None
        state = row[0]
        # text() results carry no type processor: JSONB arrives as text.
        if isinstance(state, str):
            state = json.loads(state)
        return state

    async def _upsert_state(self, conn, key: dict, state: dict) -> None:
        import json
        from datetime import datetime, timezone

        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        await conn.execute(
            text(
                "INSERT INTO session_states (tenant_id, agent_id, channel, "
                "owner_id, "
                "session_id, state, created_at, updated_at) "
                "VALUES (:tid, :aid, :chan, :uid, :sid, CAST(:state AS JSONB), "
                ":now, :now) "
                "ON CONFLICT (tenant_id, agent_id, channel, owner_id, "
                "session_id) "
                "DO UPDATE SET state = EXCLUDED.state, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                **key,
                # text() carries no column type context: send JSON text.
                "state": json.dumps(state, ensure_ascii=False),
                "now": now,
            },
        )

    @staticmethod
    def _not_found(session_id: str, what: str) -> AgentStateError:
        return AgentStateError(
            session_id=session_id,
            message=f"No persisted session state for {what}",
        )

    # -- contract ---------------------------------------------------------

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        **state_modules_mapping,
    ) -> None:
        """Persist the given state modules for one session (full replace)."""
        state_dicts = {
            name: state_module.state_dict()
            for name, state_module in state_modules_mapping.items()
        }
        key = self._key(session_id, user_id, channel)
        async with self._engine.begin() as conn:
            await self._upsert_state(conn, key, state_dicts)

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        """Load persisted state into the given state modules."""
        key = self._key(session_id, user_id, channel)
        async with self._engine.connect() as conn:
            states = await self._select_state(conn, key)
        if states is None:
            if allow_not_exist:
                return
            raise self._not_found(session_id, "load_session_state")
        for name, state_module in state_modules_mapping.items():
            if name in states:
                state_module.load_state_dict(states[name])

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        channel: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        """Set one (possibly nested) key inside the persisted state."""
        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ConfigurationException(
                config_key="session.key",
                message="key path is empty",
            )
        row_key = self._key(session_id, user_id, channel)
        async with self._engine.begin() as conn:
            # SELECT ... FOR UPDATE serializes concurrent nested-key updates
            # of one session, matching the JSON backend's per-path lock.
            states = await self._select_state(conn, row_key, for_update=True)
            if states is None:
                if not create_if_not_exist:
                    raise self._not_found(
                        session_id,
                        "update_session_state",
                    )
                states = {}
            cursor = states
            for part in path[:-1]:
                node = cursor.get(part)
                if not isinstance(node, dict):
                    node = {}
                    cursor[part] = node
                cursor = node
            cursor[path[-1]] = value
            await self._upsert_state(conn, row_key, states)

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        """Return the raw persisted state dict for one session."""
        key = self._key(session_id, user_id, channel)
        async with self._engine.connect() as conn:
            states = await self._select_state(conn, key)
        if states is None:
            if allow_not_exist:
                return {}
            raise self._not_found(session_id, "get_session_state_dict")
        return states

    async def list_session_state_dicts(self) -> list[tuple[str, str, dict]]:
        """Return ``(channel, session_id, state)`` for every stored session.

        Scoped to this store's tenant and agent, mirroring the JSON
        backend's per-workspace directory sweep in agent statistics.
        """
        import json

        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT channel, session_id, state FROM session_states "
                    "WHERE tenant_id = :tid AND agent_id = :aid",
                ),
                {"tid": self._tenant_id, "aid": self._agent_id},
            )
            rows = result.all()

        sessions: list[tuple[str, str, dict]] = []
        for channel, session_id, state in rows:
            # text() results carry no type processor: JSONB arrives as text.
            if isinstance(state, str):
                state = json.loads(state)
            sessions.append((channel or "", session_id, state or {}))
        return sessions
