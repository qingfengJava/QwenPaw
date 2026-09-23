# -*- coding: utf-8 -*-
"""Kanban task endpoints for XianWork (four-column board)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ...projects.models import (
    PROJECT_EDITOR,
    TASK_STATUSES,
    TaskCreateBody,
    TaskRecord,
    TaskUpdateBody,
)
from ...projects.service import ProjectService, get_project_service
from .projects import _require_role, caller_username

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/tasks",
    tags=["xian-tasks"],
)


@router.get("", response_model=list[TaskRecord])
async def list_tasks(
    project_id: str,
    request: Request,
    assignee: str | None = None,
    service: ProjectService = Depends(get_project_service),
):
    """All board tasks for one project (optionally by assignee)."""
    await _require_role(service, request, project_id, "")
    return await service.list_tasks(project_id, assignee=assignee)


@router.post("", status_code=201, response_model=TaskRecord)
async def create_task(
    project_id: str,
    body: TaskCreateBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, PROJECT_EDITOR)
    return await service.create_task(
        project_id,
        creator=caller_username(request),
        title=body.title,
        description=body.description,
        status=body.status,
        assignee=body.assignee,
        chat_id=body.chat_id,
    )


@router.patch("/{task_id}", response_model=TaskRecord)
async def update_task(
    project_id: str,
    task_id: str,
    body: TaskUpdateBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    """Board drag-and-drop lands here (status + sort_order)."""
    await _require_role(service, request, project_id, PROJECT_EDITOR)
    if body.status is not None and body.status not in TASK_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {list(TASK_STATUSES)}",
        )
    try:
        record = await service.update_task(
            task_id,
            actor=caller_username(request),
            title=body.title,
            description=body.description,
            status=body.status,
            assignee=body.assignee,
            sort_order=body.sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return record


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    project_id: str,
    task_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    await _require_role(service, request, project_id, PROJECT_EDITOR)
    record = await service.get_task(task_id)
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Task not found")
    await service.delete_task(task_id)
