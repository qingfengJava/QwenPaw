# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the cron task ledger unify projection (0029).

Covers: CronManager registration observers (chat-created tasks landing
in the unified ledger), CronJobSpec → ledger field reverse-mapping,
CronExecutionRecord run_id/session_id threading, and the post-run
self-check that guards the run_id linkage.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.crons.models import CronExecutionRecord
from qwenpaw.app.crons.executor import _last_assistant_text
from qwenpaw.app.experts import scheduling as scheduling_mod
from qwenpaw.app.experts.scheduling import (
    _attach_registration_observer,
    _backfill_tasks_from_authority,
    _make_registration_observer,
    _origin_from_spec,
    _schedule_json_from_spec,
    _task_prompt_from_spec,
    _verify_execution_result,
    attach_expert_scheduling,
    record_execution,
)
from qwenpaw.hooks.observability.run_log_hook import _resolve_run_origin
from qwenpaw.runtime.hooks import HookContext


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class _FakeStore:
    """Record-updating calls so projections can be asserted."""

    def __init__(self):
        self.upserts: list[dict] = []
        self.updates: list[dict] = []
        self.tasks: dict = {}
        self.begun: list[dict] = []
        self.finished: list[dict] = []

    async def upsert_task_from_spec(self, **kwargs):
        self.upserts.append(kwargs)
        row = SimpleNamespace(
            id=kwargs["job_id"],
            expert_id=kwargs["expert_id"],
            name=kwargs.get("name", ""),
        )
        self.tasks[kwargs["job_id"]] = row
        return row

    async def update_task(self, task_id, **fields):
        self.updates.append({"task_id": task_id, **fields})

    async def get_task(self, task_id):
        return self.tasks.get(task_id)

    async def begin_run(self, task, scheduled_for, run_id="", session_id=""):
        self.begun.append(
            {
                "task_id": task.id,
                "scheduled_for": scheduled_for,
                "run_id": run_id,
                "session_id": session_id,
            }
        )
        return SimpleNamespace(id="trn_1", task_id=task.id)

    async def finish_run(self, run, status, result_summary="", error=""):
        self.finished.append(
            {
                "run_id": run.id,
                "status": status,
                "result_summary": result_summary,
                "error": error,
            }
        )


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
# spec → ledger reverse mapping
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
# registration observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observer_skips_expert_task_prefix(fake_store: _FakeStore):
    """UI 链路 job（expert_task_ 前缀）由 service 层管理，观察者跳过。"""
    observer = _make_registration_observer("expert-1")
    await observer(
        "created",
        _make_spec(job_id="expert_task_stk_1"),
        "expert_task_stk_1",
    )
    assert fake_store.upserts == []
    assert fake_store.updates == []


@pytest.mark.asyncio
async def test_observer_created_projects_chat_task(fake_store: _FakeStore):
    """对话创建任务：created 事件 → 台账 upsert（source=chat 缺省）。"""
    observer = _make_registration_observer("expert-1")
    spec = _make_spec()
    await observer("created", spec, spec.id)

    assert len(fake_store.upserts) == 1
    row = fake_store.upserts[0]
    assert row["expert_id"] == "expert-1"
    assert row["job_id"] == spec.id
    assert row["source"] == "chat"
    assert row["status"] == "active"
    assert row["owner_id"] is None  # cron 默认用户不落台账 owner
    assert row["task_prompt"] == "搜索领域动态并简报"


@pytest.mark.asyncio
async def test_observer_source_from_meta_and_paused_status(
    fake_store: _FakeStore,
):
    """meta.origin_source 优先（api 标记）；disabled → paused。"""
    observer = _make_registration_observer("expert-1")
    spec = _make_spec(meta={"origin_source": "api"}, enabled=False)
    await observer("paused", spec, spec.id)

    row = fake_store.upserts[0]
    assert row["source"] == "api"
    assert row["status"] == "paused"


@pytest.mark.asyncio
async def test_observer_deleted_archives_ledger_row(fake_store: _FakeStore):
    observer = _make_registration_observer("expert-1")
    await observer("deleted", None, "8d049291-cc99")

    assert fake_store.upserts == []
    assert fake_store.updates == [
        {"task_id": "8d049291-cc99", "status": "archived"},
    ]


def test_attach_registration_observer_replaces_same_expert():
    """重挂同 expert 的观察者时替换旧闭包（幂等，不叠加）。"""

    class _Mgr:
        registration_observers: list = []

    mgr = _Mgr()
    _attach_registration_observer(mgr, "expert-1")
    first = mgr.registration_observers[0]
    _attach_registration_observer(mgr, "expert-1")
    assert len(mgr.registration_observers) == 1
    assert mgr.registration_observers[0] is not first
    _attach_registration_observer(mgr, "expert-2")
    assert len(mgr.registration_observers) == 2


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
# execution projection for chat-created (UUID) jobs + startup backfill
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


@pytest.mark.asyncio
async def test_execution_projects_chat_job_with_ledger_row(
    fake_store: _FakeStore,
):
    """对话创建任务（UUID job）：台账已有行 → 直接落执行留痕。"""
    spec = _make_spec()
    await _make_registration_observer("expert-1")("created", spec, spec.id)
    fake_store.upserts.clear()

    await record_execution(spec, _make_record(), dict(_OK_RESULT), "expert-1")

    assert fake_store.upserts == []  # 行已存在，不再补投影
    assert len(fake_store.begun) == 1
    begun = fake_store.begun[0]
    assert begun["run_id"] == "run-9"
    assert begun["session_id"] == "cron:job-9"
    assert begun["scheduled_for"] is None  # manual 触发无幂等锚
    assert fake_store.finished[0]["status"] == "succeeded"
    assert fake_store.finished[0]["result_summary"] == "简报内容"


@pytest.mark.asyncio
async def test_execution_backfills_missing_ledger_row(
    fake_store: _FakeStore,
):
    """观察者挂载前创建的任务：执行时兑底补投影再留痕。"""
    spec = _make_spec()  # 台账无行

    await record_execution(spec, _make_record(), dict(_OK_RESULT), "expert-1")

    assert len(fake_store.upserts) == 1
    assert fake_store.upserts[0]["expert_id"] == "expert-1"
    assert fake_store.upserts[0]["source"] == "chat"
    assert len(fake_store.begun) == 1
    assert len(fake_store.finished) == 1


@pytest.mark.asyncio
async def test_execution_skips_when_no_expert_binding(
    fake_store: _FakeStore,
):
    """无台账行且无 expert 绑定：无法定位归属，跳过留痕。"""
    spec = _make_spec()

    await record_execution(spec, _make_record(), dict(_OK_RESULT), None)

    assert fake_store.upserts == []
    assert fake_store.begun == []
    assert fake_store.finished == []


@pytest.mark.asyncio
async def test_execution_failed_record_maps_to_failed(
    fake_store: _FakeStore,
):
    spec = _make_spec()
    await _make_registration_observer("expert-1")("created", spec, spec.id)

    await record_execution(
        spec,
        _make_record(status="error"),
        {"task_type": "text"},
        "expert-1",
    )

    assert fake_store.finished[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_execution_prefers_authority_run_id(
    fake_store: _FakeStore,
    monkeypatch: pytest.MonkeyPatch,
):
    """agent 任务关联键取 agent_runs 权威 run id（详情页查询键）。"""
    monkeypatch.setattr(
        "qwenpaw.app.run_log_pg_store.get_latest_run_id_for_cron_job",
        _make_authority_lookup("auth0hexrunid"),
    )
    spec = _make_spec()
    await _make_registration_observer("expert-1")("created", spec, spec.id)

    await record_execution(spec, _make_record(), dict(_OK_RESULT), "expert-1")

    assert fake_store.begun[0]["run_id"] == "auth0hexrunid"


@pytest.mark.asyncio
async def test_execution_falls_back_to_trace_run_id(
    fake_store: _FakeStore,
):
    """权威反查为空（如 PG 平面不可用）→ 保持 trace run id 兑底。"""
    spec = _make_spec()
    await _make_registration_observer("expert-1")("created", spec, spec.id)

    await record_execution(spec, _make_record(), dict(_OK_RESULT), "expert-1")

    assert fake_store.begun[0]["run_id"] == "run-9"


@pytest.mark.asyncio
async def test_backfill_projects_only_missing_chat_jobs(
    fake_store: _FakeStore,
):
    """启动回填：前缀跳过、已入账跳过（含 archived 防复活）、缺行补。"""

    class _Mgr:
        async def list_jobs(self):
            return [
                _make_spec(job_id="expert_task_stk_ui"),
                _make_spec(job_id="job-archived"),
                _make_spec(job_id="job-new"),
            ]

    fake_store.tasks["job-archived"] = SimpleNamespace(id="job-archived")

    await _backfill_tasks_from_authority(_Mgr(), "expert-1")

    projected = [u["job_id"] for u in fake_store.upserts]
    assert projected == ["job-new"]
    assert fake_store.upserts[0]["expert_id"] == "expert-1"


@pytest.mark.asyncio
async def test_attach_expert_scheduling_wires_observers(fake_store):
    """装配点接线：注册+执行观察者同时挂上，并完成一次回填。"""

    class _Mgr:
        registration_observers: list = []
        execution_observers: list = []

        async def list_jobs(self):
            return []

    mgr = _Mgr()
    await attach_expert_scheduling(mgr, "expert-1")

    assert len(mgr.registration_observers) == 1
    assert len(mgr.execution_observers) == 1
    # 幂等重挂：同 expert 替换不叠加
    await attach_expert_scheduling(mgr, "expert-1")
    assert len(mgr.registration_observers) == 1
    assert len(mgr.execution_observers) == 1
    # 执行观察者透传 expert 绑定
    spec = _make_spec()
    await mgr.execution_observers[0](spec, _make_record(), dict(_OK_RESULT))
    assert len(fake_store.upserts) == 1  # 无行 → 兑底补投影


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
