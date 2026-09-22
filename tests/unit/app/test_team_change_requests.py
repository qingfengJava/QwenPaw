# -*- coding: utf-8 -*-
"""专家团审查修复的回归测试（纯单元，无 PG）。

覆盖：

- P0-1：发布提案 CAS（基准漂移拒绝发布，批准绑定摘要）；
- P1-3：reject 条件更新（并发确认/拒绝仅一方生效）；
- P1-4：applying 卡死回收机制存在性（SQL 含中断恢复子句）；
- P1-1：终态 run 迟到批准拒绝（终态不可覆写）；
- P1-2：预算原子预留失败路径（Store 返回 None → 熔断升级）；
- metadata 提案状态枚举与状态机对齐（前端唯一文案来源）。

@author qingfeng
"""

from __future__ import annotations

import inspect

import pytest

from qwenpaw.app.experts import team_changes
from qwenpaw.app.experts.team_changes import (
    KIND_PUBLISH,
    STATUS_APPLYING,
    STATUS_PENDING,
    TERMINAL_STATUSES,
    _apply_publish,
    reject_change_request,
)
from qwenpaw.app.experts.team_service import (
    CHANGE_REQUEST_STATUSES,
    compute_member_upgrades,
)
from qwenpaw.app.workforce import service as workforce_service
from qwenpaw.app.workforce.budget import reserve_node_budget
from qwenpaw.app.workforce.contracts import (
    HumanDecision,
    RUN_TERMINAL_STATUSES,
    RunPolicy,
)
from qwenpaw.app.workforce.service import DecisionConflict


# ---------------------------------------------------------------------------
# P0-1 发布提案 CAS
# ---------------------------------------------------------------------------


class _FakeStore:
    """最小团队存储替身（get_team 返回预设记录）。"""

    def __init__(self, draft_revision: int):
        self._draft_revision = draft_revision

    async def get_team(self, team_id: str):
        return type(
            "Team",
            (),
            {"draft_revision": self._draft_revision},
        )()


@pytest.mark.asyncio
async def test_apply_publish_rejects_when_draft_drifted(monkeypatch):
    """P0 安全门：确认前草稿被修改（draft_revision 递增）→ 拒绝发布。

    用户确认的是提案展示时的基准草稿；放行漂移后的新内容等于绕过
    用户确认（批准必须绑定摘要）。
    """
    monkeypatch.setattr(
        team_changes, "get_expert_store", lambda: _FakeStore(draft_revision=8),
    )
    # 基准 #5 ≠ 当前 #8：不得触发发布链
    published = {"called": False}

    async def _fail_publish(*args, **kwargs):
        published["called"] = True
        raise AssertionError("基准漂移时不应调用发布链")

    monkeypatch.setattr(
        "qwenpaw.app.experts.publish.publish_expert_team", _fail_publish,
    )
    result = await _apply_publish(
        team_id="team-1", base_revision=5,
    )
    assert result["ok"] is False
    assert "CAS 冲突" in result["error"]
    assert "#5" in result["error"] and "#8" in result["error"]
    assert published["called"] is False


@pytest.mark.asyncio
async def test_apply_publish_proceeds_when_baseline_matches(monkeypatch):
    """基准一致（#7 == #7）→ 正常进入发布链并返回发布版本号。"""
    monkeypatch.setattr(
        team_changes, "get_expert_store", lambda: _FakeStore(draft_revision=7),
    )

    async def _fake_publish(team_id, published_by=""):
        return type("Record", (), {"version": 3})()

    monkeypatch.setattr(
        "qwenpaw.app.experts.publish.publish_expert_team", _fake_publish,
    )
    result = await _apply_publish(
        team_id="team-1", base_revision=7,
    )
    assert result["ok"] is True
    assert result["published_version"] == 3


@pytest.mark.asyncio
async def test_reject_uses_conditional_update_and_reports_race(monkeypatch):
    """P1-3：reject 用条件更新（pending → rejected），竞态失败时
    返回"已被并发操作处理"，不覆写已 applied 的提案。"""

    async def fake_get_change_request(request_id: str):
        return {
            "request_id": request_id,
            "team_id": "team-1",
            "operator_id": "alice",
            "status": STATUS_PENDING,
        }

    captured: dict = {}

    async def fake_update_status(
        request_id, status, error_message="", expected_status="",
    ):
        captured["expected_status"] = expected_status
        # 模拟并发：条件更新未命中（提案已被确认线程推进为 applied）
        return False

    monkeypatch.setattr(
        team_changes, "get_change_request", fake_get_change_request,
    )
    monkeypatch.setattr(team_changes, "_update_status", fake_update_status)
    result = await reject_change_request(
        request_id="req-1", operator_id="alice",
    )
    assert result["ok"] is False
    assert "并发操作" in result["error"]
    # 期望前态必须是 pending（防止 applied/rejected 被覆写）
    assert captured["expected_status"] == STATUS_PENDING


def test_stale_apply_recovery_clause_present():
    """P1-4：过期回收必须包含 applying 中断恢复子句（防永久僵尸）。"""
    source = inspect.getsource(team_changes.expire_stale_requests)
    assert "STATUS_APPLYING" in source
    assert "stale_apply" in source
    assert "STALE_APPLY_MINUTES" in source


# ---------------------------------------------------------------------------
# P1-1 终态 run 迟到批准拒绝
# ---------------------------------------------------------------------------


class _FakeRunStore:
    """最小 run 存储替身（get_run 返回预设 run）。"""

    def __init__(self, run: dict):
        self._run = run

    async def get_run(self, run_id: str):
        return self._run


def _run_with_pending_decision(status: str) -> dict:
    """构造带挂起计划决策的 run（决策已签发、版本匹配）。"""
    return {
        "id": "run-1",
        "status": status,
        "context_bundle": {
            "execution_ctx": {
                "pending_decision": {
                    "decision_id": "dec-1",
                    "kind": "plan",
                    "revision": 2,
                    "summary": {},
                },
            },
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_status", sorted(RUN_TERMINAL_STATUSES))
async def test_late_approval_rejected_for_terminal_run(
    monkeypatch, terminal_status,
):
    """终态（done/failed/escalated/canceled）run 的迟到批准拒绝放行。

    审批中心延迟 resolve 回调 / 重复点击不得把终态 run 拉回重新
    执行（canceled 语义与 escalated 人工门不可绕过）。
    """
    store = _FakeRunStore(_run_with_pending_decision(terminal_status))
    monkeypatch.setattr(
        workforce_service, "get_run_store", lambda: store,
    )
    decision = HumanDecision(
        decision_id="dec-1",
        action="approve_plan",
        expected_revision=2,
        comment="迟到的批准",
    )
    with pytest.raises(DecisionConflict) as exc_info:
        await workforce_service.submit_decision("run-1", decision)
    assert "终态" in str(exc_info.value)


# ---------------------------------------------------------------------------
# P1-2 预算原子预留失败路径
# ---------------------------------------------------------------------------


class _FakeBudgetStore:
    """预算预留替身（reserve_budget 可编程返回 None/预留标识）。"""

    def __init__(self, reserve_result):
        self._reserve_result = reserve_result
        self.calls: list = []

    async def sum_node_tokens(self, run_id: str) -> int:
        """已结算节点消耗（run_total_tokens 的轻量聚合路径）。"""
        return 800

    async def run_budget_usage(self, run_id: str) -> int:
        return 800

    async def outstanding_tokens(self, run_id: str) -> int:
        """未决预留（fake 场景：无在途预留）。"""
        return 0

    async def reserve_budget(
        self, run_id, node_key, tokens, reason="", max_total_tokens=0,
    ):
        self.calls.append(
            {
                "tokens": tokens,
                "max_total_tokens": max_total_tokens,
            },
        )
        return self._reserve_result


@pytest.mark.asyncio
async def test_reserve_budget_escalates_when_store_returns_none():
    """Store 层原子校验未通过（并发超限返回 None）→ 熔断升级。"""
    store = _FakeBudgetStore(reserve_result=None)
    policy = RunPolicy(max_total_tokens=1000, parallelism=2)
    with pytest.raises(Exception, match="熔断升级|预算"):
        await reserve_node_budget(store, "run-1", "node-a", policy)
    # 份额仍按均分计算：剩余 200 / 并发 2 = 100
    assert store.calls[0]["tokens"] == 100
    # 必须把预算上限传给 Store 层做原子校验
    assert store.calls[0]["max_total_tokens"] == 1000


@pytest.mark.asyncio
async def test_reserve_budget_returns_reservation_on_success():
    """Store 层校验通过 → 返回预留标识（预留即占额）。"""
    store = _FakeBudgetStore(reserve_result="resv-1")
    policy = RunPolicy(max_total_tokens=1000, parallelism=2)
    reservation_id = await reserve_node_budget(
        store, "run-1", "node-a", policy,
    )
    assert reservation_id == "resv-1"


# ---------------------------------------------------------------------------
# metadata 提案状态枚举对齐（前端唯一文案来源）
# ---------------------------------------------------------------------------


def test_metadata_change_request_statuses_align_state_machine():
    """metadata 枚举必须覆盖状态机全集（防止前端文案缺项）。"""
    expected = TERMINAL_STATUSES | {STATUS_PENDING, STATUS_APPLYING}
    actual = {item["value"] for item in CHANGE_REQUEST_STATUSES}
    assert actual == expected
    # 每项必须有 label（前端唯一文案来源）与非空 color
    for item in CHANGE_REQUEST_STATUSES:
        assert item["label"]
        assert item["color"]


# ---------------------------------------------------------------------------
# compute_member_upgrades（member-updates 端点唯一实现，含 expert_name）
# ---------------------------------------------------------------------------


def test_compute_member_upgrades_includes_expert_name():
    """升级判定含员工名称（端点响应契约；原测试副本漂移的回归）。"""
    from qwenpaw.app.experts.models import ExpertRecord, TeamMember

    members = [
        TeamMember(expert_id="e-1", expert_version=1),
        TeamMember(expert_id="e-missing", expert_version=2),
    ]
    cards = [
        ExpertRecord(id="e-1", name="小助手", published_version=5),
    ]
    result = compute_member_upgrades(members, cards)
    assert result[0]["expert_name"] == "小助手"
    assert result[0]["upgradable"] is True
    # 不存在员工：名称空串、latest=0、不可升级
    assert result[1]["expert_name"] == ""
    assert result[1]["latest_version"] == 0
    assert result[1]["upgradable"] is False


# 防止未使用导入告警（KIND_PUBLISH 用于文档性引用）
_ = KIND_PUBLISH
