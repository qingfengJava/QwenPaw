# -*- coding: utf-8 -*-
"""XianWork user workspaces: registered disk directories per account.

A workspace is purely a "directory → display name" registry row in
``xian_workspaces``. Chat binding reuses the existing Session project
directory mechanism (``chats.meta.runtime_context.project_dir`` via
``ChatManager.set_project_dir``), so the ``chats`` schema is never
touched and the agent Harness keeps a single source of truth for its
working directory. Sidebar task/workspace grouping therefore matches
each chat's ``project_dir`` against workspace ``dir_path`` server-side
(both sides normalized), never on the client — dodging Windows
drive-letter case and separator pitfalls.

Harness note: binding changes take effect from the *next* turn. The
console dispatch resolves ``request_context.project_dir`` per turn
(``routers/console.py``), so a rebind between turns simply swaps the
agent's cwd/file_guard snapshot; running turns are rejected with 409
to keep the semantics explicit.

Deleting a workspace only removes the registry row (plus unbinding its
chats); the on-disk directory is never touched.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ...agent_context import get_agent_for_request
from ...enterprise import current_tenant_id, require_enterprise_engine
from ....services.project_directory import (
    normalize_project_dir,
    session_project_dir,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["xian-workspaces"])


def _viewer(request: Request) -> str:
    return getattr(request.state, "user", None) or "local"


def _dir_key(value: str | Path) -> str:
    """Platform-stable match key for directory comparison (server-side).

    ``os.path.normcase`` folds path case (and slashes) on Windows and is
    a no-op on POSIX, so a registered ``dir_path`` and a chat's
    ``project_dir`` compare equal regardless of the casing the user
    typed on either surface.
    """
    return os.path.normcase(str(normalize_project_dir(value)))


async def _load_workspace(
    engine,
    tenant_id: str,
    viewer: str,
    workspace_id: str,
) -> dict[str, Any]:
    """Load one owned workspace row or raise 404 (never leaks others')."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, name, dir_path, created_at, updated_at "
                "FROM xian_workspaces "
                "WHERE tenant_id = :tid AND id = :id AND owner_id = :owner"
            ),
            {"tid": tenant_id, "id": workspace_id, "owner": viewer},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return dict(row)


def _owned_chat_filter(request: Request):
    """Return the effective_owner predicate for the caller (M1).

    ``None`` means auth is disabled: every chat is visible (single-user
    semantics), matching ``chats/api.py::_owned_chat_ids``.
    """
    authenticated_user = getattr(request.state, "user", None)

    def _own(chat) -> bool:
        if not authenticated_user:
            return True
        return chat.effective_owner == authenticated_user

    return _own


class WorkspaceCreateBody(BaseModel):
    """POST /workspaces body."""

    name: str = Field(description="Display name shown in the sidebar")
    dir_path: str = Field(description="Absolute directory path to register")
    create: bool = Field(
        default=False,
        description="Create the directory (mkdir -p) when missing",
    )


class WorkspaceRenameBody(BaseModel):
    """PATCH /workspaces/{id} body (display name only; disk untouched)."""

    name: str


class WorkspaceChatsBody(BaseModel):
    """PUT /workspaces/{id}/chats body."""

    chat_ids: list[str] = Field(default_factory=list)


@router.get("", summary="List workspaces with optional chat grouping")
async def list_workspaces(
    request: Request,
    include_chats: bool = False,
) -> dict:
    """Owned workspaces; with ``include_chats=true`` also group chats.

    Server-side grouping: every active console chat owned by the caller
    is matched (normalized, case-folded per platform) against each
    workspace ``dir_path``. Hits nest under their workspace; everything
    else (no project_dir, or a directory set from the console plane that
    is not registered as a workspace) falls into ``unbound_chats``. Both
    groups sort by ``updated_at`` desc.
    """
    engine = require_enterprise_engine()
    tenant_id = current_tenant_id()
    viewer = _viewer(request)

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, name, dir_path, created_at, updated_at "
                "FROM xian_workspaces "
                "WHERE tenant_id = :tid AND owner_id = :owner "
                "ORDER BY updated_at DESC"
            ),
            {"tid": tenant_id, "owner": viewer},
        )
        rows = [dict(r) for r in result.mappings().all()]

    workspaces: list[dict[str, Any]] = []
    grouped: dict[str, list] = {}
    unbound: list = []

    chat_manager = None
    if include_chats:
        workspace = await get_agent_for_request(request)
        chat_manager = workspace.chat_manager

    if include_chats and chat_manager is not None:
        chats = [
            c
            for c in await chat_manager.list_chats(
                channel="console",
                archived=False,
            )
            if _owned_chat_filter(request)(c)
        ]

        def _group() -> tuple[dict[str, list], list]:
            key_to_id: dict[str, str] = {}
            for ws in rows:
                key_to_id.setdefault(_dir_key(ws["dir_path"]), ws["id"])
            buckets: dict[str, list] = {ws["id"]: [] for ws in rows}
            rest: list = []
            norm_cache: dict[str, str] = {}
            for chat in chats:
                raw = session_project_dir(chat.meta)
                ws_id = None
                if raw:
                    if raw not in norm_cache:
                        norm_cache[raw] = _dir_key(raw)
                    ws_id = key_to_id.get(norm_cache[raw])
                if ws_id is not None:
                    buckets[ws_id].append(chat)
                else:
                    rest.append(chat)
            return buckets, rest

        grouped, unbound = await asyncio.to_thread(_group)

    for ws in rows:
        items = sorted(
            grouped.get(ws["id"], []),
            key=lambda c: c.updated_at,
            reverse=True,
        )
        entry = {**ws, "chats_count": len(items)}
        if include_chats:
            entry["chats"] = [c.model_dump() for c in items]
        workspaces.append(entry)

    unbound.sort(key=lambda c: c.updated_at, reverse=True)
    return {
        "workspaces": workspaces,
        "unbound_chats": (
            [c.model_dump() for c in unbound] if include_chats else []
        ),
    }


@router.post("", status_code=201, summary="Register a workspace directory")
async def create_workspace(body: WorkspaceCreateBody, request: Request) -> dict:
    """Register one disk directory as a workspace.

    ``create=true`` mkdirs the directory (parents allowed); otherwise the
    path must already exist and be a directory. Sensitive directories
    (file-guard blacklist), the home directory itself and system roots
    are rejected. The stored ``dir_path`` is always the server-side
    ``expanduser().resolve()`` form.
    """
    engine = require_enterprise_engine()
    tenant_id = current_tenant_id()
    viewer = _viewer(request)

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    raw_dir = body.dir_path.strip()
    if not raw_dir:
        raise HTTPException(status_code=400, detail="dir_path cannot be empty")

    def _prepare() -> Path:
        from ....security.tool_guard.guardians.file_guardian import (
            FilePathToolGuardian,
        )

        target = normalize_project_dir(raw_dir)
        if target == Path(target.anchor):
            raise ValueError(f"System root cannot be a workspace: {target}")
        home = Path.home().resolve()
        if target == home:
            raise ValueError(
                f"Home directory itself cannot be a workspace: {home}",
            )
        if FilePathToolGuardian()._is_sensitive(str(target)):
            raise ValueError(
                f"Sensitive directory cannot be a workspace: {target}",
            )
        if body.create:
            target.mkdir(parents=True, exist_ok=True)
        else:
            if not target.exists():
                raise FileNotFoundError(str(target))
            if not target.is_dir():
                raise NotADirectoryError(str(target))
        return target

    try:
        target = await asyncio.to_thread(_prepare)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Path does not exist: {exc}",
        ) from exc
    except NotADirectoryError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Path is not a directory: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot create directory: {exc}",
        ) from exc

    workspace_id = uuid.uuid4().hex
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO xian_workspaces "
                    "(tenant_id, id, owner_id, name, dir_path) "
                    "VALUES (:tid, :id, :owner, :name, :dir)",
                ),
                {
                    "tid": tenant_id,
                    "id": workspace_id,
                    "owner": viewer,
                    "name": name,
                    "dir": str(target),
                },
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="This directory is already registered as a workspace",
        ) from exc
    return await _load_workspace(engine, tenant_id, viewer, workspace_id)


@router.patch(
    "/{workspace_id}",
    summary="Rename a workspace (display name only)",
)
async def rename_workspace(
    workspace_id: str,
    body: WorkspaceRenameBody,
    request: Request,
) -> dict:
    """Rename the workspace; the on-disk directory is never touched."""
    engine = require_enterprise_engine()
    tenant_id = current_tenant_id()
    viewer = _viewer(request)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE xian_workspaces SET name = :name, updated_at = now() "
                "WHERE tenant_id = :tid AND id = :id AND owner_id = :owner",
            ),
            {"name": name, "tid": tenant_id, "id": workspace_id, "owner": viewer},
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Workspace not found")
    return await _load_workspace(engine, tenant_id, viewer, workspace_id)


@router.delete(
    "/{workspace_id}",
    summary="Delete a workspace registration (never touches disk)",
)
async def delete_workspace(workspace_id: str, request: Request) -> dict:
    """Remove the registry row and unbind its chats.

    Chats whose ``project_dir`` matches this workspace fall back to the
    plain task list (their override is cleared). The directory itself,
    and any files the agent produced inside it, are left untouched.
    """
    engine = require_enterprise_engine()
    tenant_id = current_tenant_id()
    viewer = _viewer(request)
    ws = await _load_workspace(engine, tenant_id, viewer, workspace_id)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM xian_workspaces "
                "WHERE tenant_id = :tid AND id = :id AND owner_id = :owner",
            ),
            {"tid": tenant_id, "id": workspace_id, "owner": viewer},
        )

    unbound_count = 0
    workspace = await get_agent_for_request(request)
    chat_manager = workspace.chat_manager
    if chat_manager is not None:
        own = _owned_chat_filter(request)
        ws_key = await asyncio.to_thread(_dir_key, ws["dir_path"])
        chats = await chat_manager.list_chats(channel="console", archived=None)
        for chat in chats:
            if not own(chat):
                continue
            raw = session_project_dir(chat.meta)
            if not raw:
                continue
            if await asyncio.to_thread(_dir_key, raw) == ws_key:
                await chat_manager.set_project_dir(chat.id, None)
                unbound_count += 1
    return {"deleted": True, "unbound_chats": unbound_count}


@router.put(
    "/{workspace_id}/chats",
    summary="Bind chats to a workspace (effective next turn)",
)
async def bind_workspace_chats(
    workspace_id: str,
    body: WorkspaceChatsBody,
    request: Request,
) -> dict:
    """Set the Session project_dir of each chat to the workspace path.

    Ownership follows the chats-plane rule: foreign chat IDs are
    silently dropped (404 semantics without disclosing existence).
    Running chats reject the whole batch with 409 — the rebind takes
    effect from the next turn's ``request_context`` snapshot, and
    refusing mid-run keeps that contract explicit.
    """
    engine = require_enterprise_engine()
    tenant_id = current_tenant_id()
    viewer = _viewer(request)
    ws = await _load_workspace(engine, tenant_id, viewer, workspace_id)

    workspace = await get_agent_for_request(request)
    chat_manager = workspace.chat_manager
    if chat_manager is None:
        raise HTTPException(status_code=503, detail="Chat manager unavailable")

    own = _owned_chat_filter(request)
    chats = {c.id: c for c in await chat_manager.list_chats(archived=None)}
    targets = [cid for cid in body.chat_ids if cid in chats and own(chats[cid])]

    running = [
        chats[cid].name or cid
        for cid in targets
        if chats[cid].status == "running"
    ]
    if running:
        raise HTTPException(
            status_code=409,
            detail=(
                "Chat is currently in progress, cannot rebind: "
                + ", ".join(running)
            ),
        )

    bound = 0
    for cid in targets:
        if await chat_manager.set_project_dir(cid, ws["dir_path"]):
            bound += 1
    return {"bound": bound}


@router.delete(
    "/{workspace_id}/chats/{chat_id}",
    summary="Unbind one chat (falls back to the agent default directory)",
)
async def unbind_workspace_chat(
    workspace_id: str,
    chat_id: str,
    request: Request,
) -> dict:
    """Clear the chat's Session project_dir override.

    The chat returns to the plain task list and its next turn inherits
    the agent's configured directory again.
    """
    engine = require_enterprise_engine()
    tenant_id = current_tenant_id()
    viewer = _viewer(request)
    await _load_workspace(engine, tenant_id, viewer, workspace_id)

    workspace = await get_agent_for_request(request)
    chat_manager = workspace.chat_manager
    if chat_manager is None:
        raise HTTPException(status_code=503, detail="Chat manager unavailable")

    chat = await chat_manager.get_chat(chat_id)
    if chat is None or not _owned_chat_filter(request)(chat):
        raise HTTPException(status_code=404, detail="Chat not found")
    if chat.status == "running":
        raise HTTPException(
            status_code=409,
            detail="Chat is currently in progress, cannot unbind",
        )
    await chat_manager.set_project_dir(chat_id, None)
    return {"unbound": True}


@router.post(
    "/{workspace_id}/open-folder",
    summary="Open the workspace folder in the host file explorer",
)
async def open_workspace_folder(workspace_id: str, request: Request) -> dict:
    """Launch the OS file explorer at the workspace directory.

    Local deployments open Explorer/Finder/xdg directly. Remote or
    headless deployments cannot: 409 carries the absolute path so the
    frontend can fall back to copy-path + in-app browsing.
    """
    engine = require_enterprise_engine()
    tenant_id = current_tenant_id()
    viewer = _viewer(request)
    ws = await _load_workspace(engine, tenant_id, viewer, workspace_id)
    path = ws["dir_path"]

    def _open() -> None:
        if not Path(path).is_dir():
            raise FileNotFoundError(path)
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(
                ["open", path],
                check=True,
                capture_output=True,
                timeout=10,
            )
        else:
            subprocess.run(
                ["xdg-open", path],
                check=True,
                capture_output=True,
                timeout=10,
            )

    try:
        await asyncio.to_thread(_open)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Directory missing on server: {path}",
        ) from exc
    except Exception as exc:  # OSError / CalledProcessError / headless
        logger.info("open-folder failed for %s: %r", path, exc)
        raise HTTPException(
            status_code=409,
            detail=f"Cannot open folder on this deployment; path: {path}",
        ) from exc
    return {"opened": True, "path": path}
