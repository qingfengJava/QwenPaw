# -*- coding: utf-8 -*-
"""Dual-write session store (M2 migration rehearsal).

Reads come from the primary (JSON files) only. Writes are applied to the
primary first, then mirrored to the PostgreSQL shadow asynchronously;
shadow failures are counted and logged, never raised.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Sequence, Union

from .session_store import BaseSessionStore

logger = logging.getLogger(__name__)


class DualSessionStore(BaseSessionStore):
    """Primary JSON + shadow PostgreSQL session store."""

    def __init__(
        self,
        primary: BaseSessionStore | None = None,
        shadow: BaseSessionStore | None = None,
        save_dir: str | None = None,
        agent_id: str = "default",
    ) -> None:
        # ``save_dir`` keeps the workspace ``init_args`` contract: with no
        # explicit backends the dual store wires JSON-primary + PG-shadow.
        if primary is None:
            from .session import SafeJSONSession

            primary = SafeJSONSession(save_dir=save_dir or "./")
        if shadow is None:
            from .pg_session_store import PgSessionStore

            # 影子写入带上归属智能体，切换读路径后各员工会话不互覆
            shadow = PgSessionStore(agent_id=agent_id)
        self._primary = primary
        self._shadow = shadow
        self.shadow_write_failures = 0
        self._shadow_tasks: set[asyncio.Task] = set()

    def _shadow_write(self, coro_factory, what: str) -> None:
        """Schedule a fire-and-forget shadow write; failures only count."""
        async def _run() -> None:
            try:
                await coro_factory()
            except Exception as exc:  # noqa: BLE001 - shadow must not raise
                self.shadow_write_failures += 1
                logger.warning(
                    "Dual-write session shadow %s failed "
                    "(primary unaffected): %s",
                    what,
                    exc,
                )

        try:
            task = asyncio.get_running_loop().create_task(_run())
        except RuntimeError:
            task = None
            try:
                asyncio.run(_run())
            except Exception as exc:  # noqa: BLE001
                self.shadow_write_failures += 1
                logger.warning(
                    "Dual-write session shadow %s failed "
                    "(primary unaffected): %s",
                    what,
                    exc,
                )
        if task is not None:
            self._shadow_tasks.add(task)
            task.add_done_callback(self._shadow_tasks.discard)

    async def drain_shadow(self) -> None:
        """Await all in-flight shadow writes (tests + cutover)."""
        if self._shadow_tasks:
            await asyncio.gather(
                *list(self._shadow_tasks),
                return_exceptions=True,
            )

    def shadow_stats(self) -> dict:
        return {
            "shadow_write_failures": self.shadow_write_failures,
            "in_flight": len(self._shadow_tasks),
        }

    # -- contract -------------------------------------------------------------

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        **state_modules_mapping,
    ) -> None:
        await self._primary.save_session_state(
            session_id,
            user_id=user_id,
            channel=channel,
            **state_modules_mapping,
        )
        self._shadow_write(
            lambda: self._shadow.save_session_state(
                session_id,
                user_id=user_id,
                channel=channel,
                **state_modules_mapping,
            ),
            "save",
        )

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        await self._primary.load_session_state(
            session_id,
            user_id=user_id,
            channel=channel,
            allow_not_exist=allow_not_exist,
            **state_modules_mapping,
        )

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        channel: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        await self._primary.update_session_state(
            session_id,
            key,
            value,
            user_id=user_id,
            channel=channel,
            create_if_not_exist=create_if_not_exist,
        )
        self._shadow_write(
            lambda: self._shadow.update_session_state(
                session_id,
                key,
                value,
                user_id=user_id,
                channel=channel,
                create_if_not_exist=create_if_not_exist,
            ),
            "update",
        )

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        return await self._primary.get_session_state_dict(
            session_id,
            user_id=user_id,
            channel=channel,
            allow_not_exist=allow_not_exist,
        )
