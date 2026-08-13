# -*- coding: utf-8 -*-
"""Abstract session store contract.

Defines the persistence interface for agent session state so the concrete
backend (JSON files today, PostgreSQL from the M2 milestone) can be swapped
behind ``qwenpaw.app.chats.factory`` without touching callers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence, Union


class BaseSessionStore(ABC):
    """Abstract contract for session state persistence backends.

    A *state module* is any object exposing ``state_dict()`` and
    ``load_state_dict(dict)`` (see ``qwenpaw.runtime._state_utils.StateProxy``
    for the minimal shape). Implementations must provide the same semantics
    as the JSON reference implementation in ``session.py``:

    - ``load_session_state`` with ``allow_not_exist=True`` silently skips a
      missing session; with ``False`` it raises ``AgentStateError``.
    - ``get_session_state_dict`` with ``allow_not_exist=True`` returns an
      empty dict for a missing session; with ``False`` it raises
      ``AgentStateError``.
    - ``update_session_state`` accepts a dotted string or a key sequence and
      creates intermediate mappings as needed.
    """

    @abstractmethod
    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        **state_modules_mapping,
    ) -> None:
        """Persist the given state modules for one session."""
        raise NotImplementedError

    @abstractmethod
    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        """Load persisted state into the given state modules."""
        raise NotImplementedError

    @abstractmethod
    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        channel: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        """Set one (possibly nested) key inside the persisted session state."""
        raise NotImplementedError

    @abstractmethod
    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        """Return the raw persisted state dict for one session."""
        raise NotImplementedError
