# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for expert scheduling after the T13d cron-ledger convergence.

收口后（expert 两表 DROP）覆盖：CronJobSpec → 记录字段的反推工具、
执行观察者只剩的**执行检查闭环**（_verify_execution_result + inbox
告警）、装配点仅挂执行观察者、UI 链路 spec.meta 注解、以及 run-log
hook 的 cron 来源解析。注册观察者/启动回填/legacy 台账写路径已随
expert 两表退役移除（对应用例一并删除）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.crons.models import CronExecutionRecord
from qwenpaw.app.crons.executor import _last_assistant_text
from qwenpaw.app.experts import scheduling as scheduling_mod
from qwenpaw.app.experts.models import ScheduledTaskRecord
from qwenpaw.app.experts.scheduling import (
    _origin_from_spec,
    _schedule_json_from_spec,
    _task_prompt_from_spec,
    _verify_execution_result,
    SchedulingService,
    attach_expert_scheduling,
    record_execution,
)
from qwenpaw.hooks.observability.run_log_hook import _resolve_run_origin
from qwenpaw.runtime.hooks import HookContext


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class _FakeStore:
    """收口后 store 只读：record_execution 仅经 get_task 取任务归属。"""

    def __init__(self):
        self.tasks: dict = {}
        self.get_calls: list = []

    async def get_task(self, task_id):
        self.get_calls.append(task_id)
        return self.tasks.get(task_id)


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    store = _FakeStore()
    monkeypatch.setattr(
        scheduling_mod,
        "get_scheduling_store",
        lambda: store,
    )
    # 反查权威 run id 默认置空（兑底 trace id）；按需在用例内覆盖
    monkeypatch.setattr(
        "qwenpaw.app.run_log_pg_store.get_latest_run_id_for_cron_job",
        _make_authority_lookup(""),
    )
    return store


def _make_authority_lookup(return_value: str):
    async def lookup(cron_job_id: str) -> str:
        return return_value

    return lookup


def _make_spec(
    *,
    job_id: str = "8d049291-cc99-4d12-97bc-e2f363078672",
    name: str = "演示-定时提醒",
    task_type: str = "agent",
    enabled: bool = True,
    schedule_type: str = "cron",
    meta: dict | None = None,
) -> SimpleNamespace:
    request = SimpleNamespace(input="搜索领域动态并简报")
    return SimpleNamespace(
        id=job_id,
        name=name,
        enabled=enabled,
        task_type=task_type,
        text="固定文本" if task_type == "text" else None,
        request=request if task_type == "agent" else None,
        schedule=SimpleNamespace(
            type=schedule_type,
            cron="0 9 * * 1-5" if schedule_type == "cron" else None,
            run_at=None,
            timezone="Asia/Shanghai",
        ),
        dispatch=SimpleNamespace(
            channel="console",
            mode="stream",
            silent=True,
            target=SimpleNamespace(user_id="cron", session_id="s-1"),
        ),
        meta=meta if meta is not None else {},
    )


# ---------------------------------------------------------------------------
# spec → record reverse mapping（CronLedgerReader 复用的纯函数）
# ---------------------------------------------------------------------------


def test_task_prompt_prefers_request_input_over_text():
    spec = _make_spec()
    assert _task_prompt_from_spec(spec) == "搜索领域动态并简报"

    text_spec = _make_spec(task_type="text")
    assert _task_prompt_from_spec(text_spec) == "固定文本"


def test_schedule_json_cron_and_once_roundtrip():
    cron_type, cron_json = _schedule_json_from_spec(_make_spec())
    assert cron_type == "cron"
    assert cron_json == {"cron": "0 9 * * 1-5"}

    once_spec = _make_spec()
    once_spec.schedule = SimpleNamespace(
        type="once",
        cron=None,
        run_at=None,
        timezone="Asia/Shanghai",
    )
    once_type, once_json = _schedule_json_from_spec(once_spec)
    assert once_type == "once"


def test_origin_from_spec_compact_payload():
    origin = _origin_from_spec(_make_spec())
    assert origin["task_type"] == "agent"
    assert origin["channel"] == "console"
    assert origin["silent"] is True


# ---------------------------------------------------------------------------
# execution record threading + self-check
# ---------------------------------------------------------------------------


def test_execution_record_carries_run_linkage():
    record = CronExecutionRecord(
        run_at="2026-09-13T12:00:00Z",
        status="success",
        trigger="manual",
        run_id="run-1",
        session_id="cron:job-1",
    )
    assert record.run_id == "run-1"
    assert record.session_id == "cron:job-1"


@pytest.mark.asyncio
async def test_verify_execution_result_guards_run_id():
    ok = {
        "task_type": "agent",
        "run_id": "run-1",
        "delivery_status": "success",
    }
    assert await _verify_execution_result(SimpleNamespace(id="j"), ok) is None

    missing_run = {"task_type": "agent", "run_id": ""}
    reason = await _verify_execution_result(
        SimpleNamespace(id="j"),
        missing_run,
    )
    assert reason and "run_id" in reason

    failed_delivery = {
        "task_type": "agent",
        "run_id": "run-1",
        "delivery_status": "failed",
        "delivery_error": "channel down",
    }
    reason = await _verify_execution_result(
        SimpleNamespace(id="j"),
        failed_delivery,
    )
    assert reason and "channel down" in reason

    # text 任务不产生 run_id，检查直接放行
    assert await _verify_execution_result(
        SimpleNamespace(id="j"),
        {"task_type": "text"},
    ) is None


def test_last_assistant_text_extracts_reply():
    delta = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "完了"}]},
        {"role": "assistant", "content": "最终回复"},
    ]
    assert _last_assistant_text(delta) == "最终回复"
    assert _last_assistant_text([]) == ""


# ---------------------------------------------------------------------------
# 执行观察者（收口后只做执行检查闭环：异常落 inbox 告警，不写台账）
# ---------------------------------------------------------------------------


def _make_record(
    *,
    status: str = "success",
    trigger: str = "manual",
) -> CronExecutionRecord:
    return CronExecutionRecord(
        run_at="2026-09-13T12:41:31Z",
        status=status,
        trigger=trigger,
    )


_OK_RESULT = {
    "task_type": "agent",
    "run_id": "run-9",
    "session_id": "cron:job-9",
    "final_text": "简报内容",
    "delivery_status": "success",
}


def _capture_inbox(monkeypatch: pytest.MonkeyPatch) -> list:
    """Patch inbox append_event and return the capture list."""
    captured: list = []

    async def _fake_append(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(
        "qwenpaw.app.inbox_store.append_event",
        _fake_append,
    )
    return captured


@pytest.mark.asyncio
async def test_record_execution_alerts_on_check_failure(
    fake_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
):
    """检查不通过（agent 无 run_id）→ 落 inbox 告警，携带任务归属与状态。"""
    captured = _capture_inbox(monkeypatch)
    spec = _make_spec()  # UUID job（chat/api 链路）
    fake_store.tasks[spec.id] = SimpleNamespace(
        id=spec.id, expert_id="expert-1", name="演示-定时提醒",
    )
    result = {"task_type": "agent", "run_id": "", "session_id": "cron:j"}

    await record_execution(spec, _make_record(), result, "expert-1")

    assert len(captured) == 1
    event = captured[0]
    assert event["agent_id"] == "expert-1"
    assert event["event_type"] == "cron_run_check_failed"
    assert event["payload"]["task_id"] == spec.id
    # record.status=success → 投影命名空间 succeeded
    assert event["payload"]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_record_execution_skips_when_task_missing(
    fake_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
):
    """cron 平面无任务行（已删/非本域）→ 跳过告警，不抛异常。"""
    captured = _capture_inbox(monkeypatch)
    spec = _make_spec()  # 未种任务行

    await record_execution(spec, _make_record(), dict(_OK_RESULT), "expert-1")

    assert captured == []


@pytest.mark.asyncio
async def test_record_execution_payload_prefers_authority_run_id(
    fake_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
):
    """agent 任务关联键取 agent_runs 权威 run id（详情页跳转查询键）。"""
    monkeypatch.setattr(
        "qwenpaw.app.run_log_pg_store.get_latest_run_id_for_cron_job",
        _make_authority_lookup("auth0hexrunid"),
    )
    captured = _capture_inbox(monkeypatch)
    spec = _make_spec()
    fake_store.tasks[spec.id] = SimpleNamespace(
        id=spec.id, expert_id="expert-1", name="n",
    )
    # 原始 run_id 为空 → 检查不通过触发告警；payload 用权威反查值
    result = {"task_type": "agent", "run_id": "", "session_id": "cron:j"}

    await record_execution(spec, _make_record(), result, "expert-1")

    assert captured[0]["payload"]["run_id"] == "auth0hexrunid"
    assert captured[0]["payload"]["agent_run_id"] == "auth0hexrunid"


@pytest.mark.asyncio
async def test_record_execution_strips_ui_prefix_for_lookup(
    fake_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
):
    """UI 链路 job（expert_task_ 前缀）：去前缀后查 cron 平面任务行。"""
    captured = _capture_inbox(monkeypatch)
    spec = _make_spec(job_id="expert_task_stk_1")
    fake_store.tasks["stk_1"] = SimpleNamespace(
        id="stk_1", expert_id="expert-1", name="晨会简报",
    )
    result = {"task_type": "agent", "run_id": "", "session_id": "cron:j"}

    await record_execution(spec, _make_record(), result, "expert-1")

    assert "stk_1" in fake_store.get_calls
    assert captured[0]["payload"]["task_id"] == "stk_1"


@pytest.mark.asyncio
async def test_attach_expert_scheduling_wires_execution_observer(fake_store):
    """装配点接线：收口后仅挂执行观察者（注册观察者/回填已退役），幂等重挂。"""

    class _Mgr:
        execution_observers: list = []

    mgr = _Mgr()
    await attach_expert_scheduling(mgr, "expert-1")

    assert len(mgr.execution_observers) == 1
    # 注册观察者已退役：装配点不再触碰 registration_observers
    assert not hasattr(mgr, "registration_observers")

    # 幂等重挂：同 expert 替换不叠加
    await attach_expert_scheduling(mgr, "expert-1")
    assert len(mgr.execution_observers) == 1


# ---------------------------------------------------------------------------
# run-log hook origin resolution
# ---------------------------------------------------------------------------


def _make_hook_ctx(request_context: dict | None) -> HookContext:
    request = SimpleNamespace(
        user_id="u-1",
        channel="console",
        chat_id="",
    )
    if request_context is not None:
        request.request_context = request_context
    return HookContext(
        request=request,
        session_id="s-1",
        agent_id="expert_x",
        root_session_id="s-1",
        root_agent_id="expert_x",
        workspace_dir=None,
        workspace=SimpleNamespace(),
        app_services=None,
        input_msgs=[],
    )


def test_resolve_run_origin_defaults_to_chat():
    source, cron_job_id = _resolve_run_origin(_make_hook_ctx(None))
    assert source == "chat"
    assert cron_job_id == ""


def test_resolve_run_origin_reads_cron_context():
    source, cron_job_id = _resolve_run_origin(
        _make_hook_ctx(
            {"source": "cron", "cron_job_id": "job-9"},
        ),
    )
    assert source == "cron"
    assert cron_job_id == "job-9"


# ---------------------------------------------------------------------------
# T13a 收口 Phase 1：UI 链路 spec.meta 承载台账专属字段
# ---------------------------------------------------------------------------


def _ui_task(**overrides) -> ScheduledTaskRecord:
    """一条 UI 链路任务记录（cron 周期任务样本）。"""
    payload = {
        "id": "stk_1",
        "expert_id": "e1",
        "name": "晨会简报",
        "description": "每天 9 点生成团队简报",
        "task_prompt": "生成简报",
        "schedule_type": "cron",
        "schedule_json": {"cron": "0 9 * * *"},
    }
    payload.update(overrides)
    return ScheduledTaskRecord(**payload)


def test_build_spec_carries_expert_annotations():
    """原始名/描述/来源落 spec.meta，不再依赖前缀剥离。"""
    service = SchedulingService.__new__(SchedulingService)
    service._cron = None

    spec = service._build_spec(_ui_task())

    assert spec.id == "expert_task_stk_1"
    assert spec.meta["expert_task_id"] == "stk_1"
    assert spec.meta["expert_task_name"] == "晨会简报"
    assert spec.meta["expert_description"] == "每天 9 点生成团队简报"
    assert spec.meta["origin_source"] == "ui"
    # dispatch.meta 同步（CronLedgerReader 反推单一来源）
    assert spec.dispatch.meta["expert_task_name"] == "晨会简报"
    assert spec.dispatch.meta["origin_source"] == "ui"
    # session_id 空串 → executor share_session=False 分支派生专属会话
    assert spec.dispatch.target.session_id == ""


def test_build_spec_defaults_missing_description_to_empty():
    """描述缺省落空串，不丢键（读层反推无需区分缺失/空置）。"""
    service = SchedulingService.__new__(SchedulingService)
    service._cron = None

    spec = service._build_spec(_ui_task(description=""))

    assert spec.meta["expert_description"] == ""
