# -*- coding: utf-8 -*-
"""业务动作账本与可信执行信封构建（T4：可信委派/工具治理/动作账本）。

- ``team_run_actions``：外部动作**先落库后执行**——``register_action``
  以 (tenant_id, run_id, action_key) 唯一约束做幂等登记：同 key 冲突
  返回既有记录（created=False），调用方不得重复触发外部副作用；
  状态机 registered → executed | failed，撤销/中断回收走 reverted；
- ``build_execution_envelope``：服务端控制面生成 TrustedExecutionEnvelope
  （协议02）——租户/发起人/委托范围全部取自服务端持久状态（run 行 +
  RequirementBrief），模型输出与外部请求不可覆盖；授权范围未配置即
  空范围（治理面按最小授权拒绝全部越界工具），与"适配器不能证明可
  限制外部动作时仅开放经验证的只读/沙箱能力"的收窄原则一致；
- ``recover_pending``：run 中断/取消后回收遗留 registered 动作（置
  reverted 留痕，防悬挂登记被误读为已执行）。

@author qingfeng
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from .contracts import TrustedExecutionEnvelope

logger = logging.getLogger(__name__)

#: 动作状态：已登记未执行（"先落库后执行"的落库态）
ACTION_STATUS_REGISTERED = "registered"
#: 动作状态：已执行成功（result 有效，终态）
ACTION_STATUS_EXECUTED = "executed"
#: 动作状态：执行失败（error 有效；不回滚已发生的副作用）
ACTION_STATUS_FAILED = "failed"
#: 动作状态：已回滚/作废（recovery/撤权语义，终态）
ACTION_STATUS_REVERTED = "reverted"


def _json_dumps(value: Any) -> str:
    """序列化为 JSON 文本（JSONB 列统一走 CAST 参数绑定）。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def build_execution_envelope(
    run: Dict[str, Any],
    node_key: str,
    attempt_id: str,
    budget_reservation_id: str = "",
) -> TrustedExecutionEnvelope:
    """服务端生成 TrustedExecutionEnvelope（协议02；控制面权威）。

    授权边界（delegate_scope）取需求基线的 ``resource_scope``；策略
    快照引用指向 run 行内服务端留存的 policy JSONB（不内联凭据）。
    """
    # 授权范围来自需求基线（服务端持久状态），外部输入不可覆盖
    task_ctx = ((run.get("context_bundle") or {}).get("task_ctx")) or {}
    brief = task_ctx.get("requirement_brief") or {}
    run_id = str(run.get("id") or "")
    return TrustedExecutionEnvelope(
        tenant_id=str(run.get("tenant_id") or current_tenant_id()),
        initiator_user_id=str(run.get("initiator_id") or ""),
        delegate_scope=[str(s) for s in (brief.get("resource_scope") or [])],
        team_id=str(run.get("team_id") or ""),
        run_id=run_id,
        node_key=node_key,
        attempt_id=attempt_id,
        root_session_id=str(run.get("source_chat_id") or ""),
        execution_id=new_id("exec"),
        policy_snapshot_ref=f"run_policy:{run_id}",
        budget_reservation_id=budget_reservation_id,
    )


async def register_action(
    run_id: str,
    node_key: str,
    attempt_id: str,
    action_type: str,
    action_key: str,
    envelope: Optional[TrustedExecutionEnvelope] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """登记外部动作（先落库后执行；action_key 冲突 → 幂等回原记录）。

    返回 ``{"action_id", "created", "status", "result"}``：

    - ``created=True`` → 本调用完成登记，调用方可执行动作并回写状态；
    - ``created=False`` → 同 action_key 已登记（重放命中），调用方
      不得重复执行；``status=executed`` 时可直接复用 ``result``。
    """
    action_id = new_id("act")
    params = {
        "tid": current_tenant_id(),
        "id": action_id,
        "run": run_id,
        "node": node_key,
        "attempt": attempt_id,
        "atype": action_type,
        "akey": action_key,
        "env": _json_dumps(envelope.model_dump() if envelope else {}),
        "payload": _json_dumps(payload or {}),
    }
    engine = require_enterprise_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "INSERT INTO team_run_actions (tenant_id, id, run_id, "
                "node_key, attempt_id, action_type, action_key, envelope, "
                "payload) VALUES (:tid, :id, :run, :node, :attempt, "
                ":atype, :akey, CAST(:env AS JSONB), CAST(:payload AS JSONB)) "
                "ON CONFLICT (tenant_id, run_id, action_key) "
                "WHERE status <> 'reverted' DO NOTHING"
            ),
            params,
        )
        if result.rowcount:
            return {
                "action_id": action_id,
                "created": True,
                "status": ACTION_STATUS_REGISTERED,
                "result": {},
            }
        # 幂等重放：回读活跃登记（registered/executed/failed 占键；
        # 不重复执行外部副作用）。reverted 不占键（插入不会命中冲突）
        existing = await conn.execute(
            text(
                "SELECT id, status, result FROM team_run_actions WHERE "
                "tenant_id = :tid AND run_id = :run AND action_key = :akey "
                "AND status <> 'reverted'"
            ),
            params,
        )
        row = existing.mappings().first()
    if row is None:
        # DO NOTHING 与回读同事务，理论不可达；防御性兜底
        raise RuntimeError(f"动作登记回读失败: run={run_id} key={action_key}")
    return {
        "action_id": str(row["id"]),
        "created": False,
        "status": str(row["status"]),
        "result": row["result"] if isinstance(row["result"], dict) else {},
    }


async def _mark_action(
    action_id: str,
    status: str,
    *,
    result: Optional[Dict[str, Any]] = None,
    error: str = "",
) -> bool:
    """通用状态回写（仅 registered/failed 可推进；终态幂等不变更）。"""
    engine = require_enterprise_engine()
    async with engine.begin() as conn:
        db_result = await conn.execute(
            text(
                "UPDATE team_run_actions SET status = :status, "
                "result = CAST(:result AS JSONB), error = :error, "
                "updated_at = now() WHERE tenant_id = :tid AND id = :id "
                "AND status IN ('registered', 'failed')"
            ),
            {
                "tid": current_tenant_id(),
                "id": action_id,
                "status": status,
                "result": _json_dumps(result or {}),
                "error": error,
            },
        )
    return bool(db_result.rowcount)


async def mark_executed(
    action_id: str,
    result: Optional[Dict[str, Any]] = None,
) -> bool:
    """标记动作执行成功（registered → executed，回写结果）。"""
    return await _mark_action(action_id, ACTION_STATUS_EXECUTED, result=result)


async def mark_failed(action_id: str, error: str) -> bool:
    """标记动作执行失败（registered → failed，error 留痕）。"""
    return await _mark_action(action_id, ACTION_STATUS_FAILED, error=error)


async def mark_reverted(action_id: str, reason: str = "") -> bool:
    """标记动作回滚/作废（registered|failed → reverted）。"""
    return await _mark_action(
        action_id, ACTION_STATUS_REVERTED, error=reason
    )


async def get_by_action_key(
    run_id: str, action_key: str
) -> Optional[Dict[str, Any]]:
    """按动作幂等键查询登记记录（跨租户不可见）。

    同 key 可能存在多行历史（reverted 后重新登记）：活跃行优先，
    其次取最新 reverted（审计回溯）。
    """
    engine = require_enterprise_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT id, run_id, node_key, attempt_id, action_type, "
                "action_key, status, envelope, payload, result, error, "
                "created_at, updated_at FROM team_run_actions WHERE "
                "tenant_id = :tid AND run_id = :run AND action_key = :akey "
                "ORDER BY CASE WHEN status = 'reverted' THEN 1 ELSE 0 END, "
                "created_at DESC, id DESC LIMIT 1"
            ),
            {
                "tid": current_tenant_id(),
                "run": run_id,
                "akey": action_key,
            },
        )
        row = result.mappings().first()
    return dict(row) if row else None


async def list_by_run(run_id: str) -> List[Dict[str, Any]]:
    """列出 run 的全部动作登记（created_at 升序，审计视图）。"""
    engine = require_enterprise_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT id, run_id, node_key, attempt_id, action_type, "
                "action_key, status, envelope, payload, result, error, "
                "created_at, updated_at FROM team_run_actions WHERE "
                "tenant_id = :tid AND run_id = :run ORDER BY created_at, id"
            ),
            {"tid": current_tenant_id(), "run": run_id},
        )
        return [dict(row) for row in result.mappings().all()]


async def recover_pending(run_id: str, reason: str = "") -> int:
    """回收 run 内遗留的 registered 动作（中断/取消恢复，置 reverted）。

    中断恢复时挂起的登记不可能再执行完成：置 reverted 留痕，防止
    悬挂登记被误读为"已执行"，同时为重放提供新登记空间。
    """
    engine = require_enterprise_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE team_run_actions SET status = 'reverted', "
                "error = :reason, updated_at = now() WHERE tenant_id = :tid "
                "AND run_id = :run AND status = 'registered'"
            ),
            {
                "tid": current_tenant_id(),
                "run": run_id,
                "reason": reason or "recovered_unfinished_run",
            },
        )
    count = int(result.rowcount or 0)
    if count:
        logger.warning("回收 run %s 的 %d 个未完成动作", run_id, count)
    return count
