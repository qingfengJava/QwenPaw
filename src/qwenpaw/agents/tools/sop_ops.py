# -*- coding: utf-8 -*-
"""SOP 流程资产 AI 创作工具（对话生成 SOP，直调 PG 草稿行）。

SOP 环境化改造：AI 在对话中通过本组工具创建/编辑 SOP，全部只作用于
``environment='draft'`` 草稿行，绝不触碰线上 production 行，保证数据库
内容一致性（结构化 JSON 参数经 SopStore 落 PG，无文件平面漂移）。每次
写成功后向 SOP 实时编辑 topic publish 全量快照，右侧画布经 SSE 订阅
跟随重绘（AI 边画、画布边变）。

作者统一 qingfeng。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk

from ...app.agent_context import get_current_agent_id
from ...app.experts.models import (
    SOP_ENVIRONMENT_DRAFT,
    SopRecord,
)
from ...app.experts.sops import get_sop_store
from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)

#: 运行态 agent id 前缀/后缀（``expert_{id}`` / ``expert_{id}__draft``）
_AGENT_ID_PREFIX = "expert_"
_DRAFT_SUFFIX = "__draft"


def _current_expert_id() -> str:
    """Derive the owning expert id from the running agent id.

    工作台调试实例（``expert_{id}__draft``）与线上实例（``expert_{id}``）
    剥离前后缀后得到同一 ``{id}``，作为 SOP 归属员工。原生 agent（无
    ``expert_`` 前缀）返回空串，此时 SOP 归属回退为 agent id 本身。
    """
    agent_id = get_current_agent_id() or ""
    if not agent_id.startswith(_AGENT_ID_PREFIX):
        return agent_id
    stripped = agent_id[len(_AGENT_ID_PREFIX):]
    if stripped.endswith(_DRAFT_SUFFIX):
        stripped = stripped[: -len(_DRAFT_SUFFIX)]
    return stripped


async def _publish_sop_event(action: str, record: SopRecord) -> None:
    """Broadcast one SOP draft write on its live-edit topic (canvas follows).

    携带全量 nodes/edges/slots，前端直接 setNodes 重绘；广播失败绝不影响
    工具主链路（画布下次打开从 PG 取现值）。
    """
    try:
        from ...app.enterprise import current_tenant_id
        from ...app.events.bus import get_event_bus, sop_topic

        await get_event_bus().publish(
            sop_topic(current_tenant_id(), record.id),
            {
                "action": action,
                "sop_id": record.id,
                "environment": record.environment,
                "version": record.version,
                "name": record.name,
                "goal": record.goal,
                "nodes": record.nodes,
                "edges": record.edges,
                "slots": record.slots,
            },
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "sop %s tool event publish failed", record.id, exc_info=True,
        )


def _ok(text: str) -> ToolChunk:
    """Build a success ToolChunk carrying one JSON/text payload."""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )


def _err(text: str) -> ToolChunk:
    """Build an error ToolChunk (state=ERROR, surfaced to the model)."""
    return ToolChunk(
        is_last=True,
        state=ToolResultState.ERROR,
        content=[TextBlock(type="text", text=text)],
    )


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="SopCreateDraft",
    default_policy="allow",
    policy_reason="Create a draft SOP owned by the current expert (debug plane)",
    ui_description="Create a draft SOP flow (AI-authored, debug plane)",
    ui_icon="🧩",
)
async def sop_create_draft(
    name: str,
    goal: str = "",
    business_domain: str = "",
    description: str = "",
) -> ToolChunk:
    """Create a new draft SOP owned by the current digital employee.

    在草稿环境新建一条 SOP 流程资产（version=1，status=draft），随后可用
    :func:`sop_update_draft` 填充节点/连线/槽位。草稿仅本员工可见，
    发布（:func:`sop_publish_draft`）后才进线上生效。

    Args:
        name (`str`):
            SOP 流程名称（如"售后退款处理流程"）。
        goal (`str`, optional):
            流程总目标一句话（注入规划上下文的锚点）。
        business_domain (`str`, optional):
            业务域标签（如 客服/交付/财务）。
        description (`str`, optional):
            流程补充描述。

    Returns:
        `ToolChunk`: 含新建 SOP 的 ``sop_id``、名称与版本，供后续编辑引用。
    """
    clean_name = (name or "").strip()
    if not clean_name:
        return _err("Error: SOP name is required.")
    owner = _current_expert_id()
    try:
        record = await get_sop_store().create_sop(
            name=clean_name,
            description=description or "",
            business_domain=business_domain or "",
            goal=goal or "",
            owner_id=owner or None,
            environment=SOP_ENVIRONMENT_DRAFT,
        )
    except Exception as exc:  # pylint: disable=broad-except
        return _err(f"Error: failed to create SOP draft: {exc}")
    await _publish_sop_event("created", record)
    return _ok(
        json.dumps(
            {
                "sop_id": record.id,
                "name": record.name,
                "version": record.version,
                "environment": record.environment,
            },
            ensure_ascii=False,
        ),
    )


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="SopUpdateDraft",
    default_policy="allow",
    policy_reason="Update a draft SOP's nodes/edges/slots (debug plane)",
    ui_description="Update a draft SOP flow graph (AI-authored)",
    ui_icon="✏️",
)
async def sop_update_draft(
    sop_id: str,
    nodes: Optional[List[Dict[str, Any]]] = None,
    edges: Optional[List[Dict[str, Any]]] = None,
    slots: Optional[List[Dict[str, Any]]] = None,
    goal: Optional[str] = None,
    name: Optional[str] = None,
) -> ToolChunk:
    """Update one draft SOP's graph (nodes / edges / slots / goal / name).

    仅改草稿环境行（environment=draft）；省略的参数保持原值不变。节点结构
    ``{id,title,instruction,expected_outcome,tools[]}``，连线
    ``{from,to,condition}``，槽位 ``{key,label,required,ask_prompt}``。
    每次写入后向画布广播全量快照，实现"AI 边画、右侧画布边变"。

    Args:
        sop_id (`str`):
            目标 SOP id（:func:`sop_create_draft` 返回值）。
        nodes (`list[dict]`, optional):
            流程节点数组。
        edges (`list[dict]`, optional):
            流程连线数组。
        slots (`list[dict]`, optional):
            执行期需填充的槽位数组。
        goal (`str`, optional):
            更新流程总目标。
        name (`str`, optional):
            更新流程名称。

    Returns:
        `ToolChunk`: 更新结果（含最新版本与节点/连线数量）。
    """
    clean_id = (sop_id or "").strip()
    if not clean_id:
        return _err("Error: sop_id is required.")
    try:
        record = await get_sop_store().update_sop(
            clean_id,
            environment=SOP_ENVIRONMENT_DRAFT,
            name=name,
            goal=goal,
            nodes=nodes,
            edges=edges,
            slots=slots,
        )
    except ValueError as exc:
        return _err(f"Error: {exc}")
    except Exception as exc:  # pylint: disable=broad-except
        return _err(f"Error: failed to update SOP draft: {exc}")
    if record is None:
        return _err(
            f"Error: draft SOP '{clean_id}' not found "
            "(create it first via sop_create_draft).",
        )
    await _publish_sop_event("updated", record)
    return _ok(
        json.dumps(
            {
                "sop_id": record.id,
                "version": record.version,
                "node_count": len(record.nodes),
                "edge_count": len(record.edges),
                "slot_count": len(record.slots),
            },
            ensure_ascii=False,
        ),
    )


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="SopPublishDraft",
    default_policy="ask",
    policy_reason="Promote a draft SOP to production and bind the expert",
    ui_description="Publish a draft SOP to production (promote + bind expert)",
    ui_icon="🚀",
)
async def sop_publish_draft(
    sop_id: str,
    change_note: str = "",
) -> ToolChunk:
    """Promote one draft SOP to production and bind its owning expert.

    环境化发布闸门：把草稿行内容 promote 为线上新版本（写不可变快照），
    并绑定归属员工使其注入 workforce 规划参考。写操作默认需人工确认
    （``default_policy="ask"``），避免 AI 未经确认直接改线上。

    Args:
        sop_id (`str`):
            目标 SOP id。
        change_note (`str`, optional):
            本次发布变更说明（写入版本快照）。

    Returns:
        `ToolChunk`: 发布结果（含新版本号与绑定员工）。
    """
    clean_id = (sop_id or "").strip()
    if not clean_id:
        return _err("Error: sop_id is required.")
    try:
        record = await get_sop_store().promote_sop(
            clean_id,
            published_by=_current_expert_id() or "ai-agent",
            change_note=change_note or "",
        )
    except Exception as exc:  # pylint: disable=broad-except
        return _err(f"Error: failed to publish SOP: {exc}")
    if record is None:
        return _err(f"Error: SOP '{clean_id}' not found or archived.")
    # promote 成功后绑定归属员工（与 admin 发布端点同一组合语义）
    owner = record.owner_id or _current_expert_id()
    bound = False
    if owner:
        try:
            from ...app.experts.capability import get_capability_store

            await get_capability_store().ensure_binding(
                owner,
                "sop",
                clean_id,
                {"name": record.name},
            )
            bound = True
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "sop %s published but bind to %s failed",
                clean_id,
                owner,
                exc_info=True,
            )
    await _publish_sop_event("published", record)
    return _ok(
        json.dumps(
            {
                "sop_id": record.id,
                "version": record.version,
                "status": record.status,
                "bound_expert": owner if bound else "",
            },
            ensure_ascii=False,
        ),
    )
