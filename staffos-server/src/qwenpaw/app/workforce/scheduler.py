# -*- coding: utf-8 -*-
"""有界就绪调度原语（T5；引擎保持唯一编排入口）。

- ``ready_nodes``：纯函数计算就绪集——依赖全部完成的 pending 节点，
  按 plan 顺序稳定输出（调度确定性，不引入模型调用）；
- ``BoundedDispatcher``：有界 in-flight 任务集合——并发提交数量受
  ``RunPolicy.parallelism`` 约束，任一节点完成即释放调度位，下游
  节点立即就绪派发，**不等同批无关任务结束**（协议8.5：完成驱动
  调度；取代旧"整波 gather"的批量等待）。

引擎主循环消费这两个原语完成调度推进；本模块不触碰存储与状态机
（无编排副作用），可脱离 PG 做单元验证。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List, Sequence, Set, Tuple

from .contracts import NODE_STATUS_DONE, NODE_STATUS_PENDING, DagNode

logger = logging.getLogger(__name__)


def ready_nodes(
    plan_nodes: Sequence[DagNode],
    node_states: Sequence[Dict[str, Any]],
) -> List[str]:
    """计算就绪节点：pending 且依赖全部 done（按 plan 顺序稳定输出）。

    依赖关系以 plan 定义为权威（节点行不存 deps）；deps 指向未知
    节点视为未完成——保守不派发，防脏数据越权推进。
    """
    # 节点状态轻投影（node_key → status）
    states = {
        str(s.get("node_key")): str(s.get("status") or "") for s in node_states
    }
    # 已完成集合（依赖判定的唯一通过态）
    done = {k for k, v in states.items() if v == NODE_STATUS_DONE}
    ready: List[str] = []
    for node in plan_nodes:
        # 非 pending（done/在途/失败）不重复派发
        if states.get(node.node_key) != NODE_STATUS_PENDING:
            continue
        # 依赖全部完成才就绪（未知依赖按未完成处理）
        if all(dep in done for dep in node.deps):
            ready.append(node.node_key)
    return ready


class BoundedDispatcher:
    """有界 in-flight 任务集合（完成驱动调度的并发约束原语）。

    - ``submit``：提交节点执行协程；容量已满返回 False（调用方在
      下一次调度轮补位，不阻塞）；
    - ``wait_completed``：等待任一任务完成，返回本窗口内**全部**
      完成的 ``(node_key, task)``（含同时完成的多个，减少空转）；
    - ``drain``：等待全部在途任务结束并返回结果（replan/interrupt
      路径的"让在途自然收敛"语义）；
    - ``cancel_all``：请求取消全部在途并等待收敛（escalate/cancel
      的停止传播语义）。
    """

    def __init__(self, limit: int) -> None:
        # 并发上限至少为 1（防御非法配置）
        self._limit = max(1, int(limit))
        self._tasks: Dict[asyncio.Task, str] = {}

    @property
    def in_flight(self) -> int:
        """当前在途任务数。"""
        return len(self._tasks)

    @property
    def full(self) -> bool:
        """是否已达并发上限。"""
        return len(self._tasks) >= self._limit

    @property
    def empty(self) -> bool:
        """是否无在途任务。"""
        return not self._tasks

    @property
    def keys(self) -> Set[str]:
        """在途节点键集合（派发去重依据）。"""
        return set(self._tasks.values())

    def submit(
        self, node_key: str, coro_factory: Callable[[], Awaitable[Any]]
    ) -> bool:
        """提交一个节点执行协程；容量已满返回 False。"""
        # 容量约束：满载拒绝（调用方下一调度轮补位）
        if self.full:
            return False
        task = asyncio.create_task(coro_factory())
        self._tasks[task] = node_key
        return True

    async def wait_completed(self) -> List[Tuple[str, asyncio.Task]]:
        """等待任一任务完成；返回本窗口内全部完成任务（移出集合）。"""
        # 空集调用属编程错误（引擎仅在派发后等待）
        if not self._tasks:
            raise RuntimeError("BoundedDispatcher.wait_completed: 无在途任务")
        done, _ = await asyncio.wait(
            set(self._tasks), return_when=asyncio.FIRST_COMPLETED
        )
        completed: List[Tuple[str, asyncio.Task]] = []
        for task in done:
            key = self._tasks.pop(task, "")
            completed.append((key, task))
        return completed

    async def drain(self) -> List[Tuple[str, asyncio.Task]]:
        """等待全部在途任务结束并返回（调用方逐个检视结果）。"""
        if not self._tasks:
            return []
        done, _ = await asyncio.wait(
            set(self._tasks), return_when=asyncio.ALL_COMPLETED
        )
        completed: List[Tuple[str, asyncio.Task]] = []
        for task in done:
            key = self._tasks.pop(task, "")
            completed.append((key, task))
        return completed

    async def cancel_all(self) -> List[Tuple[str, asyncio.Task]]:
        """取消全部在途任务并等待收敛（返回收敛后的 (key, task)）。

        ``return_exceptions=True``：被取消任务的 CancelledError 作为
        结果返回而不抛出——本方法保证在异常清理路径（含外层取消
        传播中）也能完整收敛，不遗漏子任务。
        """
        # 先取 (task, key) 映射再清空（收敛返回仍可归因到节点）
        tracked = list(self._tasks.items())
        self._tasks.clear()
        # 先请求取消再统一等待（避免逐个等待放大尾部延迟）
        for task, _key in tracked:
            task.cancel()
        if not tracked:
            return []
        await asyncio.gather(*(task for task, _ in tracked), return_exceptions=True)
        return [(key, task) for task, key in tracked]
