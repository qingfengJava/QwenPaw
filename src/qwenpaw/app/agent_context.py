# -*- coding: utf-8 -*-
"""Agent context utilities for multi-agent support.

Provides utilities to get the correct agent instance for each request.
"""
import asyncio
import logging
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from typing import Optional, TYPE_CHECKING
from fastapi import Request
from .multi_agent_manager import MultiAgentManager
from ..config.utils import load_config

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .workspace import Workspace

# Context variable to store current agent ID across async calls
_current_agent_id: ContextVar[Optional[str]] = ContextVar(
    "current_agent_id",
    default=None,
)

# Context variable to store current session id across async calls
_current_session_id: ContextVar[Optional[str]] = ContextVar(
    "current_session_id",
    default=None,
)

# Context variable to store current root session id for cross-session approval
_current_root_session_id: ContextVar[Optional[str]] = ContextVar(
    "current_root_session_id",
    default=None,
)

_current_user_id: ContextVar[Optional[str]] = ContextVar(
    "current_user_id",
    default=None,
)

_current_channel: ContextVar[Optional[str]] = ContextVar(
    "current_channel",
    default=None,
)

_current_approval_route: ContextVar[Optional[dict]] = ContextVar(
    "current_approval_route",
    default=None,
)


async def get_agent_for_request(
    request: Request,
    agent_id: Optional[str] = None,
) -> "Workspace":
    """Get agent workspace for current request.

    Priority:
    1. agent_id parameter (explicit override)
    2. request.state.agent_id (from agent-scoped router)
    3. X-Agent-Id header (from frontend)
    4. Active agent from config

    Args:
        request: FastAPI request object
        agent_id: Agent ID override (highest priority)

    Returns:
        Workspace for the specified or active agent

    Raises:
        HTTPException: If agent not found
    """
    from fastapi import HTTPException

    # Determine which agent to use
    target_agent_id = agent_id

    # Check request.state.agent_id (set by agent-scoped router)
    if not target_agent_id and hasattr(request.state, "agent_id"):
        target_agent_id = request.state.agent_id

    # Check X-Agent-Id header
    if not target_agent_id:
        target_agent_id = request.headers.get("X-Agent-Id")

    # Load config once for fallback and validation
    config = None
    if not target_agent_id:
        # Fallback to active agent from config
        config = load_config()
        target_agent_id = config.agents.active_agent or "default"

    # Check if agent exists and is enabled
    if config is None:
        config = load_config()
    if target_agent_id not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{target_agent_id}' not found",
        )

    agent_ref = config.agents.profiles[target_agent_id]
    if not getattr(agent_ref, "enabled", True):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{target_agent_id}' is disabled",
        )

    # XianWork enterprise: when RBAC enforcement is on and the caller
    # targets a published expert (via X-Agent-Id or the agent-scoped
    # router), verify the agent ACL so a forged header cannot reach an
    # unpublished/ unauthorized expert. Absent ACL = unrestricted.
    _enforce_expert_acl(request, target_agent_id)

    # Get MultiAgentManager
    if not hasattr(request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )

    manager: MultiAgentManager = request.app.state.multi_agent_manager

    try:
        workspace = await manager.get_agent(target_agent_id)
        if not workspace:
            raise HTTPException(
                status_code=404,
                detail=f"Agent '{target_agent_id}' not found",
            )
        return workspace
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get agent: {str(e)}",
        ) from e


def _enforce_expert_acl(request: Request, agent_id: str) -> None:
    """Reject forged expert access when RBAC enforcement is active.

    Only agents published by the XianWork expert plane carry the
    ``expert_``/``team_`` prefix; everything else keeps the existing
    behavior. The check mirrors ``rbac.store.agent_allowed`` semantics
    (absent grant = unrestricted) and is a no-op while
    ``QWENPAW_RBAC_ENFORCE`` is off (gray rollout).
    """
    if not agent_id.startswith(("expert_", "team_")):
        return
    try:
        from .rbac.deps import rbac_enforcement_enabled

        if not rbac_enforcement_enabled():
            return
        username = getattr(request.state, "user", None) or ""
        if not username:
            # No authenticated identity under enforce: fail closed.
            raise HTTPException(
                status_code=403,
                detail="RBAC: no authenticated identity",
            )
        from .rbac.store import get_rbac_store
        from .users.store import get_user_store

        user = get_user_store().get_user(username)
        flat_role = user.role if user is not None else ""
        if not get_rbac_store().agent_allowed(
            username,
            agent_id,
            flat_role=flat_role,
        ):
            raise HTTPException(
                status_code=403,
                detail=f"No access to expert '{agent_id}'",
            )
    except HTTPException:
        raise
    except Exception:  # pylint: disable=broad-except
        # ACL infrastructure failure must not take down agent resolution;
        # log and allow (enforcement stays a gray-rollout backstop).
        logger.warning(
            "expert ACL check errored for %s", agent_id, exc_info=True
        )


def get_agent_project_dir(workspace: "Workspace") -> Path:
    """Return the agent's default project directory.

    The Coding tools switch does not participate in directory resolution.
    """
    from ..config.config import load_agent_config
    from ..services.project_directory import resolve_effective_project_dir

    try:
        config = load_agent_config(workspace.agent_id)
        project_dir = config.project_dir
    except Exception:
        project_dir = None

    return resolve_effective_project_dir(
        workspace.workspace_dir,
        agent_project_dir=project_dir,
    )[0]


async def get_project_dir_for_request(
    request: Request,
    workspace: "Workspace",
) -> Path:
    """Resolve the effective project directory for a Files API request."""
    from ..config.config import load_agent_config
    from ..services.project_directory import (
        resolve_effective_project_dir,
        session_project_dir,
    )

    session_override = None
    pending_override = None
    chat_id = request.headers.get("X-Chat-Id")
    if chat_id:
        chat = await workspace.chat_manager.get_chat(chat_id)
        if chat is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Chat not found")
        session_override = session_project_dir(chat.meta)
    else:
        pending_override = request.headers.get("X-Session-Project-Dir")

    def _resolve() -> Path:
        try:
            config = load_agent_config(workspace.agent_id)
            agent_project_dir = config.project_dir
        except Exception:
            agent_project_dir = None
        resolved_override = session_override
        if not chat_id and pending_override:
            pending_path = Path(pending_override).expanduser().resolve()
            if not pending_path.is_dir():
                raise NotADirectoryError(str(pending_path))
            resolved_override = str(pending_path)
        return resolve_effective_project_dir(
            workspace.workspace_dir,
            agent_project_dir=agent_project_dir,
            session_override=resolved_override,
        )[0]

    try:
        return await asyncio.to_thread(_resolve)
    except NotADirectoryError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"Project directory is unavailable: {exc}",
        ) from exc


def get_active_agent_id() -> str:
    """Get current active agent ID from config.

    Returns:
        Active agent ID, defaults to "default"
    """
    try:
        config = load_config()
        return config.agents.active_agent or "default"
    except Exception:
        return "default"


def set_current_agent_id(agent_id: str) -> None:
    """Set current agent ID in context.

    Args:
        agent_id: Agent ID to set
    """
    _current_agent_id.set(agent_id)


def get_current_agent_id() -> str:
    """Get current agent ID from context or config fallback.

    Returns:
        Current agent ID, defaults to active agent or "default"
    """
    agent_id = _current_agent_id.get()
    if agent_id:
        return agent_id
    return get_active_agent_id()


def set_current_session_id(session_id: str) -> None:
    _current_session_id.set(session_id)


@contextmanager
def scoped_session_id(session_id: str) -> Iterator[None]:
    """Temporarily expose one session through the request context."""
    token = _current_session_id.set(session_id)
    try:
        yield
    finally:
        _current_session_id.reset(token)


def get_current_session_id() -> Optional[str]:
    return _current_session_id.get()


def set_current_root_session_id(root_session_id: Optional[str]) -> None:
    """Set current root session ID in context.

    Args:
        root_session_id: Root session ID to set
    """
    _current_root_session_id.set(root_session_id)


def get_current_root_session_id() -> Optional[str]:
    """Get current root session ID from context.

    Returns:
        Root session ID or None
    """
    return _current_root_session_id.get()


def set_current_user_id(user_id: Optional[str]) -> None:
    """Set current user ID in context."""
    _current_user_id.set(user_id)


@contextmanager
def scoped_user_id(user_id: Optional[str]) -> Iterator[None]:
    """Temporarily expose one user identity through the request context.

    Channel consume loops run inside long-lived queue worker tasks, so
    the identity must be reset when the message finishes; tasks spawned
    while the scope is active (e.g. TaskTracker runs) inherit it.
    """
    token = _current_user_id.set(user_id)
    try:
        yield
    finally:
        _current_user_id.reset(token)


def get_current_user_id() -> Optional[str]:
    """Get current user ID from context."""
    return _current_user_id.get()


def resolve_trusted_user_id(
    claimed: Optional[str],
    *,
    fallback: str,
    source: str = "",
    channel: Optional[str] = None,
) -> str:
    """Resolve the effective user id for one request (M1 shadow mode).

    An authenticated identity from the request context (set by
    ``AuthMiddleware`` after token verification, or by a channel driver
    after identity binding) always wins over a client-claimed
    ``user_id``; a mismatch is logged but the request proceeds with the
    trusted identity.  Without an authenticated identity the legacy
    fallback chain (``claimed`` → ``fallback``) applies unchanged.

    A claimed id that resolves to the trusted identity through the
    channel's ``identity_bindings`` entry is a legitimate mapping, not a
    spoofing attempt, so it does not raise a warning.
    """
    auth_user = get_current_user_id()
    if auth_user:
        if claimed and claimed != auth_user and claimed != fallback:
            if not _is_bound_identity(channel, claimed, auth_user):
                logger.warning(
                    "Ignoring client-claimed user_id %r%s; using "
                    "authenticated user %r",
                    claimed,
                    f" from {source}" if source else "",
                    auth_user,
                )
        return auth_user
    return claimed or fallback


def _is_bound_identity(
    channel: Optional[str],
    claimed: str,
    auth_user: str,
) -> bool:
    """True when ``claimed`` is bound to ``auth_user`` for ``channel``."""
    if not channel or not claimed:
        return False
    try:
        from .users.store import get_user_store

        return (
            get_user_store().resolve_identity(channel, claimed) == auth_user
        )
    except Exception:  # pylint: disable=broad-except
        return False


def set_current_channel(channel: Optional[str]) -> None:
    """Set current channel in context."""
    _current_channel.set(channel)


def get_current_channel() -> Optional[str]:
    """Get current channel from context."""
    return _current_channel.get()


def set_current_approval_route(route: Optional[dict]) -> None:
    """Set routing metadata used only for spawned-child approvals."""
    _current_approval_route.set(route)


def get_current_approval_route() -> Optional[dict]:
    """Return routing metadata used only for spawned-child approvals."""
    return _current_approval_route.get()
