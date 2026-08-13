# -*- coding: utf-8 -*-
"""Unit tests for the M3 per-user turn concurrency gate."""
from __future__ import annotations

import asyncio

import pytest

from qwenpaw.app.concurrency_gate import (
    ConcurrencyGate,
    TurnQueueFull,
    get_concurrency_gate,
    reset_concurrency_gate,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_concurrency_gate()
    yield
    reset_concurrency_gate()


async def test_slot_allows_up_to_per_user() -> None:
    gate = ConcurrencyGate(per_user=2, max_queue=10, queue_timeout_s=5)
    entered: list[str] = []

    async def worker(name: str) -> None:
        async with gate.slot("u1"):
            entered.append(name)
            await asyncio.sleep(0.05)

    await asyncio.gather(worker("a"), worker("b"))
    assert sorted(entered) == ["a", "b"]


async def test_slot_blocks_beyond_per_user_until_release() -> None:
    gate = ConcurrencyGate(per_user=1, max_queue=10, queue_timeout_s=5)
    events: list[tuple[str, str]] = []

    async def holder() -> None:
        async with gate.slot("u1"):
            events.append(("enter", "holder"))
            await asyncio.sleep(0.2)
            events.append(("exit", "holder"))

    async def waiter() -> None:
        async with gate.slot("u1"):
            events.append(("enter", "waiter"))

    t_hold = asyncio.create_task(holder())
    await asyncio.sleep(0.05)  # holder acquires the only permit
    t_wait = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    # waiter is queued behind the holder, not admitted early
    assert ("enter", "waiter") not in events
    await asyncio.gather(t_hold, t_wait)
    # after release the waiter ran, strictly after the holder exited
    assert events.index(("exit", "holder")) < events.index(
        ("enter", "waiter"),
    )


async def test_users_are_independent() -> None:
    gate = ConcurrencyGate(per_user=1, max_queue=10, queue_timeout_s=5)
    entered = asyncio.Event()

    async def holder() -> None:
        async with gate.slot("user-a"):
            entered.set()
            await asyncio.sleep(0.2)

    t_hold = asyncio.create_task(holder())
    await entered.wait()
    # A different user is not blocked by user-a's held permit.
    async with gate.slot("user-b"):
        pass
    await t_hold


async def test_queue_full_rejects_immediately() -> None:
    gate = ConcurrencyGate(per_user=1, max_queue=1, queue_timeout_s=5)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with gate.slot("u1"):
            entered.set()
            await release.wait()

    async def waiter() -> None:
        async with gate.slot("u1"):
            pass

    t_hold = asyncio.create_task(holder())
    await entered.wait()
    t_wait = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)  # waiter enqueued (depth now 1 == max)

    with pytest.raises(TurnQueueFull) as exc_info:
        async with gate.slot("u1"):
            pass  # pragma: no cover - must not be admitted
    assert exc_info.value.retry_after == gate.retry_after

    release.set()
    await asyncio.gather(t_hold, t_wait)


async def test_queue_timeout_raises_turn_queue_full() -> None:
    gate = ConcurrencyGate(per_user=1, max_queue=10, queue_timeout_s=0.2)
    async with gate.slot("u1"):
        with pytest.raises(TurnQueueFull) as exc_info:
            async with gate.slot("u1"):
                pass  # pragma: no cover - must time out first
    assert exc_info.value.retry_after == 0.2
    assert "timed out" in str(exc_info.value)


async def test_would_reject_reflects_saturation() -> None:
    gate = ConcurrencyGate(per_user=1, max_queue=1, queue_timeout_s=5)
    # Unknown user: no semaphore yet, admitted.
    assert not gate.would_reject("u1")

    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with gate.slot("u1"):
            entered.set()
            await release.wait()

    async def waiter() -> None:
        async with gate.slot("u1"):
            pass

    t_hold = asyncio.create_task(holder())
    await entered.wait()
    # Permit held but queue empty: still admissible (will queue).
    assert not gate.would_reject("u1")

    t_wait = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    # Permit held + queue at capacity: reject.
    assert gate.would_reject("u1")
    # Other users unaffected.
    assert not gate.would_reject("other")

    release.set()
    await asyncio.gather(t_hold, t_wait)
    assert not gate.would_reject("u1")


async def test_empty_user_maps_to_system_key() -> None:
    gate = ConcurrencyGate(per_user=1, max_queue=10, queue_timeout_s=0.2)
    async with gate.slot(""):
        # "" and "system" share one semaphore: a second "system" turn
        # must queue behind it and times out quickly here.
        with pytest.raises(TurnQueueFull):
            async with gate.slot("system"):
                pass  # pragma: no cover - must time out


async def test_stats_snapshot() -> None:
    gate = ConcurrencyGate(per_user=3, max_queue=7, queue_timeout_s=5)
    async with gate.slot("u1"):
        snapshot = gate.stats()
    assert snapshot["per_user"] == 3
    assert snapshot["max_queue"] == 7
    assert snapshot["queued"] == 0
    assert snapshot["users"] == 1


def test_singleton_factory_and_reset() -> None:
    gate = get_concurrency_gate()
    assert get_concurrency_gate() is gate
    reset_concurrency_gate()
    assert get_concurrency_gate() is not gate


def test_singleton_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWENPAW_USER_CONCURRENCY", "5")
    monkeypatch.setenv("QWENPAW_MAX_TURN_QUEUE", "7")
    monkeypatch.setenv("QWENPAW_TURN_QUEUE_TIMEOUT_S", "9")
    reset_concurrency_gate()
    gate = get_concurrency_gate()
    assert gate.stats()["per_user"] == 5
    assert gate.stats()["max_queue"] == 7
    assert gate.retry_after == 9.0
