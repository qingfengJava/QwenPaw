# -*- coding: utf-8 -*-
"""编排引擎（Workforce Runtime 状态机心脏）。

职责边界（硬约束）：engine 只做"状态机调度 + 事件发射"，委派
（delegator）、验收（verifier）、规划（planner）、上下文（bundle）
全部独立模块。本模块是 workforce 包内唯一有运行状态的模块：

- ``_active_tasks``：run_id → 后台 asyncio.Task（cancel 传播入口）；
- ``_bundle_locks``：run 级上下文束互斥锁（并行节点完成回写时串行化）。

主循环（Plan-then-Execute）：

    规划(一次) → 波次拓扑调度 → 节点{委派→验收→(FAIL)返工循环}
    → 全部完成 → final 汇总节点(中央大脑自执行) → done + 回推事件

熔断（RunPolicy 纯计数器）：max_repair_per_node / max_replan /
max_total_seconds 任一超限 → escalated 终态（人工裁决 API 恢复）。

崩溃恢复：节点边界的 contract/result 即 PG checkpoint；进程重启后
活跃 run 被 run_store 标记 interrupted，重入 run_team_run 从已完成
节点之后续跑（幂等：done 节点直接跳过）。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from ..experts.models import (
    TEAM_MEMBER_ROLE_LEAD,
    ExpertRecord,
    ExpertTeamRecord,
)
from ..experts.store import ExpertStore
from . import bundle as bundle_mod
from .contracts import (
    NODE_ACTIVE_STATUSES,
    NODE_STATUS_DELEGATED,
    NODE_STATUS_DONE,
    NODE_STATUS_PENDING,
    NODE_STATUS_REPAIRING,
    NODE_STATUS_VERIFYING,
    RUN_STATUS_AGGREGATING,
    RUN_STATUS_AWAITING_CONFIRM,
    RUN_STATUS_CANCELED,
    RUN_STATUS_DONE,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PLANNING,
    RUN_STATUS_RUNNING,
    ContextBundle,
    DagNode,
    DagPlan,
    RepairContract,
    ResultContract,
    RunPolicy,
    TaskContract,
    VERDICT_ESCALATE,
    VERDICT_FAIL,
    VERDICT_PASS,
)
from .delegator import (
    DELEGATE_TIMEOUT_S,
    call_expert_text,
    delegate,
    parse_result_contract,
)
from .planner import build_task_contract, plan_run
from .run_store import get_run_store
from .verifier import (
    FAILURE_KIND_DEPENDENCY_CHANGED,
    FAILURE_KIND_STRUCTURAL,
    Verdict,
    verify,
)

logger = logging.getLogger(__name__)

#: run 级终态集合（幂等保护：终态 run 不再执行）
_RUN_TERMINAL = {
    RUN_STATUS_DONE,
    RUN_STATUS_FAILED,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_CANCELED,
}

#: 运行中的后台任务登记表（run_id → asyncio.Task；cancel 入口）
_active_tasks: Dict[str, asyncio.Task] = {}

#: run 级上下文束互斥锁（并行节点完成回写串行化，避免丢失更新）
_bundle_locks: Dict[str, asyncio.Lock] = {}


class EscalateSignal(Exception):
    """节点熔断信号（向上冒泡终止主循环，run 置 escalated）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        #: 熔断原因（写入 escalation_reason）
        self.reason = reason


class ReplanSignal(Exception):
    """重规划信号（Failure Analyzer 归因 dependency_changed 时抛出）。

    主循环捕获后执行清图重规划（协议 12），受 RunPolicy.max_replan
    熔断约束；已完成节点的产出摘要保留在上下文束，不随节点行删除。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        #: 重规划原因（写入事件与教训决策）
        self.reason = reason


class RunInterruptSignal(Exception):
    """节点通道瞬时异常信号（委派/汇总执行段抛出）。

    主循环捕获后 run 转 interrupted（可续跑）而非 failed（死路）——
    恢复策略与 verify 通道的 ESCALATE 对称，一次网络抖动不再报废
    整个 run 的已完成 checkpoint。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        #: 中断原因（写入 run.error）
        self.reason = reason


def start_run_background(run_id: str) -> asyncio.Task:
    """以后台任务启动一次 run（登记句柄供 cancel / 防重复启动）。"""
    # 已有活跃任务则拒绝重复启动（幂等）
    existing = _active_tasks.get(run_id)
    if existing is not None and not existing.done():
        return existing
    # 创建后台任务并登记
    task = asyncio.create_task(_guarded_run(run_id))
    _active_tasks[run_id] = task
    # 完成后清理登记（防泄漏）
    task.add_done_callback(lambda _t: _active_tasks.pop(run_id, None))
    return task


async def cancel_run(run_id: str) -> bool:
    """取消一次运行中的 run（传播取消到后台任务）；返回是否生效。

    取消后**等待终态落库再返回**（有界 10s）——修复"响应 canceled
    但详情页短暂仍显示 running"的发后不管语义；超时则接受异步收敛
    （_guarded_run 护栏兜底落终态）。
    """
    task = _active_tasks.get(run_id)
    # 无运行任务：仅状态置 canceled（终态幂等）
    if task is None or task.done():
        return False
    # 请求协作取消（CancelledError 在引擎内收敛为 canceled 终态）
    task.cancel()
    # 有界等待后台任务收敛（shield：超时只放弃等待，不二次取消任务）
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=_CANCEL_WAIT_S)
    except asyncio.TimeoutError:
        pass
    return True


#: cancel 等待终态落库的上限（秒）
_CANCEL_WAIT_S = 10.0

#: run 认领 advisory lock 的键前缀（会话级锁：进程死亡连接断开自动释放）
_RUN_CLAIM_LOCK_PREFIX = "workforce-run:"


async def _try_claim_run(run_id: str) -> tuple:
    """用 PG advisory lock 认领 run（多实例护栏，免 DDL）。

    返回 ``(claimed, lock_conn)``：

    - ``(True, conn)``：认领成功，conn 为持锁的专用连接（调用方在
      finally 中经 :func:`_release_run_claim` 释放）；
    - ``(False, None)``：锁被其他实例/任务持有——同一 run 不重复执行
      （防双实例并发委派、节点结果互相覆写、token 双倍燃烧）；
    - ``(True, None)``：锁通道不可用（PG 未达/连接失败）——降级为
      无护栏执行，保持单机部署既有可用性（护栏是增强不是开关）。

    会话级锁的崩溃语义：持有进程死亡 → 连接断开 → 锁自动释放，
    无需租约续期与过期回收。
    """
    # 专用裸连接（不经 SQLAlchemy 池）：长任务持锁不占用业务连接池
    try:
        import asyncpg

        from ...db.engine import get_pg_dsn

        dsn = get_pg_dsn().replace("postgresql+asyncpg://", "postgresql://", 1)
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=10.0)
    except Exception:
        logger.warning(
            "run 认领连接不可用，降级为无护栏执行 run=%s", run_id, exc_info=True
        )
        return True, None
    key = _RUN_CLAIM_LOCK_PREFIX + run_id
    try:
        ok = await conn.fetchval(
            "SELECT pg_try_advisory_lock(hashtext($1)::bigint)", key
        )
    except Exception:
        logger.warning(
            "run 认领锁查询失败，降级为无护栏执行 run=%s", run_id, exc_info=True
        )
        await conn.close()
        return True, None
    # 锁被持有：其他实例正在执行，拒绝重复启动
    if not ok:
        await conn.close()
        return False, None
    return True, conn


async def _release_run_claim(run_id: str, conn) -> None:
    """释放 run 认领锁并关闭专用连接（best-effort，绝不抛出）。"""
    # 未持锁（降级路径）无需释放
    if conn is None:
        return
    # 先解锁再断连（断连本身也会释放会话锁，双保险）
    try:
        await conn.execute(
            "SELECT pg_advisory_unlock(hashtext($1)::bigint)",
            _RUN_CLAIM_LOCK_PREFIX + run_id,
        )
    except Exception:
        pass
    try:
        await conn.close()
    except Exception:
        pass


async def _reset_active_nodes(store, run_id: str) -> None:
    """把 run 的中间态节点（delegated/verifying/...）回退 pending。

    取消收敛后的数据视图一致性清理：canceled 是终态不可续跑，但
    滞留在 delegated 的节点行会让详情页与数据审计呈现"执行中"假象。
    """
    # 逐节点回退（节点行数量有限；状态来自活跃态集合）
    for node in await store.list_nodes(run_id):
        if node.get("status") in NODE_ACTIVE_STATUSES:
            await store.update_node(
                run_id, node["node_key"], status=NODE_STATUS_PENDING
            )


async def _guarded_run(run_id: str) -> None:
    """带异常护栏的 run 主入口（任何异常收敛为对应终态）。"""
    store = get_run_store()
    started_at = time.monotonic()
    # 多实例护栏：PG advisory lock 认领——锁被其他实例持有时静默退出
    # （重复启动的第二个任务不做任何状态写入，避免双实例互踩）
    claimed, lock_conn = await _try_claim_run(run_id)
    if not claimed:
        logger.warning("run %s 正在被其他实例执行，跳过本次启动", run_id)
        return
    try:
        await run_team_run(run_id, started_at=started_at)
    except asyncio.CancelledError:
        # 用户取消：确保终态为 canceled（cancel_run 可能已写状态，幂等补写）
        run = await store.get_run(run_id)
        if run is not None and run["status"] not in _RUN_TERMINAL:
            await store.set_run_status(run_id, RUN_STATUS_CANCELED)
            await store.emit_event(run, "team_run_canceled")
        # 取消后节点中间态清理（数据视图一致性，见 _reset_active_nodes）
        await _reset_active_nodes(store, run_id)
    except EscalateSignal as exc:
        # 熔断：终态 escalated + 人工介入入口事件
        run = await store.get_run(run_id)
        if run is not None:
            await store.set_run_status(
                run_id,
                RUN_STATUS_ESCALATED,
                escalation_reason=exc.reason,
            )
            await store.emit_event(run, "escalated", {"reason": exc.reason})
    except Exception as exc:  # noqa: BLE001 - 引擎顶层护栏，绝不裸抛
        logger.exception("run %s 引擎异常终止", run_id)
        run = await store.get_run(run_id)
        if run is not None:
            await store.set_run_status(run_id, RUN_STATUS_FAILED, error=str(exc))
            await store.emit_event(run, "team_run_failed", {"error": str(exc)})
    finally:
        # 无论何种终态都释放认领锁（进程死亡时连接断开锁亦自动释放）
        await _release_run_claim(run_id, lock_conn)


async def run_team_run(run_id: str, started_at: Optional[float] = None) -> None:
    """执行一次 run 的完整状态机（幂等可重入：done 节点跳过）。

    started_at 为进程内单调时钟起点（时间熔断基准；续跑时由
    _guarded_run 重新起算——已执行时间的严格恢复留迭代项）。
    """
    store = get_run_store()
    # 加载 run 与终态幂等保护
    run = await store.get_run(run_id)
    if run is None:
        raise ValueError(f"run 不存在: {run_id}")
    if run["status"] in _RUN_TERMINAL:
        return
    clock_start = started_at if started_at is not None else time.monotonic()
    # 加载团队上下文（成员 + 技能绑定 + 能力挂载 + 中央大脑人格）
    team, members, member_skills, member_caps = await _load_team_context(
        run["team_id"],
    )
    if team is None or not members:
        await store.set_run_status(
            run_id, RUN_STATUS_FAILED, error="团队不存在或没有成员"
        )
        await store.emit_event(
            run, "team_run_failed", {"error": "团队不存在或没有成员"}
        )
        return
    members_by_id = {e.id: e for e in members}
    lead_id = _pick_lead(team, members)
    # 恢复或初始化上下文束与策略
    bundle = _restore_bundle(run, team, members)
    policy = (
        RunPolicy.model_validate(run["policy"]) if run.get("policy") else RunPolicy()
    )
    # 状态进入执行态（planning/interrupted → running）
    await store.set_run_status(run_id, RUN_STATUS_RUNNING)
    await store.emit_event(run, "run_started", {"team": team.name})
    # ---- Re-plan 外层循环：dependency_changed 归因时清图重规划后重入 ----
    while True:
        # ---- 规划阶段（已有 plan 则跳过：续跑 / 重入） ----
        run = await store.get_run(run_id)
        if not (run.get("plan") or {}).get("nodes"):
            await _plan_phase(
                store,
                run,
                team,
                members,
                bundle,
                member_skills=member_skills,
                member_caps=member_caps,
            )
            # 规划阶段可能改变 run 状态（awaiting_confirm / failed），重读判定
            run = await store.get_run(run_id)
            if run["status"] != RUN_STATUS_RUNNING:
                return
        # ---- 执行阶段：波次拓扑调度 ----
        replanned = False
        while True:
            # 每轮重读 run/节点状态（并行完成后的最新视图）
            run = await store.get_run(run_id)
            if run["status"] in _RUN_TERMINAL:
                return
            # 依赖关系以持久化的 plan 为权威（节点行不存 deps）
            plan = DagPlan.model_validate(run["plan"])
            plan_by_key = {n.node_key: n for n in plan.nodes}
            nodes = await store.list_nodes(run_id)
            done_keys = {
                n["node_key"] for n in nodes if n["status"] == NODE_STATUS_DONE
            }
            pending_keys = [
                n["node_key"] for n in nodes if n["status"] == NODE_STATUS_PENDING
            ]
            # 全部完成 → 进入汇总收尾
            if not pending_keys:
                break
            # 就绪节点：依赖全部 done（deps 来自 plan 定义）
            ready = [
                key
                for key in pending_keys
                if all(dep in done_keys for dep in plan_by_key[key].deps)
            ]
            # 有 pending 但无 ready = DAG 死锁（校验过不应发生，防御失败）
            if not ready:
                await store.set_run_status(
                    run_id,
                    RUN_STATUS_FAILED,
                    error="DAG 调度死锁（存在无法就绪的节点）",
                )
                await store.emit_event(
                    run, "team_run_failed", {"error": "DAG 调度死锁"}
                )
                return
            # 时间与 token 双熔断（每波开始前检查）
            _check_time_budget(clock_start, policy)
            from .budget import check_token_budget, run_total_tokens

            total_tokens = await run_total_tokens(store, run_id)
            check_token_budget(total_tokens, policy)
            # 并发执行本波节点（信号量限流；单节点异常不中断同波其他节点）
            semaphore = asyncio.Semaphore(max(1, policy.parallelism))
            results = await asyncio.gather(
                *(
                    _run_node_bounded(
                        semaphore,
                        store,
                        run_id,
                        run,
                        policy,
                        bundle,
                        node_key,
                        members_by_id,
                        member_skills,
                        lead_id,
                        clock_start,
                    )
                    for node_key in ready
                ),
                return_exceptions=True,
            )
            # 同波内熔断信号优先冒泡（escalated 终态）
            for item in results:
                if isinstance(item, EscalateSignal):
                    raise item
            # 同波内取消信号冒泡（让 _guarded_run 收敛 canceled）
            for item in results:
                if isinstance(item, asyncio.CancelledError):
                    raise item
            # Re-plan 信号：清图重规划（受 max_replan 熔断），重入外层循环
            replan_signal = next(
                (i for i in results if isinstance(i, ReplanSignal)), None
            )
            if replan_signal is not None:
                await _handle_replan(store, run_id, bundle, replan_signal, policy)
                replanned = True
                break
            # 通道瞬时异常：run 转 interrupted（可续跑）而非 failed（死路）
            interrupt_signal = next(
                (i for i in results if isinstance(i, RunInterruptSignal)), None
            )
            if interrupt_signal is not None:
                run = await store.get_run(run_id)
                await store.set_run_status(
                    run_id, RUN_STATUS_INTERRUPTED, error=interrupt_signal.reason
                )
                await store.emit_event(
                    run, "run_interrupted", {"reason": interrupt_signal.reason}
                )
                return
            # 其余节点执行异常不得静默：否则主循环会把同一 pending 节点
            # 无限重新 gather（引擎空转烧 CPU、run 永不终态）。统一冒泡给
            # _guarded_run 收敛为 failed 终态并留痕日志。
            for item in results:
                if isinstance(item, BaseException) and not isinstance(
                    item,
                    (
                        EscalateSignal,
                        asyncio.CancelledError,
                        ReplanSignal,
                        RunInterruptSignal,
                    ),
                ):
                    logger.error("节点执行异常（run=%s）: %r", run_id, item)
                    raise item
        if replanned:
            continue
        break
    # ---- 汇总收尾（final 节点已在执行阶段完成，此处收束状态） ----
    await store.set_run_status(run_id, RUN_STATUS_AGGREGATING)
    final_summary, final_result = await _collect_final(store, run_id)
    await store.update_run(run_id, summary=final_summary, result=final_result)
    await store.set_run_status(run_id, RUN_STATUS_DONE)
    run = await store.get_run(run_id)
    await store.emit_event(
        run,
        "team_run_done",
        {"summary": final_summary[:2000]},
    )


async def _retrieve_knowledge(
    goal: str,
    username: str,
    extra_kb_ids: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Knowledge Retrieval：对发起人可见 KB 做一次轻量检索（best-effort）。

    Capability Discovery 的知识面：规划前从个人/团队/企业 KB 检索与
    goal 相关的片段（每库 top2、总上限 5 条），命中注入
    ``global_ctx.knowledge`` 供规划与契约引用。任何异常静默降级为
    空集——知识检索故障绝不阻塞编排主链路。

    ``extra_kb_ids`` 为成员专家绑定的知识库（能力挂载，P1）——
    优先检索专家自己挂的库（经营性知识），再回落通用可见库。
    """
    # 延迟导入（KB 为可选子系统；保持 workforce 包加载轻）
    try:
        from ..kb.service import get_kb_service

        service = get_kb_service()
        hits: List[Dict[str, str]] = []

        def _search_kb(kb_id: str, kb_name: str) -> bool:
            """Search one KB (top2); return True when the cap is hit."""
            for chunk, _score in service.search(kb_id, goal, top_k=2):
                hits.append({"kb": kb_name, "text": chunk.text[:400]})
                if len(hits) >= 5:
                    return True
            return False

        # 成员绑定库优先（专家挂载的经营性知识）
        seen: set = set()
        for kb_id in extra_kb_ids or []:
            if kb_id in seen or len(hits) >= 5:
                break
            seen.add(kb_id)
            kb = service.get_kb(kb_id)
            if kb is None:
                continue
            if _search_kb(kb_id, kb.name):
                return hits
        for kb in service.accessible_kbs(username, flat_role=""):
            if kb.id in seen or len(hits) >= 5:
                break
            seen.add(kb.id)
            if _search_kb(kb.id, kb.name):
                return hits
        return hits
    except Exception:  # noqa: BLE001 - 知识面故障不阻塞编排
        logger.debug("知识检索降级为空集", exc_info=True)
        return []


async def _plan_phase(
    store,
    run: Dict[str, Any],
    team: ExpertTeamRecord,
    members: List[ExpertRecord],
    bundle: ContextBundle,
    member_skills: Optional[Dict[str, List[str]]] = None,
    member_caps: Optional[Dict[str, Dict[str, list]]] = None,
) -> None:
    """规划阶段：模板/LLM 产出 DagPlan，或转澄清挂起，或失败终止。"""
    run_id = run["id"]
    await store.emit_event(run, "planning_started")
    # 成员能力挂载快照（P1）：绑定 SOP/知识/工具 → 版本化全局事实。
    # 契约构建（build_task_contract）从 bundle.global_ctx["member_caps"]
    # 取数——零签名扰动的注入通道。
    caps_payload = _member_caps_payload(member_caps or {})
    bound_kb_ids = sorted(
        {
            kb_id
            for caps in (member_caps or {}).values()
            for kb_id in caps.get("kb_ids", [])
        },
    )
    # 知识检索注入（Capability Discovery 的知识面；变更时 bump 版本）
    knowledge = await _retrieve_knowledge(
        run["goal"],
        run.get("initiator_id") or "",
        extra_kb_ids=bound_kb_ids,
    )
    changed = False
    if knowledge and bundle.global_ctx.get("knowledge") != knowledge:
        bundle.global_ctx = dict(bundle.global_ctx)
        bundle.global_ctx["knowledge"] = knowledge
        bundle_mod.record_version_change(bundle, "knowledge: 规划检索命中")
        bundle.version = bundle.version + 1
        changed = True
    if caps_payload and bundle.global_ctx.get("member_caps") != caps_payload:
        bundle.global_ctx = dict(bundle.global_ctx)
        bundle.global_ctx["member_caps"] = caps_payload
        bundle_mod.record_version_change(bundle, "member_caps: 绑定 SOP/知识/工具快照")
        bundle.version = bundle.version + 1
        changed = True
    if changed:
        await store.bump_context_version(run_id)
        await store.update_run(run_id, context_bundle=bundle.model_dump())
    # 组织记忆回灌（Memory Protocol）：取该团队历史熔断教训注入规划
    # ——同一团队第二次任务自动规避此前踩过的坑（best-effort，故障降级空集）
    try:
        team_lessons = await store.list_team_lessons(run["team_id"])
    except Exception:  # noqa: BLE001 - 教训检索故障不阻塞规划
        team_lessons = []
    # 执行规划（模板优先 → 中央大脑；能力档案随 prompt 注入）
    outcome = await plan_run(
        run["goal"],
        team,
        members,
        bundle,
        member_skills=member_skills,
        team_lessons=team_lessons,
    )
    # 澄清分支：挂起等待用户答复（不消耗执行预算）
    if outcome.clarification is not None:
        await store.update_run(
            run_id,
            clarification=outcome.clarification.model_dump(),
        )
        await store.set_run_status(run_id, RUN_STATUS_AWAITING_CONFIRM)
        await store.emit_event(
            run,
            "awaiting_clarification",
            {"questions": outcome.clarification.questions},
        )
        return
    # 失败分支：规划两次未通过校验（不静默修复非法 DAG）
    if outcome.plan is None:
        await store.set_run_status(run_id, RUN_STATUS_FAILED, error=outcome.error)
        await store.emit_event(
            run, "team_run_failed", {"error": outcome.error, "stage": "planning"}
        )
        return
    # 成功：物化任务图与节点行
    await store.save_plan(run_id, outcome.plan)
    await store.emit_event(
        run,
        "plan_ready",
        {"source": outcome.source, "nodes": [n.node_key for n in outcome.plan.nodes]},
    )
    # 拆解决策写入全局上下文（Context Protocol：规划产出即全局决策，
    # 后续节点契约经 parent_decision 引用同一版本化事实）。模板重规划
    # 产生相同决策时去重，不做无意义 bump。
    decision_text = f"[Plan:{outcome.source}] " + (
        outcome.plan.plan_note or f"拆解为 {len(outcome.plan.nodes)} 个节点"
    )
    decisions = list(bundle.global_ctx.get("decisions", []))
    if not decisions or decisions[-1] != decision_text:
        decisions.append(decision_text)
        bundle.global_ctx = dict(bundle.global_ctx)
        bundle.global_ctx["decisions"] = decisions
        bundle_mod.record_version_change(bundle, f"plan: {decision_text[:120]}")
        bundle.version = bundle.version + 1
        # 持久化：版本号单点递增 + 束内容整列覆盖
        await store.bump_context_version(run_id)
        await store.update_run(run_id, context_bundle=bundle.model_dump())


async def _handle_replan(
    store,
    run_id: str,
    bundle: ContextBundle,
    signal: ReplanSignal,
    policy: RunPolicy,
) -> None:
    """Re-plan 处置（协议 12 的引擎接线）：清图重规划，重入规划阶段。

    语义：dependency_changed 归因的验收失败后——
    1. 熔断检查：replan_count 超过 policy.max_replan → EscalateSignal；
    2. 教训写入全局决策（bundle.global_ctx.decisions）并 bump 版本，
       后续所有节点契约引用新的版本化事实（Context Protocol）；
    3. 删除全部节点行与 plan 快照（已完成产出的摘要保留在
       bundle.execution_ctx，checkpoint 价值不随节点行丢失）；
    4. run 回 planning 态——外层循环检测到空 plan 自动重入规划，
       规划 prompt 携带已完成摘要与教训，新 DAG 复用既有成果。
    """
    # 熔断：重规划次数超上限 → 升级人工（防反复重规划空转）
    run = await store.get_run(run_id)
    if int(run.get("replan_count", 0) or 0) + 1 > policy.max_replan:
        raise EscalateSignal(
            f"重规划次数超上限（{policy.max_replan}）：{signal.reason}"
        )
    await store.add_replan_count(run_id)
    # 教训决策写入全局上下文（不可变决策清单，节点契约逐条可见）
    decisions = list(bundle.global_ctx.get("decisions", []))
    decisions.append(f"[Re-plan] {signal.reason}")
    bundle.global_ctx = dict(bundle.global_ctx)
    bundle.global_ctx["decisions"] = decisions
    # 版本历史轨迹 + 就地版本递增（外部引用同一束对象，须原地变更）
    bundle_mod.record_version_change(bundle, f"re-plan: {signal.reason[:120]}")
    bundle.version = bundle.version + 1
    # 持久化：版本号由 bump_context_version 单点递增，束内容整列覆盖
    await store.bump_context_version(run_id)
    await store.update_run(run_id, context_bundle=bundle.model_dump())
    # 清空任务图（节点行删除；plan 清空触发外层循环重入规划）
    await store.reset_nodes_for_replan(run_id)
    await store.update_run(run_id, plan={}, summary="", result={})
    # 回执行态：外层循环检测到空 plan 直接重入规划（若置 planning，
    # 外层规划重入后的 RUNNING 判定会误判提前 return，run 卡死）
    await store.set_run_status(run_id, RUN_STATUS_RUNNING)
    await store.emit_event(
        run,
        "replan_started",
        {"reason": signal.reason, "context_version": bundle.version},
    )


async def _run_node_bounded(
    semaphore: asyncio.Semaphore,
    store,
    run_id: str,
    run: Dict[str, Any],
    policy: RunPolicy,
    bundle: ContextBundle,
    node_key: str,
    members_by_id: Dict[str, ExpertRecord],
    member_skills: Dict[str, List[str]],
    lead_id: str,
    clock_start: float,
) -> None:
    """信号量包裹的单节点执行（限制同波并发委派数）。"""
    async with semaphore:
        await _execute_node(
            store,
            run_id,
            run,
            policy,
            bundle,
            node_key,
            members_by_id,
            member_skills,
            lead_id,
            clock_start,
        )


async def _execute_node(
    store,
    run_id: str,
    run: Dict[str, Any],
    policy: RunPolicy,
    bundle: ContextBundle,
    node_key: str,
    members_by_id: Dict[str, ExpertRecord],
    member_skills: Dict[str, List[str]],
    lead_id: str,
    clock_start: float,
) -> None:
    """单节点全生命周期：契约 → 委派 → 验收 →（FAIL）返工循环。

    - 契约只在首执行时构建并持久化（checkpoint；返工轮复用同一
      契约 + 追加 RepairContract，保证任务事实稳定）；
    - 每轮委派 attempt+1、session 复用（延续成员自身上下文）；
    - ESCALATE 抛 EscalateSignal 由主循环收敛为 run 级 escalated。
    """
    # 取 plan 中的节点定义与当前节点行
    current_run = await store.get_run(run_id)
    plan = DagPlan.model_validate(current_run["plan"])
    dag_node = next(n for n in plan.nodes if n.node_key == node_key)
    node_row = await store.get_node(run_id, node_key)
    # 契约：首执行构建持久化；重入（续跑/返工）复用已存契约
    if node_row and node_row.get("contract"):
        contract = TaskContract.model_validate(node_row["contract"])
    else:
        expert = members_by_id.get(dag_node.assignee_expert_id)
        contract = build_task_contract(
            dag_node,
            expert,
            bundle,
            member_skills=member_skills,
            run_id=run_id,
        )
        await store.update_node(run_id, node_key, contract=contract.model_dump())
    # 首轮委派前置状态
    attempt = (node_row or {}).get("attempt", 0)
    repair_count = (node_row or {}).get("repair_count", 0)
    session_id = (node_row or {}).get("session_id") or None
    expert_id = dag_node.assignee_expert_id
    # ---- 委派 → 验收 →（FAIL）返工循环 ----
    while True:
        # 预算检查前移：每轮委派前核对时间与 token 预算——波次开始时
        # 的检查无法覆盖"单波内 900s×并发"的无监督超支窗口
        _check_time_budget(clock_start, policy)
        from .budget import check_token_budget, run_total_tokens

        check_token_budget(await run_total_tokens(store, run_id), policy)
        # 取最近一次返工契约（首轮为空）
        node_now = await store.get_node(run_id, node_key) or {}
        repair = (
            RepairContract.model_validate(node_now["repair"])
            if node_now.get("repair")
            else None
        )
        # 节点状态推进：委派中
        await store.update_node(
            run_id, node_key, status=NODE_STATUS_DELEGATED, attempt=attempt + 1
        )
        await store.emit_event(
            run, "node_started", {"node_key": node_key, "attempt": attempt + 1}
        )
        # 执行节点：final/integration 由中央大脑自执行，成员节点走委派
        try:
            if expert_id:
                result, session_id = await delegate(
                    expert_id,
                    contract,
                    repair=repair,
                    session_id=session_id,
                    timeout=DELEGATE_TIMEOUT_S,
                )
            else:
                result, session_id = await _execute_brain_node(
                    lead_id,
                    dag_node,
                    contract,
                    bundle,
                    repair,
                )
        except (EscalateSignal, asyncio.CancelledError, ReplanSignal):
            raise
        except Exception as exc:
            # 通道瞬时异常（网络/超时/5xx）：节点回 pending（保留 attempt
            # 与 token 账本），冒泡 RunInterruptSignal 让主循环把 run 置
            # interrupted 可续跑——一次抖动不再报废整个 run 的已完成
            # checkpoint（与 verify 通道的 ESCALATE 恢复语义对称）。
            logger.warning("节点 %s 执行通道异常: %s", node_key, exc)
            await store.update_node(run_id, node_key, status=NODE_STATUS_PENDING)
            raise RunInterruptSignal(f"节点 {node_key} 执行通道异常: {exc}") from exc
        attempt += 1
        # 结果 checkpoint（崩溃恢复点）+ 会话与计量累计回写
        node_now = await store.get_node(run_id, node_key) or {}
        token_total = int(node_now.get("token_cost", 0) or 0) + int(
            result.token_cost or 0
        )
        await store.update_node(
            run_id,
            node_key,
            status=NODE_STATUS_VERIFYING,
            result=result.model_dump(),
            session_id=session_id or "",
            attempt=attempt,
            token_cost=token_total,
        )
        await store.emit_event(
            run,
            "node_result",
            {"node_key": node_key, "status": result.status, "attempt": attempt},
        )
        # 验收：全部节点统一由 lead 裁决——final/integration（中央大脑
        # 自执行）同样不免检。最终交付是全链路最关键的产出，"自验收"
        # 后门会让未经任何裁决的内容直达用户（企业质量门无例外）。
        verdict = await verify(
            lead_id,
            contract,
            result,
            policy,
            repair_count=repair_count,
            previous_repair=repair,
        )
        # needs_review 守门：ResultContract 解析降级（模型未按结构化
        # 约定输出）的结果不得静默 PASS——结构化事实已丢失，升级人工
        # 复核，杜绝垃圾产出无感流入上游摘要与最终交付。
        if verdict.verdict == VERDICT_PASS and result.needs_review:
            verdict = Verdict(
                VERDICT_ESCALATE,
                reason=f"节点 {node_key} 结果契约解析降级（needs_review），升级人工复核",
            )
        # 裁决留痕
        await store.update_node(run_id, node_key, verdict=verdict.verdict)
        await store.emit_event(
            run,
            "node_verdict",
            {
                "node_key": node_key,
                "verdict": verdict.verdict,
                "reason": verdict.reason,
            },
        )
        # PASS：记录上游摘要（互斥）并收敛 done
        if verdict.verdict == VERDICT_PASS:
            async with _bundle_lock(run_id):
                updated = bundle_mod.record_upstream_result(
                    bundle,
                    node_key,
                    _node_label(dag_node, members_by_id),
                    result,
                )
                # 原地同步字段（外部引用同一束对象，避免并行节点丢更新）
                bundle.global_ctx = updated.global_ctx
                bundle.task_ctx = updated.task_ctx
                bundle.execution_ctx = updated.execution_ctx
                bundle.version = updated.version
                bundle.history = updated.history
                await store.update_run(run_id, context_bundle=bundle.model_dump())
            await store.update_node(run_id, node_key, status=NODE_STATUS_DONE)
            return
        # FAIL：按归因三路分派（Failure Analyzer 协议）
        if verdict.verdict == VERDICT_FAIL and verdict.repair is not None:
            # structural：能力/工具/权限缺失，返工只会烧预算 → 直接熔断
            if verdict.failure_kind == FAILURE_KIND_STRUCTURAL:
                raise EscalateSignal(
                    f"节点 {node_key} 结构性失败（返工无意义）：{verdict.reason}；"
                    f"问题：{'；'.join(verdict.repair.issues)}"
                )
            # dependency_changed：上游产出与目标矛盾/缺失 → 全局 Re-plan
            if verdict.failure_kind == FAILURE_KIND_DEPENDENCY_CHANGED:
                raise ReplanSignal(
                    f"节点 {node_key} 依赖的上游产出不满足目标：{verdict.reason}；"
                    f"问题：{'；'.join(verdict.repair.issues)}"
                )
            # repairable（默认）：返工契约持久化 + 计数 + 事件，进入下一轮
            repair_count += 1
            # 引擎层熔断（与 verifier 双保险相互独立）：达到返工上限不再
            # 进入下一轮——防被替换/异常的验收器永远 FAIL 造成无限返工
            # 循环（CPU 空转、run 永不终态）。
            if repair_count > policy.max_repair_per_node:
                raise EscalateSignal(
                    f"节点 {node_key} 返工 {repair_count} 次仍 FAIL"
                    f"（上限 {policy.max_repair_per_node}），引擎熔断升级人工"
                )
            await store.add_repair_count(run_id)
            await store.update_node(
                run_id,
                node_key,
                status=NODE_STATUS_REPAIRING,
                repair=verdict.repair.model_dump(),
                repair_count=repair_count,
            )
            await store.emit_event(
                run,
                "repair_issued",
                {
                    "node_key": node_key,
                    "attempt": repair_count,
                    "issues": verdict.repair.issues,
                },
            )
            continue
        # ESCALATE（或 FAIL 无契约的异常形态）：熔断升级人工
        raise EscalateSignal(f"节点 {node_key} {verdict.verdict}：{verdict.reason}")


async def _execute_brain_node(
    lead_id: str,
    dag_node: DagNode,
    contract: TaskContract,
    bundle: ContextBundle,
    repair: Optional[RepairContract],
) -> tuple:
    """中央大脑自执行节点（final/integration）：汇总产出最终结果。

    复用委派通道调 lead 专家（携带全部上游摘要投影），输出同样
    走 ResultContract 解析容错。
    """
    # 汇总 prompt：目标 + 全部上游摘要（final 节点 deps=全部任务节点）
    lines = ["# 最终汇总（你是中央大脑，负责汇总全部成员产出形成最终交付）"]
    lines.append(f"\n## 总体目标\n{bundle.task_ctx.get('goal', '')}")
    lines.append(f"\n## 你的任务\n{contract.objective}")
    if contract.upstream_summaries:
        lines.append("\n## 全部成员产出")
        for key, summary in contract.upstream_summaries.items():
            lines.append(f"### {summary.get('label', key)}（{key}）")
            lines.append(str(summary.get("digest", "")))
    if repair is not None:
        lines.append("\n## 上轮汇总被驳回的问题（必须修正）")
        for issue in repair.issues:
            lines.append(f"- {issue}")
    # 复用输出格式约定（与委派一致）
    from .delegator import _RESULT_SCHEMA_HINT

    lines.append("\n## 输出要求")
    lines.append(_RESULT_SCHEMA_HINT)
    # 走 A2A 通道执行（独立 session，不复用）；usage 采集器返回三元组
    reply, session_id, _brain_tokens = await call_expert_text(
        f"expert_{lead_id}",
        "\n".join(lines),
        session_id=None,
        timeout=DELEGATE_TIMEOUT_S,
    )
    brain_result = parse_result_contract(reply, contract.task_id)
    # token 消耗写入结果契约（与其他节点一致的预算口径）
    brain_result.token_cost = _brain_tokens
    return brain_result, session_id


async def _collect_final(store, run_id: str):
    """收集 final 节点产出作为 run 级汇总与结构化结果。"""
    # 找 final 节点（engine 保证存在）
    nodes = await store.list_nodes(run_id)
    final_rows = [n for n in nodes if n.get("node_type") == "final"]
    # 无 final 行（理论不可达）兜底：取最后完成节点
    target = final_rows[0] if final_rows else (nodes[-1] if nodes else None)
    if target is None or not target.get("result"):
        return "（无汇总产出）", {}
    # 解析 final 的 ResultContract
    try:
        result = ResultContract.model_validate(target["result"])
    except Exception:  # noqa: BLE001 - 结果异常兜底展示
        return str(target["result"])[:2000], target["result"]
    return result.result_text or str(result.result), result.result


def _pick_lead(team: ExpertTeamRecord, members: List[ExpertRecord]) -> str:
    """选出中央大脑人格（lead 成员优先，缺省第一名成员）。"""
    for member in team.members:
        if member.member_role == TEAM_MEMBER_ROLE_LEAD:
            return member.expert_id
    return members[0].id


def _restore_bundle(
    run: Dict[str, Any],
    team: ExpertTeamRecord,
    members: List[ExpertRecord],
) -> ContextBundle:
    """恢复持久化的上下文束（无则构建初始束）。"""
    if run.get("context_bundle"):
        return ContextBundle.model_validate(run["context_bundle"])
    roster = [
        {
            "expert_id": e.id,
            "name": e.name,
            "title": e.title,
            "role_hint": next(
                (m.role_hint for m in team.members if m.expert_id == e.id),
                "",
            ),
        }
        for e in members
    ]
    return bundle_mod.build_initial_bundle(
        run["goal"],
        team.name,
        roster,
        run["initiator_id"],
    )


def _member_caps_payload(
    member_caps: Dict[str, Dict[str, list]],
) -> Dict[str, Dict[str, list]]:
    """压缩成员能力快照为可版本化的 prompt 友好载荷。

    - sops/kb_ids 原样保留（契约与检索都要用）；
    - tools 按字典序稳定排序（避免无意义的内容抖动触发版本 bump）。
    """
    payload: Dict[str, Dict[str, list]] = {}
    for expert_id, caps in member_caps.items():
        if not caps:
            continue
        entry: Dict[str, list] = {}
        if caps.get("sops"):
            entry["sops"] = caps["sops"]
        if caps.get("kb_ids"):
            entry["kb_ids"] = list(caps["kb_ids"])
        if caps.get("tools"):
            entry["tools"] = sorted(caps["tools"])
        if entry:
            payload[expert_id] = entry
    return payload


async def _load_team_context(team_id: str):
    """加载团队、成员专家、技能绑定与能力挂载快照（规划与契约的输入）。

    能力挂载快照（member_caps：绑定 SOP/知识库/工具）为 20260830
    P1 接线——加载失败静默降级为空 dict，绝不阻塞编排主链路。
    """
    store = ExpertStore()
    team = await store.get_team(team_id)
    if team is None:
        return None, [], {}, {}
    # 成员专家按绑定顺序加载（跳过已删除的专家行）
    members: List[ExpertRecord] = []
    for member in team.members:
        expert = await store.get_expert(member.expert_id)
        if expert is not None:
            members.append(expert)
    # 能力发现：每成员启用技能（expert_skills 权威）
    member_skills: Dict[str, List[str]] = {}
    for expert in members:
        try:
            member_skills[expert.id] = await store.enabled_skill_names(expert.id)
        except Exception:  # noqa: BLE001 - 技能查询失败不阻塞（空集降级）
            member_skills[expert.id] = []
    # 能力挂载快照（SOP/知识/工具绑定，五步范式批查）
    member_caps: Dict[str, Dict[str, list]] = {}
    try:
        from ..experts.capability import get_capability_store

        member_caps = await get_capability_store().member_capability_snapshot(
            [e.id for e in members],
        )
    except Exception:  # noqa: BLE001 - 绑定快照失败降级为空（原有能力面不受影响）
        logger.debug("成员能力挂载快照降级为空", exc_info=True)
    return team, members, member_skills, member_caps


def _check_time_budget(clock_start: float, policy: RunPolicy) -> None:
    """时间熔断检查（超限抛 EscalateSignal）。"""
    # 0 = 不限时
    if policy.max_total_seconds <= 0:
        return
    elapsed = time.monotonic() - clock_start
    if elapsed > policy.max_total_seconds:
        raise EscalateSignal(
            f"run 总时长 {int(elapsed)}s 超过上限 {policy.max_total_seconds}s"
        )


def _node_label(dag_node: DagNode, members_by_id: Dict[str, ExpertRecord]) -> str:
    """节点展示名（专家名 + 目标简述，供摘要与前端展示）。"""
    expert = members_by_id.get(dag_node.assignee_expert_id)
    prefix = expert.name if expert else "中央大脑"
    objective = dag_node.objective or dag_node.node_key
    return f"{prefix}·{objective[:40]}"


def _bundle_lock(run_id: str) -> asyncio.Lock:
    """取 run 级上下文束互斥锁（懒创建，进程内生命周期一致）。"""
    if run_id not in _bundle_locks:
        _bundle_locks[run_id] = asyncio.Lock()
    return _bundle_locks[run_id]
