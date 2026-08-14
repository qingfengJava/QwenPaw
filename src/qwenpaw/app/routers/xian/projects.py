# -*- coding: utf-8 -*-
"""Project endpoints for XianWork (projects / members / shared AI chat).

The shared-AI chat proxy reproduces the console chat execution chain but
stamps the trusted owner as ``project:{pid}`` so the runtime's per-owner
memory view yields one shared project vault (see ``projects.service``).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...chats.models import ChatSpec
from ...enterprise import current_tenant_id
from ...projects.models import (
    PROJECT_EDITOR,
    PROJECT_OWNER,
    AIBinding,
    CommentBody,
    MemberBody,
    MemberRoleBody,
    ProjectCreateBody,
    ProjectRecord,
    ProjectUpdateBody,
    role_at_least,
)
from ...projects.service import (
    ProjectService,
    get_project_service,
    project_owner_id,
)
from ..console import (
    _empty_sse_response,
    _extract_placeholder_name,
    _extract_session_and_payload,
    _is_reconnect_request,
)
from qwenpaw.schemas import AgentRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["xian-projects"])


def caller_username(request: Request) -> str:
    """Verified identity, or the ``local`` fallback (auth disabled)."""
    return getattr(request.state, "user", None) or "local"


async def _require_role(
    service: ProjectService,
    request: Request,
    project_id: str,
    minimum: str,
) -> ProjectRecord:
    """404 when the project is missing; 403 when the role is too low."""
    username = caller_username(request)
    project = await service.get_project(project_id, username)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if minimum and not role_at_least(project.member_role, minimum):
        raise HTTPException(
            status_code=403,
            detail=f"Requires project role >= {minimum}",
        )
    return project


@router.get("", response_model=list[ProjectRecord])
async def list_projects(
    request: Request,
    templates: bool = False,
    service: ProjectService = Depends(get_project_service),
):
    """Org-visible projects; ``templates=true`` lists template sources."""
    return await service.list_projects(
        username=caller_username(request),
        templates_only=templates,
    )


@router.post("", status_code=201, response_model=ProjectRecord)
async def create_project(
    body: ProjectCreateBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    """Create a project; the caller becomes its owner."""
    return await service.create_project(
        name=body.name,
        created_by=caller_username(request),
        description=body.description,
        department_id=body.department_id,
        template_tag=body.template_tag,
        instructions=body.instructions,
        ai_binding=body.ai_binding,
    )


@router.get("/{project_id}", response_model=ProjectRecord)
async def get_project(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    return await _require_role(service, request, project_id, "")


@router.patch("/{project_id}", response_model=ProjectRecord)
async def update_project(
    project_id: str,
    body: ProjectUpdateBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, PROJECT_EDITOR)
    record = await service.update_project(
        project_id,
        name=body.name,
        description=body.description,
        status=body.status,
        department_id=body.department_id,
        instructions=body.instructions,
        ai_binding=body.ai_binding,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await service.record_feed(
        project_id,
        actor=caller_username(request),
        kind="project_updated",
        payload={"name": record.name},
    )
    return record


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, PROJECT_OWNER)
    if not await service.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")


@router.post("/{project_id}/from-template/{template_tag}", status_code=201)
async def create_from_template(
    template_tag: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    """Instantiate a project from a template (copies template metadata;
    task lists stay with the template — teams start fresh)."""
    templates = await service.list_projects(templates_only=True)
    source = next(
        (t for t in templates if t.template_tag == template_tag),
        None,
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Template not found")
    record = await service.create_project(
        name=f"{source.name} (副本)"
        if source.template_tag
        else source.name,
        created_by=caller_username(request),
        description=source.description,
        ai_binding=source.ai_binding,
    )
    return record


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------


@router.get("/{project_id}/members")
async def list_members(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, "")
    return await service.list_members(project_id)


@router.post("/{project_id}/members", status_code=204)
async def add_member(
    project_id: str,
    body: MemberBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, PROJECT_OWNER)
    if not await service.upsert_member(
        project_id,
        body.username,
        body.role,
    ):
        raise HTTPException(status_code=400, detail="invalid role/project")


@router.patch("/{project_id}/members/{username}", status_code=204)
async def set_member_role(
    project_id: str,
    username: str,
    body: MemberRoleBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, PROJECT_OWNER)
    if not await service.upsert_member(
        project_id,
        username,
        body.role,
    ):
        raise HTTPException(status_code=400, detail="invalid role/project")


@router.delete("/{project_id}/members/{username}", status_code=204)
async def remove_member(
    project_id: str,
    username: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, PROJECT_OWNER)
    if not await service.remove_member(project_id, username):
        raise HTTPException(
            status_code=400,
            detail="member not removable (owner or not a member)",
        )


# ---------------------------------------------------------------------------
# feed (comments + activity stream + SSE)
# ---------------------------------------------------------------------------


@router.get("/{project_id}/feed")
async def list_feed(
    project_id: str,
    request: Request,
    before_id: int = 0,
    limit: int = 50,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, "")
    return await service.list_feed(
        project_id,
        before_id=before_id or None,
        limit=limit,
    )


@router.post("/{project_id}/comments", status_code=204)
async def post_comment(
    project_id: str,
    body: CommentBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, "")
    await service.record_feed(
        project_id,
        actor=caller_username(request),
        kind="comment",
        payload={"text": body.text[:2000]},
    )


# ---------------------------------------------------------------------------
# shared project AI chat (SSE proxy over the console execution chain)
# ---------------------------------------------------------------------------


def _resolve_agent_id(project: ProjectRecord) -> str:
    """Agent powering the project AI: its bound expert, else default."""
    binding = project.ai_binding
    if binding and binding.ref_id:
        if binding.kind == "expert_team":
            return f"team_{binding.ref_id}"
        return f"expert_{binding.ref_id}"
    return "default"


@router.post("/{project_id}/chat")
async def project_chat(
    project_id: str,
    request_data: Union[AgentRequest, dict],
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> StreamingResponse:
    """Stream the project-shared AI response (WorkBuddy bottom input).

    The chat is owned by the synthetic ``project:{pid}`` principal; the
    human caller is validated as a project member first and recorded in
    the chat meta (auditable) and the feed (visible).
    """
    project = await _require_role(service, request, project_id, "")
    username = caller_username(request)

    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="Agent runtime not ready")
    agent_id = _resolve_agent_id(project)
    try:
        workspace = await manager.get_agent(agent_id)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(
            status_code=404,
            detail=f"Project expert unavailable: {exc}",
        ) from exc

    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(status_code=503, detail="Channel Console not found")

    try:
        native_payload = _extract_session_and_payload(
            request_data,
            authenticated_user=None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Trusted re-stamp: the shared chat belongs to the project principal,
    # never the individual member (per-owner memory isolation follows).
    owner = project_owner_id(project_id)
    native_payload["sender_id"] = owner
    native_payload["meta"] = native_payload.get("meta") or {}
    native_payload["meta"]["project_id"] = project_id
    native_payload["meta"]["actor"] = username

    session_id = console_channel.resolve_session_id(
        sender_id=owner,
        channel_meta=native_payload["meta"],
    )
    name, first_text = _extract_placeholder_name(
        native_payload["content_parts"],
    )
    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        owner,
        native_payload["channel_id"],
        name=name,
    )
    # The project linkage is carried by the synthetic owner id itself
    # (``project:{pid}``); ``list_project_chats`` filters on it, so no
    # extra chat-meta write is needed here.

    tracker = workspace.task_tracker
    is_reconnect = _is_reconnect_request(request_data)

    if is_reconnect:
        queue = await tracker.attach(chat.id)
        if queue is None:
            return _empty_sse_response()
    else:
        from ...concurrency_gate import get_concurrency_gate

        gate = get_concurrency_gate()
        if gate.would_reject(owner):
            raise HTTPException(
                status_code=429,
                detail="Too many concurrent turns; please retry later.",
                headers={"Retry-After": str(int(gate.retry_after))},
            )
        queue, _ = await tracker.attach_or_start(
            chat.id,
            native_payload,
            console_channel.stream_one,
            owner=workspace,
        )
        await service.record_feed(
            project_id,
            actor=username,
            kind="ai_message",
            payload={"text": (first_text or "")[:200], "chat_id": chat.id},
        )

    async def event_generator():
        stream_it = tracker.stream_from_queue(queue, chat.id)
        try:
            async for event_data in stream_it:
                yield event_data
        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Project chat stream error")
            yield f"data: {{\"error\": {str(e)!r}}}\n\n"
        finally:
            await stream_it.aclose()
            asyncio.create_task(
                service.record_feed(
                    project_id,
                    actor=username,
                    kind="ai_reply",
                    payload={"chat_id": chat.id},
                ),
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/{project_id}/chats")
async def list_project_chats(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    """The project's shared conversations (owner-filtered)."""
    await _require_role(service, request, project_id, "")
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="Agent runtime not ready")
    project = await service.get_project(project_id)
    agent_id = _resolve_agent_id(project) if project else "default"
    workspace = await manager.get_agent(agent_id)
    owner = project_owner_id(project_id)
    chats: list[ChatSpec] = await workspace.chat_manager.list_chats(
        user_id=owner,
        archived=False,
    )
    return [
        {
            "id": c.id,
            "name": c.name,
            "status": c.status,
            "updated_at": c.updated_at.isoformat(),
            "project_id": project_id,
        }
        for c in chats
    ]
