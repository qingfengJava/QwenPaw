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
    RUN_STATUS_RUNNING,
    ContextBundle,
    DagNode,
    DagPlan,
    RepairContract,
    ResultContract,
    RunPolicy,
    TaskContract,
    VERDICT_FAIL,
    VERDICT_PASS,
)
from .delegator import DELEGATE_TIMEOUT_S, call_expert_text, delegate, parse_result_contract
from .planner import build_task_contract, plan_run
from .run_store import get_run_store
from .verifier import verify

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
    """取消一次运行中的 run（传播取消到后台任务）；返回是否生效。"""
    task = _active_tasks.get(run_id)
    # 无运行任务：仅状态置 canceled（终态幂等）
    if task is None or task.done():
        return False
    # 请求协作取消（CancelledError 在引擎内收敛为 canceled 终态）
    task.cancel()
    return True


async def _guarded_run(run_id: str) -> None:
    """带异常护栏的 run 主入口（任何异常收敛为 failed 终态）。"""
    store = get_run_store()
    started_at = time.monotonic()
    try:
        await run_team_run(run_id, started_at=started_at)
    except asyncio.CancelledError:
        # 用户取消：确保终态为 canceled（cancel_run 可能已写状态，幂等补写）
        run = await store.get_run(run_id)
        if run is not None and run["status"] not in _RUN_TERMINAL:
            await store.set_run_status(run_id, RUN_STATUS_CANCELED)
            await store.emit_event(run, "team_run_canceled")
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
    # 加载团队上下文（成员 + 技能绑定 + 中央大脑人格）
    team, members, member_skills = await _load_team_context(run["team_id"])
    if team is None or not members:
        await store.set_run_status(run_id, RUN_STATUS_FAILED, error="团队不存在或没有成员")
        await store.emit_event(run, "team_run_failed", {"error": "团队不存在或没有成员"})
        return
    members_by_id = {e.id: e for e in members}
    lead_id = _pick_lead(team, members)
    # 恢复或初始化上下文束与策略
    bundle = _restore_bundle(run, team, members)
    policy = RunPolicy.model_validate(run["policy"]) if run.get("policy") else RunPolicy()
    # 状态进入执行态（planning/interrupted → running）
    await store.set_run_status(run_id, RUN_STATUS_RUNNING)
    await store.emit_event(run, "run_started", {"team": team.name})
    # ---- 规划阶段（已有 plan 则跳过：续跑 / 重入） ----
    if not (run.get("plan") or {}).get("nodes"):
        await _plan_phase(store, run, team, members, bundle)
        # 规划阶段可能改变 run 状态（awaiting_confirm / failed），重读判定
        run = await store.get_run(run_id)
        if run["status"] != RUN_STATUS_RUNNING:
            return
    # ---- 执行阶段：波次拓扑调度 ----
    while True:
        # 每轮重读 run/节点状态（并行完成后的最新视图）
        run = await store.get_run(run_id)
        if run["status"] in _RUN_TERMINAL:
            return
        # 依赖关系以持久化的 plan 为权威（节点行不存 deps）
        plan = DagPlan.model_validate(run["plan"])
        plan_by_key = {n.node_key: n for n in plan.nodes}
        nodes = await store.list_nodes(run_id)
        done_keys = {n["node_key"] for n in nodes if n["status"] == NODE_STATUS_DONE}
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
            await store.set_run_status(run_id, RUN_STATUS_FAILED, error="DAG 调度死锁（存在无法就绪的节点）")
            await store.emit_event(run, "team_run_failed", {"error": "DAG 调度死锁"})
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
                _run_node_bounded(semaphore, store, run_id, run, policy, bundle, node_key, members_by_id, member_skills, lead_id)
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
        # 其余节点执行异常不得静默：否则主循环会把同一 pending 节点
        # 无限重新 gather（引擎空转烧 CPU、run 永不终态）。统一冒泡给
        # _guarded_run 收敛为 failed 终态并留痕日志。
        for item in results:
            if isinstance(item, BaseException) and not isinstance(
                item, (EscalateSignal, asyncio.CancelledError)
            ):
                logger.error("节点执行异常（run=%s）: %r", run_id, item)
                raise item
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


async def _plan_phase(
    store,
    run: Dict[str, Any],
    team: ExpertTeamRecord,
    members: List[ExpertRecord],
    bundle: ContextBundle,
) -> None:
    """规划阶段：模板/LLM 产出 DagPlan，或转澄清挂起，或失败终止。"""
    run_id = run["id"]
    await store.emit_event(run, "planning_started")
    # 执行规划（模板优先 → 中央大脑）
    outcome = await plan_run(run["goal"], team, members, bundle)
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
        await store.emit_event(run, "team_run_failed", {"error": outcome.error, "stage": "planning"})
        return
    # 成功：物化任务图与节点行
    await store.save_plan(run_id, outcome.plan)
    await store.emit_event(
        run,
        "plan_ready",
        {"source": outcome.source, "nodes": [n.node_key for n in outcome.plan.nodes]},
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
        # 取最近一次返工契约（首轮为空）
        node_now = await store.get_node(run_id, node_key) or {}
        repair = (
            RepairContract.model_validate(node_now["repair"])
            if node_now.get("repair")
            else None
        )
        # 节点状态推进：委派中
        await store.update_node(run_id, node_key, status=NODE_STATUS_DELEGATED, attempt=attempt + 1)
        await store.emit_event(run, "node_started", {"node_key": node_key, "attempt": attempt + 1})
        # 执行节点：final/integration 由中央大脑自执行，成员节点走委派
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
        attempt += 1
        # 结果 checkpoint（崩溃恢复点）+ 会话与计量累计回写
        node_now = await store.get_node(run_id, node_key) or {}
        token_total = int(node_now.get("token_cost", 0) or 0) + int(result.token_cost or 0)
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
        # 验收：final 节点（中央大脑自执行）自验收通过，其余由 lead 裁决
        await store.update_node(run_id, node_key, status=NODE_STATUS_VERIFYING)
        if expert_id:
            verdict = await verify(
                lead_id,
                contract,
                result,
                policy,
                repair_count=repair_count,
                previous_repair=repair,
            )
        else:
            from .verifier import Verdict

            verdict = Verdict(VERDICT_PASS, reason="final 汇总节点自验收")
        # 裁决留痕
        await store.update_node(run_id, node_key, verdict=verdict.verdict)
        await store.emit_event(
            run,
            "node_verdict",
            {"node_key": node_key, "verdict": verdict.verdict, "reason": verdict.reason},
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
                await store.update_run(run_id, context_bundle=bundle.model_dump())
            await store.update_node(run_id, node_key, status=NODE_STATUS_DONE)
            return
        # FAIL：返工契约持久化 + 计数 + 事件，进入下一轮
        if verdict.verdict == VERDICT_FAIL and verdict.repair is not None:
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
                {"node_key": node_key, "attempt": repair_count, "issues": verdict.repair.issues},
            )
            continue
        # ESCALATE（或 FAIL 无契约的异常形态）：熔断升级人工
        raise EscalateSignal(
            f"节点 {node_key} {verdict.verdict}：{verdict.reason}"
        )


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


async def _load_team_context(team_id: str):
    """加载团队、成员专家与技能绑定（规划与契约构建的输入）。"""
    store = ExpertStore()
    team = await store.get_team(team_id)
    if team is None:
        return None, [], {}
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
    return team, members, member_skills


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
