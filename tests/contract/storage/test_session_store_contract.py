# -*- coding: utf-8 -*-
"""Session store contract tests.

Every ``BaseSessionStore`` implementation must satisfy these contracts so
backends (JSON today, PostgreSQL from the M2 milestone) stay interchangeable
behind ``qwenpaw.app.chats.factory.build_session_store``.
"""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path

import pytest

from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.chats.session_store import BaseSessionStore
from qwenpaw.exceptions import AgentStateError
from qwenpaw.runtime._state_utils import StateProxy

from .. import BaseContractTest


class SessionStoreContractTest(BaseContractTest):
    """Contract: every session store backend behaves identically."""

    @abstractmethod
    def create_instance(self) -> BaseSessionStore:
        """Provide a session store backed by a fresh, empty storage."""

    async def test_save_and_get_round_trip(self, instance: BaseSessionStore):
        module = StateProxy()
        module.data = {"turns": 3}
        await instance.save_session_state("s1", user_id="alice", state=module)

        loaded = await instance.get_session_state_dict("s1", user_id="alice")
        assert loaded["state"]["turns"] == 3

    async def test_load_populates_state_modules(
        self,
        instance: BaseSessionStore,
    ):
        writer = StateProxy()
        writer.data = {"memory": [1, 2]}
        await instance.save_session_state("s1", user_id="alice", mem=writer)

        reader = StateProxy()
        await instance.load_session_state("s1", user_id="alice", mem=reader)
        assert reader.data == {"memory": [1, 2]}

    async def test_load_missing_session_allowed_by_default(
        self,
        instance: BaseSessionStore,
    ):
        # allow_not_exist=True (the default) silently skips a missing session.
        await instance.load_session_state("ghost", reader=StateProxy())

    async def test_load_missing_session_raises_when_disallowed(
        self,
        instance: BaseSessionStore,
    ):
        with pytest.raises(AgentStateError):
            await instance.load_session_state(
                "ghost",
                allow_not_exist=False,
                reader=StateProxy(),
            )

    async def test_get_state_dict_missing_returns_empty(
        self,
        instance: BaseSessionStore,
    ):
        assert await instance.get_session_state_dict("ghost") == {}

    async def test_get_state_dict_missing_raises_when_disallowed(
        self,
        instance: BaseSessionStore,
    ):
        with pytest.raises(AgentStateError):
            await instance.get_session_state_dict(
                "ghost",
                allow_not_exist=False,
            )

    async def test_update_session_state_nested_keys(
        self,
        instance: BaseSessionStore,
    ):
        # Dotted-string and sequence key forms must both work and merge.
        await instance.update_session_state(
            "s1",
            "agent.flags",
            {"a": 1},
            user_id="alice",
        )
        await instance.update_session_state(
            "s1",
            ["agent", "count"],
            2,
            user_id="alice",
        )

        state = await instance.get_session_state_dict("s1", user_id="alice")
        assert state["agent"]["flags"] == {"a": 1}
        assert state["agent"]["count"] == 2

    async def test_update_missing_session_raises_when_disallowed(
        self,
        instance: BaseSessionStore,
    ):
        with pytest.raises(AgentStateError):
            await instance.update_session_state(
                "ghost",
                "key",
                1,
                create_if_not_exist=False,
            )

    async def test_sessions_isolated_by_user(
        self,
        instance: BaseSessionStore,
    ):
        # The same session_id under different users must never collide.
        alice = StateProxy()
        alice.data = {"owner": "alice"}
        bob = StateProxy()
        bob.data = {"owner": "bob"}
        await instance.save_session_state("s1", user_id="alice", state=alice)
        await instance.save_session_state("s1", user_id="bob", state=bob)

        alice_state = await instance.get_session_state_dict(
            "s1",
            user_id="alice",
        )
        bob_state = await instance.get_session_state_dict("s1", user_id="bob")
        assert alice_state["state"]["owner"] == "alice"
        assert bob_state["state"]["owner"] == "bob"


class TestSafeJSONSessionContract(SessionStoreContractTest):
    """JSON file backend (reference implementation)."""

    @pytest.fixture(autouse=True)
    def _storage(self, tmp_path: Path) -> None:
        self._save_dir = str(tmp_path)

    def create_instance(self) -> BaseSessionStore:
        return SafeJSONSession(save_dir=self._save_dir)


# Future backends (M2 milestone): add ``TestPgSessionStoreContract`` below —
# every contract test above will automatically run against it.
