# -*- coding: utf-8 -*-
"""In-process event bus for real-time XianWork subscriptions.

The bus powers the project-feed SSE endpoint: write paths publish topic
events (``feed:{tenant}:{project_id}``) and each SSE subscriber receives
its own replayable stream. The protocol interface deliberately mirrors
what a Redis Streams implementation would offer (``last_event_id``
replay), so swapping in a cross-process backend later is a config change
rather than a redesign::

    class RedisEventBus(EventBus):
        # XADD on publish; XREAD (+XRANGE for replay) on subscribe.
        ...

Scalability note: the in-process implementation is bounded — a slow
subscriber drops the oldest buffered events (the PG ``feed_events`` table
remains the durable source of truth; clients reconnect with
``Last-Event-ID`` and fall back to a paginated fetch).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Protocol, Set

logger = logging.getLogger(__name__)

#: Per-subscriber replay buffer (also the slow-consumer bound).
_BUFFER_SIZE = 256


@dataclass
class BusEvent:
    """One broadcast event with a monotonic in-process sequence id."""

    seq: int
    topic: str
    data: dict


class EventBus(Protocol):
    """Minimal topic-bus contract (in-process today, Redis tomorrow)."""

    async def publish(self, topic: str, event: dict) -> None:
        """Broadcast *event* to every current subscriber of *topic*."""

    def subscribe(
        self,
        topic: str,
        last_event_id: str = "",
    ) -> AsyncIterator[BusEvent]:
        """Stream events for *topic*, replaying from *last_event_id*."""


class InProcessEventBus:
    """Single-process fan-out with per-subscriber replay buffers."""

    def __init__(self) -> None:
        self._seq = 0
        self._subscribers: Dict[str, Set["_Subscription"]] = {}
        self._history: Dict[str, List[BusEvent]] = {}

    async def publish(self, topic: str, event: dict) -> None:
        """Assign a sequence id and fan out to live subscribers.

        The critical section below is deliberately *synchronous-only*
        (list/dict/set mutations, no ``await``), so it is atomic under
        the single-threaded event loop by construction. An earlier
        ``asyncio.Lock`` here bound itself to the first event loop that
        ever published and then dead-locked every later loop reusing
        this process-wide singleton (pytest-asyncio spins a fresh loop
        per test) — locks must not outlive their loop.
        """
        self._seq += 1
        bus_event = BusEvent(seq=self._seq, topic=topic, data=event)
        history = self._history.setdefault(topic, [])
        history.append(bus_event)
        if len(history) > _BUFFER_SIZE:
            del history[: len(history) - _BUFFER_SIZE]
        subscribers = list(self._subscribers.get(topic, ()))
        for subscriber in subscribers:
            subscriber.push(bus_event)

    def subscribe(self, topic: str, last_event_id: str = ""):
        """Return an async iterator over *topic* events.

        ``last_event_id`` (the SSE ``Last-Event-ID`` header) replays the
        retained buffer tail so brief disconnects are seamless.
        """
        return _Subscription(self, topic, last_event_id)

    # -- internals used by _Subscription ------------------------------

    def _register(self, subscription: "_Subscription") -> None:
        self._subscribers.setdefault(subscription.topic, set()).add(
            subscription
        )

    def _unregister(self, subscription: "_Subscription") -> None:
        bucket = self._subscribers.get(subscription.topic)
        if bucket is not None:
            bucket.discard(subscription)
            if not bucket:
                self._subscribers.pop(subscription.topic, None)

    def _replay(self, topic: str, last_seq: int) -> List[BusEvent]:
        return [
            event
            for event in self._history.get(topic, [])
            if event.seq > last_seq
        ]


@dataclass(eq=False)
class _Subscription:
    """One subscriber's queue + lifecycle bookkeeping.

    Identity semantics (``eq=False``): subscriptions are tracked in sets
    by object identity, never by value.
    """

    bus: InProcessEventBus
    topic: str
    last_event_id: str
    _queue: "asyncio.Queue[BusEvent | None]" = field(
        default_factory=lambda: asyncio.Queue(maxsize=_BUFFER_SIZE),
    )
    _registered: bool = False
    _closed: bool = False

    def push(self, event: BusEvent) -> None:
        """Deliver one event; drop oldest when the consumer is slow."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("bus: event dropped for slow subscriber")

    def __aiter__(self):
        return self

    async def __anext__(self) -> BusEvent:
        if not self._registered:
            self.bus._register(self)
            self._registered = True
            last_seq = 0
            if self.last_event_id:
                try:
                    last_seq = int(self.last_event_id)
                except ValueError:
                    last_seq = 0
            for event in self.bus._replay(self.topic, last_seq):
                self.push(event)
        if self._closed:
            raise StopAsyncIteration
        event = await self._queue.get()
        if event is None:
            self._closed = True
            raise StopAsyncIteration
        return event

    def close(self) -> None:
        """Stop the iteration (called from finally blocks)."""
        if not self._closed:
            self._closed = True
            self.bus._unregister(self)
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                pass


_bus: InProcessEventBus | None = None


def get_event_bus() -> InProcessEventBus:
    """Process-wide singleton bus (single-worker topology)."""
    global _bus  # pylint: disable=global-statement
    if _bus is None:
        _bus = InProcessEventBus()
    return _bus


def feed_topic(tenant_id: str, project_id: str) -> str:
    """Canonical topic name for one project's feed."""
    return f"feed:{tenant_id}:{project_id}"


def now_ms() -> int:
    """Epoch milliseconds (event timestamps for clients)."""
    return int(time.time() * 1000)
