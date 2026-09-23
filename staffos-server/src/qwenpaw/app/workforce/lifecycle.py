# -*- coding: utf-8 -*-
"""run 生命周期辅助（T5：取消传播、恢复分类、版本漂移检查）。

职责边界：本模块承载协议8.4/8.1 的**纯判定与轻量核对**动作；状态
机推进仍由 engine 单点完成（引擎唯一编排入口）：

- ``recovery_class``：按节点与在途动作状态给出恢复分类（协议8.4
  恢复表：结果已持久化→继续验收；可证明无外部作用→有限重试；
  外部结果未知→先核对）；
- ``reconcile_resumed_run``：续跑前核对在途外部动作——挂起的
  registered 动作在执行器消失后不可能完成，置 reverted 留痕（重新
  登记由重放承接），并发射持久事件供详情页提示核对；
- ``drifted_members``：版本漂移检查（协议8.1）——创建时钉住的成员
  版本与当前实例不一致 → 暂停要求显式处理，不静默切换。

@author qingfeng
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping

from .contracts import NODE_STATUS_VERIFYING

logger = logging.getLogger(__name__)

#: 恢复分类：结果已持久化但未验收 → 继续验收，不重复执行
RECOVERY_VERIFY = "verify"
#: 恢复分类：存在在途（registered）外部动作 → 先核对再继续
RECOVERY_RECONCILE = "reconcile"
#: 恢复分类：无外部作用证据 → 按策略有限重试（attempt 账本留痕）
RECOVERY_RETRY = "retry"
#: 恢复分类：无中间状态 → 全新派发
RECOVERY_FRESH = "fresh"


def recovery_class(
    node_state: Mapping[str, Any],
    has_pending_action: bool,
) -> str:
    """按节点状态与在途动作给出恢复分类（协议8.4 恢复表）。

    - 节点已产出结果停在验收态 → ``verify``（继续验收不重跑）；
    - 存在 registered 外部动作 → ``reconcile``（外部结果未知先核对；
      动作账本 revert/重放承接，杜绝副作用重复发生）；
    - 其余中间态（delegated/repairing 等，执行器已消失）→
      ``retry``（session 复用 + attempt 留痕的有限重试）；
    - pending → ``fresh``。
    """
    # 结果已持久化但未验收：继续验收（checkpoint 语义）
    if str(node_state.get("status") or "") == NODE_STATUS_VERIFYING and (
        node_state.get("result")
    ):
        return RECOVERY_VERIFY
    # 在途外部动作：先核对（结果未知不得盲目重试）
    if has_pending_action:
        return RECOVERY_RECONCILE
    # pending：无中间状态，全新派发
    status = str(node_state.get("status") or "")
    if status == "pending":
        return RECOVERY_FRESH
    return RECOVERY_RETRY


async def reconcile_resumed_run(store, run_id: str, reason: str = "") -> int:
    """续跑前核对在途外部动作（协议8.4；返回回收数量）。

    挂起的 registered 动作在执行器消失后不可能完成执行：置 reverted
    留痕（同 key 重新登记由部分唯一索引放行），并发射持久事件供
    详情页呈现"已核对 N 个未完成动作"。
    """
    # 延迟导入避免与 action_ledger 的潜在环（engine → lifecycle）
    from .action_ledger import recover_pending

    swept = await recover_pending(run_id, reason=reason or "reconciled_on_resume")
    if swept:
        run = await store.get_run(run_id)
        if run is not None:
            await store.emit_event(
                run, "run_reconciled", {"reverted_actions": swept}
            )
    return swept


def drifted_members(
    pinned_versions: Mapping[str, int],
    live_versions: Mapping[str, int],
) -> List[Dict[str, Any]]:
    """版本漂移检查（协议8.1）：返回钉住版本与实际版本不一致的成员。

    ``pinned_versions``/``live_versions`` 均为 ``expert_id → version``；
    只比较两侧都存在的成员（创建时未钉版本的旧 run 不参与检查——
    向后兼容）；漂移结果附钉住/实际版本供人工裁决参考。
    """
    drift: List[Dict[str, Any]] = []
    for expert_id, pinned in pinned_versions.items():
        live = live_versions.get(expert_id)
        # 实例已删除/不存在：交由引擎的成员加载失败路径处理
        if live is None:
            continue
        if int(live) != int(pinned):
            drift.append(
                {
                    "expert_id": expert_id,
                    "pinned_version": int(pinned),
                    "live_version": int(live),
                }
            )
    return drift
