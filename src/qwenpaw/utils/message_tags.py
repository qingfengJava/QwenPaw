# -*- coding: utf-8 -*-
"""消息 metadata tag 判定：区分「真实用户请求」与「运行时注入消息」。

``qwenpaw_tag`` 是跨层复用的消息身份标记（agent middleware、memory manager、
loop gate 都要判断哪条消息才是用户本轮真实请求）。判定逻辑只允许存在
一份：scroll 的 active-turn 锚点与独立验收门的任务目标提取必须同源，
否则注入消息会被其中一处误当成新请求（#5746 失败模式的根因）。

@author qingfeng
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from ..constant import (
    EXTERNAL_USER_QUERY_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)


def message_tag(msg: Any) -> str:
    """读取一条消息的 ``qwenpaw_tag``，无 metadata 或非 dict 时返回空串。"""
    # metadata 可能是 None / 非字典（外部构造的消息），一律视为无标记
    metadata = getattr(msg, "metadata", None)
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get(QWENPAW_MESSAGE_TAG_KEY) or "")


def is_external_user_query(msg: Any) -> bool:
    """判断 *msg* 是否用户本轮的真实外部请求（而非运行时注入消息）。"""
    # 角色必须是 user，且带外部请求标记
    return (
        getattr(msg, "role", None) == "user"
        and message_tag(msg) == EXTERNAL_USER_QUERY_MESSAGE_TAG
    )


def latest_external_user_query(messages: Iterable[Any]) -> Optional[Any]:
    """倒序取最近一条外部用户请求；没有则返回 ``None``。"""
    # 反向扫描：上下文尾部才是本轮请求
    ordered = list(messages or [])
    for msg in reversed(ordered):
        if is_external_user_query(msg):
            return msg
    return None


def message_text(msg: Any) -> str:
    """拼接一条消息的全部文本块（非文本块忽略，绝不抛错）。"""
    # content 允许是纯字符串（历史消息/外部构造）
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    # 常规形态：TextBlock 列表（dict 或对象两种表示都兼容）
    parts = []
    for block in content or []:
        block_type = block.get("type") if isinstance(block, dict) else getattr(
            block,
            "type",
            None,
        )
        if block_type != "text":
            continue
        text = block.get("text") if isinstance(block, dict) else getattr(
            block,
            "text",
            None,
        )
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def latest_external_user_text(messages: Iterable[Any]) -> str:
    """取最近一条外部用户请求的文本（无请求时返回空串）。"""
    # 先定位消息再取文本，避免两处各自实现反向扫描
    msg = latest_external_user_query(messages)
    return message_text(msg) if msg is not None else ""


__all__ = [
    "is_external_user_query",
    "latest_external_user_query",
    "latest_external_user_text",
    "message_tag",
    "message_text",
]
