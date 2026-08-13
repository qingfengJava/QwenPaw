# -*- coding: utf-8 -*-
"""Dual-write chat repository (M2 migration rehearsal).

Reads are served by the primary (JSON) backend only — the PostgreSQL shadow
never influences behavior. Writes hit the primary first; the shadow write is
scheduled asynchronously and its failures are counted and logged, never
raised, so a shadow outage cannot take the primary down with it.

``compare_sample`` is the consistency oracle for the migration runbook: it
re-reads a sample of primary rows from the shadow and reports mismatches.
The promotion gate requires a sustained mismatch rate of zero.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from ..models import ChatSpec, ChatsFile
from ...channels.schema import DEFAULT_CHANNEL
from .base import BaseChatRepository

logger = logging.getLogger(__name__)


class DualChatRepository(BaseChatRepository):
    """Primary JSON + shadow PostgreSQL chat repository."""

    def __init__(
        self,
        primary: BaseChatRepository,
        shadow: BaseChatRepository,
    ) -> None:
        self._primary = primary
        self._shadow = shadow
        self.shadow_write_failures = 0
        self._shadow_tasks: set[asyncio.Task] = set()

    # -- shadow plumbing ----------------------------------------------------

    def _shadow_write(self, coro_factory, what: str) -> None:
        """Schedule a fire-and-forget shadow write; failures only count."""
        async def _run() -> None:
            try:
                await coro_factory()
            except Exception as exc:  # noqa: BLE001 - shadow must not raise
                self.shadow_write_failures += 1
                logger.warning(
                    "Dual-write shadow %s failed (primary unaffected): %s",
                    what,
                    exc,
                )

        try:
            task = asyncio.get_running_loop().create_task(_run())
        except RuntimeError:
            # No running loop (sync caller context): fall back to a private
            # loop so the shadow write still happens during rehearsals.
            task = None
            try:
                asyncio.run(_run())
            except Exception as exc:  # noqa: BLE001
                self.shadow_write_failures += 1
                logger.warning(
                    "Dual-write shadow %s failed (primary unaffected): %s",
                    what,
                    exc,
                )
        if task is not None:
            self._shadow_tasks.add(task)
            task.add_done_callback(self._shadow_tasks.discard)

    async def drain_shadow(self) -> None:
        """Await all in-flight shadow writes (tests + migration cutover)."""
        if self._shadow_tasks:
            await asyncio.gather(*list(self._shadow_tasks), return_exceptions=True)

    def shadow_stats(self) -> dict:
        """Return shadow health counters for the consistency dashboard."""
        return {
            "shadow_write_failures": self.shadow_write_failures,
            "in_flight": len(self._shadow_tasks),
        }

    async def compare_sample(self, limit: int = 50) -> dict:
        """Re-read a sample of primary rows from the shadow and diff them.

        Returns ``{"sampled": n, "mismatches": k, "missing": [ids...],
        "diverged": [ids...]}``. A sustained all-zero result is the gate for
        promoting the shadow to primary.
        """
        primary_chats = (await self._primary.load()).chats
        if not primary_chats:
            return {"sampled": 0, "mismatches": 0, "missing": [], "diverged": []}
        sample = random.sample(
            primary_chats,
            min(limit, len(primary_chats)),
        )
        missing: list[str] = []
        diverged: list[str] = []
        for spec in sample:
            shadow_spec = await self._shadow.get_chat(spec.id)
            if shadow_spec is None:
                missing.append(spec.id)
                continue
            if shadow_spec.model_dump() != spec.model_dump():
                diverged.append(spec.id)
        mismatches = len(missing) + len(diverged)
        if mismatches:
            logger.warning(
                "Dual-write compare_sample: %d/%d mismatched "
                "(missing=%d, diverged=%d)",
                mismatches,
                len(sample),
                len(missing),
                len(diverged),
            )
        return {
            "sampled": len(sample),
            "mismatches": mismatches,
            "missing": missing,
            "diverged": diverged,
        }

    # -- read path: primary only --------------------------------------------

    async def load(self) -> ChatsFile:
        return await self._primary.load()

    async def list_chats(self) -> list[ChatSpec]:
        return await self._primary.list_chats()

    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        return await self._primary.get_chat(chat_id)

    async def get_chat_by_id(
        self,
        session_id: str,
        user_id: str,
        channel: str = DEFAULT_CHANNEL,
    ) -> Optional[ChatSpec]:
        return await self._primary.get_chat_by_id(session_id, user_id, channel)

    async def filter_chats(
        self,
        user_id: Optional[str] = None,
        channel: Optional[str] = None,
        archived: Optional[bool] = None,
    ) -> list[ChatSpec]:
        return await self._primary.filter_chats(user_id, channel, archived)

    # -- write path: primary first, shadow second ----------------------------

    async def save(self, chats_file: ChatsFile) -> None:
        await self._primary.save(chats_file)
        self._shadow_write(
            lambda: self._shadow.save(chats_file),
            "save",
        )

    async def upsert_chat(self, spec: ChatSpec) -> None:
        await self._primary.upsert_chat(spec)
        self._shadow_write(lambda: self._shadow.upsert_chat(spec), "upsert")

    async def touch_chat_by_session(
        self,
        session_id: str,
        channel: str,
        user_id: str | None = None,
    ) -> Optional[ChatSpec]:
        touched = await self._primary.touch_chat_by_session(
            session_id,
            channel,
            user_id,
        )
        if touched is not None:
            self._shadow_write(
                lambda: self._shadow.upsert_chat(touched),
                "touch",
            )
        return touched

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        deleted = await self._primary.delete_chats(chat_ids)
        if deleted:
            self._shadow_write(
                lambda: self._shadow.delete_chats(chat_ids),
                "delete",
            )
        return deleted
