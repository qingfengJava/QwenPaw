# -*- coding: utf-8 -*-
"""XianWork 会话文件 API：列表 + 误删恢复.

Author: qingfeng

数据基座是 0007_media_registry 扩展后的 ``media_files`` 会话文件
登记表：

- 用户上传（``/console/upload``）落库时携带 chat_id / session_id /
  owner_id / source='upload'；
- Agent 产出（write_file / edit_file / append_file 成功后的钩子）
  以内容寻址名落库，source='agent_output'，经 session_id 关联会话。

本路由对前端暴露两个端点：

- ``GET /api/xian/files?chat_id=`` —— 列出该会话登记的全部文件
  （区分上传/产出，标记本地副本是否仍存在）；
- ``POST /api/xian/files/{stored_name}/restore`` —— 把 PG 持久副本
  写回 ``storage_uri`` 记录的本地路径，用于用户误删后的恢复。

权限模型与 xian 面其它路由一致：先校验目标会话归属当前登录
用户（未登录本地模式放行），恢复端点还要求登记行的会话键能
解析到该会话，防止跨用户越权恢复。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ...agent_context import get_agent_for_request
from ...enterprise import require_enterprise_engine
from ...media_store import list_media_records, load_media_record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["xian-files"])


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
    return chat


@router.get("", summary="List files registered for a chat")
async def list_chat_files(chat_id: str, request: Request) -> dict:
    """列出会话登记文件（用户上传 + Agent 产出），新到旧排序.

    每项附 ``exists_local``（本地副本是否还在，磁盘 IO 走线程池）
    与 ``url``（``/console/media`` 回显地址，PG 副本优先）。
    """
    # 会话归属校验（404 语义），并取 session_id 作为 Agent 产出的关联键
    chat = await _load_owned_chat(request, chat_id)

    # 引擎存在性检查：无 PG 部署直接 503（登记表是本路由的数据源）
    require_enterprise_engine()

    records = await list_media_records(
        chat_id=chat_id,
        session_id=chat.session_id,
    )

    def _mark_local(rec: dict[str, Any]) -> dict[str, Any]:
        """线程池内探测本地副本存在性，并拼装回显 URL."""
        uri = rec.get("storage_uri")
        exists = bool(uri) and rec.get("storage_type") in (
            "db",
            "local",
        ) and Path(uri).is_file()
        return {
            **rec,
            "exists_local": exists,
            "url": f"/api/console/media/{rec['stored_name']}",
        }

    items = await asyncio.to_thread(
        lambda: [_mark_local(r) for r in records],
    )
    return {"chat_id": chat_id, "files": items}


@router.post(
    "/{stored_name}/restore",
    summary="Restore a registered file from the PG copy to its local path",
)
async def restore_chat_file(stored_name: str, request: Request) -> dict:
    """把登记行的 PG 持久副本写回 ``storage_uri`` 本地路径.

    适用场景：Agent 产出的报告被用户在本地误删后恢复，或本地
    ``media/`` 目录被清理后找回上传文件。同内容多版本（内容寻址
    stored_name）时按行恢复 —— 每个历史版本都可独立找回。
    """
    # 引擎存在性检查：无 PG 部署直接 503（PG 副本是恢复的数据源）
    require_enterprise_engine()

    record = await load_media_record(stored_name)
    if record is None:
        raise HTTPException(status_code=404, detail="File record not found")

    # 越权防护：登记行必须能解析到归属当前用户的会话
    # （chat_id 直连优先，Agent 产行走 session_id 反查）。
    workspace = await get_agent_for_request(request)
    chat_manager = workspace.chat_manager
    if chat_manager is None:
        raise HTTPException(status_code=503, detail="Chat manager unavailable")

    linked_chat_id = record.get("chat_id")
    if not linked_chat_id and record.get("session_id"):
        linked_chat_id = await chat_manager.get_chat_id_by_session(
            record["session_id"],
            "console",
        )
    if not linked_chat_id:
        raise HTTPException(status_code=404, detail="Linked chat not found")
    chat = await chat_manager.get_chat(linked_chat_id)
    if chat is None or not _owns_chat(request, chat):
        raise HTTPException(status_code=404, detail="Chat not found")

    data = record.get("data")
    if not data:
        raise HTTPException(
            status_code=409,
            detail="No durable copy for this record (storage_type local)",
        )

    storage_uri = record.get("storage_uri")
    if not storage_uri or not Path(storage_uri).is_absolute():
        raise HTTPException(
            status_code=409,
            detail="Record has no restorable local path",
        )

    target = Path(storage_uri)

    def _write_back() -> None:
        """线程池内写回：父目录缺失时重建（工作空间被整体删掉的场景）."""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    try:
        await asyncio.to_thread(_write_back)
    except OSError as exc:
        logger.warning("media restore failed for %s: %r", stored_name, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Restore failed: {exc}",
        ) from exc
    return {
        "restored": True,
        "stored_name": stored_name,
        "file_name": record.get("file_name"),
        "path": str(target),
        "size": len(data),
    }
