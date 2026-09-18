# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from ..channels.schema import DEFAULT_CHANNEL

# ---------------------------------------------------------------------------
# APScheduler v3 uses ISO 8601 weekday numbering (0=Mon … 6=Sun) for
# CronTrigger(day_of_week=...), while standard crontab uses 0=Sun … 6=Sat.
# from_crontab() does NOT convert either.  Three-letter English abbreviations
# (mon, tue, …, sun) are unambiguous in both systems, so we normalise the
# 5th cron field to abbreviations at validation time.
# ---------------------------------------------------------------------------

_CRONTAB_NUM_TO_NAME: dict[str, str] = {
    "0": "sun",
    "1": "mon",
    "2": "tue",
    "3": "wed",
    "4": "thu",
    "5": "fri",
    "6": "sat",
    "7": "sun",
}


def _crontab_dow_to_name(field: str) -> str:
    """Convert the day-of-week field from crontab numbers to abbreviations.

    Handles: ``*``, single values, comma-separated lists, and ranges.
    Already-named values (``mon``, ``tue``, …) are passed through unchanged.
    """
    if field == "*":
        return field

    def _convert_token(tok: str) -> str:
        if "/" in tok:
            base, step = tok.rsplit("/", 1)
            return f"{_convert_token(base)}/{step}"
        if "-" in tok:
            parts = tok.split("-", 1)
            return "-".join(_CRONTAB_NUM_TO_NAME.get(p, p) for p in parts)
        return _CRONTAB_NUM_TO_NAME.get(tok, tok)

    return ",".join(_convert_token(t) for t in field.split(","))


class ScheduleSpec(BaseModel):
    type: Literal["cron", "once"] = "cron"
    cron: Optional[str] = None
    run_at: Optional[datetime] = None
    timezone: str = "UTC"
    repeat_every_days: Optional[int] = Field(default=None, ge=1)
    repeat_end_type: Optional[Literal["never", "until", "count"]] = None
    repeat_until: Optional[datetime] = None
    repeat_count: Optional[int] = Field(default=None, ge=1)

    @classmethod
    def normalize_cron_5_fields(cls, v: str) -> str:
        parts = [p for p in v.split() if p]
        if len(parts) == 5:
            parts[4] = _crontab_dow_to_name(parts[4])
            return " ".join(parts)

        if len(parts) == 4:
            # treat as: hour dom month dow
            hour, dom, month, dow = parts
            return f"0 {hour} {dom} {month} {_crontab_dow_to_name(dow)}"

        if len(parts) == 3:
            # treat as: dom month dow
            dom, month, dow = parts
            return f"0 0 {dom} {month} {_crontab_dow_to_name(dow)}"

        # 6 fields (seconds) or too short: reject
        raise ValueError(
            "cron must have 5 fields (or 4/3 fields that can be "
            "normalized); seconds not supported",
        )

    @model_validator(mode="after")
    def _validate_schedule_type(self) -> "ScheduleSpec":
        if self.type == "cron":
            if not (self.cron and self.cron.strip()):
                raise ValueError("schedule.type is cron but cron is empty")
            self.cron = self.normalize_cron_5_fields(self.cron)
            self.run_at = None
            self.repeat_every_days = None
            self.repeat_end_type = None
            self.repeat_until = None
            self.repeat_count = None
            return self

        if self.run_at is None:
            raise ValueError("schedule.type is once but run_at is missing")
        self.cron = None
        if self.repeat_every_days is None:
            self.repeat_end_type = None
            self.repeat_until = None
            self.repeat_count = None
            return self

        if self.repeat_end_type is None:
            self.repeat_end_type = "never"

        if self.repeat_end_type == "never":
            self.repeat_until = None
            self.repeat_count = None
            return self

        if self.repeat_end_type == "until":
            if self.repeat_until is None:
                raise ValueError(
                    "repeat_end_type is until but repeat_until is missing",
                )
            if self.repeat_until <= self.run_at:
                raise ValueError(
                    "repeat_until must be later than run_at "
                    "(deadline must be after execution time)",
                )
            self.repeat_count = None
            return self

        if self.repeat_count is None:
            raise ValueError(
                "repeat_end_type is count but repeat_count is missing",
            )
        self.repeat_until = None
        return self


class DispatchTarget(BaseModel):
    user_id: str
    session_id: str


class DispatchSpec(BaseModel):
    type: Literal["channel"] = "channel"
    channel: str = Field(default=DEFAULT_CHANNEL)
    target: DispatchTarget
    mode: Literal["stream", "final"] = Field(default="stream")
    silent: bool = Field(
        default=False,
        description=(
            "Run an agent task without delivering its events to the channel."
        ),
    )
    meta: Dict[str, Any] = Field(default_factory=dict)


class JobRuntimeSpec(BaseModel):
    max_concurrency: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=120, ge=1)
    misfire_grace_seconds: int = Field(default=600, ge=0)
    share_session: bool = Field(
        default=True,
        description=(
            "Whether to share session with target user. "
            "If False, creates isolated context with unique run ID."
        ),
    )
    tool_safety: bool = Field(
        default=False,
        description=(
            "Tool execution safety for this cron job. "
            "When enabled (True), uses AUTO mode — risky tools require "
            "approval (may block unattended execution). "
            "When disabled (False), uses OFF mode — all tools execute "
            "without approval checks, suitable for trusted automated tasks."
        ),
    )


class CronJobRequest(BaseModel):
    """Passthrough payload to workspace.stream_query(request=...).

    This is aligned with AgentRequest(extra="allow"). We keep it permissive.
    """

    model_config = ConfigDict(extra="allow")

    input: Optional[Any] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None


TaskType = Literal["text", "agent"]


class CronJobSpec(BaseModel):
    id: Optional[str] = None
    name: str
    enabled: bool = True

    schedule: ScheduleSpec
    task_type: TaskType = "agent"
    text: Optional[str] = None
    request: Optional[CronJobRequest] = None
    dispatch: DispatchSpec
    save_result_to_inbox: Optional[bool] = None

    runtime: JobRuntimeSpec = Field(default_factory=JobRuntimeSpec)
    meta: Dict[str, Any] = Field(default_factory=dict)

    #: 个人任务归属（S2 用户个人平面）：owner_user_id 非空=个人任务，仅
    #: owner 本人 + 平台管理员可见可改（跨人严格隔离）；为空=员工共享任务
    #: （S1，使用授权内全员可见，员工级管理授权者可写）。随 spec 序列化
    #: 在 json（jobs.json）与 pg（cron_jobs.spec JSONB + 投影列）两平面往返。
    owner_user_id: Optional[str] = None
    #: owner 部门归属快照（写入时经 org 目录解析，ops 检索/归属统计用；
    #: 无 PG 或 owner 无部门时为 None）。存部门 path（本系统部门稳定标识，
    #: 与 RBAC ``dept:{path}`` 团队镜像同源）。
    department_id: Optional[str] = None
    #: owner 项目归属快照（预留列；个人定时任务暂无项目维度，恒 None）。
    project_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_task_type_fields(self) -> "CronJobSpec":
        if self.task_type == "text":
            if not (self.text and self.text.strip()):
                raise ValueError("task_type is text but text is empty")
            if self.dispatch.silent:
                raise ValueError(
                    "silent delivery is only supported for agent tasks",
                )
            self.request = None
        elif self.task_type == "agent":
            if self.request is None:
                raise ValueError("task_type is agent but request is missing")
            # Keep request.user_id and request.session_id in sync with target
            target = self.dispatch.target
            self.request = self.request.model_copy(
                update={
                    "user_id": target.user_id,
                    "session_id": target.session_id,
                },
            )
        if self.save_result_to_inbox is None:
            # Product rule:
            # - text + recurring(cron) => default OFF
            # - all other combinations => default ON
            self.save_result_to_inbox = not (
                self.task_type == "text" and self.schedule.type == "cron"
            )
        return self


class JobsFile(BaseModel):
    version: int = 2
    jobs: list[CronJobSpec] = Field(default_factory=list)


class CronJobState(BaseModel):
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_status: Optional[
        Literal["success", "error", "running", "skipped", "cancelled"]
    ] = None
    last_error: Optional[str] = None


class CronExecutionRecord(BaseModel):
    run_at: datetime
    status: Literal["success", "error", "running", "skipped", "cancelled"]
    error: Optional[str] = None
    trigger: Literal["scheduled", "manual"] = "scheduled"
    #: 关联 agent_runs 的运行 ID（agent 任务执行后回填，执行详情跳转键）
    run_id: Optional[str] = None
    #: 本次执行落库的会话 ID（share_session=False 时为 cron:{job_id}）
    session_id: Optional[str] = None
    #: 执行结果摘要（final_text 截断 500 字，worklog 时间线标题来源）
    result_summary: Optional[str] = None
    #: 调度槽位时间（trigger=scheduled 时取 run_at，手动触发为空）
    scheduled_for: Optional[datetime] = None


class CronJobView(BaseModel):
    spec: CronJobSpec
    state: CronJobState = Field(default_factory=CronJobState)


class CronDispatchTargetItem(BaseModel):
    channel: str
    user_id: str
    session_id: str


class CronDispatchTargetsResponse(BaseModel):
    channels: list[str] = Field(default_factory=list)
    items: list[CronDispatchTargetItem] = Field(default_factory=list)
