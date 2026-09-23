# -*- coding: utf-8 -*-
"""团队配置 AI 对话工具：模型只能提出候选，不能代替用户确认（P5）。

四个工具覆盖"读取草稿 → 准备变更 → 准备发布 → 查询状态"全链路：

- ``team_get_configuration``：读取有权管理的团队当前草稿、修订和 metadata；
- ``team_prepare_change``：生成结构化补丁候选、差异卡和校验结果，
  持久化为 ``team_change_requests`` 行，返回 ``request_id`` 供确认端点消费；
- ``team_prepare_publish``：基于已保存草稿生成独立发布确认请求；
- ``team_get_change_status``：查询持久化提案的当前状态（断线重连/追问）。

不向模型开放"确认按钮"工具。保存/发布由用户点击结构化卡片触发
HTTP 确认端点，服务端执行后即形成回执。

安全约束：

- 仅向有配置权限的根交互会话发现这些工具（成员子会话不获得）；
- 工具函数内部重复执行权限校验，防止绕过发现层；
- 权限、owner、tenant 等字段不在 AI 可写白名单。

@author qingfeng
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...app.agent_context import (
    get_current_agent_id,
    get_current_session_id,
    get_current_user_id,
)
from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)


# ── 辅助函数 ──────────────────────────────────────────────────────


def _ok(text: str) -> ToolChunk:
    """构造成功 ToolChunk。"""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


def _err(text: str) -> ToolChunk:
    """构造错误 ToolChunk（模型可见）。"""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.ERROR,
        content=[TextBlock(type="text", text=text)],
    )


def _derive_team_id() -> str:
    """从当前 agent id 推导团队 id。

    团队实例 agent id 格式为 ``team_{team_id}`` / ``team_{team_id}__draft``。
    非团队 agent 返回空串。
    """
    agent_id = get_current_agent_id() or ""
    if not agent_id.startswith("team_"):
        return ""
    stripped = agent_id[len("team_"):]
    if stripped.endswith("__draft"):
        stripped = stripped[: -len("__draft")]
    return stripped


async def _check_team_manageable(team_id: str) -> Optional[str]:
    """校验当前用户对目标团队是否有配置管理权限。

    返回 None 表示有权限，否则返回错误信息。
    """
    username = get_current_user_id()
    if not username:
        return "Error: 无法识别当前用户身份"
    if not team_id:
        return "Error: 无法识别目标团队（当前 agent 非团队实例）"

    from ...app.experts.team_access import resolve_team_capabilities

    caps = await resolve_team_capabilities(username, team_id)
    if not caps.can_edit_draft:
        return (
            f"Error: 用户 {username} 对团队 {team_id} 无配置编辑权限"
        )
    return None


# ── 工具定义 ──────────────────────────────────────────────────────


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="TeamGetConfiguration",
    default_policy="allow",
    policy_reason="Read team draft configuration (read-only, no side effects)",
    ui_description="读取团队当前草稿配置（AI 可分析但不可直接修改）",
    ui_icon="📋",
)
async def team_get_configuration(
    team_id: str = "",
) -> ToolChunk:
    """Read the current draft configuration of a team you have manage rights on.

    返回团队草稿的完整配置（名称、描述、成员、编排、任务模板、使用案例），
    以及当前 draft_revision（CAS 基准）和 metadata 摘要。此工具只读不写。

    Args:
        team_id (`str`, optional):
            目标团队 ID。留空时自动从当前 agent 上下文推导。

    Returns:
        `ToolChunk`: 团队草稿配置 JSON（含 draft_revision）。
    """
    resolved_team_id = team_id.strip() or _derive_team_id()
    if not resolved_team_id:
        return _err("Error: team_id is required (or run within a team agent).")

    # 权限校验
    perm_error = await _check_team_manageable(resolved_team_id)
    if perm_error:
        return _err(perm_error)

    from ...app.experts.store import get_expert_store
    from ...app.experts.team_config import summarize_team_config

    store = get_expert_store()
    team_record = await store.get_team(resolved_team_id)
    if team_record is None:
        return _err(f"Error: team '{resolved_team_id}' not found.")

    config_summary = summarize_team_config(team_record)
    draft_revision = getattr(team_record, "draft_revision", 0) or 0
    published_version = getattr(team_record, "published_version", 0) or 0

    result = {
        "team_id": resolved_team_id,
        "name": team_record.name,
        "description": team_record.description,
        "mode": team_record.mode,
        "router_prompt": team_record.router_prompt,
        "members": [
            {
                "expert_id": m.expert_id,
                "member_role": m.member_role,
                "role_hint": m.role_hint,
                "seq": m.seq,
                "expert_version": getattr(m, "expert_version", None),
            }
            for m in team_record.members
        ],
        "orchestration": team_record.orchestration or {},
        "sample_tasks": team_record.sample_tasks or [],
        "showcase": team_record.showcase or [],
        "config_summary": config_summary,
        "draft_revision": draft_revision,
        "published_version": published_version,
    }
    return _ok(json.dumps(result, ensure_ascii=False, default=str))


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="TeamPrepareChange",
    default_policy="allow",
    policy_reason="Prepare a team config change candidate (does NOT save)",
    ui_description="准备团队配置变更候选（需用户确认后才保存）",
    ui_icon="✏️",
)
async def team_prepare_change(
    patch: Dict[str, Any],
    team_id: str = "",
) -> ToolChunk:
    """Prepare a structured change candidate for a team configuration.

    根据传入的 patch（部分字段补丁）生成候选变更，服务端计算差异、
    运行校验，并将候选持久化为 ``team_change_requests`` 行（状态 pending）。
    **不会立即保存草稿**——需要用户在聊天界面确认后才执行 CAS 写入。

    返回 ``request_id``（确认端点消费）、``diff``（差异卡）、
    ``validation``（校验结果）。

    Args:
        patch (`dict`):
            结构化补丁，可包含 name/description/mode/router_prompt/
            members/orchestration/sample_tasks/showcase 等字段。
            仅提供的字段会覆盖，其余保持不变。
        team_id (`str`, optional):
            目标团队 ID。留空时自动从当前 agent 上下文推导。

    Returns:
        `ToolChunk`: 候选结果 JSON（含 request_id、diff、validation）。
    """
    resolved_team_id = team_id.strip() or _derive_team_id()
    if not resolved_team_id:
        return _err("Error: team_id is required (or run within a team agent).")

    # 权限校验
    perm_error = await _check_team_manageable(resolved_team_id)
    if perm_error:
        return _err(perm_error)

    if not patch or not isinstance(patch, dict):
        return _err("Error: patch must be a non-empty dict.")

    from ...app.experts.store import get_expert_store
    from ...app.experts.team_config import validate_publishable_team
    from ...app.experts.team_changes import (
        create_change_request,
        KIND_SAVE_DRAFT,
    )
    from ...app.experts.models import ExpertTeamRecord, TeamMember

    store = get_expert_store()
    current_team = await store.get_team(resolved_team_id)
    if current_team is None:
        return _err(f"Error: team '{resolved_team_id}' not found.")

    # 构建候选完整配置（当前值 + patch 覆盖）
    candidate = _build_candidate(current_team, patch)

    # 构建候选完整 TeamRecord 用于校验
    candidate_members = [
        TeamMember(
            expert_id=m.get("expert_id", ""),
            member_role=m.get("member_role", "member"),
            role_hint=m.get("role_hint", ""),
            seq=m.get("seq", 0),
        )
        for m in (candidate.get("members") or [])
    ]
    candidate_team = ExpertTeamRecord(
        id=resolved_team_id,
        name=candidate.get("name", current_team.name),
        description=candidate.get("description", current_team.description),
        mode=candidate.get("mode", current_team.mode),
        router_prompt=candidate.get(
            "router_prompt", current_team.router_prompt,
        ),
        status=current_team.status,
        version=current_team.version,
        owner_id=current_team.owner_id,
        orchestration=candidate.get(
            "orchestration", current_team.orchestration,
        ),
        sample_tasks=candidate.get(
            "sample_tasks", current_team.sample_tasks,
        ),
        showcase=candidate.get("showcase", current_team.showcase),
        members=candidate_members,
    )

    # 运行校验
    issues = validate_publishable_team(candidate_team)
    validation_result = {
        "ok": not issues,
        "issues": issues,
    }

    # 计算差异卡（仅列出变更字段）
    diff = _compute_diff(current_team, patch)

    # 持久化候选
    username = get_current_user_id() or "unknown"
    session_id = get_current_session_id() or ""

    try:
        record = await create_change_request(
            team_id=resolved_team_id,
            operator_id=username,
            session_id=session_id,
            kind=KIND_SAVE_DRAFT,
            candidate_payload=candidate,
            validation_result=validation_result,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return _err(f"Error: failed to create change request: {exc}")

    result = {
        "request_id": record["request_id"],
        "team_id": resolved_team_id,
        "kind": "save_draft",
        "diff": diff,
        "validation": validation_result,
        "base_revision": record["base_revision"],
        "expires_at": record["expires_at"],
        "status": "pending",
        "message": (
            "变更候选已准备，请用户在确认卡片中点击「保存草稿」以执行。"
            if not issues
            else (
                "变更候选已准备，但存在校验问题：\n"
                + "\n".join(f"- {i}" for i in issues)
                + "\n仍可保存为草稿，但无法发布。"
            )
        ),
    }
    return _ok(json.dumps(result, ensure_ascii=False, default=str))


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="TeamPreparePublish",
    default_policy="allow",
    policy_reason="Prepare a team publish request (does NOT publish)",
    ui_description="准备团队发布请求（需用户确认后才发布）",
    ui_icon="🚀",
)
async def team_prepare_publish(
    team_id: str = "",
) -> ToolChunk:
    """Prepare a publish confirmation request for a team.

    基于当前草稿生成发布确认请求，持久化为 ``team_change_requests`` 行。
    **不会立即发布**——需要用户在聊天界面确认后才触发原子发布。

    返回 ``request_id``、当前草稿摘要、发布预检结果。

    Args:
        team_id (`str`, optional):
            目标团队 ID。留空时自动从当前 agent 上下文推导。

    Returns:
        `ToolChunk`: 发布请求 JSON（含 request_id、预检结果）。
    """
    resolved_team_id = team_id.strip() or _derive_team_id()
    if not resolved_team_id:
        return _err("Error: team_id is required (or run within a team agent).")

    # 权限校验（发布需要 can_publish）
    username = get_current_user_id()
    if not username:
        return _err("Error: 无法识别当前用户身份")
    if not resolved_team_id:
        return _err("Error: 无法识别目标团队")

    from ...app.experts.team_access import resolve_team_capabilities

    caps = await resolve_team_capabilities(username, resolved_team_id)
    if not caps.can_publish:
        return _err(
            f"Error: 用户 {username} 对团队 {resolved_team_id} 无发布权限"
        )

    from ...app.experts.store import get_expert_store
    from ...app.experts.team_config import validate_publishable_team
    from ...app.experts.team_changes import (
        create_change_request,
        KIND_PUBLISH,
    )
    from ...app.experts.capability_view import team_capability_view

    store = get_expert_store()
    current_team = await store.get_team(resolved_team_id)
    if current_team is None:
        return _err(f"Error: team '{resolved_team_id}' not found.")

    # 发布预检
    issues = list(validate_publishable_team(current_team))
    cap_view = await team_capability_view(resolved_team_id)
    for member in cap_view.get("members", []):
        if not member.get("published"):
            issues.append(
                f"成员 [{member.get('name') or member.get('expert_id')}] "
                f"未发布：{member.get('unavailable_reason')}"
            )

    validation_result = {"ok": not issues, "issues": issues}

    session_id = get_current_session_id() or ""
    try:
        record = await create_change_request(
            team_id=resolved_team_id,
            operator_id=username,
            session_id=session_id,
            kind=KIND_PUBLISH,
            candidate_payload={"team_id": resolved_team_id},
            validation_result=validation_result,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return _err(f"Error: failed to create publish request: {exc}")

    draft_revision = getattr(current_team, "draft_revision", 0) or 0
    published_version = getattr(current_team, "published_version", 0) or 0

    result = {
        "request_id": record["request_id"],
        "team_id": resolved_team_id,
        "kind": "publish",
        "current_version": published_version,
        "draft_revision": draft_revision,
        "validation": validation_result,
        "member_count": len(current_team.members),
        "expires_at": record["expires_at"],
        "status": "pending",
        "message": (
            "发布请求已准备，请用户在确认卡片中点击「确认发布」以执行。"
            if not issues
            else (
                "发布请求已准备，但存在阻塞问题：\n"
                + "\n".join(f"- {i}" for i in issues)
                + "\n请解决后再确认发布。"
            )
        ),
    }
    return _ok(json.dumps(result, ensure_ascii=False, default=str))


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="TeamGetChangeStatus",
    default_policy="allow",
    policy_reason="Read change request status (read-only)",
    ui_description="查询团队配置变更提案的当前状态",
    ui_icon="🔍",
)
async def team_get_change_status(
    request_id: str,
) -> ToolChunk:
    """Query the current status of a team change request.

    用于断线重连或用户追问时查询提案状态。返回提案完整信息，
    包括 status（pending/applying/applied/rejected/expired/conflict/failed）、
    差异摘要和执行结果。

    Args:
        request_id (`str`):
            变更提案 ID（由 team_prepare_change 或 team_prepare_publish 返回）。

    Returns:
        `ToolChunk`: 提案状态 JSON。
    """
    clean_id = (request_id or "").strip()
    if not clean_id:
        return _err("Error: request_id is required.")

    from ...app.experts.team_changes import get_change_request

    record = await get_change_request(clean_id)
    if record is None:
        return _err(f"Error: change request '{clean_id}' not found.")

    # 权限校验：操作者或管理员可查
    username = get_current_user_id()
    if username and record["operator_id"] != username:
        from ...app.experts.team_access import resolve_team_capabilities
        caps = await resolve_team_capabilities(
            username, record["team_id"],
        )
        if not caps.manageable:
            return _err(
                "Error: 无权查看此提案（非发起者且无管理权限）"
            )

    # 精简返回（不暴露完整 candidate_payload）
    result = {
        "request_id": record["request_id"],
        "team_id": record["team_id"],
        "kind": record["kind"],
        "status": record["status"],
        "base_revision": record["base_revision"],
        "base_published_version": record["base_published_version"],
        "validation_result": record.get("validation_result", {}),
        "error_message": record.get("error_message", ""),
        "expires_at": record.get("expires_at", ""),
        "created_at": record.get("created_at", ""),
        "applied_at": record.get("applied_at", ""),
    }
    return _ok(json.dumps(result, ensure_ascii=False, default=str))


# ── 内部工具函数 ──────────────────────────────────────────────────


def _build_candidate(
    current_team: Any,
    patch: Dict[str, Any],
) -> Dict[str, Any]:
    """合并当前配置与补丁，生成候选完整配置。"""
    candidate: Dict[str, Any] = {
        "name": current_team.name,
        "description": current_team.description,
        "mode": current_team.mode,
        "router_prompt": current_team.router_prompt,
        "members": [
            {
                "expert_id": m.expert_id,
                "member_role": m.member_role,
                "role_hint": m.role_hint,
                "seq": m.seq,
                # 版本绑定原样保留（P2）：丢弃会导致确认时全量重建
                # 成员表清空绑定，漂移检测失效
                "expert_version": getattr(m, "expert_version", None),
            }
            for m in current_team.members
        ],
        "orchestration": current_team.orchestration or {},
        "sample_tasks": current_team.sample_tasks or [],
        "showcase": current_team.showcase or [],
    }
    # 覆盖 patch 中提供的字段
    for key in (
        "name", "description", "mode", "router_prompt",
        "members", "orchestration", "sample_tasks", "showcase",
    ):
        if key in patch:
            candidate[key] = patch[key]
    return candidate


def _compute_diff(
    current_team: Any,
    patch: Dict[str, Any],
) -> Dict[str, Any]:
    """计算差异卡：哪些字段会变更，旧值→新值。"""
    diff: Dict[str, Any] = {}
    field_map = {
        "name": current_team.name,
        "description": current_team.description,
        "mode": current_team.mode,
        "router_prompt": current_team.router_prompt,
    }
    for key, old_val in field_map.items():
        if key in patch and patch[key] != old_val:
            diff[key] = {"old": old_val, "new": patch[key]}

    # 集合类字段：比较长度或内容
    for key in ("members", "orchestration", "sample_tasks", "showcase"):
        if key in patch:
            old_val = getattr(current_team, key, None)
            if isinstance(old_val, list):
                old_val = [
                    {"expert_id": m.expert_id, "member_role": m.member_role}
                    if hasattr(m, "expert_id") else m
                    for m in old_val
                ]
            elif isinstance(old_val, dict):
                pass
            else:
                old_val = list(old_val) if old_val else []
            new_val = patch[key]
            if old_val != new_val:
                diff[key] = {
                    "changed": True,
                    "old_count": len(old_val) if hasattr(old_val, "__len__") else 0,
                    "new_count": len(new_val) if hasattr(new_val, "__len__") else 0,
                }
    return diff


__all__ = [
    "team_get_configuration",
    "team_prepare_change",
    "team_prepare_publish",
    "team_get_change_status",
]
