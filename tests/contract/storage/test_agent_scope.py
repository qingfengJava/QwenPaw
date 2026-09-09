# -*- coding: utf-8 -*-
"""Agent-scope regression tests for the PG chats/session stores.

The JSON backend isolated each digital employee by workspace file layout;
the shared PG tables need the ``agent_id`` column (migration 0016) and
every read/write scoped to it. These tests pin the isolation contract:

- two employees never see each other's chats or session states;
- a full-registry ``save()`` from one employee can never wipe another
  employee's rows (the delete is agent-scoped, not tenant-scoped).

Runs only with ``QWENPAW_TEST_PG_DSN`` set (hermetic default run skips).

@author qingfeng
"""

from __future__ import annotations

import uuid

import pytest

from qwenpaw.app.chats.models import ChatSpec, ChatsFile
from qwenpaw.app.chats.pg_session_store import PgSessionStore
from qwenpaw.app.chats.repo.pg_repo import PgChatRepository


def _spec(chat_id: str, session_id: str, user_id: str = "local") -> ChatSpec:
    """Build a minimal ChatSpec for one employee's chat."""
    return ChatSpec(
        id=chat_id,
        session_id=session_id,
        user_id=user_id,
        channel="console",
    )


@pytest.fixture
def engine(pg_engine):  # noqa: F811 - fixture from contract conftest
    """Reuse the migrated/cleaned contract-test engine."""
    return pg_engine


def _repo(engine, agent_id: str) -> PgChatRepository:
    return PgChatRepository(engine=engine, agent_id=agent_id)


class TestPgChatRepositoryAgentScope:
    """chats 表按 agent_id 隔离的行为契约。"""

    async def test_lists_are_isolated_per_agent(self, engine) -> None:
        alice = _repo(engine, "expert_alice")
        bob = _repo(engine, "expert_bob")
        await alice.upsert_chat(_spec(f"a-{uuid.uuid4()}", "s-alice"))
        await bob.upsert_chat(_spec(f"b-{uuid.uuid4()}", "s-bob"))

        alice_ids = {c.session_id for c in await alice.filter_chats()}
        bob_ids = {c.session_id for c in await bob.filter_chats()}

        assert alice_ids == {"s-alice"}
        assert bob_ids == {"s-bob"}

    async def test_save_never_wipes_other_agents_rows(
        self,
        engine,
    ) -> None:
        """核心回归：全量 save 只替换本员工的 registry（否则删光他人 chats）。"""
        alice = _repo(engine, "expert_alice")
        bob = _repo(engine, "expert_bob")
        bob_chat = _spec(f"b-{uuid.uuid4()}", "s-bob")
        await bob.upsert_chat(bob_chat)

        # Alice 全量写入自己的 registry（save 会删除"不在文件里的行"）
        keep = _spec(f"a-{uuid.uuid4()}", "s-alice")
        await alice.save(ChatsFile(version=1, chats=[keep]))

        # Bob 的 chats 必须原封不动
        assert (await bob.get_chat(bob_chat.id)) is not None
        assert {c.id for c in await bob.filter_chats()} == {bob_chat.id}
        # Alice 也只看到自己的一行
        assert {c.id for c in await alice.filter_chats()} == {keep.id}

    async def test_get_chat_is_agent_scoped(self, engine) -> None:
        alice = _repo(engine, "expert_alice")
        bob = _repo(engine, "expert_bob")
        spec = _spec(f"a-{uuid.uuid4()}", "s-alice")
        await alice.upsert_chat(spec)

        # UUID 直查也不能跨员工命中（404 语义）
        assert (await alice.get_chat(spec.id)) is not None
        assert (await bob.get_chat(spec.id)) is None

    async def test_get_chat_by_session_is_agent_scoped(self, engine) -> None:
        alice = _repo(engine, "expert_alice")
        bob = _repo(engine, "expert_bob")
        spec = _spec(f"a-{uuid.uuid4()}", "shared-session")
        await alice.upsert_chat(spec)

        # 同 session_id 在另一员工下查不到
        assert (await bob.get_chat_by_id("shared-session", "local")) is None
        found = await alice.get_chat_by_id("shared-session", "local")
        assert found is not None and found.id == spec.id

    async def test_delete_chats_is_agent_scoped(self, engine) -> None:
        alice = _repo(engine, "expert_alice")
        bob = _repo(engine, "expert_bob")
        spec = _spec(f"b-{uuid.uuid4()}", "s-bob")
        await bob.upsert_chat(spec)

        # Alice 无法删除 Bob 的 chat
        assert await alice.delete_chats([spec.id]) is False
        assert (await bob.get_chat(spec.id)) is not None
        # Bob 自己可以删
        assert await bob.delete_chats([spec.id]) is True


class TestPgSessionStoreAgentScope:
    """session_states 表按 agent_id 隔离的行为契约。"""

    async def test_same_session_id_not_shared_across_agents(
        self,
        engine,
    ) -> None:
        """同 (session, user, channel) 在两个员工下互不覆盖。"""

        class _State:
            def __init__(self, value: str) -> None:
                self.value = value

            def state_dict(self):
                return {"v": self.value}

            def load_state_dict(self, data):
                self.value = data["v"]

        alice_store = PgSessionStore(engine=engine, agent_id="expert_alice")
        bob_store = PgSessionStore(engine=engine, agent_id="expert_bob")

        await alice_store.save_session_state(
            "shared-session",
            user_id="local",
            channel="console",
            turn=_State("alice-turn"),
        )
        await bob_store.save_session_state(
            "shared-session",
            user_id="local",
            channel="console",
            turn=_State("bob-turn"),
        )

        alice_state = _State("")
        await alice_store.load_session_state(
            "shared-session",
            user_id="local",
            channel="console",
            turn=alice_state,
        )
        assert alice_state.value == "alice-turn"

    async def test_upsert_updates_same_agent_row(self, engine) -> None:
        class _State:
            def __init__(self, value: str) -> None:
                self.value = value

            def state_dict(self):
                return {"v": self.value}

            def load_state_dict(self, data):
                self.value = data["v"]

        store = PgSessionStore(engine=engine, agent_id="expert_alice")
        await store.save_session_state(
            "sess-1",
            user_id="local",
            channel="console",
            turn=_State("v1"),
        )
        await store.save_session_state(
            "sess-1",
            user_id="local",
            channel="console",
            turn=_State("v2"),
        )
        state = _State("")
        await store.load_session_state(
            "sess-1",
            user_id="local",
            channel="console",
            turn=state,
        )
        assert state.value == "v2"
