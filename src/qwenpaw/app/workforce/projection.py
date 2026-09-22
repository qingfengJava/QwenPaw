# -*- coding: utf-8 -*-
"""运行投影：从权威账本构建详情/摘要/动作权限（T2）。

前端不自创授权规则（计划 §8.3）：详情接口返回
``allowed_actions`` 与 ``waiting_reason``，全部从 run/node 权威状态
推导；v1 状态字段保持旧语义兼容读取，v2 语义经新增字段并行下发。

@author qingfeng
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import (
    RUN_STATUS_AGGREGATING,
    RUN_STATUS_AWAITING_CONFIRM,
    RUN_STATUS_CANCELED,
    RUN_STATUS_DONE,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PAUSED,
    RUN_STATUS_PLANNING,
    RUN_STATUS_REPAIRING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_VERIFYING,
    WAIT_REASON_PLAN_APPROVAL,
    WAIT_REASON_REQUIREMENT_CONFIRM,
)

#: 各 run 状态下允许的用户动作（服务端唯一口径）
_ALLOWED_ACTIONS: Dict[str, List[str]] = {
    RUN_STATUS_PLANNING: ["cancel"],
    RUN_STATUS_AWAITING_CONFIRM: ["clarify", "cancel"],
    RUN_STATUS_RUNNING: ["cancel"],
    RUN_STATUS_VERIFYING: ["cancel"],
    RUN_STATUS_REPAIRING: ["cancel"],
    RUN_STATUS_AGGREGATING: ["cancel"],
    RUN_STATUS_INTERRUPTED: ["resume", "cancel"],
    RUN_STATUS_ESCALATED: ["escalation", "cancel"],
    # 用户暂停（协作挂起，非终态）：可续跑/取消
    RUN_STATUS_PAUSED: ["resume", "cancel"],
    # 终态：done/failed/canceled 无可执行动作（历史只读）
    RUN_STATUS_DONE: [],
    RUN_STATUS_FAILED: [],
    RUN_STATUS_CANCELED: [],
}

#: 终态集合（投影判断只读视图）
_TERMINAL = {RUN_STATUS_DONE, RUN_STATUS_FAILED, RUN_STATUS_CANCELED}


def allowed_actions(status: str) -> List[str]:
    """给定 run 状态推导用户可执行动作（终态为空清单）。"""
    # 未知状态保守返回空（不放大权限）
    return list(_ALLOWED_ACTIONS.get(status, []))


def waiting_reason(
    status: str,
    *,
    clarification_pending: bool = False,
    plan_approval_pending: bool = False,
) -> str:
    """推导可恢复等待原因（v2 wait_reason 语义；终态返回空）。

    批准门优先级高于澄清（同一挂起状态两者互斥，批准门由服务端
    签发挂起决策对象，澄清由 Clarification 记录驱动）。
    """
    # 终态无等待语义
    if status in _TERMINAL:
        return ""
    if plan_approval_pending:
        # 计划批准门（T3）：等待 approve_plan 决策放行
        return WAIT_REASON_PLAN_APPROVAL
    if status == RUN_STATUS_AWAITING_CONFIRM or clarification_pending:
        # 需求确认/澄清等待（协议15 的待办语义）
        return WAIT_REASON_REQUIREMENT_CONFIRM
    return ""


def build_run_view(
    run: Dict[str, Any],
    nodes: List[Dict[str, Any]],
    *,
    attempts: Optional[List[Dict[str, Any]]] = None,
    revisions: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """组装运行详情视图：兼容字段 + 账本投影 + 动作权限。

    ``run``/``nodes`` 为权威记录原样投影（不重建状态）；attempts/
    revisions/events 为 T2 账本的可选增量；``allowed_actions`` 由
    服务端推导，前端不得自行添加动作。
    """
    status = str(run.get("status") or "")
    # 挂起决策对象（计划批准门）驱动 v2 等待语义
    execution_ctx = (run.get("context_bundle") or {}).get("execution_ctx") or {}
    plan_approval_pending = bool(execution_ctx.get("pending_decision"))
    reason = waiting_reason(
        status,
        clarification_pending=bool(run.get("clarification")),
        plan_approval_pending=plan_approval_pending,
    )
    # 节点进度统计（一次遍历内存统计）
    done_nodes = sum(1 for n in nodes if n.get("status") == "done")
    total_nodes = len(nodes)
    # 动作权限：批准门挂起时细化（approve_plan + 澄清/取消）
    actions = allowed_actions(status)
    if reason == WAIT_REASON_PLAN_APPROVAL:
        actions = ["approve_plan", "clarify", "cancel"]
    # 决策投影（T3）：挂起决策对象与已批准决策留痕（顶层平铺，前端
    # 不必深挖 context_bundle 内部结构）
    pending_decision = execution_ctx.get("pending_decision")
    approved_decisions = execution_ctx.get("approved_decisions") or []
    view: Dict[str, Any] = {
        **run,
        "nodes": nodes,
        # 服务端动作权限（前端不自创授权规则）
        "allowed_actions": actions,
        "waiting_reason": reason,
        "pending_decision": pending_decision,
        "approved_decisions": approved_decisions,
        # 进度摘要（列表页/详情头部共用）
        "progress": {
            "done_nodes": done_nodes,
            "total_nodes": total_nodes,
            "finished": status in _TERMINAL,
        },
    }
    # 账本增量（有则投影，无则空——不伪造）
    if attempts is not None:
        view["attempts"] = attempts
    if revisions is not None:
        view["revisions"] = revisions
    if events is not None:
        view["events"] = events
    return view


__all__ = [
    "allowed_actions",
    "build_run_view",
    "waiting_reason",
]
