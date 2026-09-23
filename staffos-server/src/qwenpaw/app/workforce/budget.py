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
    """聚合 run 全部节点的 token 消耗（含返工轮累计值）。

    T5 起优先走 SQL SUM（``sum_node_tokens``）——预算检查在完成驱动
    调度下高频执行，逐节点反序列化 JSON 的开销必须避免（协议8.5）；
    旧调用方（测试桩）缺该方法时回退 list_nodes 聚合。
    """
    # 轻量聚合路径（生产 RunStore 恒有该方法）
    sum_tokens = getattr(store, "sum_node_tokens", None)
    if sum_tokens is not None:
        return int(await sum_tokens(run_id) or 0)
    # 兼容回退：节点行逐条求和（节点数有限）
    nodes: List[Dict[str, Any]] = await store.list_nodes(run_id)
    return sum(int(n.get("token_cost", 0) or 0) for n in nodes)


async def run_budget_usage(store, run_id: str) -> int:
    """预留感知的 run 预算用量（T2 账本；T5 调度熔断的计量口径）。

    = 已结算节点累计（节点行 token_cost）+ 未决预留（预留即占额，
    防并发"各自看余额"超售）。结算/释放后预留从 outstanding 消失，
    实际用量已在节点行体现——同一笔消耗不会被双计。
    """
    # 已结算消耗（节点行累计）
    settled = await run_total_tokens(store, run_id)
    # 未决预留（pending 按预留额、settled 按实际用量计入）
    outstanding = await store.outstanding_tokens(run_id)
    return settled + outstanding


async def reserve_node_budget(
    store,
    run_id: str,
    node_key: str,
    policy: RunPolicy,
) -> str:
    """委派前原子预留（T4）：预留额 = 剩余预算按波次并发均分。

    预留即占额（pending 预留计入 ``run_budget_usage`` 的 outstanding），
    并发成员不会"各自看余额"造成超售；剩余额度不足以分出正份额时
    熔断升级。仅在配置了有限 ``max_total_tokens`` 时调用（不限预算
    无超售面，跳过预留）。

    原子性由 Store 层保证：``reserve_budget`` 事务内锁 run 行并复核
    用量，并发预留超限返回 None——此处升级为预算熔断（Escalate）。
    """
    # 延迟导入避免与 engine 的循环依赖（与 check_token_budget 同法）
    from .engine import EscalateSignal

    # 预留感知的当前用量（已结算 + 未决预留；share 均分的参考值）
    usage = await run_budget_usage(store, run_id)
    # 剩余额度按波次并发均分（并发上限内的节点合计不超剩余额）
    remaining = policy.max_total_tokens - usage
    share = remaining // max(1, policy.parallelism)
    if share <= 0:
        raise EscalateSignal(
            f"run 预算剩余 {remaining} 不足并发均分预留"
            f"（预算 {policy.max_total_tokens}，已用 {usage}）"
        )
    # 原子预留（Store 层锁内复核用量；None = 并发超限/余量不足）
    reservation_id = await store.reserve_budget(
        run_id,
        node_key,
        share,
        reason="pre-delegate reservation",
        max_total_tokens=policy.max_total_tokens,
    )
    if reservation_id is None:
        raise EscalateSignal(
            f"run 预算并发预留失败（预算 {policy.max_total_tokens}，"
            f"本轮份额 {share} 超出剩余额度），熔断升级待人工处理"
        )
    return reservation_id


async def release_quietly(store, reservation_id: str) -> None:
    """释放预留（异常路径兜底；失败仅告警，不改变原失败路径）。"""
    # 无预留（不限预算/预留前失败）直接返回
    if not reservation_id:
        return
    try:
        await store.release_reservation(reservation_id)
    except Exception:  # pragma: no cover - 释放失败不改变失败路径
        logger.warning("释放预算预留 %s 失败（已忽略）", reservation_id)


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
