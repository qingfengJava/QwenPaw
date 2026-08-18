# -*- coding: utf-8 -*-
"""Workforce run 持久化与事件存储（team_runs / team_run_nodes）。

职责（与既有 ``experts/store.py`` 同风格的 PG 访问层）：

- run / node 的 CRUD 与状态流转（参数绑定 SQL，禁止拼接）；
- 规划产物物化：DagPlan 落 ``team_runs.plan`` 并 upsert 节点行；
- 事件双写：进程内总线（run topic + 项目 topic）+ PG ``feed_events``
  （仅挂项目的 run 写表，feed_events.project_id 为 NOT NULL）；
- checkpoint：节点边界写 contract/result 即快照（崩溃恢复依据）；
- 启动恢复扫描：活跃态 run 改写为 interrupted（engine 续跑入口）。

@author qingfeng
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from ..events.bus import feed_topic, get_event_bus, now_ms
from .contracts import (
    NODE_ACTIVE_STATUSES,
    NODE_STATUS_PENDING,
    RUN_ACTIVE_STATUSES,
    RUN_STATUS_INTERRUPTED,
    DagPlan,
    ResultContract,
)

logger = logging.getLogger(__name__)

#: run 详情 SSE 订阅的规范 topic 名（与 workforce 路由约定一致）
def run_topic(tenant_id: str, run_id: str) -> str:
    """Canonical topic name for one team run's event stream."""
    return f"run:{tenant_id}:{run_id}"


#: run 表可被 update_run 更新的字段白名单（防越权字段注入）
_RUN_UPDATABLE = {
    "status",
    "goal",
    "plan",
    "policy",
    "context_bundle",
    "context_version",
    "summary",
    "result",
    "clarification",
    "repair_count",
    "replan_count",
    "error",
    "escalation_reason",
    "source_chat_id",
    "project_id",
}

#: node 表可被 update_node 更新的字段白名单
_NODE_UPDATABLE = {
    "status",
    "contract",
    "result",
    "repair",
    "verdict",
    "repair_count",
    "session_id",
    "token_cost",
    "attempt",
    "assignee_expert_id",
    "assignee_user_id",
    "node_type",
}


def _json_dumps(value: Any) -> str:
    """序列化为 JSON 文本（JSONB 列统一走 CAST 参数绑定）。"""
    return json.dumps(value, ensure_ascii=False, default=str)


class WorkforceRunStore:
    """team_runs / team_run_nodes 的租户内 CRUD 与事件发射。"""

    # ------------------------------------------------------------------
    # run CRUD
    # ------------------------------------------------------------------

    async def create_run(
        self,
        team_id: str,
        goal: str,
        initiator_id: str,
        project_id: Optional[str] = None,
        source_chat_id: Optional[str] = None,
        policy: Optional[Dict[str, Any]] = None,
        context_bundle: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建一条 planning 状态的 run 并返回完整行（dict）。"""
        # 生成业务 ID 与租户上下文
        rid = run_id or new_id("run")
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        # 单条插入（参数绑定；JSONB 列经 CAST 传入）
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO team_runs (tenant_id, id, team_id, "
                    "project_id, source_chat_id, initiator_id, status, "
                    "goal, policy, context_bundle) VALUES "
                    "(:tid, :id, :team, :pid, :chat, :initiator, "
                    "'planning', :goal, CAST(:policy AS JSONB), "
                    "CAST(:bundle AS JSONB))"
                ),
                {
                    "tid": tid,
                    "id": rid,
                    "team": team_id,
                    "pid": project_id,
                    "chat": source_chat_id,
                    "initiator": initiator_id,
                    "goal": goal,
                    "policy": _json_dumps(policy or {}),
                    "bundle": _json_dumps(context_bundle or {}),
                },
            )
        # 回读完整行（含 DB 默认值），保证调用方拿到一致视图
        row = await self.get_run(rid)
        assert row is not None, "run 插入后回读失败"
        return row

    async def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 取一条 run（不存在返回 None）。"""
        # 租户内主键查询
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT * FROM team_runs WHERE tenant_id = :tid "
                    "AND id = :id"
                ),
                {"tid": current_tenant_id(), "id": run_id},
            )
            row = result.mappings().first()
        # 映射为普通 dict（JSONB 已是 dict，datetime 保留原样）
        return dict(row) if row else None

    async def update_run(self, run_id: str, **fields: Any) -> bool:
        """按白名单更新 run 的若干列（未命中行返回 False）。"""
        # 未知字段直接拒绝（调用方 bug 早暴露）
        unknown = set(fields) - _RUN_UPDATABLE
        if unknown:
            raise ValueError(f"team_runs 不允许更新字段: {sorted(unknown)}")
        # 空更新视为成功（幂等）
        if not fields:
            return True
        # 组装 SET 片段（列名来自白名单常量，值全部参数绑定）
        tid = current_tenant_id()
        sets = []
        params: Dict[str, Any] = {"tid": tid, "id": run_id}
        for key, value in fields.items():
            # JSONB 字段序列化后 CAST；其余原样绑定
            if key in ("plan", "policy", "context_bundle", "result", "clarification"):
                params[f"v_{key}"] = _json_dumps(value)
                sets.append(f"{key} = CAST(:v_{key} AS JSONB)")
            else:
                params[f"v_{key}"] = value
                sets.append(f"{key} = :v_{key}")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"UPDATE team_runs SET {', '.join(sets)} "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                params,
            )
        return bool(result.rowcount)

    async def set_run_status(
        self,
        run_id: str,
        status: str,
        error: str = "",
        escalation_reason: str = "",
    ) -> bool:
        """流转 run 状态（终态附带原因字段，便于审计与前端展示）。"""
        # 每次调用都会写入传入的 error/escalation_reason（含空串清空语义），调用方需自行保证语义
        return await self.update_run(
            run_id,
            status=status,
            error=error,
            escalation_reason=escalation_reason,
        )

    async def list_runs(
        self,
        initiator_id: Optional[str] = None,
        team_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """按过滤条件列出 run（新到旧；列表页不带 nodes）。"""
        # 条件内联拼接（仅布尔开关，值仍参数绑定）
        conditions = ["tenant_id = :tid"]
        params: Dict[str, Any] = {"tid": current_tenant_id(), "limit": limit}
        if initiator_id:
            conditions.append("initiator_id = :initiator")
            params["initiator"] = initiator_id
        if team_id:
            conditions.append("team_id = :team")
            params["team"] = team_id
        if project_id:
            conditions.append("project_id = :pid")
            params["pid"] = project_id
        if status:
            conditions.append("status = :status")
            params["status"] = status
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT * FROM team_runs WHERE "
                    + " AND ".join(conditions)
                    + " ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
            rows = result.mappings().all()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # 规划产物物化（DagPlan → 节点行）
    # ------------------------------------------------------------------

    async def save_plan(self, run_id: str, plan: DagPlan) -> None:
        """保存任务图并物化节点行（幂等 upsert，不覆盖执行状态列）。

        plan_note/source 等元信息与 nodes 一并存入 plan JSONB；
        节点行的 contract/result 等执行字段仅在规划重建（re-plan）时
        重置——普通更新不动已执行内容。
        """
        # 先落 plan 快照
        await self.update_run(run_id, plan=plan.model_dump())
        # 逐节点 upsert（DDL 幂等语义：已存在则刷新指派与类型）
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            for node in plan.nodes:
                await conn.execute(
                    text(
                        "INSERT INTO team_run_nodes (tenant_id, run_id, "
                        "node_key, assignee_expert_id, assignee_user_id, "
                        "node_type, status) VALUES (:tid, :rid, :key, "
                        ":expert, :assignee_user, :ntype, 'pending') "
                        "ON CONFLICT (tenant_id, run_id, node_key) "
                        "DO UPDATE SET assignee_expert_id = EXCLUDED."
                        "assignee_expert_id, assignee_user_id = EXCLUDED."
                        "assignee_user_id, node_type = EXCLUDED.node_type"
                    ),
                    {
                        "tid": tid,
                        "rid": run_id,
                        "key": node.node_key,
                        "expert": node.assignee_expert_id,
                        "assignee_user": node.assignee_user_id or None,
                        "ntype": node.node_type,
                    },
                )

    async def reset_nodes_for_replan(self, run_id: str) -> None:
        """重规划时清空全部节点执行痕迹（保留节点行重建语义给 save_plan）。

        re-plan 会产生全新的 node_key 集合，旧行删除避免残留误导；
        历史 attempt 信息已通过 feed 事件留痕，可追溯。
        """
        # 直接删除该 run 全部节点行（replan 计数在 run 级保留）
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM team_run_nodes WHERE tenant_id = :tid "
                    "AND run_id = :rid"
                ),
                {"tid": tid, "rid": run_id},
            )

    # ------------------------------------------------------------------
    # node CRUD
    # ------------------------------------------------------------------

    async def list_nodes(self, run_id: str) -> List[Dict[str, Any]]:
        """列出 run 全部节点（node_key 字典序，DAG 展示稳定）。"""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT * FROM team_run_nodes WHERE tenant_id = :tid "
                    "AND run_id = :rid ORDER BY node_key"
                ),
                {"tid": current_tenant_id(), "rid": run_id},
            )
            rows = result.mappings().all()
        return [dict(row) for row in rows]

    async def get_node(self, run_id: str, node_key: str) -> Optional[Dict[str, Any]]:
        """取单个节点行（不存在返回 None）。"""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT * FROM team_run_nodes WHERE tenant_id = :tid "
                    "AND run_id = :rid AND node_key = :key"
                ),
                {"tid": current_tenant_id(), "rid": run_id, "key": node_key},
            )
            row = result.mappings().first()
        return dict(row) if row else None

    async def update_node(self, run_id: str, node_key: str, **fields: Any) -> bool:
        """按白名单更新节点列（contract/result 即 checkpoint）。"""
        # 未知字段直接拒绝
        unknown = set(fields) - _NODE_UPDATABLE
        if unknown:
            raise ValueError(f"team_run_nodes 不允许更新字段: {sorted(unknown)}")
        # 空更新幂等成功
        if not fields:
            return True
        # 组装 SET 片段（列名白名单，值参数绑定）
        tid = current_tenant_id()
        sets = []
        params: Dict[str, Any] = {"tid": tid, "rid": run_id, "key": node_key}
        for key, value in fields.items():
            # 契约三列序列化 CAST；其余原样
            if key in ("contract", "result", "repair"):
                params[f"v_{key}"] = _json_dumps(value)
                sets.append(f"{key} = CAST(:v_{key} AS JSONB)")
            else:
                params[f"v_{key}"] = value
                sets.append(f"{key} = :v_{key}")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"UPDATE team_run_nodes SET {', '.join(sets)} "
                    "WHERE tenant_id = :tid AND run_id = :rid "
                    "AND node_key = :key"
                ),
                params,
            )
        return bool(result.rowcount)

    # ------------------------------------------------------------------
    # 上下文版本与上游摘要
    # ------------------------------------------------------------------

    async def bump_context_version(self, run_id: str) -> int:
        """上下文版本 +1 并返回新版本号（全局决策/澄清/移交时调用）。"""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE team_runs SET context_version = context_version "
                    "+ 1 WHERE tenant_id = :tid AND id = :rid RETURNING "
                    "context_version"
                ),
                {"tid": current_tenant_id(), "rid": run_id},
            )
            row = result.first()
        # 未命中行返回 0（调用方按需断言）
        return int(row[0]) if row else 0

    async def add_repair_count(self, run_id: str) -> None:
        """run 级累计返工次数 +1（观测指标）。"""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE team_runs SET repair_count = repair_count + 1 "
                    "WHERE tenant_id = :tid AND id = :rid"
                ),
                {"tid": current_tenant_id(), "rid": run_id},
            )

    async def add_replan_count(self, run_id: str) -> None:
        """run 级重规划计数 +1（熔断依据）。"""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE team_runs SET replan_count = replan_count + 1 "
                    "WHERE tenant_id = :tid AND id = :rid"
                ),
                {"tid": current_tenant_id(), "rid": run_id},
            )

    # ------------------------------------------------------------------
    # 事件发射（总线双 topic + PG feed_events）
    # ------------------------------------------------------------------

    async def emit_event(
        self,
        run: Dict[str, Any],
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        actor: str = "workforce",
    ) -> None:
        """发射一条 run 事件：run topic + 项目 topic + PG 留痕。

        - 总线 run topic（RunDetail SSE 消费）：始终发布；
        - 总线项目 topic（项目动态流）：run 挂项目时额外发布；
        - PG ``feed_events``：run 挂项目时持久留痕（表要求 project_id
          非空；无项目的 run 仅走内存总线，历史以 team_runs 留痕）。
        全程 best-effort：事件失败仅记日志，不影响引擎主流程。
        """
        # 组装统一事件体（run 维度信息 + 业务 payload）
        tid = run.get("tenant_id") or current_tenant_id()
        event = {
            "kind": kind,
            "run_id": run["id"],
            "team_id": run.get("team_id"),
            "actor": actor,
            "payload": payload or {},
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # 总线：run topic（详情页 SSE）
            bus = get_event_bus()
            await bus.publish(run_topic(tid, run["id"]), event)
            # 总线：项目 topic（项目动态流；挂项目才发）
            project_id = run.get("project_id")
            if project_id:
                await bus.publish(feed_topic(tid, project_id), event)
            # PG 持久留痕（挂项目才写；feed_events.project_id NOT NULL）
            if project_id:
                engine = require_enterprise_engine()
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO feed_events (tenant_id, "
                            "project_id, actor, kind, payload) VALUES "
                            "(:tid, :pid, :actor, :kind, "
                            "CAST(:payload AS JSONB))"
                        ),
                        {
                            "tid": tid,
                            "pid": project_id,
                            "actor": actor,
                            "kind": kind,
                            "payload": _json_dumps(event),
                        },
                    )
        except Exception:  # pragma: no cover - best-effort 事件通道
            # 事件通道故障不阻塞编排（持久真相在 run/node 行）
            logger.exception("workforce 事件发射失败 kind=%s", kind)

    # ------------------------------------------------------------------
    # 启动恢复扫描（Checkpoint Protocol 的入口）
    # ------------------------------------------------------------------

    async def mark_interrupted_runs(self) -> int:
        """进程启动时把活跃态 run 标记为 interrupted，返回受影响行数。

        单 worker 拓扑下进程重启必然丢失内存中的 asyncio 任务；
        本扫描保证：活跃 run 在持久层可见地进入 interrupted 态，
        用户可从 RunDetail 发起续跑（engine 从节点 attempt 恢复）。
        同时把活跃 run 的中间态节点（delegated/verifying/...）回退
        pending——否则主循环只统计 pending/done，中间态节点续跑时
        被静默跳过，run 可带着缺失产出收敛。
        """
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            # 中间态节点回退 pending（单 worker 拓扑：启动时刻无并发
            # 引擎任务，重置安全；contract/session 保留供委派复用）。
            # 必须先于 run 状态 UPDATE 执行：同事务内后一条语句能看到
            # 前条的改动，若先改写 run 状态，下面 join 的
            # r.status = ANY(:active) 将匹配不到任何行，重置静默失效。
            await conn.execute(
                text(
                    "UPDATE team_run_nodes n SET status = :pending "
                    "FROM team_runs r WHERE r.tenant_id = n.tenant_id "
                    "AND r.id = n.run_id AND r.tenant_id = :tid "
                    "AND r.status = ANY(:active) "
                    "AND n.status = ANY(:node_active)"
                ),
                {
                    "tid": current_tenant_id(),
                    "active": list(RUN_ACTIVE_STATUSES),
                    "node_active": list(NODE_ACTIVE_STATUSES),
                    "pending": NODE_STATUS_PENDING,
                },
            )
            result = await conn.execute(
                text(
                    "UPDATE team_runs SET status = :interrupted WHERE "
                    "tenant_id = :tid AND status = ANY(:active)"
                ),
                {
                    "interrupted": RUN_STATUS_INTERRUPTED,
                    "tid": current_tenant_id(),
                    "active": list(RUN_ACTIVE_STATUSES),
                },
            )
        count = result.rowcount or 0
        if count:
            logger.warning("启动恢复：%d 个活跃 run 已标记为 interrupted", count)
        return count


# ---------------------------------------------------------------------------
# 模块级单例访问（与 ExpertStore 的使用方式对齐：路由层 new 一次）
# ---------------------------------------------------------------------------

_store: Optional[WorkforceRunStore] = None


def get_run_store() -> WorkforceRunStore:
    """进程级单例（无状态对象，单例仅为减少分配）。"""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = WorkforceRunStore()
    return _store
