# -*- coding: utf-8 -*-
"""T0 兼容接缝修复的回归测试（无 PG 纯单元）。

覆盖五个接缝中可纯函数验证的三项：

1. 规划回执：``call_expert_text`` 三元组解包 + token 归集（含重试轮
   累计——首轮失败消耗不能凭空消失）；
2. runtime_enabled 统一门：无模板节点时显式关闭编排同样拒绝 LLM 规划；
3. PlanOutcome 用量语义：规划通道必然采集（usage_reported=True）。

成员角色往返 / 改派命中实际目标 / 终态取消保护依赖 PG，见
``tests/integration/test_workforce_runs.py`` 的 T0 段（无 DSN 跳过）。

@author qingfeng
"""

from __future__ import annotations

import json

import pytest

from qwenpaw.app.experts.models import (
    EXPERT_STATUS_PUBLISHED,
    ExpertRecord,
    ExpertTeamRecord,
    TeamMember,
)
from qwenpaw.app.workforce import planner as planner_mod
from qwenpaw.app.workforce.contracts import OrchestrationSpec


def _team(orchestration: dict | None = None) -> ExpertTeamRecord:
    """一个已发布团队（lead 成员一名）。"""
    return ExpertTeamRecord(
        id="team-1",
        name="研发团",
        status=EXPERT_STATUS_PUBLISHED,
        members=[
            TeamMember(expert_id="lead-1", member_role="lead", seq=0),
        ],
        orchestration=orchestration or {},
    )


def _lead() -> ExpertRecord:
    """lead 成员专家（agent_spec 含最小配置）。"""
    return ExpertRecord(id="lead-1", name="主管")


def _plan_reply() -> str:
    """合法规划回执（固定输入：一个任务节点 + final）。"""
    payload = {
        "need_clarification": False,
        "nodes": [
            {
                "node_key": "impl",
                "deps": [],
                "assignee_expert_id": "lead-1",
                "node_type": "task",
                "objective": "实现功能",
                "expected_output": ["代码"],
            },
            {
                "node_key": "final",
                "deps": ["impl"],
                "node_type": "final",
                "objective": "汇总",
            },
        ],
        "plan_note": "先实现后汇总",
    }
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


@pytest.fixture
def fake_channel(monkeypatch):
    """替身 A2A 通道：记录调用并按脚本返回三元组。"""
    calls: list[dict] = []

    async def fake_call(
        to_agent,
        prompt,
        session_id=None,
        timeout=900.0,
        from_agent="workforce",
    ):
        # 记录调用（供断言调用次数与目标）
        calls.append({"to_agent": to_agent, "prompt": prompt[:40]})
        # 回执具名三元组：(文本, session, tokens)
        return _plan_reply(), "sess-plan-1", 321

    monkeypatch.setattr(
        "qwenpaw.app.workforce.delegator.call_expert_text",
        fake_call,
    )
    return calls


async def test_plan_llm_collects_token_usage(fake_channel):
    """LLM 规划归集 token 消耗（三元组解包，不再丢弃 usage）。"""
    outcome = await planner_mod.plan_run(
        "做一个登录页",
        _team(),
        [_lead()],
        planner_mod.ContextBundle(),
    )
    assert outcome.error == ""
    assert outcome.plan is not None
    # 规划消耗进入结果（run 级预算依据）
    assert outcome.token_cost == 321
    assert outcome.usage_reported is True
    assert len(fake_channel) == 1


async def test_plan_retry_accumulates_tokens(monkeypatch):
    """首轮校验失败 → 重试成功：两轮消耗累计（321 + 123）。"""
    round_no = {"n": 0}

    async def fake_call(
        to_agent,
        prompt,
        session_id=None,
        timeout=900.0,
        from_agent="workforce",
    ):
        round_no["n"] += 1
        if round_no["n"] == 1:
            # 首轮返回非法 DAG（deps 引用不存在节点）触发定向重试
            bad = {
                "need_clarification": False,
                "nodes": [
                    {
                        "node_key": "a",
                        "deps": ["ghost"],
                        "node_type": "task",
                        "objective": "x",
                    },
                ],
                "plan_note": "",
            }
            return (
                "```json\n" + json.dumps(bad, ensure_ascii=False) + "\n```",
                "sess-1",
                321,
            )
        return _plan_reply(), "sess-2", 123

    monkeypatch.setattr(
        "qwenpaw.app.workforce.delegator.call_expert_text",
        fake_call,
    )
    outcome = await planner_mod.plan_run(
        "做一个登录页",
        _team(),
        [_lead()],
        planner_mod.ContextBundle(),
    )
    assert outcome.error == ""
    assert outcome.plan is not None
    # 失败重试也是真实消耗：首轮 321 不能凭空消失
    assert outcome.token_cost == 321 + 123
    assert round_no["n"] == 2


async def test_runtime_enabled_gate_blocks_llm_path_too():
    """无模板节点且 runtime_enabled=false：同样拒绝动态 LLM 规划。"""
    outcome = await planner_mod.plan_run(
        "做一个登录页",
        _team(orchestration={"runtime_enabled": False}),
        [_lead()],
        planner_mod.ContextBundle(),
    )
    # 统一门：错误信息与模板路径一致，且未发起任何模型调用
    assert "runtime_enabled=false" in outcome.error
    assert outcome.plan is None


async def test_runtime_enabled_gate_allows_template_path(fake_channel):
    """开关开启且模板节点存在：模板路径照常（回归不破坏）。"""
    spec = OrchestrationSpec(
        nodes=[
            {
                "node_key": "impl",
                "deps": [],
                "assignee_expert_id": "lead-1",
                "node_type": "task",
                "objective": "实现功能",
            },
        ],
        plan_note="模板链",
    )
    outcome = await planner_mod.plan_run(
        "做一个登录页",
        _team(orchestration=spec.model_dump()),
        [_lead()],
        planner_mod.ContextBundle(),
    )
    assert outcome.error == ""
    assert outcome.source == "orchestration"
    # 模板路径不调 LLM（规划消耗为 0 且明示已采集）
    assert fake_channel == []
    assert outcome.token_cost == 0
    assert outcome.usage_reported is True
