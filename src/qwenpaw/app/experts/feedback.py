# -*- coding: utf-8 -*-
"""Message feedback + evolution proposals (反馈驱动演进闭环, 决策 D7).

- ``message_feedback``：消息级 👍/👎 采集，(message_id, user_id) 唯一，
  重复提交 = 覆盖（语义修正）；``rate_summary`` 供工作记录/详情页消费。
- ``evolution_proposals``：变更提案生命周期
  draft → ready_for_review → approved | rejected → published | rolled_back。
  发布动作由各 target 的权威模块执行（system_prompt 直写 + SOP 版本链），
  状态机留痕不物理删。

LLM 自动归因（20260830 P2 完整版）：差评触发专家自省——13 桶归因 +
SOP 结构变更候选自动起草提案（每日限量防刷屏）；提案发布时记录差评
基线（attach_monitor），窗口内差评率显著恶化自动回滚并留痕
（check_auto_rollback，三重门槛防误伤）。详见文件尾部与设计文档 §八。
@author qingfeng
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from .store import get_expert_store
from .models import (
    EXPERT_STATUS_PUBLISHED,
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_DRAFT,
    PROPOSAL_STATUS_PUBLISHED,
    PROPOSAL_STATUS_READY_FOR_REVIEW,
    PROPOSAL_STATUS_REJECTED,
    PROPOSAL_STATUS_ROLLED_BACK,
    EvolutionProposal,
)

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"(\{.*\})", re.DOTALL)

_PROPOSAL_COLS = (
    "id, expert_id, title, trigger_type, risk_level, hypothesis, "
    "evidence, candidate, status, reviewed_by, reviewed_at, "
    "created_at, updated_at"
)

#: 合法评审动作（review 接口白名单）
_REVIEW_ACTIONS = ("approve", "reject")

#: 归因桶（StaffDeck 13 桶对应物；自省输出必须落桶，便于汇总分析）
ATTRIBUTION_BUCKETS = (
    "model_issue",  # 模型能力不足
    "skill_instruction_issue",  # 技能指令缺陷
    "sop_trigger_issue",  # SOP 触发/识别偏差
    "sop_slot_issue",  # SOP 槽位/信息收集缺陷
    "sop_transition_issue",  # SOP 步骤流转缺陷
    "sop_capability_issue",  # SOP 能力引用缺失
    "knowledge_gap",  # 知识缺口
    "tool_or_runtime_issue",  # 工具/运行时故障
    "user_random_or_unclear",  # 用户输入随机/不清晰
    "positive_or_resolved",  # 实为正面或已解决
    "needs_model_analysis",  # 需更强模型分析
    "unknown",  # 无法归因
)

#: SOP 相关桶（自省在这些桶下可产出 SOP 结构变更候选）
_SOP_BUCKETS = (
    "sop_trigger_issue",
    "sop_slot_issue",
    "sop_transition_issue",
    "sop_capability_issue",
)

#: 自动回滚监控阈值（三重门槛防误伤）
AUTO_ROLLBACK_MIN_NEW_RATINGS = 5
AUTO_ROLLBACK_MIN_HOURS = 24
AUTO_ROLLBACK_RATE_DROP = 0.2


def _row_to_proposal(row) -> EvolutionProposal:
    """Map one evolution_proposals row."""
    return EvolutionProposal(
        id=row.id,
        expert_id=row.expert_id,
        title=row.title,
        trigger_type=row.trigger_type,
        risk_level=row.risk_level,
        hypothesis=row.hypothesis or "",
        evidence=list(row.evidence or []),
        candidate=row.candidate or {},
        status=row.status,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class FeedbackStore:
    """Message ratings (upsert) + summary aggregation."""

    async def rate(
        self,
        message_id: str,
        user_id: str,
        rating: str,
        session_id: str = "",
        expert_id: str = "",
        comment: str = "",
    ) -> Dict[str, Any]:
        """Upsert one rating; returns the final state.

        rating 白名单外取值直接拒绝（调用方 400），此处断言防御。
        """
        if rating not in ("up", "down"):
            raise ValueError("rating must be 'up' or 'down'")
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            existing = await conn.execute(
                text(
                    "SELECT id FROM message_feedback WHERE "
                    "tenant_id = :tid AND message_id = :mid "
                    "AND user_id = :uid"
                ),
                {"tid": tid, "mid": message_id, "uid": user_id},
            )
            row = existing.first()
            if row is None:
                await conn.execute(
                    text(
                        "INSERT INTO message_feedback (tenant_id, id, "
                        "message_id, session_id, expert_id, user_id, "
                        "rating, comment) VALUES (:tid, :id, :mid, "
                        ":sid, :eid, :uid, :rating, :comment)"
                    ),
                    {
                        "tid": tid,
                        "id": new_id("mfb"),
                        "mid": message_id,
                        "sid": session_id,
                        "eid": expert_id,
                        "uid": user_id,
                        "rating": rating,
                        "comment": comment,
                    },
                )
                return {
                    "message_id": message_id,
                    "rating": rating,
                    "updated": False,
                }
            await conn.execute(
                text(
                    "UPDATE message_feedback SET rating = :rating, "
                    "comment = :comment, "
                    # 归属字段非空才覆盖（改口不抹掉归属）
                    "expert_id = CASE WHEN :eid <> '' THEN :eid "
                    "ELSE expert_id END, "
                    "session_id = CASE WHEN :sid <> '' THEN :sid "
                    "ELSE session_id END, "
                    "updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {
                    "tid": tid,
                    "id": row.id,
                    "rating": rating,
                    "comment": comment,
                    "eid": expert_id,
                    "sid": session_id,
                },
            )
            return {
                "message_id": message_id,
                "rating": rating,
                "updated": True,
            }

    async def summary(
        self,
        expert_id: str,
        days: int = 30,
    ) -> Dict[str, Any]:
        """Windowed 👍/👎 counts + positive rate (SQL aggregate, one query)."""
        since = datetime.now(dt_timezone.utc) - timedelta(days=days)
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT rating, count(*) AS n FROM message_feedback "
                    "WHERE tenant_id = :tid AND expert_id = :eid "
                    "AND created_at >= :since GROUP BY rating"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "since": since,
                },
            )
            counts = {r.rating: int(r.n) for r in result}
        up = counts.get("up", 0)
        down = counts.get("down", 0)
        total = up + down
        return {
            "days": days,
            "feedback_up": up,
            "feedback_down": down,
            "total": total,
            "positive_rate": round(up / total, 4) if total else None,
        }

    async def recent_for_expert(
        self,
        expert_id: str,
        days: int = 30,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Recent ratings of one expert (差评列表/反馈样本)."""
        since = datetime.now(dt_timezone.utc) - timedelta(days=days)
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, message_id, session_id, user_id, rating, "
                    "comment, created_at FROM message_feedback WHERE "
                    "tenant_id = :tid AND expert_id = :eid "
                    "AND created_at >= :since "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "since": since,
                    "lim": limit,
                },
            )
            return [
                {
                    "id": r.id,
                    "message_id": r.message_id,
                    "session_id": r.session_id,
                    "user_id": r.user_id,
                    "rating": r.rating,
                    "comment": r.comment or "",
                    "created_at": r.created_at,
                }
                for r in result
            ]


class EvolutionStore:
    """Proposal lifecycle: create → review → publish / rollback."""

    async def create_proposal(
        self,
        expert_id: str,
        title: str,
        trigger_type: str = "manual",
        risk_level: str = "low",
        hypothesis: str = "",
        evidence: Optional[List[dict]] = None,
        candidate: Optional[dict] = None,
    ) -> EvolutionProposal:
        """Insert a draft proposal (direct terminal insert refused)."""
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        proposal_id = new_id("evo")
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO evolution_proposals (tenant_id, id, "
                    "expert_id, title, trigger_type, risk_level, "
                    "hypothesis, evidence, candidate, status) VALUES "
                    "(:tid, :id, :eid, :title, :trigger, :risk, :hyp, "
                    "CAST(:evidence AS JSONB), CAST(:candidate AS JSONB), "
                    ":status) RETURNING " + _PROPOSAL_COLS
                ),
                {
                    "tid": tid,
                    "id": proposal_id,
                    "eid": expert_id,
                    "title": title,
                    "trigger": trigger_type,
                    "risk": risk_level,
                    "hyp": hypothesis,
                    "evidence": json.dumps(evidence or []),
                    "candidate": json.dumps(candidate or {}),
                    "status": PROPOSAL_STATUS_DRAFT,
                },
            )
            return _row_to_proposal(result.one())

    async def get_proposal(
        self,
        proposal_id: str,
    ) -> Optional[EvolutionProposal]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _PROPOSAL_COLS + " FROM "
                    "evolution_proposals WHERE tenant_id = :tid "
                    "AND id = :id"
                ),
                {"tid": current_tenant_id(), "id": proposal_id},
            )
            row = result.first()
            return _row_to_proposal(row) if row else None

    async def list_proposals(
        self,
        expert_id: str = "",
        status: str = "",
    ) -> List[EvolutionProposal]:
        """List proposals (filters optional, newest first)."""
        engine = require_enterprise_engine()
        clauses = ["tenant_id = :tid"]
        params: Dict[str, object] = {"tid": current_tenant_id()}
        if expert_id:
            clauses.append("expert_id = :eid")
            params["eid"] = expert_id
        if status:
            clauses.append("status = :status")
            params["status"] = status
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _PROPOSAL_COLS + " FROM "
                    "evolution_proposals WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY updated_at DESC"
                ),
                params,
            )
            return [_row_to_proposal(r) for r in result]

    async def _transition(
        self,
        proposal_id: str,
        status: str,
        reviewed_by: str = "",
    ) -> Optional[EvolutionProposal]:
        """One guarded status transition (updated_at always touched)."""
        engine = require_enterprise_engine()
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "id": proposal_id,
            "status": status,
        }
        reviewer_fragment = ""
        if reviewed_by:
            reviewer_fragment = ", reviewed_by = :by, reviewed_at = now()"
            params["by"] = reviewed_by
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE evolution_proposals SET status = :status"
                    + reviewer_fragment
                    + ", updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :id RETURNING " + _PROPOSAL_COLS
                ),
                params,
            )
            row = result.first()
            return _row_to_proposal(row) if row else None

    async def attach_monitor(self, proposal_id: str, monitor: dict) -> None:
        """Merge a monitor baseline into candidate（发布时差评基线）."""
        proposal = await self.get_proposal(proposal_id)
        if proposal is None:
            return
        candidate = dict(proposal.candidate or {})
        candidate["monitor"] = monitor
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE evolution_proposals SET "
                    "candidate = CAST(:candidate AS JSONB), "
                    "updated_at = now() WHERE tenant_id = :tid AND id = :id"
                ),
                {
                    "tid": current_tenant_id(),
                    "id": proposal_id,
                    "candidate": json.dumps(candidate),
                },
            )

    async def submit_for_review(
        self,
        proposal_id: str,
    ) -> Optional[EvolutionProposal]:
        """draft → ready_for_review（其余状态拒绝，防跳步）。"""
        current = await self.get_proposal(proposal_id)
        if current is None or current.status != PROPOSAL_STATUS_DRAFT:
            raise ValueError("only draft proposals can be submitted")
        return await self._transition(
            proposal_id,
            PROPOSAL_STATUS_READY_FOR_REVIEW,
        )

    async def review(
        self,
        proposal_id: str,
        action: str,
        reviewer: str,
    ) -> Optional[EvolutionProposal]:
        """ready_for_review → approved | rejected（高风控仍须管理员，
        RBAC 由路由层保证）。"""
        if action not in _REVIEW_ACTIONS:
            raise ValueError("action must be 'approve' or 'reject'")
        current = await self.get_proposal(proposal_id)
        if current is None or (current.status != PROPOSAL_STATUS_READY_FOR_REVIEW):
            raise ValueError("proposal is not under review")
        target = (
            PROPOSAL_STATUS_APPROVED
            if action == "approve"
            else PROPOSAL_STATUS_REJECTED
        )
        return await self._transition(
            proposal_id,
            target,
            reviewed_by=reviewer,
        )

    async def mark_published(self, proposal_id: str) -> None:
        """approved → published（发布动作由权威模块执行后回调）。"""
        current = await self.get_proposal(proposal_id)
        if current is None or current.status != PROPOSAL_STATUS_APPROVED:
            raise ValueError("only approved proposals can be published")
        await self._transition(proposal_id, PROPOSAL_STATUS_PUBLISHED)

    async def mark_rolled_back(self, proposal_id: str) -> None:
        """published → rolled_back（回滚留痕，不删历史）。"""
        current = await self.get_proposal(proposal_id)
        if current is None or current.status != PROPOSAL_STATUS_PUBLISHED:
            raise ValueError("only published proposals can be rolled back")
        await self._transition(proposal_id, PROPOSAL_STATUS_ROLLED_BACK)


_feedback_store: FeedbackStore | None = None
_evolution_store: EvolutionStore | None = None


def get_feedback_store() -> FeedbackStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _feedback_store  # pylint: disable=global-statement
    if _feedback_store is None:
        _feedback_store = FeedbackStore()
    return _feedback_store


def get_evolution_store() -> EvolutionStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _evolution_store  # pylint: disable=global-statement
    if _evolution_store is None:
        _evolution_store = EvolutionStore()
    return _evolution_store


# ---------------------------------------------------------------------------
# 差评自省归因（20260830 P2：反馈 → 演进提案的自动起草段）
# ---------------------------------------------------------------------------

#: 每专家每天自动起草的反馈提案上限（防差评风暴刷屏）
AUTO_PROPOSAL_DAILY_CAP = 3


def maybe_schedule_attribution(expert_id: str, rating: str) -> None:
    """差评触发的自省归因 + 自动回滚复检（fire-and-forget）。

    归因链路：专家反思 → 13 桶归因 + 候选起草（draft 态，人工审批）。
    同一触发点顺带复检已发布提案的差评率（自动回滚监控）。
    """
    if rating != "down":
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_attribute_downvote(expert_id))
        loop.create_task(check_auto_rollback(expert_id))
    except RuntimeError:
        # 无运行中事件循环（纯同步上下文/测试）：跳过归因
        return


async def _bound_sop_summaries(expert_id: str) -> List[Dict[str, Any]]:
    """Bound published SOPs of one expert（id/name/steps，供自省参照）."""
    try:
        from .capability import get_capability_store
        from .sops import get_sop_store

        cap_store = get_capability_store()
        sop_store = get_sop_store()
        summaries: List[Dict[str, Any]] = []
        for binding in await cap_store.list_bindings(
            expert_id,
            resource_type="sop",
        ):
            if not binding.enabled:
                continue
            sop = await sop_store.get_sop(binding.resource_id)
            if sop is None or sop.status != "published":
                continue
            summaries.append(
                {
                    "sop_id": sop.id,
                    "name": sop.name,
                    "goal": sop.goal,
                    "steps": [
                        {
                            "t": n.get("title", ""),
                            "ok": n.get("expected_outcome", ""),
                        }
                        for n in (sop.nodes or [])
                        if isinstance(n, dict)
                    ],
                },
            )
        return summaries
    except Exception:  # noqa: BLE001 - SOP 摘要失败不阻塞自省
        logger.debug("绑定 SOP 摘要加载失败", exc_info=True)
        return []


async def _attribute_downvote(expert_id: str) -> None:
    """One attribution run (runs in background; all failures silent)."""
    try:
        store = get_evolution_store()
        # 限流：今日该专家已自动起草的反馈提案数（内存过滤 trigger）
        todays = [
            p
            for p in await store.list_proposals(expert_id=expert_id)
            if p.trigger_type == "feedback"
            and (p.created_at or _utcnow()).date() == _utcnow().date()
        ]
        if len(todays) >= AUTO_PROPOSAL_DAILY_CAP:
            return
        expert = await get_expert_store().get_expert(expert_id)
        if expert is None:
            return
        # 证据：最近差评样本（含评论，最多 5 条）
        downs = [
            f
            for f in await get_feedback_store().recent_for_expert(
                expert_id,
                days=7,
                limit=10,
            )
            if f["rating"] == "down"
        ][:5]
        if not downs:
            return
        # 未发布的专家无运行时（call_expert_text 通道不可用）→ 放弃
        if expert.status != EXPERT_STATUS_PUBLISHED:
            return
        bound_sops = await _bound_sop_summaries(expert_id)
        suggestion = await _reflect_on_downvotes(expert, downs, bound_sops)
        bucket = str(suggestion.get("bucket") or "unknown")
        if bucket not in ATTRIBUTION_BUCKETS:
            bucket = "unknown"
        # 候选目标选择：SOP 相关桶 + 模型给出合法 SOP 变更 → SOP 候选；
        # 否则 system_prompt 候选；模型认为无需修改 → 仅证据草稿
        sop_change = (
            (suggestion.get("sop_change") or {}) if bucket in _SOP_BUCKETS else {}
        )
        sop_target = None
        if sop_change.get("sop_id") and isinstance(
            sop_change.get("nodes"),
            list,
        ):
            for sop in bound_sops:
                if sop["sop_id"] == sop_change["sop_id"]:
                    sop_target = sop
                    break
        if sop_target is not None:
            candidate: Dict[str, Any] = {
                "target": "sop",
                "sop_id": sop_target["sop_id"],
                "sop_name": sop_target["name"],
                "previous_nodes": sop_target["steps"],
                "new_nodes": sop_change["nodes"],
                "bucket": bucket,
                "auto": True,
            }
        elif str(suggestion.get("system_prompt") or "").strip():
            candidate = {
                "target": "system_prompt",
                "previous_value": expert.system_prompt,
                "new_value": str(suggestion.get("system_prompt") or ""),
                "bucket": bucket,
                "auto": True,
            }
        else:
            candidate = {
                "target": "none",
                "bucket": bucket,
                "auto": True,
            }
        await store.create_proposal(
            expert_id=expert_id,
            title=str(suggestion.get("title") or "差评自省改进提案")[:120],
            trigger_type="feedback",
            risk_level="medium",
            hypothesis=f"[{bucket}] " + str(suggestion.get("hypothesis") or "")[:480],
            evidence=[
                {
                    "message_id": f.get("message_id"),
                    "comment": f.get("comment"),
                    "created_at": str(f.get("created_at") or ""),
                }
                for f in downs
            ],
            candidate=candidate,
        )
    except Exception:  # noqa: BLE001 - 归因失败静默（采集面已留痕）
        logger.debug("差评自省归因失败（静默）", exc_info=True)


async def _reflect_on_downvotes(
    expert: Any,
    downs: List[Dict[str, Any]],
    bound_sops: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """让专家本人对差评做一次结构化自省（LLM 通道，P2 升级版）。

    输出：归因桶（ATTRIBUTION_BUCKETS 之一）+ 人设修订候选 + 可选的
    绑定 SOP 节点变更候选。通道异常向上抛由调用方静默——绝不阻塞
    评分主链路。
    """
    from ..workforce.delegator import call_expert_text
    from .models import expert_agent_id

    samples = "\n".join(
        f"- 评分 👎 · 用户备注：{f.get('comment') or '（无备注）'}" for f in downs
    )
    sop_block = ""
    if bound_sops:
        lines = []
        for sop in bound_sops:
            steps = "；".join(
                f"{i}.{s.get('t', '')}"
                for i, s in enumerate(sop.get("steps") or [], start=1)
            )
            lines.append(f"- sop_id={sop['sop_id']}《{sop['name']}》：{steps}")
        sop_block = (
            "\n你绑定了以下 SOP（差评若与流程相关，可提出节点级修订）：\n"
            + "\n".join(lines)
            + "\n"
        )
    prompt = (
        "# 数字员工自省（你正在反思自己的差评）\n\n"
        f"你是数字员工「{expert.name}」。以下是最近收到的差评：\n"
        f"{samples}\n{sop_block}\n"
        "请以改进你自己为唯一目标，先归因（bucket 从下列枚举中选一个：\n"
        f"{', '.join(ATTRIBUTION_BUCKETS)}），\n"
        "再输出一个 ```json 代码块：\n"
        "```json\n"
        "{\n"
        '  "bucket": "归因桶（见上枚举）",\n'
        '  "title": "改进提案标题（一句话）",\n'
        '  "hypothesis": "改进假设：为什么这个变更能解决上述差评",\n'
        '  "system_prompt": "修订后的完整领域人设提示词（无需修改则空串）",\n'
        '  "sop_change": {"sop_id": "需修订的 SOP id（无需则省略）", '
        '"nodes": [{"id":"n1","title":"…","instruction":"…",'
        '"expected_outcome":"…"}]}\n'
        "}\n"
        "```\n"
        "纪律：只输出一个 JSON 代码块；system_prompt 必须是可直接替换"
        "使用的完整提示词；sop_change.nodes 必须是修订后的完整节点数组。"
    )
    reply, _session, _tokens = await call_expert_text(
        expert_agent_id(expert.id),
        prompt,
        session_id=None,
    )
    match = _JSON_FENCE_RE.search(reply) or _BARE_JSON_RE.search(reply)
    if match is None:
        return {}
    data = json.loads(match.group(1))
    sop_change = data.get("sop_change")
    return {
        "bucket": str(data.get("bucket") or ""),
        "title": str(data.get("title") or ""),
        "hypothesis": str(data.get("hypothesis") or ""),
        "system_prompt": str(data.get("system_prompt") or ""),
        "sop_change": sop_change if isinstance(sop_change, dict) else {},
    }


# ---------------------------------------------------------------------------
# 发布后自动回滚监控（20260830 P2 剩余：差评率恶化 → 自动回滚）
# ---------------------------------------------------------------------------


async def attach_publish_baseline(store, proposal_id: str) -> None:
    """提案发布时记录差评基线（candidate.monitor，供回滚判定）。"""
    proposal = await store.get_proposal(proposal_id)
    if proposal is None:
        return
    summary = await get_feedback_store().summary(proposal.expert_id, days=30)
    await store.attach_monitor(
        proposal_id,
        {
            "at": _utcnow().isoformat(),
            "up": summary["feedback_up"],
            "down": summary["feedback_down"],
            "positive_rate": summary["positive_rate"],
        },
    )


async def check_auto_rollback(expert_id: str) -> None:
    """复检该专家已发布（自动）提案的差评率；显著恶化则自动回滚。

    判定（三重门槛防误伤）：候选带 monitor 基线；发布满
    ``AUTO_ROLLBACK_MIN_HOURS``；窗口内新增评分 ≥
    ``AUTO_ROLLBACK_MIN_NEW_RATINGS`` 且好评率较基线跌幅 ≥
    ``AUTO_ROLLBACK_RATE_DROP``。回滚经既有权威路径（system_prompt
    恢复 + 重发布 / SOP 版本链恢复）并留痕 rolled_back。
    """
    try:
        store = get_evolution_store()
        published = [
            p
            for p in await store.list_proposals(expert_id=expert_id)
            if p.status == PROPOSAL_STATUS_PUBLISHED
            and (p.candidate or {}).get("auto")
            and isinstance((p.candidate or {}).get("monitor"), dict)
        ]
        if not published:
            return
        now = _utcnow()
        summary = await get_feedback_store().summary(expert_id, days=30)
        for proposal in published:
            candidate = proposal.candidate or {}
            monitor = candidate.get("monitor") or {}
            reviewed_at = proposal.reviewed_at or proposal.updated_at
            if reviewed_at is None:
                continue
            age_hours = (now - reviewed_at).total_seconds() / 3600
            if age_hours < AUTO_ROLLBACK_MIN_HOURS:
                continue
            base_total = int(monitor.get("up", 0)) + int(monitor.get("down", 0))
            new_total = summary["total"] - base_total
            if new_total < AUTO_ROLLBACK_MIN_NEW_RATINGS:
                continue
            base_rate = monitor.get("positive_rate")
            if base_rate is None or summary["positive_rate"] is None:
                continue
            if base_rate - summary["positive_rate"] < AUTO_ROLLBACK_RATE_DROP:
                continue
            # 触发自动回滚（走权威恢复路径，留痕）
            await _rollback_candidate(proposal)
            logger.warning(
                "auto-rollback triggered: proposal=%s expert=%s "
                "base_rate=%s now=%s new_ratings=%s",
                proposal.id,
                expert_id,
                base_rate,
                summary["positive_rate"],
                new_total,
            )
            return
    except Exception:  # noqa: BLE001 - 监控失败静默（不影响评分链路）
        logger.debug("自动回滚复检失败（静默）", exc_info=True)


async def _rollback_candidate(proposal: EvolutionProposal) -> None:
    """Restore one published proposal's candidate via authority modules."""
    from .sops import get_sop_store

    store = get_evolution_store()
    candidate = proposal.candidate or {}
    target = candidate.get("target")
    if target == "system_prompt":
        record = await get_expert_store().update_expert(
            proposal.expert_id,
            system_prompt=str(candidate.get("previous_value") or ""),
        )
        if record is not None and record.status == EXPERT_STATUS_PUBLISHED:
            from .publish import publish_expert

            await publish_expert(
                proposal.expert_id,
                published_by="auto-rollback",
            )
    elif target == "sop":
        sop_id = str(candidate.get("sop_id") or "")
        previous_nodes = candidate.get("previous_nodes")
        if sop_id and isinstance(previous_nodes, list):
            # 恢复节点为基线形态（发布为新版本，版本链留痕）
            nodes = [
                {
                    "id": f"n{i}",
                    "title": str(step.get("t") or ""),
                    "expected_outcome": str(step.get("ok") or ""),
                }
                for i, step in enumerate(previous_nodes, start=1)
            ]
            await get_sop_store().publish_new_version(
                sop_id,
                nodes=nodes,
                change_note=f"auto-rollback proposal {proposal.id}",
                published_by="auto-rollback",
            )
    await store.mark_rolled_back(proposal.id)


async def attribution_heatmap(
    days: int = 30,
    expert_id: str = "",
) -> Dict[str, Any]:
    """差评归因热力数据（设计文档 §九 缺口③的消费面）。

    数据源：窗口内 ``evolution_proposals``（LLM 自省归因的产出物，
    ``candidate.bucket`` 为权威桶位；hypothesis 前缀 ``[bucket]`` 为
    冗余投影不作依据）。单表一次批量查询 + 内存聚合（五步范式，
    禁止 N+1）：

    - ``matrix[bucket][date]``：桶 × 日期计数矩阵（空洞日期补零）；
    - ``totals[bucket]``：窗口内桶总量（供排行与最热桶）；
    - ``top_experts``：按归因量倒序 top5（一次 IN 批量取名投影）。

    日期统一 UTC 日历日（YYYY-MM-DD），与提案 created_at 的
    TIMESTAMPTZ 无时区歧义。
    """
    from datetime import datetime, timedelta, timezone

    window_days = max(1, min(int(days), 90))
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    clauses = ["tenant_id = :tid", "created_at >= :since"]
    params: Dict[str, Any] = {
        "tid": current_tenant_id(),
        "since": since,
    }
    if expert_id:
        clauses.append("expert_id = :eid")
        params["eid"] = expert_id

    engine = require_enterprise_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT created_at, expert_id, candidate FROM "
                "evolution_proposals WHERE "
                + " AND ".join(clauses)
            ),
            params,
        )
        rows = result.all()

    # ---- 内存聚合：桶 × 日期矩阵 + 桶总量 + 员工归因计数 ----
    matrix: Dict[str, Dict[str, int]] = {
        bucket: {} for bucket in ATTRIBUTION_BUCKETS
    }
    expert_counts: Dict[str, int] = {}
    total = 0
    for row in rows:
        candidate = row.candidate if isinstance(row.candidate, dict) else {}
        bucket = str(candidate.get("bucket") or "unknown")
        if bucket not in ATTRIBUTION_BUCKETS:
            bucket = "unknown"
        created_at = row.created_at
        if hasattr(created_at, "astimezone"):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            day = created_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        else:
            day = str(created_at or "")[:10]
        bucket_days = matrix[bucket]
        bucket_days[day] = bucket_days.get(day, 0) + 1
        expert_counts[row.expert_id] = expert_counts.get(row.expert_id, 0) + 1
        total += 1

    # 窗口日期序列（升序，空洞补零由前端/消费方按 dates 基准取 0）
    dates = [
        (since + timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(window_days)
    ]

    # top5 员工：一次 IN 批量取名（禁止逐条查询的 N+1）
    top_ids = [
        eid
        for eid, _count in sorted(
            expert_counts.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )[:5]
    ]
    names: Dict[str, str] = {}
    if top_ids:
        async with engine.connect() as conn:
            name_rows = await conn.execute(
                text(
                    "SELECT id, name FROM experts WHERE tenant_id = :tid "
                    "AND id = ANY(:ids)"
                ),
                {
                    "tid": current_tenant_id(),
                    "ids": list(top_ids),
                },
            )
            names = {r.id: (r.name or r.id) for r in name_rows}
    top_experts = [
        {
            "expert_id": eid,
            "name": names.get(eid, eid),
            "count": expert_counts[eid],
        }
        for eid in top_ids
    ]

    totals = {
        bucket: sum(counts.values())
        for bucket, counts in matrix.items()
    }
    return {
        "days": window_days,
        "buckets": list(ATTRIBUTION_BUCKETS),
        "dates": dates,
        "matrix": matrix,
        "totals": totals,
        "top_experts": top_experts,
        "total": total,
    }


def _utcnow():
    """Current UTC time (helper kept for readability)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
