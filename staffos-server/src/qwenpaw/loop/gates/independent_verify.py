# -*- coding: utf-8 -*-
"""Independent verification gate for the single-employee ReAct loop.

数字员工 PROFILE.md 承诺的「核验」此前只存在于提示词文本：自评门
（``CompletionRubricGate``）让**同一个** agent 自己宣布 COMPLETED，
`SubAgentRubric` 则是返回 GRADER_ERROR 的占位实现。本门把 L1 专家团已
验证过的验收闭环下沉到 L2：产出 → **独立模型裁决** → 结构化返工 → 超限
熔断提示用户，裁决规则完全复用 :mod:`qwenpaw.verification`（单一来源）。

成本控制（按任务复杂度自动分级）：只有规则判定为复杂任务（多交付物 /
跨专业 / 编排语义）的 turn 才会启用验收，闲聊与单步问答零额外调用；
裁决通道异常一律放行，绝不因验收器故障卡死聊天。

@author qingfeng
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ...constant import (
    QWENPAW_MESSAGE_TAG_KEY,
    VERIFY_REPAIR_MESSAGE_TAG,
)
from .base import StopAction, StopHandlerResult
from .loop_gate import LoopGate

logger = logging.getLogger(__name__)

#: L2 没有节点级契约，验收基线只有一条硬要求，其余由裁决器从原文推导
_BASELINE_CRITERION = "产出完整覆盖用户在本轮请求中提出的全部显式要求"

#: 熔断放行时追加给用户的提示段前缀（缺口可见，不静默通过）
_ESCALATION_NOTICE_HEAD = "\n\n---\n⚠️ 独立验收未通过（已达返工上限，转人工判断）"


@dataclass
class _VerifyState:
    """Per-turn verification state (keyed by session)."""

    #: 本轮用户请求原文（同时充当 turn 身份：文本变化即新 turn）
    objective: str = ""

    #: 本 turn 是否参与独立验收（复杂度分级结果）
    armed: bool = False

    #: 已发生的返工轮次
    repairs: int = 0

    #: 最近一次已裁决的候选消息 id（防同一产出被重复裁决）
    judged_message_id: str = ""

    #: 待注入的返工指令（build_continuation 消费）
    pending_repair: Any = None

    #: 最近一次裁决结果（观测与提示文案复用）
    last_verdict: Any = None

    #: 已追加过熔断提示（防重复污染同一条消息）
    notice_appended: bool = field(default=False)


class IndependentVerifierGate(LoopGate):
    """Grade the final draft with an independent model before stopping.

    Runs last among quality gates so budget/iteration limits win first.
    Only triggers on text-only responses (the agent is about to stop) and
    only for turns the complexity rules classify as ``complex``.
    """

    def __init__(
        self,
        *,
        max_repairs: int = 1,
        timeout_seconds: int = 60,
        min_objective_chars: int = 24,
        escalate_notice: bool = True,
    ) -> None:
        super().__init__()
        self._max_repairs = max_repairs
        self._timeout_seconds = timeout_seconds
        self._min_objective_chars = min_objective_chars
        self._escalate_notice = escalate_notice

    @property
    def name(self) -> str:
        return "independent-verify"

    @property
    def priority(self) -> int:
        # 预算/迭代/重复保护类门先行拦截，质量类自评门（90）之后再独立裁决
        return 95

    def reset_turn(self) -> None:
        """Start a fresh verification cycle for the new user turn.

        Counter reset is driven by ``check()`` comparing the objective,
        because ``reset_turn`` receives no context; here only the pending
        repair is dropped so a peer-triggered sub-turn cannot reuse it.
        """
        state: Optional[_VerifyState] = self._state()
        if state is not None:
            state.pending_repair = None

    async def check(self, ctx: Any) -> StopHandlerResult:
        """Adjudicate the draft with an independent verification call."""
        bypass = StopHandlerResult(action=StopAction.BYPASS)
        # 工具调用轮不裁决；没有候选产出也无从裁决
        if isinstance(ctx, dict) and ctx.get("has_tool_calls"):
            return bypass
        final_msg = ctx.get("final_msg") if isinstance(ctx, dict) else None
        if final_msg is None:
            return bypass
        agent = ctx.get("agent") if isinstance(ctx, dict) else None
        objective = self._current_objective(agent)
        # 取不到本轮用户请求（如后台任务/心跳触发）时不参与验收
        if not objective:
            return bypass
        state = self._state_for_turn(objective)
        if not state.armed:
            return bypass
        # 同一候选产出只裁决一次（返工注入后才会出现新候选）
        candidate_id = str(getattr(final_msg, "id", "") or "")
        if candidate_id and candidate_id == state.judged_message_id:
            return bypass
        state.judged_message_id = candidate_id
        state.pending_repair = None
        try:
            # 独立通道裁决（异常在 judge 内收敛为 ESCALATE，不外抛）
            verdict = await self._judge(objective, final_msg, agent, state)
        except Exception:  # pylint: disable=broad-except
            logger.warning("independent verification failed", exc_info=True)
            return bypass
        state.last_verdict = verdict
        return self._dispatch(verdict, state, final_msg)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _current_objective(self, agent: Any) -> str:
        """Return this turn's real user request, or empty when unavailable."""
        if agent is None:
            return ""
        from ...utils.message_tags import latest_external_user_text

        context = getattr(getattr(agent, "state", None), "context", None) or []
        try:
            text = latest_external_user_text(context)
        except Exception:  # pylint: disable=broad-except
            logger.debug("objective extraction failed", exc_info=True)
            return ""
        return text.strip()

    def _state_for_turn(self, objective: str) -> _VerifyState:
        """Return state for the current turn, re-grading complexity on change.

        The objective text is the turn identity: a new user request resets the
        repair budget, while injected continuations keep the same objective.
        """
        state: Optional[_VerifyState] = self._state()
        if state is not None and state.objective == objective:
            return state
        # 新 turn：按复杂度规则重新分级，预算从零开始
        fresh = _VerifyState(
            objective=objective,
            armed=self._is_complex(objective),
        )
        self.activate(fresh)
        logger.debug(
            "independent verify armed=%s (objective_chars=%d)",
            fresh.armed,
            len(objective),
        )
        return fresh

    def _is_complex(self, objective: str) -> bool:
        """Grade the request with the workforce rule classifier (zero cost)."""
        # 短请求不可能是多交付物任务，直接不启用验收（保护追问零成本）
        if len(objective) < self._min_objective_chars:
            return False
        from ...app.workforce.intent import INTENT_COMPLEX, classify_by_rules

        ruled = classify_by_rules(objective)
        return ruled is not None and ruled.intent == INTENT_COMPLEX

    async def _judge(
        self,
        objective: str,
        final_msg: Any,
        agent: Any,
        state: _VerifyState,
    ) -> Any:
        """Render the judge prompt, call the independent channel, log span."""
        from ...verification.judge import judge
        from ...verification.kernel import JudgeRequest, render_judge_prompt
        from ...utils.message_tags import message_text

        request = JudgeRequest(
            objective=objective,
            criteria=[_BASELINE_CRITERION],
            output_text=message_text(final_msg),
            previous_acceptance=list(
                state.last_verdict.repair.acceptance
                if state.last_verdict is not None
                and state.last_verdict.repair is not None
                else [],
            ),
            # 无节点契约：显式要求清单由裁决器从用户原文推导
            derive_requirements=True,
        )
        prompt = render_judge_prompt(request)
        started_wall = time.time()
        started_perf = time.perf_counter()
        verdict = await judge(
            prompt,
            task_id="turn",
            attempt=state.repairs + 1,
            acceptance=[_BASELINE_CRITERION],
            agent_id=self._agent_id(agent),
            agent_config=getattr(agent, "_agent_config", None),
            model_slot=getattr(
                getattr(agent, "_agent_config", None),
                "verifier_model",
                None,
            ),
            timeout=float(self._timeout_seconds),
        )
        self._emit_span(
            verdict,
            started_wall=started_wall,
            duration_ms=int((time.perf_counter() - started_perf) * 1000),
            attempt=state.repairs + 1,
        )
        return verdict

    @staticmethod
    def _agent_id(agent: Any) -> str:
        """Resolve the agent identity for the verification model channel."""
        request_context = getattr(agent, "_request_context", None) or {}
        agent_id = request_context.get("agent_id") if isinstance(
            request_context,
            dict,
        ) else None
        if agent_id:
            return str(agent_id)
        config = getattr(agent, "_agent_config", None)
        return str(getattr(config, "id", "") or "")

    def _emit_span(
        self,
        verdict: Any,
        *,
        started_wall: float,
        duration_ms: int,
        attempt: int,
    ) -> None:
        """Record the verification as a ``verify`` span (never raises)."""
        try:
            from ...observability.span_sink import get_span_sink

            repair = getattr(verdict, "repair", None)
            get_span_sink().emit_span(
                kind="verify",
                name="independent_verify",
                started_at=started_wall,
                ended_at=time.time(),
                duration_override_ms=duration_ms,
                input={"attempt": attempt},
                output={
                    "verdict": getattr(verdict, "verdict", ""),
                    "reason": getattr(verdict, "reason", ""),
                    "failure_kind": getattr(verdict, "failure_kind", ""),
                    "issues": list(getattr(repair, "issues", []) or []),
                },
            )
        except Exception:  # pylint: disable=broad-except
            logger.debug("verify span emit failed", exc_info=True)

    def _dispatch(
        self,
        verdict: Any,
        state: _VerifyState,
        final_msg: Any,
    ) -> StopHandlerResult:
        """Turn one verdict into a gate decision."""
        from ...verification.kernel import (
            FAILURE_KIND_REPAIRABLE,
            VERDICT_FAIL,
            VERDICT_PASS,
        )

        verdict_value = getattr(verdict, "verdict", "")
        # 裁决通过：正常收尾（reason 留痕，产出原样返回）
        if verdict_value == VERDICT_PASS:
            state.pending_repair = None
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="独立验收通过",
            )
        # 非 FAIL（含无法裁决 ESCALATE）：验收器故障不得阻塞聊天，直接放行
        if verdict_value != VERDICT_FAIL:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"独立验收无法裁决，放行：{getattr(verdict, 'reason', '')}",
            )
        repair = getattr(verdict, "repair", None)
        failure_kind = getattr(verdict, "failure_kind", "")
        # 结构性失败（能力/工具/权限缺失）：返工无意义，直接熔断到用户
        if failure_kind != FAILURE_KIND_REPAIRABLE or repair is None:
            return self._escalate(
                final_msg,
                reason=getattr(verdict, "reason", "") or "验收判定为结构性缺陷",
                issues=list(getattr(repair, "issues", []) or []),
            )
        # 返工预算已用尽：熔断提示人工，绝不静默放行
        if state.repairs >= self._max_repairs:
            return self._escalate(
                final_msg,
                reason=f"已达返工上限（{state.repairs}/{self._max_repairs}）",
                issues=list(getattr(repair, "issues", []) or []),
            )
        # 可返工缺陷：注入结构化返工指令（问题/期望修改/保留项/复验标准）
        state.repairs += 1
        state.pending_repair = repair
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="独立验收未通过，按返工指令修正",
            reset_peers=True,
            # 返工指令是合成消息：必须打专属 tag 并保持子轮预算可追
            continuation_metadata={
                QWENPAW_MESSAGE_TAG_KEY: VERIFY_REPAIR_MESSAGE_TAG,
            },
        )

    def build_continuation(self) -> str:
        """Return the structured repair instruction for the next attempt."""
        from ...verification.kernel import render_repair_prompt

        state: Optional[_VerifyState] = self._state()
        if state is None or state.pending_repair is None:
            return ""
        return render_repair_prompt(state.pending_repair)

    def _escalate(
        self,
        final_msg: Any,
        *,
        reason: str,
        issues: list[str],
    ) -> StopHandlerResult:
        """Stop and surface unmet requirements instead of a silent pass."""
        state: Optional[_VerifyState] = self._state()
        if state is not None:
            state.pending_repair = None
            self.deactivate()
        if self._escalate_notice:
            self._append_notice(final_msg, reason=reason, issues=issues)
        return StopHandlerResult(
            action=StopAction.TERMINATE,
            reason=f"独立验收熔断：{reason}",
        )

    @staticmethod
    def _append_notice(
        message: Any,
        *,
        reason: str,
        issues: list[str],
    ) -> None:
        """Append the verification gap notice to the candidate message."""
        try:
            from agentscope.message import TextBlock

            lines = [f"（{reason}）"]
            lines.extend(f"- 未达成：{issue}" for issue in issues)
            content = getattr(message, "content", None)
            if isinstance(content, list):
                content.append(
                    TextBlock(
                        type="text",
                        text=_ESCALATION_NOTICE_HEAD + "\n",
                    ),
                )
                content.append(
                    TextBlock(
                        type="text",
                        text="\n".join(lines),
                    ),
                )
            elif isinstance(content, str):
                message.content = (
                    content
                    + _ESCALATION_NOTICE_HEAD
                    + "\n"
                    + "\n".join(lines)
                )
        except Exception:  # pylint: disable=broad-except
            logger.debug("escalation notice append failed", exc_info=True)


__all__ = ["IndependentVerifierGate"]
