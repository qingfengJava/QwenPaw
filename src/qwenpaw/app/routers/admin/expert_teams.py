# -*- coding: utf-8 -*-
"""Admin expert-team management API: member orchestration + publishing."""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...experts.models import (
    ExpertTeamCreateBody,
    ExpertTeamRecord,
    ExpertTeamUpdateBody,
    TeamMember,
    expert_team_agent_id,
)
from ...experts.publish import archive_expert_team, publish_expert_team
from ...experts.store import DraftRevisionConflict, get_expert_store
from ...kb import bindings as kb_bindings
from ...rbac import PERM_ADMIN_EXPERTS, require_perm
from ...write_audit import record_write_audit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/expert-teams",
    tags=["admin-expert-teams"],
    dependencies=[Depends(require_perm(PERM_ADMIN_EXPERTS))],
)


def _manager(request: Request):
    return getattr(request.app.state, "multi_agent_manager", None)


def _actor(request: Request) -> str:
    """从认证上下文取操作者（fail-closed，审计链不虚构身份）。

    认证开启时缺失身份 → 401（不虚构操作者，保证审计与提案
    operator_id 比对真实）；认证关闭（本机单机桌面模式）→
    "local"（诚实标识未认证操作者，区别于虚构的 admin 身份）。
    """
    user = getattr(request.state, "user", None)
    if user:
        return str(user)
    from ...rbac.deps import rbac_enforcement_enabled

    if rbac_enforcement_enabled():
        raise HTTPException(status_code=401, detail="认证上下文缺失")
    return "local"


@router.get("", response_model=List[ExpertTeamRecord])
async def list_teams(status: Optional[str] = None) -> List[ExpertTeamRecord]:
    return await get_expert_store().list_teams(status=status)


@router.post("", status_code=201, response_model=ExpertTeamRecord)
async def create_team(body: ExpertTeamCreateBody) -> ExpertTeamRecord:
    return await get_expert_store().create_team(
        name=body.name,
        description=body.description,
        mode=body.mode,
        router_prompt=body.router_prompt,
        members=[
            TeamMember(
                expert_id=m.expert_id,
                role_hint=m.role_hint,
                member_role=m.member_role,
                seq=m.seq,
                expert_version=m.expert_version,
            )
            for m in body.members
        ],
        orchestration=body.orchestration,
        sample_tasks=body.sample_tasks,
        showcase=body.showcase,
    )


@router.get("/metadata")
async def team_metadata() -> dict:
    """团队配置元数据（可用角色/模式/有效限额；前端唯一枚举来源）。

    静态路径必须注册在 ``/{team_id}`` 之前，否则会被路径参数吞掉。
    """
    from ...experts.team_service import team_metadata as build_metadata

    return await build_metadata()


@router.get("/{team_id}", response_model=ExpertTeamRecord)
async def get_team(team_id: str) -> ExpertTeamRecord:
    record = await get_expert_store().get_team(team_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return record


@router.get("/{team_id}/capabilities")
async def team_capabilities(team_id: str) -> dict:
    """团队有效能力投影（能力矩阵数据源；声明≠可执行）。"""
    from ...experts.capability_view import team_capability_view

    record = await get_expert_store().get_team(team_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return await team_capability_view(team_id)


@router.post("/{team_id}/validate")
async def validate_team(team_id: str) -> dict:
    """发布预检：配置跨字段 + 成员可用性 + 模板引用（返回问题清单）。"""
    from ...experts.team_service import validate_team as run_validate

    record = await get_expert_store().get_team(team_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return await run_validate(team_id)


@router.get("/{team_id}/versions")
async def team_versions(team_id: str) -> list:
    """团队发布版本清单（version 降序的审计摘要）。"""
    record = await get_expert_store().get_team(team_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return await get_expert_store().list_team_versions(team_id)


@router.get("/{team_id}/member-updates")
async def member_updates(team_id: str) -> list:
    """成员升级提醒：批量比较团队绑定版本与成员最新发布版本。

    返回列表，每项包含 ``expert_id``、``bound_version``（团队草稿选定版本）、
    ``latest_version``（成员最新发布指针）、``upgradable``（是否可升级）。
    不维护易过期的布尔标记，而是实时比较。
    """
    store = get_expert_store()
    team = await store.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    # 一次性批量获取成员卡片（五步范式：一次批量查询，内存组装；
    # 判定逻辑唯一实现在 team_service.compute_member_upgrades）
    expert_ids = {m.expert_id for m in team.members}
    cards = await store.list_expert_cards()
    relevant = [e for e in cards if e.id in expert_ids]
    from ...experts.team_service import compute_member_upgrades

    return compute_member_upgrades(team.members, relevant)


@router.patch("/{team_id}", response_model=ExpertTeamRecord)
async def update_team(
    team_id: str,
    body: ExpertTeamUpdateBody,
) -> ExpertTeamRecord:
    members = None
    if body.members is not None:
        members = [
            TeamMember(
                expert_id=m.expert_id,
                role_hint=m.role_hint,
                member_role=m.member_role,
                seq=m.seq,
                expert_version=m.expert_version,
            )
            for m in body.members
        ]
    try:
        record = await get_expert_store().update_team(
            team_id,
            expected_revision=body.expected_revision,
            name=body.name,
            description=body.description,
            mode=body.mode,
            router_prompt=body.router_prompt,
            members=members,
            orchestration=body.orchestration,
            sample_tasks=body.sample_tasks,
            showcase=body.showcase,
        )
    except DraftRevisionConflict as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": str(exc),
                "team_id": exc.team_id,
                "expected": exc.expected,
                "actual": exc.actual,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    # 成员/编排变更影响 kb 团队归属解析，全量失效绑定缓存（T6）
    kb_bindings.invalidate_principal_cache()
    return record


@router.delete("/{team_id}", status_code=204)
async def delete_team(team_id: str) -> None:
    if not await get_expert_store().delete_team(team_id):
        raise HTTPException(status_code=404, detail="Expert team not found")
    kb_bindings.invalidate_principal_cache()


@router.post("/{team_id}/publish", response_model=ExpertTeamRecord)
async def publish(team_id: str, request: Request) -> ExpertTeamRecord:
    """Publish members (validated) then materialize the supervisor."""
    actor = _actor(request)
    try:
        return await publish_expert_team(
            team_id,
            published_by=actor,
            manager=_manager(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{team_id}/archive", response_model=ExpertTeamRecord)
async def archive(team_id: str, request: Request) -> ExpertTeamRecord:
    record = await archive_expert_team(
        team_id,
        manager=_manager(request),
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    kb_bindings.invalidate_principal_cache(team_id)
    return record


@router.get("/{team_id}/agent_id")
async def runtime_agent_id(team_id: str) -> dict:
    return {
        "team_id": team_id,
        "agent_id": expert_team_agent_id(team_id),
    }


# ----------------------------------------------------------------------
# kb-bindings（T6）：专家组作为绑定主体（principal_type='team'）
# ----------------------------------------------------------------------


class TeamKbBindingBody(BaseModel):
    """Body for binding a knowledge space to one expert team（T6）。"""

    space_id: str
    remark: str = ""


async def _require_team(team_id: str) -> ExpertTeamRecord:
    """404 sentinel when the team does not exist（路由层前置哨兵）。"""
    record = await get_expert_store().get_team(team_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return record


@router.get("/{team_id}/kb-bindings")
async def list_team_kb_bindings(
    team_id: str,
) -> list[dict]:
    """List knowledge spaces bound to one team（名称/scope 已组装）。"""
    await _require_team(team_id)
    return await kb_bindings.list_bindings(
        kb_bindings.team_principal_agent_id(team_id),
    )


@router.put("/{team_id}/kb-bindings")
async def bind_team_kb(
    team_id: str,
    body: TeamKbBindingBody,
    request: Request,
) -> Any:
    """Bind a space to one team behind the manage gate（201/200 幂等）。

    管理权门与 agent 直绑同一 ``can_manage_space``（绑定即授权不另立
    规则）；存储行 ``agent_id`` 列存 ``team_{team_id}`` 运行态形态、
    ``principal_type='team'``（0048 列，列名不改保兼容）。
    """
    username = _actor(request)
    await _require_team(team_id)
    allowed = await kb_bindings.can_manage_space(body.space_id, username)
    if allowed is None:
        raise HTTPException(status_code=404, detail="kb not found")
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="no manage right on this kb",
        )
    stored_id = kb_bindings.team_principal_agent_id(team_id)
    rows = await kb_bindings.list_bindings(stored_id)
    existing = next(
        (r for r in rows if r["space_id"] == body.space_id),
        None,
    )
    if existing is not None:
        return JSONResponse(
            status_code=200,
            content={**existing, "created": False},
        )
    ok = await kb_bindings.bind_principal(
        principal_type=kb_bindings.PRINCIPAL_TEAM,
        principal_id=team_id,
        space_id=body.space_id,
        granted_by=username,
        remark=body.remark,
    )
    if ok is not True:
        raise HTTPException(
            status_code=503,
            detail="kb binding storage unavailable",
        )
    rows_after = await kb_bindings.list_bindings(stored_id)
    row = next(
        (r for r in rows_after if r["space_id"] == body.space_id),
        None,
    )
    if row is None:
        raise HTTPException(
            status_code=409,
            detail="binding was concurrently removed; retry",
        )
    # 审计留痕：团队主体绑定授权（谁把哪个库绑给了哪个专家组）
    record_write_audit(
        tool_name="team_kb.binding.bind",
        target=f"{stored_id}:{body.space_id}",
        actor_id=username,
        after={"granted_by": username, "remark": body.remark},
    )
    return JSONResponse(status_code=201, content={**row, "created": True})


@router.delete("/{team_id}/kb-bindings/{spaceId}", status_code=204)
async def unbind_team_kb(
    team_id: str,
    spaceId: str,
    request: Request,
) -> None:
    """Unbind one space from one team（行不存在 404）。"""
    await _require_team(team_id)
    removed = await kb_bindings.unbind_agent_kb(
        kb_bindings.team_principal_agent_id(team_id),
        spaceId,
        principal_type=kb_bindings.PRINCIPAL_TEAM,
    )
    if not removed:
        raise HTTPException(status_code=404, detail="binding not found")
    # 审计留痕：团队主体解绑（谁把哪个库从专家组上摘除）
    record_write_audit(
        tool_name="team_kb.binding.unbind",
        target=(
            f"{kb_bindings.team_principal_agent_id(team_id)}:{spaceId}"
        ),
        actor_id=_actor(request),
    )


# ----------------------------------------------------------------------
# P5 AI 修改安全闭环：变更提案确认/拒绝/查询端点
# ----------------------------------------------------------------------


class ConfirmChangeRequestBody(BaseModel):
    """Body for confirming a team change request."""
    session_id: str = ""


@router.get("/{team_id}/change-requests/{request_id}")
async def get_change_request_status(
    team_id: str,
    request_id: str,
) -> dict:
    """查询变更提案当前状态（断线重连/追问用）。"""
    from ...experts.team_changes import get_change_request

    record = await get_change_request(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Change request not found")
    if record["team_id"] != team_id:
        raise HTTPException(status_code=404, detail="Change request not found")
    return record


@router.post("/{team_id}/change-requests/{request_id}/confirm")
async def confirm_change_request_endpoint(
    team_id: str,
    request_id: str,
    request: Request,
    body: ConfirmChangeRequestBody = ConfirmChangeRequestBody(),
) -> dict:
    """用户确认变更提案：服务端执行 CAS 写入或发布。

    安全门：从认证上下文取身份，校验租户、权限、提案操作者、会话归属。
    不信任 body.user_id。
    """
    from ...experts.team_changes import confirm_change_request
    from ...events.bus import get_event_bus, team_config_topic
    from ...enterprise import current_tenant_id

    actor = _actor(request)
    result = await confirm_change_request(
        request_id=request_id,
        operator_id=actor,
        session_id=body.session_id,
    )
    if not result.get("ok"):
        status_code = 400
        error_msg = result.get("error", "")
        if "不存在" in error_msg:
            status_code = 404
        elif "不一致" in error_msg or "无权" in error_msg:
            status_code = 403
        elif "过期" in error_msg:
            status_code = 410
        elif "冲突" in error_msg:
            status_code = 409
        raise HTTPException(status_code=status_code, detail=error_msg)
    # 发布事件通知前端刷新
    try:
        bus = get_event_bus()
        await bus.publish(
            team_config_topic(current_tenant_id(), team_id),
            {
                "type": "change_applied",
                "team_id": team_id,
                "request_id": request_id,
                "kind": result.get("kind", ""),
                "actor": actor,
            },
        )
    except Exception:  # noqa: BLE001
        logger.debug("team event publish failed", exc_info=True)
    # 审计留痕
    record_write_audit(
        tool_name="team_change.confirm",
        target=f"team:{team_id}:request:{request_id}",
        actor_id=actor,
        after={"kind": result.get("kind"), "status": result.get("status")},
    )
    return result


@router.post("/{team_id}/change-requests/{request_id}/reject")
async def reject_change_request_endpoint(
    team_id: str,
    request_id: str,
    request: Request,
) -> dict:
    """用户拒绝变更提案。"""
    from ...experts.team_changes import reject_change_request
    from ...events.bus import get_event_bus, team_config_topic
    from ...enterprise import current_tenant_id

    actor = _actor(request)
    result = await reject_change_request(
        request_id=request_id,
        operator_id=actor,
    )
    if not result.get("ok"):
        status_code = 400
        error_msg = result.get("error", "")
        if "不存在" in error_msg:
            status_code = 404
        raise HTTPException(status_code=status_code, detail=error_msg)
    # 发布事件
    try:
        bus = get_event_bus()
        await bus.publish(
            team_config_topic(current_tenant_id(), team_id),
            {
                "type": "change_rejected",
                "team_id": team_id,
                "request_id": request_id,
                "actor": actor,
            },
        )
    except Exception:  # noqa: BLE001
        logger.debug("team event publish failed", exc_info=True)
    return result
