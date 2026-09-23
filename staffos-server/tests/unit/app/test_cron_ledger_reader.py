# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Unit tests for the cron ledger reader mapping (T13b Phase 2 读层).

黄金映射用例：逐行覆盖设计文档
``docs/design/2026-09-18-cron-ledger-convergence.md`` §3.1 的反推规则
（纯函数层，无 IO）——前缀剥离、状态映射、owner 归一、meta 注解
优先、缺省兑底、脏行容错；另覆盖读/双写平面门控的三态判定。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from qwenpaw.app.crons.models import (
    CronJobRequest,
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    JobRuntimeSpec,
    ScheduleSpec,
)
from qwenpaw.app.experts import cron_ledger as ledger_mod
from qwenpaw.app.experts.cron_ledger import (
    _as_bool,
    _as_mapping,
    _expert_id_from_agent_id,
    _strip_name_prefix,
    _task_id_from_job_id,
    run_from_history_row,
    run_status_from_cron,
    task_from_cron_row,
)

_T0 = datetime(2030, 1, 1, 9, 0, 0, tzinfo=timezone.utc)


def _spec_dict(
    *,
    job_id: str = "expert_task_stk_1",
    name: str = "[数字员工] 晨会简报",
    prompt: str = "生成简报",
    schedule_type: str = "cron",
    cron: str = "0 9 * * *",
    enabled: bool = True,
    meta: dict | None = None,
    target_user: str = "cron",
) -> dict:
    """One CronJobSpec serialized like the JSONB plane stores it."""
    kwargs: dict = {"type": schedule_type, "timezone": "Asia/Shanghai"}
    if schedule_type == "cron":
        kwargs["cron"] = cron
    else:
        kwargs["run_at"] = _T0.isoformat()
    spec = CronJobSpec(
        id=job_id,
        name=name,
        schedule=ScheduleSpec(**kwargs),
        task_type="agent",
        request=CronJobRequest(input=prompt),
        dispatch=DispatchSpec(
            target=DispatchTarget(user_id=target_user, session_id=""),
        ),
        runtime=JobRuntimeSpec(),
        enabled=enabled,
        meta=meta or {},
    )
    return spec.model_dump(mode="json")


def _task_row(spec: dict | str, *, job_id: str = "", **overrides) -> dict:
    """One cron_jobs row (text()-mappings shape) for the reader."""
    if not job_id and isinstance(spec, dict):
        job_id = str(spec.get("id") or "")
    row = {
        "agent_id": "expert_exp1",
        "job_id": job_id,
        "spec": spec,
        "enabled": True,
        "run_count": 0,
        "created_at": _T0,
        "updated_at": _T0,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 纯工具：归属/前缀/归一
# ---------------------------------------------------------------------------


def test_id_prefix_helpers():
    """agent_id/job_id 逆映射与前缀剥除的边界。"""
    assert _expert_id_from_agent_id("expert_abc") == "abc"
    assert _expert_id_from_agent_id("agent_other") is None
    assert _expert_id_from_agent_id("") is None
    assert _task_id_from_job_id("expert_task_stk_1") == "stk_1"
    # chat/api 链路 job_id 无前缀：原样
    assert _task_id_from_job_id("8d04-uuid") == "8d04-uuid"
    assert _strip_name_prefix("[数字员工] 日报", "fb") == "日报"
    assert _strip_name_prefix("plain", "fb") == "plain"
    assert _strip_name_prefix("   ", "fb") == "fb"


def test_value_coercions():
    """JSONB/布尔列跨驱动取值归一（dict/str/脏值）。"""
    assert _as_mapping({"a": 1}) == {"a": 1}
    assert _as_mapping('{"a": 1}') == {"a": 1}
    assert _as_mapping("not-json") == {}
    assert _as_mapping([1, 2]) == {}
    assert _as_mapping(None) == {}
    for truthy in (True, "t", "true", "1", 1):
        assert _as_bool(truthy) is True
    for falsy in (False, "f", "false", "0", "", None):
        assert _as_bool(falsy) is False


def test_run_status_namespace_mapping():
    """history.status → 台账命名空间（success 之外一律 failed）。"""
    assert run_status_from_cron("success") == "succeeded"
    assert run_status_from_cron("error") == "failed"
    assert run_status_from_cron("skipped") == "failed"
    assert run_status_from_cron("cancelled") == "failed"
    assert run_status_from_cron(None) == "failed"


# ---------------------------------------------------------------------------
# task_from_cron_row：§3.1 逐行黄金映射
# ---------------------------------------------------------------------------


def test_task_ui_meta_annotation_is_single_source():
    """meta 注解优先：name/description/source 直读 spec.meta（T13a 写入）。"""
    spec = _spec_dict(
        meta={
            "expert_task_name": "晨会简报",
            "expert_description": "每天 9 点",
            "origin_source": "ui",
        },
    )
    task = task_from_cron_row(_task_row(spec, run_count=7))
    assert task is not None
    assert task.id == "stk_1"
    assert task.expert_id == "exp1"
    assert task.cron_job_id == "expert_task_stk_1"
    assert task.name == "晨会简报"
    assert task.description == "每天 9 点"
    assert task.source == "ui"
    assert task.status == "active"
    assert task.run_count == 7
    assert task.task_prompt == "生成简报"
    assert task.schedule_type == "cron"
    assert task.schedule_json == {"cron": "0 9 * * *"}
    assert task.timezone == "Asia/Shanghai"
    # next_run_at 属运行态：读层恒 None（由 SchedulingService 注入）
    assert task.next_run_at is None
    # "cron" 占位归一 None
    assert task.owner_id is None
    assert task.last_run_at is None
    assert task.last_status == ""


def test_task_unannotated_row_falls_back_to_prefix_strip():
    """未回填注解的旧行：剥展示前缀兑底，source 缺省 chat（对齐台账写方）。"""
    task = task_from_cron_row(_task_row(_spec_dict()))
    assert task is not None
    assert task.name == "晨会简报"
    assert task.description == ""
    assert task.source == "chat"


def test_task_status_matrix_enabled_and_once():
    """enabled→active/paused；once+success→completed（对齐 finish_run）。"""
    once_spec = _spec_dict(schedule_type="once", cron="")
    base = _task_row(once_spec)

    paused = task_from_cron_row({**base, "enabled": "false"})
    assert paused is not None and paused.status == "paused"

    once_success = task_from_cron_row(base, any_success=True)
    assert once_success is not None and once_success.status == "completed"

    # 有历史但无 success：once 未完结仍 active
    once_pending = task_from_cron_row(base, any_success=False)
    assert once_pending is not None and once_pending.status == "active"

    # 非 once 任务：success 历史不触发 completed
    cron_ok = task_from_cron_row(_task_row(_spec_dict()), any_success=True)
    assert cron_ok is not None and cron_ok.status == "active"


def test_task_last_run_projection_from_history_hint():
    """最新 history 行反推 last_run_at/last_status（映射台账命名空间）。"""
    task = task_from_cron_row(
        _task_row(_spec_dict()),
        last_run_at=_T0,
        last_run_status="error",
    )
    assert task is not None
    assert task.last_run_at == _T0
    assert task.last_status == "failed"

    # 有 run_at 无 status 行→空串（从未有历史时不落 "failed"）
    fresh = task_from_cron_row(_task_row(_spec_dict()))
    assert fresh is not None
    assert fresh.last_status == "" and fresh.last_run_at is None


def test_task_owner_and_spec_string_shapes():
    """owner 取 dispatch.target.user_id；spec 为 JSON 字符串亦可（asyncpg 原文）。"""
    spec = _spec_dict(target_user="u42", meta={"expert_task_name": "n"})
    task = task_from_cron_row(
        _task_row(
            json.dumps(spec, ensure_ascii=False),
            job_id="expert_task_stk_1",
        ),
    )
    assert task is not None
    assert task.owner_id == "u42"
    assert task.name == "n"


def test_task_dirty_rows_return_none():
    """非员工平面/脏 spec：返回 None 不拖垮列表（读层容错契约）。"""
    assert (
        task_from_cron_row(
            _task_row(_spec_dict(), agent_id="wb_other"),
        )
        is None
    )
    assert task_from_cron_row(_task_row({"garbage": True})) is None


# ---------------------------------------------------------------------------
# run_from_history_row
# ---------------------------------------------------------------------------


def test_run_row_reverse_projection():
    """id 合成 job_id:seq；started/finished 同 run_at（D5）；空列归一。"""
    run = run_from_history_row(
        {
            "agent_id": "expert_exp1",
            "job_id": "expert_task_stk_1",
            "seq": 3,
            "run_at": _T0,
            "status": "success",
            "error": "",
            "result_summary": "摘要",
            "run_id": "run-9",
            "session_id": "cron:expert_task_stk_1",
            "scheduled_for": _T0,
        },
    )
    assert run is not None
    assert run.id == "expert_task_stk_1:3"
    assert run.task_id == "stk_1"
    assert run.expert_id == "exp1"
    assert run.status == "succeeded"
    assert run.result_summary == "摘要"
    assert run.run_id == "run-9"
    assert run.session_id == "cron:expert_task_stk_1"
    assert run.scheduled_for == _T0
    assert run.started_at == _T0 and run.finished_at == _T0


def test_run_row_defaults_and_non_expert_guard():
    """旧行四列空值→空串/None；非员工平面 None。"""
    run = run_from_history_row(
        {
            "agent_id": "expert_exp1",
            "job_id": "raw-job",
            "seq": 1,
            "run_at": _T0,
            "status": "error",
            "error": "boom",
            "result_summary": "",
            "run_id": "",
            "session_id": "",
            "scheduled_for": None,
        },
    )
    assert run is not None
    assert run.task_id == "raw-job"
    assert run.status == "failed"
    assert run.error == "boom"
    assert run.run_id == "" and run.session_id == ""
    assert run.scheduled_for is None
    assert run_from_history_row({"agent_id": "wb_x", "job_id": "j"}) is None


# ---------------------------------------------------------------------------
# json 后端告警（D1：专家域 cron 平面必须 PG 权威）
# ---------------------------------------------------------------------------


@pytest.fixture
def _clean_backend_cache():
    from qwenpaw.db.write_gateway import reset_backend_cache

    reset_backend_cache()
    yield
    reset_backend_cache()


def test_warn_if_json_backend_only_once(
    monkeypatch: pytest.MonkeyPatch, _clean_backend_cache, caplog
):
    """D1 提醒只发一次（json 后端），dual 后端不告警。"""
    monkeypatch.setattr(ledger_mod, "_json_backend_warned", False)
    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
    with caplog.at_level("WARNING"):
        ledger_mod.warn_if_json_backend("e1")
        ledger_mod.warn_if_json_backend("e2")
    assert sum("stays EMPTY" in r.message for r in caplog.records) == 1

    monkeypatch.setattr(ledger_mod, "_json_backend_warned", False)
    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
    from qwenpaw.db.write_gateway import reset_backend_cache

    reset_backend_cache()
    caplog.clear()  # 段间隔离：只断言第二段新增告警
    with caplog.at_level("WARNING"):
        ledger_mod.warn_if_json_backend("e3")
    assert not any("stays EMPTY" in r.message for r in caplog.records)
