# -*- coding: utf-8 -*-
"""Unit tests: 绑定 SOP/工具 → TaskContract / 委派 prompt 的接线（P1）。

纯函数测试（无 PG / 无事件循环）：member_caps 经 bundle.global_ctx
注入后，契约应产出 sop_refs、合并工具清单、把 SOP 验收要点并入
quality_criteria；委派 prompt 应渲染 SOP 参考段且不泄露全团队快照。
"""

from __future__ import annotations

from qwenpaw.app.experts.models import ExpertRecord
from qwenpaw.app.workforce.bundle import ContextBundle
from qwenpaw.app.workforce.contracts import DagNode
from qwenpaw.app.workforce.delegator import render_task_prompt
from qwenpaw.app.workforce.planner import build_task_contract


def _expert(tool_enabled: bool = True) -> ExpertRecord:
    """One member expert with a builtin tool enabled in its spec."""
    return ExpertRecord(
        id="captest_member",
        name="测试员",
        agent_spec={
            "tools": {"builtin_tools": {"web_search": {"enabled": tool_enabled}}},
        },
    )


def _bundle_with_caps() -> ContextBundle:
    """Bundle whose global_ctx carries the member capability snapshot."""
    bundle = ContextBundle()
    bundle.global_ctx = {
        "member_caps": {
            "captest_member": {
                "tools": ["http_get", "web_search"],
                "sops": [
                    {
                        "name": "合同审查",
                        "goal": "输出合规审查意见",
                        "steps": [
                            {"t": "收集合同文本", "ok": "文本齐备可解析"},
                            {"t": "条款风险识别", "ok": "逐条列出风险等级"},
                        ],
                    },
                ],
                "kb_ids": ["kb_main"],
            },
        },
    }
    return bundle


def _node() -> DagNode:
    return DagNode(
        node_key="n1",
        node_type="task",
        objective="审查一份采购合同",
        expected_output=["审查意见"],
        deps=[],
        assignee_expert_id="captest_member",
    )


def test_contract_merges_tools_and_sop_refs():
    contract = build_task_contract(_node(), _expert(), _bundle_with_caps())
    # 工具清单 = agent_spec 内置 ∪ 绑定挂载（去重排序）
    assert contract.available_tools == ["http_get", "web_search"]
    # 绑定 SOP 进入契约
    assert len(contract.sop_refs) == 1
    assert contract.sop_refs[0]["name"] == "合同审查"
    # SOP 验收要点并入验收标准（默认 2 条 + SOP 2 条）
    joined = "\n".join(contract.quality_criteria)
    assert "收集合同文本" in joined
    assert "文本齐备可解析" in joined


def test_contract_without_caps_stays_clean():
    """无能力快照（旧数据/降级）时契约保持原语义（不空转注入）。"""
    contract = build_task_contract(_node(), _expert(), ContextBundle())
    assert contract.sop_refs == []
    assert contract.available_tools == ["web_search"]
    assert len(contract.quality_criteria) == 2


def test_prompt_renders_sop_section_without_team_snapshot_leak():
    contract = build_task_contract(_node(), _expert(), _bundle_with_caps())
    prompt = render_task_prompt(contract)
    # SOP 参考段渲染（含非硬状态机语义）
    assert "参考流程" in prompt
    assert "合同审查" in prompt
    assert "文本齐备可解析" in prompt
    assert "非硬性状态机" in prompt
    # 最小充分上下文：全团队能力快照不泄露给单个成员
    assert "member_caps" not in prompt
    assert "kb_main" not in prompt
