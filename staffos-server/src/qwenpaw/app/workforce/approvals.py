# -*- coding: utf-8 -*-
"""团队批准 ↔ 审批中心桥接（T3）：不建第二审批系统。

现有审批机制（:mod:`qwenpaw.app.approvals`）是会话维度的通用待办面
（``create_pending_summary`` 支持非 ToolGuard 来源，审批中心可见）。
团队运行的需求/计划批准是**持久**的挂起门（用户可能隔天批准），其
权威状态在 ``team_runs`` 与上下文束挂起决策对象中——本模块只做桥接：

1. **签发通知**：决策挂起时向审批中心登记一条通用待办（best-effort，
   失败不影响团队门），让管理员/发起人在统一入口看到待批事项；
2. **处置同步**：决策经 decisions 通道应用后，同步解决审批中心的
   对应待办（已超时/不存在则忽略）。

Future 语义约束：团队批准不等待审批中心的 Future（超时模型不适配
持久门），``wait_for_approval`` 通道留给 T4 工具治理的 ``approve_action``
（执行时强约束、短超时、拒绝即熔断）。

@author qingfeng
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 团队批准在审批中心的来源类型前缀（审批中心按 source_type 展示）
_SOURCE_PREFIX = "team_run"

#: 桥接注册/解决的开关（审批中心不可用时降级为纯事件链）
_BRIDGE_ENABLED = True


def _service():
    """取审批中心单例（未装配/异常返回 None，桥接静默降级）。"""
    if not _BRIDGE_ENABLED:
        return None
    try:
        from ..approvals import get_approval_service

        return get_approval_service()
    except Exception:  # noqa: BLE001 - 桥接绝不影响团队主链路
        return None


async def issue_team_approval(
    *,
    run_id: str,
    decision_id: str,
    kind: str,
    revision: int,
    summary: Dict[str, Any],
    initiator_id: str = "",
) -> Optional[str]:
    """向审批中心登记一条团队批准待办，返回审批中心 request_id。

    ``kind``：requirement / plan（与挂起决策对象一致）。
    """
    svc = _service()
    if svc is None:
        return None
    try:
        from ..approvals.models import ApprovalRequestSummary

        pending = await svc.create_pending_summary(
            session_id=f"team-run:{run_id}",
            root_session_id=f"team-run:{run_id}",
            owner_agent_id="workforce",
            user_id=initiator_id or "system",
            channel="console",
            agent_id="workforce",
            summary=ApprovalRequestSummary(
                source_type=f"{_SOURCE_PREFIX}_{kind}",
                name=f"团队{'计划' if kind == 'plan' else '需求'}批准",
                severity="medium",
                result_summary=str(summary.get("digest", ""))[:500],
                payload={
                    "team_run_id": run_id,
                    "decision_id": decision_id,
                    "kind": kind,
                    "revision": revision,
                    **summary,
                },
            ),
        )
        return pending.request_id if pending is not None else None
    except Exception:  # noqa: BLE001 - best-effort 桥接
        logger.warning(
            "团队批准登记审批中心失败 run=%s decision=%s",
            run_id,
            decision_id,
            exc_info=True,
        )
        return None


async def resolve_team_approval(request_id: Optional[str], *, approved: bool) -> bool:
    """按审批中心 request_id 同步解决待办（不存在/已超时返回 False）。

    ``request_id`` 为签发时 :func:`issue_team_approval` 的返回值；
    未桥接（None）或已从审批中心消失（超时回收）时静默跳过。
    """
    svc = _service()
    if svc is None or not request_id:
        return False
    try:
        from ...security.tool_guard.approval import ApprovalDecision

        await svc.resolve_request(
            request_id,
            ApprovalDecision.APPROVED if approved else ApprovalDecision.DENIED,
        )
        return True
    except Exception:  # noqa: BLE001 - best-effort 桥接
        logger.info(
            "审批中心待办同步跳过 request=%s", request_id, exc_info=True
        )
        return False


__all__ = ["issue_team_approval", "resolve_team_approval"]
