# -*- coding: utf-8 -*-
"""T9: ``<knowledge-bases>`` 目录注入渲染（Agent 接入层，spec §7.2）。

数字员工运行时，builder 查其 ``agent_kb_bindings`` 绑定库，用本模块渲染成
一段 ``<knowledge-bases>`` 目录块注入 system prompt——让 Agent 自主判断
「何时该查哪个库」（description 即路由信号）。仿 skills 的「目录注入 +
按需拉取」契约：目录只给 id/name/description，全文由 ``kb_read`` 按需拉。

@author qingfeng
"""

from __future__ import annotations

from typing import Any, Sequence

#: 目录块引导语：向 Agent 交代检索纪律（先 kb_search 再作答，闲聊不检索）
_INTRO = (
    "以下是当前数字员工可检索的知识库。涉及以下领域问题时，"
    "必须先调用 kb_search 检索对应知识库，再结合结果作答；"
    "闲聊或不相关话题不要检索。"
)


def render_kb_catalog(spaces: Sequence[Any]) -> str:
    """把绑定库清单渲染成 ``<knowledge-bases>`` 目录块。

    Args:
        spaces: 绑定库序列（鸭子类型取 ``.id`` / ``.name`` /
            ``.description``，兼容 pg 平面 ``KbSpace`` 与 json 平面
            ``KnowledgeBase``）。

    Returns:
        非空时返回完整目录块字符串；空序列返回 ``""``（无绑定 Agent
        零注入，builder 据此不注册工具、不改 prompt）。
    """
    # 空绑定：零注入（提前返回，避免产出只有引导语的空壳块）
    if not spaces:
        return ""

    # 逐库渲染一个 <knowledge-base> 节点（id/name/description 三要素）
    nodes: list[str] = []
    for space in spaces:
        space_id = str(getattr(space, "id", "") or "")
        name = str(getattr(space, "name", "") or "")
        description = str(getattr(space, "description", "") or "")
        nodes.append(
            "<knowledge-base>\n"
            f"<id>{space_id}</id>\n"
            f"<name>{name}</name>\n"
            f"<description>{description}</description>\n"
            "</knowledge-base>",
        )

    # 组装：外层块 + 引导语 + 各库节点
    body = "\n".join(nodes)
    return f"<knowledge-bases>\n{_INTRO}\n{body}\n</knowledge-bases>"


__all__ = ["render_kb_catalog"]
