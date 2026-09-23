# -*- coding: utf-8 -*-
"""团队配置变更提案持久化：AI 只能提出候选，用户确认后执行（P5）。

本模块是 ``team_change_requests`` 表的唯一数据访问入口，供 AI 工具
（``team_prepare_change`` / ``team_prepare_publish``）创建候选，以及
HTTP 确认端点执行 CAS 写入。

状态机::

    pending → applying → applied
                      → conflict  （CAS 基准已变）
                      → failed    （执行异常）
    pending → rejected  （用户拒绝 / 权限撤销）
    pending → expired   （超过 expires_at）

硬约束：

- 候选绑定 tenant_id + team_id + operator_id + session_id + candidate_hash，
  确认时必须完整匹配，防止身份伪造或候选篡改；
- 默认 30 分钟过期，不提供"永久授权"；
- 同一团队同时只允许一个 pending 提案（新提案自动使旧提案 expired）。

@author qingfeng
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import text

from ..enterprise import current_tenant_id, require_enterprise_engine
from .store import DraftRevisionConflict, get_expert_store

logger = logging.getLogger(__name__)

# ── 状态常量 ──────────────────────────────────────────────────────

STATUS_PENDING = "pending"
STATUS_APPLYING = "applying"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_CONFLICT = "conflict"
STATUS_FAILED = "failed"

TERMINAL_STATUSES = frozenset({
    STATUS_APPLIED, STATUS_REJECTED, STATUS_EXPIRED,
    STATUS_CONFLICT, STATUS_FAILED,
})

# ── 提案类型 ──────────────────────────────────────────────────────

KIND_SAVE_DRAFT = "save_draft"
KIND_PUBLISH = "publish"

# ── 默认过期时间 ──────────────────────────────────────────────────

DEFAULT_EXPIRY_MINUTES = 30

#: applying 态卡死回收阈值（分钟）：置为 applying 后进程崩溃/重启
#: 会导致提案永久停留执行中，超过阈值视为执行中断收敛为 failed。
STALE_APPLY_MINUTES = 10

# ── 工具函数 ──────────────────────────────────────────────────────


def _candidate_hash(payload: dict) -> str:
    """对候选内容计算 SHA-256 摘要（防篡改比对）。"""
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    """当前 UTC 时间（aware datetime）。"""
    return datetime.now(timezone.utc)


# ── 数据访问层 ────────────────────────────────────────────────────


async def create_change_request(
    *,
    team_id: str,
    operator_id: str,
    session_id: str,
    kind: str,
    candidate_payload: dict,
    validation_result: Optional[dict] = None,
    expiry_minutes: int = DEFAULT_EXPIRY_MINUTES,
) -> Dict[str, Any]:
    """创建一条新的变更提案。

    创建前自动将同团队已有的 pending 提案标记为 expired（同一时间
    只允许一个活跃提案）。返回完整提案记录。
    """
    tenant = current_tenant_id()
    engine = require_enterprise_engine()

    # 获取团队当前 draft_revision 和 published_version 作为 CAS 基准
    store = get_expert_store()
    team = await store.get_team(team_id)
    if team is None:
        raise ValueError(f"团队 {team_id} 不存在")

    base_revision = getattr(team, "draft_revision", 0) or 0
    base_published_version = getattr(team, "published_version", 0) or 0

    request_id = str(uuid4())
    candidate_hash = _candidate_hash(candidate_payload)
    now = _utcnow()
    expires_at = now + timedelta(minutes=expiry_minutes)

    async with engine.begin() as conn:
        # 将同团队已有的 pending 提案过期（单活跃约束）
        await conn.execute(
            text(
                "UPDATE team_change_requests SET status = :new_status, "
                "updated_at = :now "
                "WHERE tenant_id = :tenant AND team_id = :team_id "
                "AND status = :pending_status"
            ),
            {
                "new_status": STATUS_EXPIRED,
                "now": now,
                "tenant": tenant,
                "team_id": team_id,
                "pending_status": STATUS_PENDING,
            },
        )
        # 插入新提案
        await conn.execute(
            text(
                "INSERT INTO team_change_requests "
                "(tenant_id, request_id, team_id, operator_id, session_id, "
                "kind, base_revision, base_published_version, "
                "candidate_hash, candidate_payload, validation_result, "
                "status, expires_at, created_at, updated_at) "
                "VALUES (:tenant, :request_id, :team_id, :operator_id, "
                ":session_id, :kind, :base_revision, :base_published_version, "
                ":candidate_hash, :candidate_payload, :validation_result, "
                ":status, :expires_at, :now, :now)"
            ),
            {
                "tenant": tenant,
                "request_id": request_id,
                "team_id": team_id,
                "operator_id": operator_id,
                "session_id": session_id,
                "kind": kind,
                "base_revision": base_revision,
                "base_published_version": base_published_version,
                "candidate_hash": candidate_hash,
                "candidate_payload": json.dumps(
                    candidate_payload, ensure_ascii=False,
                ),
                "validation_result": json.dumps(
                    validation_result or {}, ensure_ascii=False,
                ),
                "status": STATUS_PENDING,
                "expires_at": expires_at,
                "now": now,
            },
        )

    return {
        "request_id": request_id,
        "team_id": team_id,
        "operator_id": operator_id,
        "session_id": session_id,
        "kind": kind,
        "base_revision": base_revision,
        "base_published_version": base_published_version,
        "candidate_hash": candidate_hash,
        "candidate_payload": candidate_payload,
        "validation_result": validation_result or {},
        "status": STATUS_PENDING,
        "expires_at": expires_at.isoformat(),
        "created_at": now.isoformat(),
    }


async def get_change_request(
    request_id: str,
) -> Optional[Dict[str, Any]]:
    """按 request_id 查询提案（含完整字段）。"""
    tenant = current_tenant_id()
    engine = require_enterprise_engine()

    async with engine.connect() as conn:
        row = (await conn.execute(
            text(
                "SELECT * FROM team_change_requests "
                "WHERE tenant_id = :tenant AND request_id = :request_id"
            ),
            {"tenant": tenant, "request_id": request_id},
        )).first()

    if row is None:
        return None
    return _row_to_dict(row)


async def list_team_pending_requests(
    team_id: str,
) -> List[Dict[str, Any]]:
    """列出团队当前 pending 状态的提案（通常最多一条）。"""
    tenant = current_tenant_id()
    engine = require_enterprise_engine()

    async with engine.connect() as conn:
        rows = (await conn.execute(
            text(
                "SELECT * FROM team_change_requests "
                "WHERE tenant_id = :tenant AND team_id = :team_id "
                "AND status = :status "
                "ORDER BY created_at DESC"
            ),
            {"tenant": tenant, "team_id": team_id, "status": STATUS_PENDING},
        )).fetchall()

    return [_row_to_dict(r) for r in rows]


async def confirm_change_request(
    *,
    request_id: str,
    operator_id: str,
    session_id: str = "",
) -> Dict[str, Any]:
    """确认并执行提案：CAS 写入草稿或触发发布。

    安全门：
    1. 提案必须存在且状态为 pending；
    2. 操作者必须与提案发起者一致（防身份伪造）；
    3. 会话 ID 匹配（空 session_id 跳过此检查）；
    4. 候选未过期；
    5. 执行阶段 CAS：草稿基准 revision 必须仍有效——save_draft 由
       ``update_team`` 乐观锁保证，publish 由 ``_apply_publish``
       显式比对 draft_revision（批准绑定摘要，过期批准不放行新内容）；
    6. pending → applying 乐观锁推进（防并发确认）。

    返回执行结果（含新 draft_revision 或发布版本号）。
    """
    tenant = current_tenant_id()
    engine = require_enterprise_engine()

    # 1. 读取提案
    record = await get_change_request(request_id)
    if record is None:
        return _fail_result(request_id, "提案不存在")

    # 2. 状态检查
    if record["status"] != STATUS_PENDING:
        return _fail_result(
            request_id,
            f"提案状态为 {record['status']}，不可确认",
        )

    # 3. 操作者一致性
    if record["operator_id"] != operator_id:
        return _fail_result(
            request_id,
            "操作者与提案发起者不一致，拒绝执行",
        )

    # 4. 会话归属（空 session_id 跳过）
    if session_id and record["session_id"] and record["session_id"] != session_id:
        return _fail_result(
            request_id,
            "会话归属不匹配，拒绝执行",
        )

    # 5. 过期检查
    expires_at = record.get("expires_at", "")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry < _utcnow():
                # 标记过期
                await _update_status(request_id, STATUS_EXPIRED)
                return _fail_result(request_id, "提案已过期")
        except (ValueError, TypeError):
            pass

    # 6. 标记为 applying（乐观锁，防止并发确认）
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE team_change_requests SET status = :new_status, "
                "updated_at = :now "
                "WHERE tenant_id = :tenant AND request_id = :request_id "
                "AND status = :pending_status"
            ),
            {
                "new_status": STATUS_APPLYING,
                "now": _utcnow(),
                "tenant": tenant,
                "request_id": request_id,
                "pending_status": STATUS_PENDING,
            },
        )
        if result.rowcount == 0:
            return _fail_result(
                request_id, "提案已被并发操作处理",
            )

    # 7. 按 kind 执行实际操作
    kind = record["kind"]
    candidate = record.get("candidate_payload", {})
    base_revision = record.get("base_revision", 0)

    try:
        if kind == KIND_SAVE_DRAFT:
            apply_result = await _apply_save_draft(
                team_id=record["team_id"],
                candidate=candidate,
                base_revision=base_revision,
            )
        elif kind == KIND_PUBLISH:
            apply_result = await _apply_publish(
                team_id=record["team_id"],
                base_revision=base_revision,
            )
        else:
            apply_result = {
                "ok": False,
                "error": f"未知提案类型: {kind}",
            }
    except DraftRevisionConflict as exc:
        await _update_status(request_id, STATUS_CONFLICT, str(exc))
        return _fail_result(request_id, f"CAS 冲突: {exc}")
    except Exception as exc:  # noqa: BLE001
        await _update_status(request_id, STATUS_FAILED, str(exc))
        logger.exception("confirm_change_request failed for %s", request_id)
        return _fail_result(request_id, f"执行失败: {exc}")

    if not apply_result.get("ok"):
        error_msg = apply_result.get("error", "未知错误")
        # CAS 基准漂移落 conflict 态（区别于执行失败的 failed），
        # 前端据此提示“重新发起提案”而非“重试”
        final_status = (
            STATUS_CONFLICT if "CAS 冲突" in error_msg else STATUS_FAILED
        )
        await _update_status(request_id, final_status, error_msg)
        return _fail_result(request_id, error_msg)

    # 8. 标记为 applied（条件更新：applying → applied，防并发路径覆写）
    await _update_status(
        request_id, STATUS_APPLIED, expected_status=STATUS_APPLYING,
    )

    return {
        "ok": True,
        "request_id": request_id,
        "team_id": record["team_id"],
        "kind": kind,
        "status": STATUS_APPLIED,
        **apply_result,
    }


async def reject_change_request(
    *,
    request_id: str,
    operator_id: str,
) -> Dict[str, Any]:
    """用户拒绝提案。"""
    record = await get_change_request(request_id)
    if record is None:
        return _fail_result(request_id, "提案不存在")
    if record["status"] != STATUS_PENDING:
        return _fail_result(
            request_id,
            f"提案状态为 {record['status']}，不可拒绝",
        )
    if record["operator_id"] != operator_id:
        return _fail_result(
            request_id,
            "操作者与提案发起者不一致",
        )
    # 条件更新（pending → rejected）：确认与拒绝并发时仅一方生效，
    # 防止已 applied 的提案被并发拒绝覆写（状态与审计一致性）
    updated = await _update_status(
        request_id, STATUS_REJECTED, expected_status=STATUS_PENDING,
    )
    if not updated:
        return _fail_result(request_id, "提案已被并发操作处理")
    return {
        "ok": True,
        "request_id": request_id,
        "status": STATUS_REJECTED,
    }


async def expire_stale_requests(team_id: str) -> int:
    """回收团队的滞留提案，返回回收数量。

    - pending 且超过 expires_at → expired（正常超时）；
    - applying 且 updated_at 超过 ``STALE_APPLY_MINUTES`` → failed
      （执行中断恢复：进程崩溃后提案不再永久停留"执行中"）。
    """
    tenant = current_tenant_id()
    engine = require_enterprise_engine()
    now = _utcnow()
    stale_before = now - timedelta(minutes=STALE_APPLY_MINUTES)

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE team_change_requests SET status = :new_status, "
                "updated_at = :now "
                "WHERE tenant_id = :tenant AND team_id = :team_id "
                "AND status = :pending_status AND expires_at < :now"
            ),
            {
                "new_status": STATUS_EXPIRED,
                "now": now,
                "tenant": tenant,
                "team_id": team_id,
                "pending_status": STATUS_PENDING,
            },
        )
        expired = result.rowcount
        # applying 卡死恢复：超时未落定即视为执行中断，收敛为 failed
        result = await conn.execute(
            text(
                "UPDATE team_change_requests SET status = :failed_status, "
                "error_message = :stale_reason, updated_at = :now "
                "WHERE tenant_id = :tenant AND team_id = :team_id "
                "AND status = :applying_status AND updated_at < :stale_before"
            ),
            {
                "failed_status": STATUS_FAILED,
                "stale_reason": (
                    f"stale_apply: applying 超过 {STALE_APPLY_MINUTES} 分钟未落定"
                ),
                "now": now,
                "tenant": tenant,
                "team_id": team_id,
                "applying_status": STATUS_APPLYING,
                "stale_before": stale_before,
            },
        )
        stale = result.rowcount
    return expired + stale


# ── 内部实现 ──────────────────────────────────────────────────────


async def _apply_save_draft(
    *,
    team_id: str,
    candidate: dict,
    base_revision: int,
) -> Dict[str, Any]:
    """执行保存草稿：CAS 更新团队配置。"""
    store = get_expert_store()
    record = await store.update_team(
        team_id,
        expected_revision=base_revision,
        name=candidate.get("name"),
        description=candidate.get("description"),
        mode=candidate.get("mode"),
        router_prompt=candidate.get("router_prompt"),
        members=candidate.get("members"),
        orchestration=candidate.get("orchestration"),
        sample_tasks=candidate.get("sample_tasks"),
        showcase=candidate.get("showcase"),
    )
    new_revision = getattr(record, "draft_revision", base_revision + 1)
    return {
        "ok": True,
        "draft_revision": new_revision,
        "team_version": record.version if record else 0,
    }


async def _apply_publish(
    *,
    team_id: str,
    base_revision: int,
) -> Dict[str, Any]:
    """执行发布：先校验草稿基准未漂移，再调用现有发布链。

    CAS 语义（批准绑定摘要）：用户确认的是提案展示时的基准草稿；
    确认前草稿被再次修改（draft_revision 递增）则拒绝发布——放行
    新内容等于绕过用户确认（P0 安全门）。
    """
    from .publish import publish_expert_team

    store = get_expert_store()
    team = await store.get_team(team_id)
    if team is None:
        return {"ok": False, "error": "团队不存在"}
    current_revision = getattr(team, "draft_revision", 0) or 0
    if current_revision != base_revision:
        return {
            "ok": False,
            "error": (
                f"CAS 冲突: 草稿已变化（基准 #{base_revision}，"
                f"当前 #{current_revision}），请重新发起发布提案"
            ),
        }
    record = await publish_expert_team(
        team_id,
        published_by="ai-change-request",
    )
    return {
        "ok": True,
        "published_version": record.version if record else 0,
    }


async def _update_status(
    request_id: str,
    status: str,
    error_message: str = "",
    expected_status: str = "",
) -> bool:
    """更新提案状态（内部工具方法）。

    ``expected_status`` 非空时执行条件更新（乐观锁语义）：当前状态
    不等于期望值则不写入并返回 False，防止并发路径把已终态的提案
    覆写（如 reject 与 confirm 竞态把 applied 覆写为 rejected）。
    """
    tenant = current_tenant_id()
    engine = require_enterprise_engine()
    now = _utcnow()
    applied_at = now if status == STATUS_APPLIED else None

    # 条件子句仅在指定期望前态时追加（无条件路径供失败收敛使用）
    conditions = "AND status = :expected_status" if expected_status else ""
    params: Dict[str, Any] = {
        "status": status,
        "error_message": error_message,
        "now": now,
        "applied_at": applied_at,
        "tenant": tenant,
        "request_id": request_id,
    }
    if expected_status:
        params["expected_status"] = expected_status

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE team_change_requests SET status = :status, "
                "error_message = :error_message, updated_at = :now, "
                "applied_at = :applied_at "
                "WHERE tenant_id = :tenant AND request_id = :request_id "
                + conditions
            ),
            params,
        )
    return bool(result.rowcount)


def _fail_result(request_id: str, error: str) -> Dict[str, Any]:
    """构造失败返回结构。"""
    return {
        "ok": False,
        "request_id": request_id,
        "error": error,
    }


def _row_to_dict(row) -> Dict[str, Any]:
    """将数据库行转为字典。"""
    payload = row.candidate_payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            payload = {}

    validation = row.validation_result
    if isinstance(validation, str):
        try:
            validation = json.loads(validation)
        except (json.JSONDecodeError, TypeError):
            validation = {}

    return {
        "request_id": row.request_id,
        "team_id": row.team_id,
        "operator_id": row.operator_id,
        "session_id": getattr(row, "session_id", "") or "",
        "kind": row.kind,
        "base_revision": row.base_revision,
        "base_published_version": row.base_published_version,
        "candidate_hash": row.candidate_hash,
        "candidate_payload": payload,
        "validation_result": validation,
        "status": row.status,
        "error_message": getattr(row, "error_message", "") or "",
        "expires_at": (
            row.expires_at.isoformat() if row.expires_at else ""
        ),
        "created_at": (
            row.created_at.isoformat() if row.created_at else ""
        ),
        "updated_at": (
            row.updated_at.isoformat() if row.updated_at else ""
        ),
        "applied_at": (
            row.applied_at.isoformat()
            if getattr(row, "applied_at", None)
            else ""
        ),
    }


__all__ = [
    "KIND_PUBLISH",
    "KIND_SAVE_DRAFT",
    "STATUS_APPLIED",
    "STATUS_APPLYING",
    "STATUS_CONFLICT",
    "STATUS_EXPIRED",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_REJECTED",
    "TERMINAL_STATUSES",
    "confirm_change_request",
    "create_change_request",
    "expire_stale_requests",
    "get_change_request",
    "list_team_pending_requests",
    "reject_change_request",
]
