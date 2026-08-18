# -*- coding: utf-8 -*-
"""run 级 token 预算聚合与熔断（Governance Engine 的预算面）。

计量口径说明（避免双计）：

- **逐调用明细**由既有 per-call 计量管道写入 ``token_usage_events``
  （agent_id=成员专家），workforce 不重复写表；
- **run 级预算**以节点回执累计为准（delegator 的 usage 采集器从
  SSE ``turn_usage`` 事件取 ``total_tokens``，逐节点累加到
  ``team_run_nodes.token_cost``），本模块聚合为 run 总量并与
  ``RunPolicy.max_total_tokens`` 对比，超限抛 EscalateSignal
  （engine 收敛为 escalated 人工终态）。

@author qingfeng
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from .contracts import RunPolicy

logger = logging.getLogger(__name__)


async def run_total_tokens(store, run_id: str) -> int:
    """聚合 run 全部节点的 token 消耗（含返工轮累计值）。"""
    # 节点行逐条求和（节点数有限，无需 SQL 聚合）
    nodes: List[Dict[str, Any]] = await store.list_nodes(run_id)
    return sum(int(n.get("token_cost", 0) or 0) for n in nodes)


def check_token_budget(total_tokens: int, policy: RunPolicy) -> None:
    """token 熔断检查（超限抛 EscalateSignal；0 = 不限）。"""
    # 未配置预算直接放行
    if policy.max_total_tokens <= 0:
        return
    if total_tokens > policy.max_total_tokens:
        # 延迟导入避免与 engine 的循环依赖
        from .engine import EscalateSignal

        raise EscalateSignal(
            f"run token 消耗 {total_tokens} 超过预算 {policy.max_total_tokens}"
        )
