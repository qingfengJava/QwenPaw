# -*- coding: utf-8 -*-
"""XianWork 分享链接 API：一个会话一条能力令牌链接.

Author: qingfeng

数据基座是 0008_xian_shares 新增的 ``xian_shares`` 表：

- ``POST /api/xian/shares`` —— 为归属当前用户的会话创建（或复用）分享，
  返回 ``{token, url}``；同一会话重复分享恒返回同一 token；
- ``GET /api/xian/shares/view/{token}`` —— 公开端点（免登录，凭 token
  访问）：返回会话元信息 + 完整对话时间线（与 GET /chats/{id} 同构，
  前端复用 historyToTimeline 渲染）+ 会话登记文件列表（含经本路由
  代理的下载 URL）；
- ``GET /api/xian/shares/view/{token}/files/{stored_name}`` —— 公开文件
  下载：校验文件登记行确实归属被分享会话后流式返回 PG 字节副本。

权限模型：创建/撤销走登录态 + 会话归属校验（M1 语义，同 files.py）；
查看/下载只认 token（能力 URL 语义——持有链接即可读），对应的公开
前缀 ``/api/xian/shares/view/`` 在 ``app/auth.py::_PUBLIC_PREFIXES``
登记。会话被删除后分享视图自然 404，无需额外失效逻辑。
"""
from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ...agent_context import get_agent_for_request
from ...enterprise import current_tenant_id, require_enterprise_engine
from ...media_store import list_media_records, load_media_record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shares", tags=["xian-shares"])

#: SPA 路由前缀（App.tsx BrowserRouter basename）——分享链接的落点页面.
_SHARE_URL_PREFIX = "/xianwork/share/"


def _viewer(request: Request) -> str:
    """当前登录账号；未开认证的本地部署回退 local（与 xian 面一致）."""
    return getattr(request.state, "user", None) or "local"


def _owns_chat(request: Request, chat) -> bool:
    """会话归属校验（M1 语义）：未认证放行，认证后按 effective_owner."""
    authenticated_user = getattr(request.state, "user", None)
    if not authenticated_user:
        return True
    return chat.effective_owner == authenticated_user


async def _load_owned_chat(request: Request, chat_id: str):
    """加载归属当前用户的会话；不存在或越权一律 404（不泄露存在性）."""
    workspace = await get_agent_for_request(request)
    chat_manager = workspace.chat_manager
    chat = await chat_manager.get_chat(chat_id) if chat_manager else None
    if chat is None or not _owns_chat(request, chat):
        raise HTTPException(status_code=404, detail="Chat not found")
    return workspace, chat


class ShareCreateBody(BaseModel):
    """POST /shares body."""

    chat_id: str = Field(description="Chat UUID to share")


async def _load_share(
    engine,
    tenant_id: str,
    token: str,
) -> dict[str, Any]:
    """加载未撤销的分享行；无效/撤销一律 404（不泄露存在性）."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT token, chat_id, owner_id, created_at, updated_at "
                "FROM xian_shares "
                "WHERE tenant_id = :tid AND token = :token AND revoked = false"
            ),
            {"tid": tenant_id, "token": token},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Share not found")
    return dict(row)


def _share_payload(token: str, chat_id: str) -> dict[str, str]:
    """创建端点的统一返回（相对路径，前端自行拼 origin）."""
    return {"token": token, "url": f"{_SHARE_URL_PREFIX}{token}"}


@router.post("", status_code=201, summary="Create (or reuse) a chat share link")
async def create_share(body: ShareCreateBody, request: Request) -> dict:
    """为会话生成分享链接；同会话重复分享幂等返回同一链接.

    能力 URL 语义：链接本身即凭据，创建端点因此要求会话归属当前
    登录用户（未登录本地模式放行，与 xian 面其它写端点一致）。
    """
    engine = require_enterprise_engine()
    tenant_id = current_tenant_id()
    viewer = _viewer(request)

    # 会话归属校验（404 语义，不越权泄露他人会话可分享性）
    await _load_owned_chat(request, body.chat_id)

    # 幂等复用：同租户同会话已有有效分享则原样返回
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT token FROM xian_shares "
                "WHERE tenant_id = :tid AND chat_id = :chat_id "
                "AND revoked = false"
            ),
            {"tid": tenant_id, "chat_id": body.chat_id},
        )
        existing = result.scalar_one_or_none()
    if existing:
        return _share_payload(existing, body.chat_id)

    # 并发兜底：撞唯一索引（ux_xian_shares_chat）时读回已存在的行
    token = secrets.token_urlsafe(18)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO xian_shares "
                    "(tenant_id, token, chat_id, owner_id) "
                    "VALUES (:tid, :token, :chat_id, :owner)"
                ),
                {
                    "tid": tenant_id,
                    "token": token,
                    "chat_id": body.chat_id,
                    "owner": viewer,
                },
            )
    except IntegrityError:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT token FROM xian_shares "
                    "WHERE tenant_id = :tid AND chat_id = :chat_id "
                    "AND revoked = false"
                ),
                {"tid": tenant_id, "chat_id": body.chat_id},
            )
            existing = result.scalar_one_or_none()
        if not existing:
            raise HTTPException(409, "Share creation conflict") from None
        return _share_payload(existing, body.chat_id)
    return _share_payload(token, body.chat_id)


@router.get(
    "/view/{token}",
    summary="Public share view: chat meta + transcript + files",
)
async def view_share(token: str, request: Request) -> dict:
    """凭 token 免登录读取分享内容（只读快照，不触发第三方恢复）.

    返回的 ``messages`` 与 ``GET /chats/{id}`` 同构，前端分享页复用
    ``historyToTimeline`` 渲染；``files`` 为会话登记文件（用户上传 +
    Agent 产出），下载地址走本路由的公开文件端点。
    """
    engine = require_enterprise_engine()
    share = await _load_share(engine, current_tenant_id(), token)

    # 分享视图用默认 agent 的工作区定位会话存储（token 即授权，无需登录态）
    workspace = await get_agent_for_request(request)
    chat_manager = workspace.chat_manager
    chat = await chat_manager.get_chat(share["chat_id"]) if chat_manager else None
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    state = await workspace.session.get_session_state_dict(
        chat.session_id,
        chat.user_id,
        chat.channel,
    )

    # 与 chats/api.py::get_chat 同构的时间线组装（只读：跳过第三方
    # hydrate，避免公开访问触发会话恢复写放大）
    memories: list = []
    state_raw = ((state.get("agent") or {}).get("state")) or {}
    if isinstance(state_raw, dict):
        try:
            from agentscope.state import AgentState

            memories = list(AgentState.model_validate(state_raw).context)
        except Exception:
            logger.debug(
                "Share view: failed to parse agent.state for chat %s",
                share["chat_id"],
                exc_info=True,
            )
    if not memories:
        from ...chats.utils import parse_legacy_memory_state

        memory_raw = (state.get("agent") or {}).get("memory") or {}
        if memory_raw:
            memories, _ = parse_legacy_memory_state(memory_raw)

    from ...chats.utils import agentscope_msg_to_message

    messages = [m.model_dump(mode="json") for m in agentscope_msg_to_message(memories)]

    # 会话登记文件：下载 URL 经公开分享端点代理（token 作用域内可读）
    records = await list_media_records(
        chat_id=chat.id,
        session_id=chat.session_id,
    )
    files = [
        {
            "stored_name": rec["stored_name"],
            "file_name": rec.get("file_name"),
            "media_type": rec.get("media_type"),
            "size": rec.get("size"),
            "source": rec.get("source"),
            "url": f"/api/xian/shares/view/{token}/files/{rec['stored_name']}",
        }
        for rec in records
    ]

    return {
        "token": token,
        "chat": {
            "id": chat.id,
            "name": chat.name or "新任务",
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
        },
        "shared_at": share["created_at"],
        "messages": messages,
        "files": files,
    }


@router.get(
    "/view/{token}/files/{stored_name}",
    summary="Public share file download (PG durable copy)",
)
async def view_share_file(token: str, stored_name: str) -> Response:
    """分享页文件下载：校验登记行归属被分享会话后返回字节副本."""
    engine = require_enterprise_engine()
    share = await _load_share(engine, current_tenant_id(), token)

    record = await load_media_record(stored_name)
    if record is None or record.get("data") is None:
        raise HTTPException(status_code=404, detail="File not found")

    # 越权防护：文件登记行必须关联到被分享的会话 —— chat_id 直连
    # 优先；Agent 产行（无 chat_id）回退 session_id 同源校验，防止
    # 拿分享 token 探测其它会话的文件
    linked_chat_id = record.get("chat_id")
    if linked_chat_id != share["chat_id"]:
        session_id = record.get("session_id")
        linked: str | None = None
        if session_id:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT id FROM chats "
                        "WHERE id = :chat_id AND session_id = :session_id"
                    ),
                    {"chat_id": share["chat_id"], "session_id": session_id},
                )
                linked = result.scalar_one_or_none()
        if linked is None:
            raise HTTPException(status_code=404, detail="File not found")

    data = record["data"]
    # RFC 6266：ASCII 回退名 + UTF-8 扩展名（中文文件名两顾）
    raw_name = (record.get("file_name") or stored_name).replace('"', "")
    quoted_name = quote(raw_name, safe="")
    ascii_name = raw_name.encode("ascii", "ignore").decode("ascii") or stored_name
    return Response(
        content=data,
        media_type=record.get("media_type") or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; '
                f"filename*=UTF-8''{quoted_name}"
            ),
        },
    )
