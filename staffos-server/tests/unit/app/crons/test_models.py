# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError

from qwenpaw.app.crons.models import (
    CronJobSpec,
    DispatchSpec,
    DispatchTarget,
    ScheduleSpec,
    _crontab_dow_to_name,
)
from tests.unit.app.conftest import make_cron_job_spec


# ---------------------------------------------------------------------------
# _crontab_dow_to_name — crontab numeric DOW → abbreviation
# ---------------------------------------------------------------------------


def test_dow_wildcard_passthrough():
    assert _crontab_dow_to_name("*") == "*"


def test_dow_single_numeric_to_name():
    assert _crontab_dow_to_name("0") == "sun"
    assert _crontab_dow_to_name("1") == "mon"
    assert _crontab_dow_to_name("7") == "sun"  # crontab 7 = Sunday


def test_dow_named_passthrough():
    # Already-named values must not be mutated.
    assert _crontab_dow_to_name("mon") == "mon"
    assert _crontab_dow_to_name("fri") == "fri"


def test_dow_comma_list():
    assert _crontab_dow_to_name("1,3,5") == "mon,wed,fri"


def test_dow_range():
    assert _crontab_dow_to_name("1-5") == "mon-fri"


def test_dow_step():
    # */2 on DOW field: wildcard base with step
    assert _crontab_dow_to_name("*/2") == "*/2"


# ---------------------------------------------------------------------------
# ScheduleSpec — cron type
# ---------------------------------------------------------------------------


def test_schedule_cron_normalizes_5_fields():
    spec = ScheduleSpec(type="cron", cron="0 9 * * 1")
    assert spec.cron == "0 9 * * mon"


def test_schedule_cron_normalizes_4_fields():
    spec = ScheduleSpec(type="cron", cron="9 * * 1")
    assert spec.cron == "0 9 * * mon"


def test_schedule_cron_named_dow_unchanged():
    spec = ScheduleSpec(type="cron", cron="0 9 * * mon")
    assert spec.cron == "0 9 * * mon"


def test_schedule_cron_rejects_empty():
    with pytest.raises(ValidationError, match="cron is empty"):
        ScheduleSpec(type="cron", cron="")


def test_schedule_cron_rejects_6_fields():
    with pytest.raises(ValidationError):
        ScheduleSpec(type="cron", cron="0 0 9 * * mon")


def test_schedule_once_requires_run_at():
    with pytest.raises(ValidationError, match="run_at is missing"):
        ScheduleSpec(type="once")


# ---------------------------------------------------------------------------
# CronJobSpec validation
# ---------------------------------------------------------------------------


def test_cron_job_spec_agent_syncs_request_with_target():
    spec = make_cron_job_spec(user_id="alice", session_id="console:alice")
    assert spec.request is not None
    assert spec.request.user_id == "alice"
    assert spec.request.session_id == "console:alice"


def test_cron_job_spec_text_rejects_empty_text():
    with pytest.raises(ValidationError, match="text is empty"):
        CronJobSpec(
            name="Bad",
            schedule=ScheduleSpec(type="cron", cron="0 9 * * mon"),
            task_type="text",
            text="",
            dispatch=DispatchSpec(
                target=DispatchTarget(user_id="u1", session_id="console:u1"),
            ),
        )


def test_dispatch_silent_defaults_to_false():
    dispatch = DispatchSpec(
        target=DispatchTarget(user_id="u1", session_id="console:u1"),
    )

    assert dispatch.silent is False


def test_cron_job_spec_agent_accepts_silent_delivery():
    payload = make_cron_job_spec().model_dump(mode="json")
    payload["dispatch"]["silent"] = True

    spec = CronJobSpec.model_validate(payload)

    assert spec.dispatch.silent is True


def test_cron_job_spec_text_rejects_silent_delivery():
    with pytest.raises(
        ValidationError,
        match="silent delivery is only supported for agent tasks",
    ):
        CronJobSpec(
            name="Silent text",
            schedule=ScheduleSpec(type="cron", cron="0 9 * * mon"),
            task_type="text",
            text="Hello",
            dispatch=DispatchSpec(
                target=DispatchTarget(
                    user_id="u1",
                    session_id="console:u1",
                ),
                silent=True,
            ),
        )


# ---------------------------------------------------------------------------
# CronJobSpec owner fields — S2 用户个人平面归属
# ---------------------------------------------------------------------------


def test_cron_job_spec_owner_fields_default_none():
    # 未指定归属 → 三字段均 None（落员工共享语义）
    spec = make_cron_job_spec()
    assert spec.owner_user_id is None
    assert spec.department_id is None
    assert spec.project_id is None


def test_cron_job_spec_owner_fields_round_trip():
    # 个人任务归属随 spec 序列化在 json/pg 两平面往返不丢失
    spec = make_cron_job_spec().model_copy(
        update={
            "owner_user_id": "alice",
            "department_id": "/root/eng",
            "project_id": None,
        },
    )
    payload = spec.model_dump(mode="json")
    assert payload["owner_user_id"] == "alice"
    assert payload["department_id"] == "/root/eng"

    restored = CronJobSpec.model_validate(payload)
    assert restored.owner_user_id == "alice"
    assert restored.department_id == "/root/eng"
    assert restored.project_id is None
