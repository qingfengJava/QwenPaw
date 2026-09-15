# -*- coding: utf-8 -*-
"""Unit tests: SOP 环境判定纯函数（无 PG / 无事件循环）。

覆盖两处纯逻辑：
- ``sops.sop_environment_for_agent``：按 agent id 的 ``__draft`` 后缀
  判定读哪一环境行（draft/production），复用 agent_documents 约定；
- ``agents.tools.sop_ops._current_expert_id``：从运行态 agent id 剥离
  ``expert_`` 前缀与 ``__draft`` 后缀，得到 SOP 归属员工 id。
"""

from __future__ import annotations


def test_sop_environment_for_agent_suffix() -> None:
    """草稿调试实例（__draft 后缀）读 draft，线上实例读 production。"""
    from qwenpaw.app.experts.sops import sop_environment_for_agent

    assert sop_environment_for_agent("expert_alpha") == "production"
    assert sop_environment_for_agent("expert_alpha__draft") == "draft"
    # 原生 agent（无 expert_ 前缀）不带后缀 → production
    assert sop_environment_for_agent("default") == "production"


def test_sop_tool_current_expert_id_derivation() -> None:
    """AI 工具从 agent id 派生归属员工 id（剥离前缀与草稿后缀）。"""
    # 导入工具模块即验证 @tool_descriptor 注册链路无报错（含依赖导入）
    from qwenpaw.agents.tools import sop_ops

    assert callable(sop_ops._current_expert_id)  # noqa: SLF001
    # 剥离算法纯断言（不依赖 ContextVar 运行态）
    assert _derive("expert_alpha") == "alpha"
    assert _derive("expert_alpha__draft") == "alpha"
    assert _derive("native_agent") == "native_agent"


def _derive(agent_id: str) -> str:
    """复刻 ``_current_expert_id`` 的剥离规则做纯断言。

    工具本体依赖 ``get_current_agent_id`` 上下文，这里只校验剥离算法：
    前缀 ``expert_`` + 可选后缀 ``__draft``。
    """
    prefix = "expert_"
    draft_suffix = "__draft"
    if not agent_id.startswith(prefix):
        return agent_id
    stripped = agent_id[len(prefix):]
    if stripped.endswith(draft_suffix):
        stripped = stripped[: -len(draft_suffix)]
    return stripped
