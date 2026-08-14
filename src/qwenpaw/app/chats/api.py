# -*- coding: utf-8 -*-
"""Chat management API."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agentscope.message import Msg
from agentscope.state import AgentState

from .session import SafeJSONSession
from .manager import ChatManager, MAX_BATCH_SIZE
from .models import (
    BatchArchiveResult,
    ChatSpec,
    ChatUpdate,
    ChatHistory,
)
from .utils import agentscope_msg_to_message, parse_legacy_memory_state
from ...services.project_directory import (
    resolve_effective_project_dir,
    session_project_dir,
)
from ...checkpoints.runtime import RUNTIME as CHECKPOINT_RUNTIME

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/chats", tags=["chats"])


async def get_workspace(request: Request):
    """Get the workspace for the active agent."""
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


async def get_chat_manager(
    request: Request,
) -> ChatManager:
    """Get the chat manager for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        ChatManager instance for the specified agent

    Raises:
        HTTPException: If manager is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.chat_manager


async def get_session(
    request: Request,
) -> SafeJSONSession:
    """Get the session for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        SafeJSONSession instance for the specified agent

    Raises:
        HTTPException: If session is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.session


class ProjectDirectoryUpdate(BaseModel):
    """Controlled Session project directory update."""

    project_dir: str


async def get_owned_chat(
    chat_id: str,
    request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
) -> ChatSpec:
    """Load one chat and enforce ownership for authenticated callers (M1).

    Returns 404 (never 403) when the chat belongs to another account, so
    the existence of other users' chats is never disclosed.  When auth is
    disabled there is no authenticated identity and the check is skipped
    (single-user semantics).
    """
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    authenticated_user = getattr(request.state, "user", None)
    if authenticated_user and chat.effective_owner != authenticated_user:
        logger.warning(
            "User %r blocked from chat %s (owner %r)",
            authenticated_user,
            chat_id,
            chat.effective_owner,
        )
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


async def _project_directory_response(chat: ChatSpec, workspace) -> dict:
    """Build the effective Session project directory response."""
    from ...config.config import load_agent_config

    def _build() -> dict:
        agent_config = load_agent_config(workspace.agent_id)
        project_dir, source = resolve_effective_project_dir(
            workspace.workspace_dir,
            agent_project_dir=agent_config.project_dir,
            session_override=session_project_dir(chat.meta),
        )
        return {
            "project_dir": str(project_dir),
            "source": source,
            "agent_project_dir": agent_config.project_dir,
            "exists": project_dir.is_dir(),
        }

    return await asyncio.to_thread(_build)


@router.get("", response_model=list[ChatSpec])
async def list_chats(
    request: Request,
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    archived: Optional[bool] = Query(
        None,
        description=(
            "Filter by archived status. "
            "false=active only, true=archived only, "
            "null/omit=all (default)"
        ),
    ),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """List all chats with optional filters.

    When ``archived`` is omitted, returns all chats (both active and archived).
    Pass ``archived=false`` for active only,
    ``archived=true`` for archived only.

    M1: an authenticated caller only ever sees their own chats — the
    ``user_id`` query parameter is advisory and can never widen the
    result beyond the verified identity.
    """
    authenticated_user = getattr(request.state, "user", None)
    if authenticated_user:
        if user_id and user_id != authenticated_user:
            logger.warning(
                "Ignoring user_id=%r query param from authenticated user %r",
                user_id,
                authenticated_user,
            )
        user_id = authenticated_user

    chats = await mgr.list_chats(
        user_id=user_id,
        channel=channel,
        archived=archived,
    )
    tracker = workspace.task_tracker
    statuses = await tracker.get_status_many([spec.id for spec in chats])
    return [
        spec.model_copy(update={"status": statuses.get(spec.id, "idle")})
        for spec in chats
    ]


@router.post("", response_model=ChatSpec)
async def create_chat(
    request: ChatSpec,
    http_request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Create a new chat.

    Server generates chat_id (UUID) automatically.  When authentication
    is enabled the chat is always owned by the verified caller — any
    client-claimed ``user_id``/``owner_id`` is discarded (M1).

    Args:
        request: Chat creation request
        http_request: FastAPI request (carries the verified identity)
        mgr: Chat manager dependency

    Returns:
        Created chat spec with UUID
    """
    authenticated_user = getattr(http_request.state, "user", None)
    effective_user = authenticated_user or request.user_id
    chat_id = str(uuid4())
    spec = ChatSpec(
        id=chat_id,
        name=request.name,
        session_id=request.session_id,
        user_id=effective_user,
        owner_id=effective_user,
        channel=request.channel,
        meta=request.meta,
    )
    return await mgr.create_chat(spec)


@router.post("/batch-delete", response_model=dict)
async def batch_delete_chats(
    chat_ids: list[str],
    http_request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Delete chats by chat IDs.

    M1: authenticated callers can only delete their own chats; foreign
    IDs are silently dropped from the batch.

    Args:
        chat_ids: List of chat IDs
        mgr: Chat manager dependency
    Returns:
        True if deleted, False if failed

    """
    chats = {chat.id: chat for chat in await mgr.list_chats(archived=None)}
    authenticated_user = getattr(http_request.state, "user", None)
    if authenticated_user:
        chat_ids = [
            cid
            for cid in chat_ids
            if (c := chats.get(cid)) is not None
            and c.effective_owner == authenticated_user
        ]
    deleted = await mgr.delete_chats(chat_ids=chat_ids)
    if deleted:
        await CHECKPOINT_RUNTIME.delete_session_checkpoints(
            workspace,
            [
                (chat.session_id, chat.user_id, chat.channel)
                for chat_id in chat_ids
                if (chat := chats.get(chat_id)) is not None
            ],
        )
    return {"deleted": deleted}


# ----- Archive endpoints -----


class BatchChatIds(BaseModel):
    """Request body for batch archive/unarchive."""

    chat_ids: list[str] = Field(
        ...,
        max_length=MAX_BATCH_SIZE,
        description="List of chat IDs to process",
    )


async def _owned_chat_ids(
    chat_ids: list[str],
    request: Request,
    mgr: ChatManager,
) -> list[str]:
    """Drop IDs not owned by the authenticated caller (M1).

    One list + in-memory membership check (no per-id queries).  When auth
    is disabled the batch passes through unchanged.
    """
    authenticated_user = getattr(request.state, "user", None)
    if not authenticated_user:
        return chat_ids
    owned_ids = {
        c.id
        for c in await mgr.list_chats(archived=None)
        if c.effective_owner == authenticated_user
    }
    return [cid for cid in chat_ids if cid in owned_ids]


@router.post("/actions/batch-archive", response_model=BatchArchiveResult)
async def batch_archive_chats(
    payload: BatchChatIds,
    http_request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Batch archive chats. Running chats are skipped."""
    tracker = workspace.task_tracker
    return await mgr.batch_archive(
        chat_ids=await _owned_chat_ids(payload.chat_ids, http_request, mgr),
        get_status=tracker.get_status,
    )


@router.post("/actions/batch-unarchive", response_model=BatchArchiveResult)
async def batch_unarchive_chats(
    payload: BatchChatIds,
    http_request: Request,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Batch unarchive chats."""
    return await mgr.batch_unarchive(
        chat_ids=await _owned_chat_ids(payload.chat_ids, http_request, mgr),
    )


@router.post("/{chat_id}/archive", response_model=ChatSpec)
async def archive_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
    _owned: ChatSpec = Depends(get_owned_chat),
):
    """Archive a single chat. Idempotent.

    Returns 409 if the chat is currently running.
    """
    status = await workspace.task_tracker.get_status(chat_id)
    try:
        result = await mgr.archive_chat(chat_id, check_status=status)
    except ValueError as e:
        raise HTTPException(
            status_code=409,
            detail="Chat is currently in progress, cannot archive",
        ) from e
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return result


@router.post("/{chat_id}/unarchive", response_model=ChatSpec)
async def unarchive_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    _owned: ChatSpec = Depends(get_owned_chat),
):
    """Unarchive a single chat. Idempotent."""
    result = await mgr.unarchive_chat(chat_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return result


@router.get("/{chat_id}/project-dir")
async def get_chat_project_dir(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
    _owned: ChatSpec = Depends(get_owned_chat),
) -> dict:
    """Return the Session override and effective project directory."""
    chat = await mgr.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


@router.put("/{chat_id}/project-dir")
async def set_chat_project_dir(
    chat_id: str,
    body: ProjectDirectoryUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
    _owned: ChatSpec = Depends(get_owned_chat),
) -> dict:
    """Persist a validated Session project directory override."""

    def _resolve_target() -> Path:
        target = Path(body.project_dir).expanduser().resolve()
        if not target.is_dir():
            raise NotADirectoryError(str(target))
        return target

    try:
        target = await asyncio.to_thread(_resolve_target)
    except NotADirectoryError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Project directory is unavailable: {exc}",
        ) from exc
    chat = await mgr.set_project_dir(chat_id, str(target))
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


@router.delete("/{chat_id}/project-dir")
async def clear_chat_project_dir(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
    _owned: ChatSpec = Depends(get_owned_chat),
) -> dict:
    """Clear the override and inherit the Agent default project directory."""
    chat = await mgr.set_project_dir(chat_id, None)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return await _project_directory_response(chat, workspace)


# ----- Existing CRUD endpoints -----


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    session: SafeJSONSession = Depends(get_session),
    workspace=Depends(get_workspace),
    owned: ChatSpec = Depends(get_owned_chat),
):
    """Get detailed information about a specific chat by UUID.

    Args:
        chat_id: Chat UUID
        mgr: Chat manager dependency
        session: SafeJSONSession dependency
        owned: Ownership-checked chat (M1; 404 when foreign)

    Returns:
        ChatHistory with messages and status (idle/running)

    Raises:
        HTTPException: If chat not found (404)
    """
    chat_spec = owned

    state = await session.get_session_state_dict(
        chat_spec.session_id,
        chat_spec.user_id,
        chat_spec.channel,
    )
    backend = workspace.config.backend
    context = ((state.get("agent") or {}).get("state") or {}).get("context")
    if not context and backend != "qwenpaw":
        try:
            await workspace.harness_runtime.hydrate_session(
                backend=backend,
                session_id=chat_spec.session_id,
                user_id=chat_spec.user_id,
                channel=chat_spec.channel,
                settings=dict(workspace.config.backend_settings),
            )
            state = await session.get_session_state_dict(
                chat_spec.session_id,
                chat_spec.user_id,
                chat_spec.channel,
            )
        except Exception:
            logger.debug(
                "Third-party session recovery failed for %s",
                chat_spec.session_id,
                exc_info=True,
            )
    status = await workspace.task_tracker.get_status(chat_id)
    if not state:
        return ChatHistory(messages=[], status=status)

    agent_raw = state.get("agent", {})
    memories: list[Msg] = []

    state_raw = agent_raw.get("state")
    if isinstance(state_raw, dict):
        try:
            agent_state = AgentState.model_validate(state_raw)
            memories = list(agent_state.context)
        except Exception:
            logger.debug(
                "Failed to parse agent.state, falling back to legacy",
                exc_info=True,
            )

    # Legacy fallback: 1.x ``agent.memory`` format.
    if not memories:
        memory_raw = agent_raw.get("memory", {})
        if memory_raw:
            memories, _summary = parse_legacy_memory_state(memory_raw)

    messages = agentscope_msg_to_message(memories)
    return ChatHistory(messages=messages, status=status)


@router.put("/{chat_id}", response_model=ChatSpec)
async def update_chat(
    chat_id: str,
    spec: ChatUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
    _owned: ChatSpec = Depends(get_owned_chat),
):
    """Update an existing chat.

    Args:
        chat_id: Chat UUID
        spec: Partial chat update payload
        mgr: Chat manager dependency

    Returns:
        Updated chat spec

    Raises:
        HTTPException: If chat not found (404)
    """
    updated = await mgr.patch_chat(chat_id, spec)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return updated


@router.delete("/{chat_id}", response_model=dict)
async def delete_chat(
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
    _owned: ChatSpec = Depends(get_owned_chat),
):
    """Delete a chat by UUID.

    Note: This only deletes the chat spec (UUID mapping).
    JSONSession state is NOT deleted.

    Args:
        chat_id: Chat UUID
        mgr: Chat manager dependency

    Returns:
        True if deleted, False if failed

    Raises:
        HTTPException: If chat not found (404)
    """
    chat = _owned
    deleted = await mgr.delete_chats(chat_ids=[chat_id])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    if chat is not None:
        await CHECKPOINT_RUNTIME.delete_session_checkpoints(
            workspace,
            [(chat.session_id, chat.user_id, chat.channel)],
        )
    return {"deleted": True}
