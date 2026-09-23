# -*- coding: utf-8 -*-
"""Agent 产出文件登记钩子（media_files 会话文件登记体系的写入侧）.

Author: qingfeng

Agent 在任务过程中通过 write_file / edit_file / append_file 写出的
文件（报告、代码产物等）原则上直接落在会话绑定的默认工作空间，
本地是唯一副本 —— 用户一旦误删便无法找回。本模块通过
ToolHookRegistry 的 before/after 钩子在每次写入成功后把文件内容
以 ``source='agent_output'`` 快照进 PostgreSQL ``media_files`` 表：

- before 钩子只把 ``file_path`` 参数暂存进 ``ctx.extra``（不改动输入）；
- after 钩子在工具成功（ToolResultState.SUCCESS）后读取该文件，
  计算 sha256，并以内容寻址名 ``{sha256前16位}_{安全文件名}`` upsert
  进 media_files —— 同内容重复写入天然去重，内容变化则产生新版本行，
  恢复端点可把任意历史版本写回 ``storage_uri`` 记录的本地路径。

全程 best-effort：文件超过快照上限、PG 不可用、读取失败等一律
静默跳过（仅记日志），绝不影响工具调用本身。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

from agentscope.message import ToolResultState

from ._hooks import ToolHookRegistry

logger = logging.getLogger(__name__)

# 参与登记的文件写入类工具（工具名 -> 输入参数中的路径字段名）
_FILE_WRITE_TOOLS: dict[str, str] = {
    "write_file": "file_path",
    "edit_file": "file_path",
    "append_file": "file_path",
}

# 单文件快照上限：超大产物（数据集、模型、视频等）只留本地，不进 PG
MAX_AGENT_OUTPUT_SNAPSHOT_BYTES = 20 * 1024 * 1024

# 与 console 上传侧一致的安全文件名规则（字母数字/./-/_，最长 200）
_SAFE_NAME_RE = re.compile(r"[^\w.\-]")


def _safe_file_name(name: str) -> str:
    """清洗展示用文件名，保证可作为 stored_name 片段（无路径分隔符）."""
    base = Path(name).name if name else "file"
    return _SAFE_NAME_RE.sub("_", base)[:200] or "file"


def _guess_media_type(path: Path) -> str:
    """按扩展名推断 MIME 类型，推断失败回退通用二进制类型."""
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


async def _stash_file_path(
    args: dict[str, Any],
    ctx: Any,
) -> dict[str, Any] | None:
    """before 钩子：把工具入参里的文件路径暂存进 ctx.extra.

    返回 ``None`` 表示不修改工具输入 —— 暂存仅供 after 钩子登记使用。
    """
    path_field = _FILE_WRITE_TOOLS.get(ctx.tool_name)
    if path_field:
        ctx.extra["media_out_path"] = args.get(path_field)
    return None


async def _register_agent_output(
    response: Any,
    ctx: Any,
) -> Any:
    """after 钩子：写入成功后把产物文件快照登记进 media_files.

    返回 ``None`` 保持原工具响应不变；任何异常仅记日志（调用方
    ToolCoordinator 亦会兜底），保证不干扰工具执行流程。
    """
    # 只登记成功的写入（ERROR / INTERRUPTED 的产物状态不可信）
    if getattr(response, "state", None) is not ToolResultState.SUCCESS:
        return None

    raw_path = ctx.extra.get("media_out_path")
    if not raw_path or not isinstance(raw_path, str):
        return None

    # 延迟导入避开循环依赖（file_io 属 agents 层，可能反向依赖 tool_calls）
    from ..agents.tools.file_io import _resolve_file_path

    # 复用 file_io 的路径解析：相对路径按当前工作目录/项目目录展开
    absolute_path = Path(_resolve_file_path(raw_path))

    def _read_and_hash() -> tuple[bytes, str] | None:
        """线程池内读取文件并计算指纹；超限或不存在返回 None."""
        try:
            if not absolute_path.is_file():
                return None
            size = absolute_path.stat().st_size
            if size > MAX_AGENT_OUTPUT_SNAPSHOT_BYTES:
                logger.info(
                    "agent output snapshot skipped (size %s > cap): %s",
                    size,
                    absolute_path,
                )
                return None
            data = absolute_path.read_bytes()
            return data, hashlib.sha256(data).hexdigest()
        except OSError as exc:
            logger.info(
                "agent output snapshot unreadable: %s (%s)",
                absolute_path,
                exc,
            )
            return None

    payload = await asyncio.to_thread(_read_and_hash)
    if payload is None:
        return None
    data, digest = payload

    # 内容寻址存储名：同内容 upsert 幂等，内容变化生成新版本行
    safe_name = _safe_file_name(absolute_path.name)
    stored_name = f"{digest[:16]}_{safe_name}"

    from ..app.media_store import save_media_blob

    await save_media_blob(
        stored_name=stored_name,
        file_name=safe_name,
        media_type=_guess_media_type(absolute_path),
        data=data,
        # chat_id 在工具执行上下文不可得，列表/恢复端点经 session_id 关联
        chat_id=None,
        session_id=ctx.session_id,
        owner_id=None,
        source="agent_output",
        storage_type="db",
        storage_uri=str(absolute_path),
        sha256=digest,
    )
    return None


def register_media_output_hooks(registry: ToolHookRegistry) -> None:
    """把产出文件登记钩子挂到写文件类工具上（字段合并语义）.

    ToolHookRegistry.register 只覆盖显式传入的字段，因此不会影响
    其它地方（如 react_agent）为同名工具注册的超时元数据。
    """
    for tool_name in _FILE_WRITE_TOOLS:
        registry.register(
            tool_name,
            before=_stash_file_path,
            after=_register_agent_output,
        )
