# -*- coding: utf-8 -*-
"""企业治理写路径审计 helper（T8）。

沿用 ``providers._audit_agent_model_change`` 的既有模式（audit_events 面）：
谁（actor_id）在何时对什么（target）做了什么（tool_name），变更前后
（before/after）留档，供合规追溯。所有 KB / Ontology / 绑定管理面写路径
经此统一接线，避免每处复制 try/except 样板。

审计绝不抛异常：写失败仅告警，不阻塞业务主流程。

@author qingfeng
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from qwenpaw.governance.audit import AuditLog
from qwenpaw.governance.policy import (
    GovernanceAction,
    GovernanceDecision,
    ToolCallSpec,
)

logger = logging.getLogger(__name__)


def _audit_log() -> AuditLog:
    """审计后端门面工厂（测试经 monkeypatch 本函数注入 spy）。"""
    return AuditLog.get_instance()


def record_write_audit(
    *,
    tool_name: str,
    target: str,
    actor_id: str = "",
    workspace_dir: str = "",
    before: Dict[str, Any] | None = None,
    after: Dict[str, Any] | None = None,
    reason: str = "",
) -> None:
    """Record one write-path audit row (best-effort, never raises).

    Args:
        tool_name: 动作名（如 ``kb_review`` / ``ontology.object.update``）
        target: 操作对象标识（如 ``kb_id:doc_id``）
        actor_id: 操作者（用户名/审核人；缺省视为管理面操作）
        workspace_dir: 审计归属工作区（KB/本体面无工作区语义，留空）
        before: 变更前快照（仅关键字段，避免审计行过大）
        after: 变更后快照（同上）
        reason: 审计备注
    """
    try:
        spec = ToolCallSpec(
            tool_name=tool_name,
            target=target,
            agent_id="",
            session_id="",
            raw_params={"before": before or {}, "after": after or {}},
            user_id=actor_id,
        )
        _audit_log().record(
            workspace_dir,
            spec,
            GovernanceDecision(
                action=GovernanceAction.ALLOW,
                reason=reason or "governed write via admin/management plane",
            ),
        )
    except Exception:  # noqa: BLE001 - audit must never raise
        logger.warning(
            "audit write failed for %s (%s)",
            tool_name,
            target,
            exc_info=True,
        )


__all__ = ["record_write_audit"]
