# -*- coding: utf-8 -*-
"""Admin workforce API（/api/admin/workforce/**）。

管理端的 workforce 运行面（console 管理端编排配置的消费端）：

- ``GET /runs``：全租户 run 列表（不限发起人）；
- ``GET /stats``：运行统计聚合（总数 / 状态分布 / 返工率 / 升级率 /
  token 成本合计，team_runs + team_run_nodes 单轮 SQL 聚合）；
- ``POST /teams/{team_id}/test-run``：团队编排配置"试运行"——创建一次
  测试 run 并后台启动引擎（与 xian 创建通道同一套 run_store/engine
  链路，initiator 记为管理员），用于验证 orchestration 模板质量。

权限：PERM_ADMIN_EXPERTS（与专家团队管理同域）；只依赖 workforce 包
与 run_store，不 import experts.publish（防循环导入，与 xian 面
workforce 路由同一约束）。

@author qingfeng
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from ...enterprise import current_tenant_id, require_enterprise_engine
from ...experts.store import ExpertStore
from ...rbac import PERM_ADMIN_EXPERTS, require_perm
from ...workforce import bundle as bundle_mod
from ...workforce import engine as engine_mod
from ...workforce.contracts import RunPolicy
from ...workforce.run_store import get_run_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workforce",
    tags=["admin-workforce"],
    dependencies=[Depends(require_perm(PERM_ADMIN_EXPERTS))],
)


class TestRunBody(BaseModel):
    """试运行请求体（goal 可选，默认内置试运行目标）。"""

    goal: str = ""


@router.get("/runs")
async def list_all_runs(
    team_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """全租户 run 列表（管理端只读视图；limit 上限 500 防误拖全表）。"""
    store = get_run_store()
    return await store.list_runs(
        team_id=team_id,
        status=status,
        limit=max(1, min(limit, 500)),
    )


@router.get("/stats")
async def run_stats() -> Dict[str, Any]:
    """运行统计聚合：状态分布 / 返工率 / 升级率 / token 成本。

    单轮 SQL 聚合（team_runs 维度 + team_run_nodes 维度各一条），
    与 feed_events / token_usage_events 解耦——workforce 的 token
    成本以 node.token_cost 聚合值为权威（明细行由既有 per-call
    管道写 token_usage_events，此处不重复计数）。
    """
    tid = current_tenant_id()
    engine = require_enterprise_engine()
    async with engine.begin() as conn:
        runs_row = (
            await conn.execute(
                text(
                    "SELECT count(*) AS total, "
                    "count(*) FILTER (WHERE status = 'done') AS done, "
                    "count(*) FILTER (WHERE status = 'failed') AS failed, "
                    "count(*) FILTER (WHERE status = 'escalated') AS escalated, "
                    "count(*) FILTER (WHERE status IN "
                    "('running','planning','awaiting_confirm','verifying',"
                    "'repairing','aggregating')) AS active, "
                    "count(*) FILTER (WHERE status = 'interrupted') AS interrupted, "
                    "count(*) FILTER (WHERE repair_count > 0) AS repaired_runs, "
                    "COALESCE(SUM(repair_count), 0) AS repair_total, "
                    "COALESCE(SUM(replan_count), 0) AS replan_total "
                    "FROM team_runs WHERE tenant_id = :tid"
                ),
                {"tid": tid},
            )
        ).one()
        tokens_row = (
            await conn.execute(
                text(
                    "SELECT COALESCE(SUM(n.token_cost), 0) AS tokens_total "
                    "FROM team_run_nodes n WHERE n.tenant_id = :tid"
                ),
                {"tid": tid},
            )
        ).one()
    total = int(runs_row.total or 0)
    return {
        "total_runs": total,
        "done": int(runs_row.done or 0),
        "failed": int(runs_row.failed or 0),
        "escalated": int(runs_row.escalated or 0),
        "active": int(runs_row.active or 0),
        "interrupted": int(runs_row.interrupted or 0),
        "repaired_runs": int(runs_row.repaired_runs or 0),
        "repair_total": int(runs_row.repair_total or 0),
        "replan_total": int(runs_row.replan_total or 0),
        "tokens_total": int(tokens_row.tokens_total or 0),
        # 比率（总数为 0 时置 0，避免除零）
        "repair_rate": round(int(runs_row.repaired_runs or 0) / total, 4) if total else 0.0,
        "escalation_rate": round(int(runs_row.escalated or 0) / total, 4) if total else 0.0,
    }


@router.post("/teams/{team_id}/test-run", status_code=201)
async def create_test_run(
    team_id: str,
    body: TestRunBody,
    request: Request,
) -> Dict[str, Any]:
    """团队试运行：验证 orchestration 编排配置（管理端专用通道）。

    与 xian 创建通道共用 run_store / bundle / engine 链路；initiator
    记为管理员账号（request.state.user），goal 缺省用内置试运行目标。
    """
    store = get_run_store()
    expert_store = ExpertStore()
    team = await expert_store.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.status != "published":
        raise HTTPException(status_code=400, detail="Team is not published")
    actor = getattr(request.state, "user", None) or "admin"
    goal = body.goal.strip() or "试运行：验证团队编排配置（管理员发起）"
    # 熔断策略：团队模板优先（试运行即验证模板本身）
    policy: Dict[str, Any] = {}
    if isinstance(team.orchestration, dict) and team.orchestration.get("policy"):
        policy = RunPolicy.model_validate(team.orchestration["policy"]).model_dump()
    # 成员花名册投影（与 xian 创建通道一致）
    members = []
    for member in team.members:
        expert = await expert_store.get_expert(member.expert_id)
        if expert is not None:
            members.append(expert)
    if not members:
        raise HTTPException(status_code=400, detail="Team has no published members")
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
    bundle = bundle_mod.build_initial_bundle(goal, team.name, roster, actor)
    run = await store.create_run(
        team_id=team_id,
        goal=goal,
        initiator_id=actor,
        policy=policy,
        context_bundle=bundle.model_dump(),
    )
    await store.emit_event(run, "team_run_created", {"goal": goal[:200], "test_run": True})
    engine_mod.start_run_background(run["id"])
    return {**run, "nodes": []}
