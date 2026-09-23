# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from qwenpaw.exceptions import ConfigurationException

from ..rbac import (
    is_platform_admin,
    manage_allowed,
    rbac_enforcement_enabled,
)
from .manager import CronManager
from .models import (
    CronDispatchTargetItem,
    CronDispatchTargetsResponse,
    CronExecutionRecord,
    CronJobSpec,
    CronJobView,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cron", tags=["cron"])


async def get_cron_manager(
    request: Request,
) -> CronManager:
    """Get cron manager for the active agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    if workspace.cron_manager is None:
        raise HTTPException(
            status_code=500,
            detail="CronManager not initialized",
        )
    return workspace.cron_manager


def _viewer(request: Request) -> str:
    """本次请求的登录用户（认证关闭时为空串）。"""
    return str(getattr(request.state, "user", None) or "")


async def _agent_id_for(request: Request) -> str:
    """解析本次请求针对的员工 id（与 get_cron_manager 同源 workspace）。"""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    return str(getattr(workspace, "agent_id", "default") or "default")


async def _resolve_owner_department(owner: str | None) -> str | None:
    """尽力解析 owner 部门归属快照（无 PG / 无部门 / 抖动 → None）。"""
    if not owner:
        return None
    try:
        from ..orgs.service import get_org_service

        _org, dept_path = await get_org_service().resolve_user_scope(owner)
        return dept_path
    except Exception:  # pylint: disable=broad-except
        logger.debug("cron: owner department resolve failed", exc_info=True)
        return None


def _job_visible(job: CronJobSpec, viewer: str, admin: bool) -> bool:
    """可见性：共享任务（owner 空）全员；个人任务仅 owner + 平台管理员。"""
    if not rbac_enforcement_enabled() or not viewer or admin:
        return True
    owner = job.owner_user_id
    return owner is None or owner == viewer


def _ensure_visible(job: CronJobSpec, viewer: str) -> None:
    """不可见的个人任务按 404 处理（不泄露存在性）。"""
    admin = is_platform_admin(viewer) if viewer else False
    if not _job_visible(job, viewer, admin):
        raise HTTPException(status_code=404, detail="job not found")


async def _authorize_job_write(
    request: Request,
    agent_id: str,
    job: CronJobSpec,
) -> None:
    """写/删/暂停/手动执行鉴权。

    - RBAC 关闭：直通（单机零变化）；
    - 平台管理员：直通（审计）；
    - 个人任务（owner 非空）：仅 owner 本人（team_lead 亦不介入他人个人资产）；
    - 共享任务（owner 空）：员工级管理授权（与 S1 写闸同源，403 文案对齐前端）。
    """
    if not rbac_enforcement_enabled():
        return
    viewer = _viewer(request)
    if not viewer:
        raise HTTPException(
            status_code=403, detail="RBAC: no authenticated identity"
        )
    if is_platform_admin(viewer):
        return
    owner = job.owner_user_id
    if owner:
        if viewer != owner:
            raise HTTPException(
                status_code=403, detail="无权操作他人的个人定时任务"
            )
        return
    if not await manage_allowed(viewer, agent_id):
        raise HTTPException(
            status_code=403,
            detail="无该员工配置权限（请联系管理员授予管理授权）",
        )


@router.get(
    "/dispatch-targets",
    response_model=CronDispatchTargetsResponse,
)
async def list_dispatch_targets(
    request: Request,
    channel: str
    | None = Query(
        default=None,
        description="Optional channel filter",
    ),
    keyword: str
    | None = Query(
        default=None,
        description="Optional keyword for user/session/channel",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=2000,
        description="Max number of target items",
    ),
):
    """List candidate dispatch targets derived from known chats."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    chats = await workspace.chat_manager.list_chats(channel=channel)
    kw = (keyword or "").strip().lower()

    deduped: dict[tuple[str, str, str], CronDispatchTargetItem] = {}
    for chat in chats:
        item = CronDispatchTargetItem(
            channel=chat.channel,
            user_id=chat.user_id,
            session_id=chat.session_id,
        )
        if kw:
            haystack = (
                f"{item.channel} {item.user_id} {item.session_id}".lower()
            )
            if kw not in haystack:
                continue
        deduped[(item.channel, item.user_id, item.session_id)] = item
        if len(deduped) >= limit:
            break

    items = list(deduped.values())
    channels = sorted({item.channel for item in items})
    if "console" not in channels:
        channels.insert(0, "console")
    return CronDispatchTargetsResponse(channels=channels, items=items)


@router.get("/jobs", response_model=list[CronJobSpec])
async def list_jobs(
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    # 共享任务全员可见 + 个人任务仅 owner/平台管理员（跨人不可见）
    jobs = await mgr.list_jobs()
    viewer = _viewer(request)
    admin = is_platform_admin(viewer) if viewer else False
    return [job for job in jobs if _job_visible(job, viewer, admin)]


@router.get("/jobs/{job_id}", response_model=CronJobView)
async def get_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    _ensure_visible(job, _viewer(request))
    return CronJobView(spec=job, state=mgr.get_state(job_id))


@router.post("/jobs", response_model=CronJobSpec)
async def create_job(
    spec: CronJobSpec,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    # server generates id; ignore client-provided spec.id
    job_id = str(uuid.uuid4())
    agent_id = await _agent_id_for(request)
    viewer = _viewer(request)
    owner = spec.owner_user_id
    if rbac_enforcement_enabled() and viewer:
        can_manage = is_platform_admin(viewer) or await manage_allowed(
            viewer, agent_id
        )
        if not can_manage:
            # 业务用户只能建个人任务：强制 owner=本人（不可伪建共享/他人）
            owner = viewer
        # 管理者：owner 由提交决定（None=共享 / 具体用户=个人）
    # 个人任务补 owner 部门归属快照（尽力解析，无 PG/无部门→None）
    department = await _resolve_owner_department(owner)
    created = spec.model_copy(
        update={
            "id": job_id,
            "owner_user_id": owner,
            "department_id": department,
            "project_id": None,
        }
    )
    try:
        await mgr.create_or_replace_job(created)
    except (ConfigurationException, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return created


@router.put("/jobs/{job_id}", response_model=CronJobSpec)
async def replace_job(
    job_id: str,
    spec: CronJobSpec,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    if spec.id is None:
        spec.id = job_id
    elif spec.id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    agent_id = await _agent_id_for(request)
    existing = await mgr.get_job(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="job not found")
    # 鉴权按**现有行**归属（防通过改 owner 越权：个人→共享需管理权）
    await _authorize_job_write(request, agent_id, existing)
    # owner/归属列不可被写请求篡改：沿用现有行（改归属属管理动作）
    spec = spec.model_copy(
        update={
            "owner_user_id": existing.owner_user_id,
            "department_id": existing.department_id,
            "project_id": existing.project_id,
        }
    )
    try:
        await mgr.create_or_replace_job(spec)
    except (ConfigurationException, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return spec


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    agent_id = await _agent_id_for(request)
    existing = await mgr.get_job(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="job not found")
    await _authorize_job_write(request, agent_id, existing)
    ok = await mgr.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": True}


@router.post("/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    agent_id = await _agent_id_for(request)
    existing = await mgr.get_job(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="job not found")
    await _authorize_job_write(request, agent_id, existing)
    try:
        await mgr.pause_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"paused": True}


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    agent_id = await _agent_id_for(request)
    existing = await mgr.get_job(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="job not found")
    await _authorize_job_write(request, agent_id, existing)
    try:
        await mgr.resume_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"resumed": True}


@router.post("/jobs/{job_id}/run")
async def run_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    agent_id = await _agent_id_for(request)
    existing = await mgr.get_job(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="job not found")
    await _authorize_job_write(request, agent_id, existing)
    try:
        await mgr.run_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"started": True}


@router.get("/jobs/{job_id}/state")
async def get_job_state(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    _ensure_visible(job, _viewer(request))
    return mgr.get_state(job_id).model_dump(mode="json")


@router.get("/jobs/{job_id}/history", response_model=list[CronExecutionRecord])
async def get_job_history(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await mgr.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    _ensure_visible(job, _viewer(request))
    return await mgr.get_history(job_id)
