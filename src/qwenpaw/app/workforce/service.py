# -*- coding: utf-8 -*-
"""团队运行控制面服务（T3）：统一创建、批准、决策与暂停用例。

职责边界（计划 §T3）：

- **同一准入**：xian 员工通道与管理端试运行共用 :func:`create_team_run`
  （发布校验 / 花名册投影 / 治理面策略 / 幂等键），禁止旁路建 run；
- **统一决策**：需求确认 / 计划批准 / 续跑 / 取消经 :func:`submit_decision`
  处置，``decision_id`` 绑定服务端已登记摘要（挂起时签发），批准对象
  修订号经 :func:`~qwenpaw.app.workforce.contracts.decision_matches`
  校验——过期批准不放行新内容（协议 15）；
- **暂停**：:func:`pause_run` 请求协作暂停（区别于 cancel 终态语义）。

本模块不落 SQL：持久化全部经 :mod:`~qwenpaw.app.workforce.run_store`
与引擎；审批中心桥接见 :mod:`~qwenpaw.app.workforce.approvals`。

@author qingfeng
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError

from . import approvals as approvals_mod
from . import bundle as bundle_mod
from .contracts import (
    RUN_STATUS_AWAITING_CONFIRM,
    RUN_STATUS_CANCELED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PAUSED,
    RUN_STATUS_PLANNING,
    RUN_STATUS_RUNNING,
    HumanDecision,
    RequirementBrief,
)
from .run_store import WorkforceRunStore, get_run_store

logger = logging.getLogger(__name__)

#: 挂起决策对象在上下文束执行上下文中的键（版本化随束持久）
_PENDING_DECISION_KEY = "pending_decision"


class DecisionError(Exception):
    """决策处置失败（调用方转换为 4xx）。"""


class DecisionConflict(DecisionError):
    """状态/版本冲突（409）。"""


class DecisionNotFound(DecisionError):
    """决策标识不存在或不匹配（404）。"""


def _store_pending_decision(
    bundle_dict: Dict[str, Any],
    *,
    decision_id: str,
    kind: str,
    revision: int,
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    """在上下文束执行上下文登记待决策对象（服务端唯一签发点）。"""
    bundle = dict(bundle_dict)
    execution_ctx = dict(bundle.get("execution_ctx") or {})
    execution_ctx[_PENDING_DECISION_KEY] = {
        "decision_id": decision_id,
        "kind": kind,
        "revision": revision,
        "summary": summary,
    }
    bundle["execution_ctx"] = execution_ctx
    return bundle


def _load_pending_decision(
    run: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """读取当前挂起的决策对象（无则 None）。"""
    bundle = run.get("context_bundle") or {}
    execution_ctx = bundle.get("execution_ctx") or {}
    pending = execution_ctx.get(_PENDING_DECISION_KEY)
    return dict(pending) if pending else None


async def create_team_run(
    *,
    team_id: str,
    goal: str,
    initiator_id: str,
    project_id: Optional[str] = None,
    source_chat_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    store: Optional[WorkforceRunStore] = None,
    expert_store=None,
) -> Dict[str, Any]:
    """创建一次团队运行（xian / admin 试运行共用的唯一准入）。

    幂等键语义：提供 ``idempotency_key`` 时以之作为 run 主键——重复
    提交（聊天升级重试等）命中唯一约束后返回既有 run（不重复创建、
    不重复启动引擎），响应带 ``idempotent_replay=True``。
    """
    from .engine import start_run_background

    store = store or get_run_store()
    if expert_store is None:
        from ..experts.store import ExpertStore

        expert_store = ExpertStore()
    # 团队存在且已发布（未发布团队无运行时成员可用）
    team = await expert_store.get_team(team_id)
    if team is None:
        raise LookupError("team_not_found")
    if team.status != "published":
        raise ValueError("team_not_published")
    # 熔断策略：只读治理面——团队 orchestration.policy（管理端配置），
    # 未配置用引擎默认。请求体不参与（调用方不可自行放宽熔断上限）。
    policy: Dict[str, Any] = {}
    if isinstance(team.orchestration, dict) and team.orchestration.get("policy"):
        from .contracts import RunPolicy

        policy = RunPolicy.model_validate(team.orchestration["policy"]).model_dump()
    # 成员花名册投影（不带 agent_spec，避免上下文污染）
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
            # 钉住成员版本（T5/协议8.1）：调用前核验实际员工版本的
            # 基准——实例升级发生漂移时引擎暂停待显式处理
            "version": int(e.version or 0),
        }
        for e in members
    ]
    # 初始上下文束 + 需求基线（RequirementBrief v1：规划与验收的尺子）
    bundle = bundle_mod.build_initial_bundle(goal, team.name, roster, initiator_id)
    task_ctx = dict(bundle.task_ctx)
    task_ctx["requirement_brief"] = RequirementBrief(
        source_ref=source_chat_id or "",
        business_goal=goal,
    ).model_dump()
    bundle.task_ctx = task_ctx
    # 幂等键即 run 主键（冲突 → 回读既有 run，不重复创建/启动）。
    # 主键列宽 64：超长组合键（caller:key）散列为定长十六进制，
    # 冲突判定语义不变（同输入同散列）
    if idempotency_key and len(idempotency_key) > 64:
        import hashlib

        idempotency_key = hashlib.sha256(
            idempotency_key.encode("utf-8")
        ).hexdigest()[:64]
    run_id = idempotency_key or None
    try:
        run = await store.create_run(
            team_id=team_id,
            goal=goal,
            initiator_id=initiator_id,
            project_id=project_id,
            source_chat_id=source_chat_id,
            policy=policy,
            context_bundle=bundle.model_dump(),
            run_id=run_id,
        )
    except IntegrityError:
        existing = await store.get_run(idempotency_key or "")
        if existing is None:
            raise
        return {**existing, "idempotent_replay": True, "nodes": []}
    await store.emit_event(run, "team_run_created", {"goal": goal[:200]})
    start_run_background(run["id"])
    return {**run, "nodes": []}


async def pause_run(run_id: str) -> Dict[str, Any]:
    """暂停一次运行中的 run（协作暂停；与 cancel 终态语义区分）。

    先落 paused 状态再取消后台任务：引擎 CancelledError 收敛分支
    检测到 paused 不改写终态（见 engine._guarded_run），节点中间态
    统一回 pending，续跑从持久视图恢复。
    """
    from . import engine as engine_mod

    store = get_run_store()
    run = await store.get_run(run_id)
    if run is None:
        raise LookupError("run_not_found")
    status = run["status"]
    # 幂等：已暂停直接返回
    if status == RUN_STATUS_PAUSED:
        return {"status": RUN_STATUS_PAUSED}
    if status not in (
        RUN_STATUS_PLANNING,
        RUN_STATUS_RUNNING,
        RUN_STATUS_AWAITING_CONFIRM,
    ):
        raise DecisionConflict(f"状态 {status} 不可暂停")
    # 幂等预置 paused（无后台任务时即为终局状态）
    await store.set_run_status(run_id, RUN_STATUS_PAUSED)
    await store.emit_event(run, "run_paused", {"from_status": status})
    # 传播协作取消到后台任务（引擎收敛分支保持 paused）
    await engine_mod.pause_background_task(run_id)
    return {"status": RUN_STATUS_PAUSED}


async def resume_paused_run(run_id: str) -> Dict[str, Any]:
    """续跑暂停/中断的 run（从持久视图恢复，done 节点跳过）。"""
    from . import engine as engine_mod

    store = get_run_store()
    run = await store.get_run(run_id)
    if run is None:
        raise LookupError("run_not_found")
    if run["status"] not in (RUN_STATUS_INTERRUPTED, RUN_STATUS_PAUSED):
        raise DecisionConflict(f"状态 {run['status']} 不可续跑")
    engine_mod.start_run_background(run_id)
    return {"status": RUN_STATUS_RUNNING}


async def submit_decision(
    run_id: str,
    decision: HumanDecision,
) -> Dict[str, Any]:
    """统一决策处置（协议 15）：需求确认 / 计划批准 / 续跑 / 取消。

    ``decision_id`` 必须与服务端挂起时签发的标识一致；
    ``expected_revision`` 必须等于批准对象当前修订号——版本不一致
    视为过期批准，拒绝放行（重规划/澄清后旧批准自动失效）。
    """
    from . import engine as engine_mod
    from .contracts import decision_matches

    store = get_run_store()
    run = await store.get_run(run_id)
    if run is None:
        raise LookupError("run_not_found")
    status = run["status"]

    # ---- resume / cancel：全局生命周期动作（不依赖挂起决策） ----
    if decision.action == "resume":
        return await resume_paused_run(run_id)
    if decision.action == "cancel":
        if status in engine_mod._RUN_TERMINAL:
            return {"status": status}
        cancelled = await engine_mod.cancel_run(run_id)
        if not cancelled:
            await store.set_run_status(run_id, RUN_STATUS_CANCELED)
            await store.emit_event(run, "team_run_canceled")
        return {"status": RUN_STATUS_CANCELED}

    # ---- 对象绑定动作：必须有服务端签发的挂起决策 ----
    pending = _load_pending_decision(run)
    if pending is None or pending.get("decision_id") != decision.decision_id:
        raise DecisionNotFound("决策标识不存在或已失效")
    # 批准对象版本校验：过期/重复批准拒绝（重规划后 revision 递增）
    if not decision_matches(decision, int(pending.get("revision", 0))):
        raise DecisionConflict(
            "批准对象版本已变化（expected_revision 不匹配），请基于最新摘要重新决策"
        )
    kind = str(pending.get("kind", ""))
    if decision.action == "approve_plan" and kind == "plan":
        return await _apply_object_approval(store, run_id, run, decision, pending)
    if decision.action == "confirm_requirement" and kind == "requirement":
        return await _apply_object_approval(store, run_id, run, decision, pending)
    # 动作与挂起对象不匹配（如对计划门提交需求确认）
    raise DecisionConflict("决策动作与当前挂起对象不匹配")


async def _apply_object_approval(
    store: WorkforceRunStore,
    run_id: str,
    run: Dict[str, Any],
    decision: HumanDecision,
    pending: Dict[str, Any],
) -> Dict[str, Any]:
    """放行挂起的计划/需求门：清挂起对象并重入引擎。"""
    from . import engine as engine_mod
    from .contracts import ContextBundle

    # 恢复为契约模型再修订（bump 依赖模型方法；持久化用 dict）
    bundle_obj = ContextBundle.model_validate(run.get("context_bundle") or {})
    execution_ctx = dict(bundle_obj.execution_ctx)
    # 记录已批准决策留痕（approved revisions 语义；详情接口可投影）
    approved = list(execution_ctx.get("approved_decisions") or [])
    approved.append(
        {
            "decision_id": decision.decision_id,
            "kind": pending.get("kind"),
            "revision": pending.get("revision"),
            "comment": decision.comment,
        }
    )
    execution_ctx["approved_decisions"] = approved
    execution_ctx.pop(_PENDING_DECISION_KEY, None)
    bundle_obj.execution_ctx = execution_ctx
    # 版本 bump（批准改变执行事实；reason 入版本历史轨迹）
    bundle_obj = bundle_mod.bump(bundle_obj, reason=f"decision:{decision.action}")
    await store.bump_context_version(run_id)
    await store.update_run(run_id, context_bundle=bundle_obj.model_dump())
    await store.set_run_status(run_id, RUN_STATUS_RUNNING)
    await store.emit_event(
        run,
        "decision_applied",
        {
            "decision_id": decision.decision_id,
            "action": decision.action,
            "revision": pending.get("revision"),
            "comment": decision.comment[:200],
        },
    )
    # 审批中心待办同步解决（best-effort；权威链在 run 状态）
    await approvals_mod.resolve_team_approval(
        pending.get("approval_request_id"), approved=True
    )
    # 计划已物化：主循环跳过规划直接进入执行波次
    engine_mod.start_run_background(run_id)
    return {"status": RUN_STATUS_RUNNING, "decision_id": decision.decision_id}


__all__ = [
    "create_team_run",
    "pause_run",
    "resume_paused_run",
    "submit_decision",
    "DecisionConflict",
    "DecisionError",
    "DecisionNotFound",
]
