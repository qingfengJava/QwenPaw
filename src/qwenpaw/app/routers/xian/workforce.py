# -*- coding: utf-8 -*-
"""XianWork workforce API（/api/xian/workforce/**，第 12 个 xian 路由）。

员工面的专家团任务入口：创建（三通道：指定团队直开 / 项目 AI 升级 /
聊天升级）、列表、详情（DAG+节点全量留痕）、SSE 实时事件、取消/
续跑、澄清答复、人工裁决（Human Escalation）、跨用户移交。

权限模型：发起人（initiator）或项目成员（project_members 归属校验，
复用 ProjectService.get_project(username) 语义）；越权一律 404 不
泄露存在性。只依赖 workforce 包与 run_store，不 import experts.publish
（防 xian 路由循环导入）。

@author qingfeng
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...enterprise import current_tenant_id
from ...events.bus import get_event_bus, now_ms
from ...projects.service import ProjectService, get_project_service
from ...experts.store import ExpertStore
from ...workforce import bundle as bundle_mod
from ...workforce import engine as engine_mod
from ...workforce.contracts import (
    NODE_ACTIVE_STATUSES,
    NODE_STATUS_PENDING,
    RUN_STATUS_AWAITING_CONFIRM,
    RUN_STATUS_CANCELED,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PLANNING,
    RUN_STATUS_RUNNING,
    Clarification,
    ContextBundle,
    RunPolicy,
)
from ...workforce.planner import build_task_contract
from ...workforce.contracts import DagNode
from ...workforce.run_store import get_run_store, run_topic
from .projects import _require_role, caller_username

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workforce", tags=["xian-workforce"])

#: SSE 空闲保活间隔（与项目 feed 一致，防代理断连）
_KEEPALIVE_S = 25.0


# ---------------------------------------------------------------------------
# 请求体
# ---------------------------------------------------------------------------


class RunCreateBody(BaseModel):
    """创建 run 的请求体（三通道共用）。

    刻意不收 ``policy``：熔断策略是治理面配置，来源只能是团队
    orchestration.policy（管理端配置）或默认值——若允许员工请求体
    覆盖，任何人传 ``max_total_seconds=-1`` 即可关掉全部熔断。
    """

    #: 专家团 ID（必填；团队须为 published）
    team_id: str
    #: 用户原始需求
    goal: str = Field(min_length=1)
    #: 来源会话（聊天升级通道；完成后事件回推该会话前端）
    source_chat_id: Optional[str] = None
    #: 关联项目（项目 AI 升级 / 跨用户移交的前提）
    project_id: Optional[str] = None


class ClarifyBody(BaseModel):
    """澄清答复请求体（awaiting_confirm 状态的输入）。"""

    #: 问题 → 答案映射
    answers: Dict[str, str] = Field(default_factory=dict)


class EscalationBody(BaseModel):
    """人工裁决请求体（escalated 状态的输入）。"""

    #: 裁决动作：retry=放行重试该节点 / abort=终止任务
    action: str = Field(pattern="^(retry|abort)$")
    #: 裁决说明（留痕）
    note: str = ""


class HandoverBody(BaseModel):
    """跨用户移交请求体（项目组内数字员工协同）。"""

    #: 目标用户（必须是 run 所属项目的成员）
    target_user_id: str
    #: 目标用户的专家 ID（接管执行的数字员工）
    target_expert_id: str
    #: 移交说明（为什么移交给 TA、期望做什么）
    handover_note: str = ""


# ---------------------------------------------------------------------------
# 权限辅助
# ---------------------------------------------------------------------------


async def _ensure_run_access(
    run: Dict[str, Any],
    request: Request,
    service: ProjectService,
) -> None:
    """run 访问权校验：发起人或项目成员；越权 404（不泄露存在性）。"""
    caller = caller_username(request)
    # 发起人直接放行
    if caller and run.get("initiator_id") == caller:
        return
    # 项目成员放行（get_project 已含成员归属语义）
    project_id = run.get("project_id")
    if project_id:
        project = await service.get_project(project_id, caller)
        if project is not None:
            return
    # 其余一律 404（跨用户越权不暴露 run 是否存在）
    raise HTTPException(status_code=404, detail="Run not found")


async def _load_run_or_404(
    run_id: str,
    request: Request,
    service: ProjectService,
) -> Dict[str, Any]:
    """加载 run 并校验访问权（不存在/越权统一 404）。"""
    run = await get_run_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await _ensure_run_access(run, request, service)
    return run


# ---------------------------------------------------------------------------
# 创建与查询
# ---------------------------------------------------------------------------


@router.post("/runs", status_code=201)
async def create_run(
    body: RunCreateBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> Dict[str, Any]:
    """创建并后台启动一次专家团任务（三通道共用入口）。"""
    store = get_run_store()
    caller = caller_username(request)
    # 团队存在且已发布（未发布团队无运行时成员可用）
    expert_store = ExpertStore()
    team = await expert_store.get_team(body.team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    # 未发布团队不可发起（与 admin 试运行通道同款校验）
    if team.status != "published":
        raise HTTPException(status_code=400, detail="Team is not published")
    # 项目归属校验（挂项目的 run：caller 必须是项目成员）
    if body.project_id:
        await _require_role(service, request, body.project_id, "")
    # 熔断策略：只读治理面——团队 orchestration.policy（管理端配置），
    # 未配置用引擎默认。请求体不参与（员工不可自行放宽熔断上限）。
    policy: Dict[str, Any] = {}
    if isinstance(team.orchestration, dict) and team.orchestration.get("policy"):
        policy = RunPolicy.model_validate(team.orchestration["policy"]).model_dump()
    # 构建初始上下文束（成员花名册投影，不带 agent_spec）
    members = []
    for member in team.members:
        expert = await expert_store.get_expert(member.expert_id)
        if expert is not None:
            members.append(expert)
    roster = [
        {
            "expert_id": e.id,
            "name": e.name,
            "title": e.title,
            "role_hint": next(
                (m.role_hint for m in team.members if m.expert_id == e.id),
                "",
            ),
        }
        for e in members
    ]
    bundle = bundle_mod.build_initial_bundle(
        body.goal,
        team.name,
        roster,
        caller,
    )
    # 落库（planning 态）+ 创建事件 + 后台启动引擎
    run = await store.create_run(
        team_id=body.team_id,
        goal=body.goal,
        initiator_id=caller,
        project_id=body.project_id,
        source_chat_id=body.source_chat_id,
        policy=policy,
        context_bundle=bundle.model_dump(),
    )
    await store.emit_event(run, "team_run_created", {"goal": body.goal[:200]})
    engine_mod.start_run_background(run["id"])
    # 返回详情（含空节点列表）
    return {**run, "nodes": []}


@router.get("/runs")
async def list_runs(
    request: Request,
    team_id: Optional[str] = None,
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    service: ProjectService = Depends(get_project_service),
) -> List[Dict[str, Any]]:
    """列出可见 run：默认自己发起；project_id 过滤时校验成员归属。"""
    store = get_run_store()
    caller = caller_username(request)
    # 项目维度查询：校验成员归属后按项目列全量（团队协同可见性）
    if project_id:
        await _require_role(service, request, project_id, "")
        return await store.list_runs(
            team_id=team_id,
            project_id=project_id,
            status=status,
        )
    # 个人维度：只看自己发起的（最小权限）
    return await store.list_runs(
        initiator_id=caller,
        team_id=team_id,
        status=status,
    )


@router.get("/runs/{run_id}")
async def get_run_detail(
    run_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> Dict[str, Any]:
    """run 详情：DAG 计划 + 全部节点留痕（契约/结果/裁决/返工记录）。"""
    store = get_run_store()
    # 加载并校验访问权
    run = await _load_run_or_404(run_id, request, service)
    # 节点全量（时间线渲染数据源）
    nodes = await store.list_nodes(run_id)
    return {**run, "nodes": nodes}


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    last_event_id: str = Header(default="", alias="Last-Event-ID"),
    service: ProjectService = Depends(get_project_service),
) -> StreamingResponse:
    """run 维度 SSE 实时事件流（Last-Event-ID 断线续传）。"""
    # 访问权校验后订阅 run topic
    await _load_run_or_404(run_id, request, service)
    topic = run_topic(current_tenant_id(), run_id)
    subscription = get_event_bus().subscribe(topic, last_event_id)

    # 与项目 feed 相同的保活 generator 模式
    async def generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        subscription.__anext__(),
                        timeout=_KEEPALIVE_S,
                    )
                except asyncio.TimeoutError:
                    yield f": keepalive {now_ms()}\n\n"
                    continue
                except StopAsyncIteration:
                    break
                payload = json.dumps(
                    {"event": event.data, "seq": event.seq},
                    ensure_ascii=False,
                    default=str,
                )
                yield f"id: {event.seq}\ndata: {payload}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            subscription.close()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# 生命周期操作：取消 / 续跑 / 澄清 / 人工裁决 / 移交
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> Dict[str, Any]:
    """取消运行中的 run（传播取消到后台任务；终态幂等）。"""
    store = get_run_store()
    run = await _load_run_or_404(run_id, request, service)
    # 终态不可取消（幂等返回当前状态）
    if run["status"] == RUN_STATUS_CANCELED:
        return {"status": RUN_STATUS_CANCELED}
    # 传播协作取消（引擎收敛 canceled 终态与事件）
    cancelled = await engine_mod.cancel_run(run_id)
    if not cancelled:
        # 无运行任务（如 interrupted/awaiting_confirm）：直接落终态
        await store.set_run_status(run_id, RUN_STATUS_CANCELED)
        await store.emit_event(run, "team_run_canceled")
    return {"status": RUN_STATUS_CANCELED}


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> Dict[str, Any]:
    """续跑中断/失败的 run（从已完成节点之后恢复，幂等跳过 done）。"""
    store = get_run_store()
    run = await _load_run_or_404(run_id, request, service)
    # 仅中断态允许续跑（failed 需人工评估后另行处理，防止盲重放）
    if run["status"] != RUN_STATUS_INTERRUPTED:
        raise HTTPException(status_code=409, detail=f"状态 {run['status']} 不可续跑")
    # 重入引擎（done 节点自动跳过）
    engine_mod.start_run_background(run_id)
    return {"status": RUN_STATUS_RUNNING}


@router.post("/runs/{run_id}/clarify")
async def answer_clarification(
    run_id: str,
    body: ClarifyBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> Dict[str, Any]:
    """答复澄清问题：答复写入上下文束（版本 bump）并重入规划。"""
    store = get_run_store()
    run = await _load_run_or_404(run_id, request, service)
    # 仅挂起等澄清的 run 可答复
    if run["status"] != RUN_STATUS_AWAITING_CONFIRM:
        raise HTTPException(status_code=409, detail="当前状态不等待澄清")
    # 恢复束并追加澄清问答（规划重入的输入）
    bundle = ContextBundle.model_validate(run["context_bundle"])
    history = list(bundle.task_ctx.get("clarifications", []))
    for question, answer in body.answers.items():
        history.append({"question": question, "answer": answer})
    bundle.task_ctx["clarifications"] = history
    # 版本 bump（澄清答复改变了任务事实；reason 入版本历史轨迹）+ 持久化
    bundle = bundle_mod.bump(bundle, reason="clarification")
    new_version = await store.bump_context_version(run_id)
    await store.update_run(run_id, context_bundle=bundle.model_dump())
    # 澄清记录更新（answers 并入留痕）
    clarification = Clarification.model_validate(run.get("clarification") or {})
    clarification.answers.update(body.answers)
    await store.update_run(run_id, clarification=clarification.model_dump())
    # 状态回规划态并重启引擎（plan 为空 → 重新规划）
    await store.set_run_status(run_id, RUN_STATUS_PLANNING)
    await store.emit_event(
        run,
        "clarification_answered",
        {"context_version": new_version},
    )
    engine_mod.start_run_background(run_id)
    return {"status": RUN_STATUS_PLANNING, "context_version": new_version}


@router.post("/runs/{run_id}/nodes/{node_key}/escalation")
async def resolve_escalation(
    run_id: str,
    node_key: str,
    body: EscalationBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> Dict[str, Any]:
    """人工裁决熔断节点：retry 放行重试 / abort 终止任务。"""
    store = get_run_store()
    run = await _load_run_or_404(run_id, request, service)
    # 仅熔断态可裁决
    if run["status"] != RUN_STATUS_ESCALATED:
        raise HTTPException(status_code=409, detail="run 未处于熔断状态")
    node = await store.get_node(run_id, node_key)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if body.action == "retry":
        # 放行重试：节点回 pending（保留契约与返工历史，attempt 延续）
        await store.update_node(run_id, node_key, status=NODE_STATUS_PENDING)
        await store.set_run_status(run_id, RUN_STATUS_RUNNING, escalation_reason="")
        await store.emit_event(
            run,
            "escalation_resolved",
            {"node_key": node_key, "action": "retry", "note": body.note},
        )
        # 重入引擎（其余 done 节点跳过）
        engine_mod.start_run_background(run_id)
        return {"status": RUN_STATUS_RUNNING}
    # 终止：终态 failed 并**保留**熔断原因（set_run_status 会整列覆写
    # escalation_reason，必须显式回传——否则 abort 后与自然失败无法
    # 区分，审计线索丢失）
    await store.set_run_status(
        run_id,
        RUN_STATUS_FAILED,
        escalation_reason=run.get("escalation_reason") or "",
    )
    await store.emit_event(
        run,
        "escalation_resolved",
        {"node_key": node_key, "action": "abort", "note": body.note},
    )
    return {"status": RUN_STATUS_FAILED}


@router.post("/runs/{run_id}/nodes/{node_key}/handover")
async def handover_node(
    run_id: str,
    node_key: str,
    body: HandoverBody,
    request: Request,
    service: ProjectService = Depends(get_project_service),
) -> Dict[str, Any]:
    """跨用户移交：节点改派目标用户的专家（上下文版本延续不重置）。

    前置约束：run 必须挂项目（project_members 归属校验）；目标专家
    必须存在且已发布。移交后节点回 pending，等待引擎按新指派调度；
    若节点已完成则拒绝（不可变更历史）。
    """
    store = get_run_store()
    run = await _load_run_or_404(run_id, request, service)
    # 移交前提：run 挂项目（跨用户协同的项目边界）
    project_id = run.get("project_id")
    if not project_id:
        raise HTTPException(status_code=409, detail="跨用户移交要求任务归属项目")
    # 目标用户必须是项目成员（get_project 含成员归属语义）
    target_project = await service.get_project(project_id, body.target_user_id)
    if target_project is None:
        raise HTTPException(status_code=404, detail="目标用户不是项目成员")
    # 目标专家存在且已发布
    expert_store = ExpertStore()
    expert = await expert_store.get_expert(body.target_expert_id)
    if expert is None:
        raise HTTPException(status_code=404, detail="目标专家不存在")
    if expert.status != "published":
        raise HTTPException(status_code=400, detail="Target expert is not published")
    # 节点存在且未完成（done 节点不可移交）
    node = await store.get_node(run_id, node_key)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node["status"] == "done":
        raise HTTPException(status_code=409, detail="节点已完成，不可移交")
    # 执行中节点不可移交：引擎可能正在委派，移交写入会被旧委派的
    # 结果落地覆盖（竞态守卫；等待本轮完成或先取消任务）
    if node["status"] in NODE_ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="节点执行中，请等待本轮完成或先取消任务")
    # 以最新上下文束重建契约（版本延续，同一事实传递给新执行者）
    bundle = ContextBundle.model_validate(run["context_bundle"])
    plan = run.get("plan") or {}
    dag_node_def = next(
        (n for n in plan.get("nodes", []) if n.get("node_key") == node_key),
        None,
    )
    if dag_node_def is None:
        raise HTTPException(status_code=409, detail="节点定义缺失")
    dag_node = DagNode.model_validate(dag_node_def)
    contract = build_task_contract(dag_node, expert, bundle)
    # 落库新指派与新契约 + 版本延续记录 + 双方可见事件
    await store.update_node(
        run_id,
        node_key,
        assignee_user_id=body.target_user_id,
        assignee_expert_id=body.target_expert_id,
        status=NODE_STATUS_PENDING,
        contract=contract.model_dump(),
        session_id="",
    )
    await store.emit_event(
        run,
        "handover",
        {
            "node_key": node_key,
            "from_user": run["initiator_id"],
            "to_user": body.target_user_id,
            "to_expert": expert.name,
            "note": body.handover_note,
            "context_version": run["context_version"],
        },
        actor=caller_username(request) or "workforce",
    )
    # 活态 run 立即重入引擎（pending 节点等待调度）
    if run["status"] in (RUN_STATUS_RUNNING, RUN_STATUS_INTERRUPTED):
        engine_mod.start_run_background(run_id)
    return {
        "node_key": node_key,
        "assignee_user_id": body.target_user_id,
        "assignee_expert_id": body.target_expert_id,
    }
