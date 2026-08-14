# -*- coding: utf-8 -*-
"""Project automations for XianWork (scheduled prompts via cron engine).

Creating an automation schedules a cron job on the project's shared AI
agent (the expert bound to the project, else default). The job dispatches
its prompt into the project-shared console session so every member sees
the result in the feed / assets. The ``project_automations`` row is the
project-plane projection; the cron manager stays the scheduler authority.
"""
from __future__ import annotations

import logging
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from ...enterprise import current_tenant_id, new_id, require_enterprise_engine
from ...projects.models import PROJECT_EDITOR
from ...projects.service import (
    ProjectService,
    get_project_service,
    project_owner_id,
)
from .projects import _require_role, _resolve_agent_id, caller_username

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["xian-automations"])


class AutomationBody(BaseModel):
    name: str
    schedule: str  # 5-field crontab, e.g. "0 9 * * *"
    prompt: str = ""
    enabled: bool = True
    timezone: str = "Asia/Shanghai"


def _row_to_view(row) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "schedule": row.schedule,
        "prompt": row.prompt,
        "enabled": bool(row.enabled),
        "cron_job_id": row.cron_job_id,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
    }


async def _project_cron_manager(request: Request, project):
    """The cron manager of the agent powering this project's AI."""
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="Agent runtime not ready")
    workspace = await manager.get_agent(_resolve_agent_id(project))
    if workspace.cron_manager is None:
        raise HTTPException(status_code=500, detail="CronManager not ready")
    return workspace.cron_manager


@router.get("/{project_id}/automations")
async def list_automations(
    project_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> List[dict]:
    project = await _require_role(service, request, project_id, "")
    engine = require_enterprise_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, project_id, name, schedule, prompt, enabled, "
                "cron_job_id, last_run_at FROM project_automations "
                "WHERE tenant_id = :tid AND project_id = :pid "
                "ORDER BY created_at"
            ),
            {"tid": current_tenant_id(), "pid": project_id},
        )
        rows = [_row_to_view(r) for r in result]
    # Enrich with live cron state (paused/next run) when reachable.
    try:
        cron = await _project_cron_manager(request, project)
        jobs = {job.id: job for job in await cron.list_jobs()}
    except Exception:  # pylint: disable=broad-except
        return rows
    for row in rows:
        job = jobs.get(row.get("cron_job_id"))
        if job is not None:
            row["enabled"] = job.enabled
            state = cron.get_state(job.id)
            row["next_run_at"] = getattr(state, "next_run_at", None)
    return rows


@router.post("/{project_id}/automations", status_code=201)
async def create_automation(
    project_id: str,
    body: AutomationBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> dict:
    project = await _require_role(service, request, project_id, PROJECT_EDITOR)
    if not body.name.strip() or not body.schedule.strip():
        raise HTTPException(status_code=400, detail="name/schedule required")

    from ...crons.models import (
        CronJobSpec,
        DispatchSpec,
        DispatchTarget,
        JobRuntimeSpec,
        ScheduleSpec,
    )

    owner = project_owner_id(project_id)
    session_id = f"project_auto:{project_id}"
    spec = CronJobSpec(
        id=str(uuid.uuid4()),
        name=f"[{project.name}] {body.name}",
        enabled=body.enabled,
        schedule=ScheduleSpec(
            type="cron",
            cron=body.schedule,
            timezone=body.timezone,
        ),
        task_type="text",
        text=body.prompt or body.name,
        dispatch=DispatchSpec(
            type="channel",
            channel="console",
            target=DispatchTarget(user_id=owner, session_id=session_id),
            silent=False,
            meta={"project_id": project_id, "project_automation": body.name},
        ),
        runtime=JobRuntimeSpec(tool_safety=True),
        meta={"project_id": project_id},
    )
    cron = await _project_cron_manager(request, project)
    try:
        await cron.create_or_replace_job(spec)
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    engine = require_enterprise_engine()
    aid = new_id("auto")
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "INSERT INTO project_automations (tenant_id, id, project_id, "
                "name, schedule, prompt, enabled, cron_job_id) VALUES "
                "(:tid, :id, :pid, :name, :schedule, :prompt, :enabled, "
                ":job) RETURNING id, project_id, name, schedule, prompt, "
                "enabled, cron_job_id, last_run_at"
            ),
            {
                "tid": current_tenant_id(),
                "id": aid,
                "pid": project_id,
                "name": body.name,
                "schedule": body.schedule,
                "prompt": body.prompt,
                "enabled": body.enabled,
                "job": spec.id,
            },
        )
        row = result.one()
    await service.record_feed(
        project_id,
        actor=caller_username(request),
        kind="automation_created",
        payload={"name": body.name, "schedule": body.schedule},
    )
    return _row_to_view(row)


@router.delete("/{project_id}/automations/{automation_id}", status_code=204)
async def delete_automation(
    project_id: str,
    automation_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
):
    project = await _require_role(service, request, project_id, PROJECT_EDITOR)
    engine = require_enterprise_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM project_automations WHERE tenant_id = :tid "
                "AND project_id = :pid AND id = :aid RETURNING name, "
                "cron_job_id"
            ),
            {
                "tid": current_tenant_id(),
                "pid": project_id,
                "aid": automation_id,
            },
        )
        row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    if row.cron_job_id:
        try:
            cron = await _project_cron_manager(request, project)
            await cron.delete_job(row.cron_job_id)
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "cron job %s delete failed for automation %s",
                row.cron_job_id,
                automation_id,
                exc_info=True,
            )
    await service.record_feed(
        project_id,
        actor=caller_username(request),
        kind="automation_removed",
        payload={"name": row.name},
    )
