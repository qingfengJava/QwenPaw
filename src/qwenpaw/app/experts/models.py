# -*- coding: utf-8 -*-
"""Pydantic models for the expert / expert-team domain."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

EXPERT_STATUS_DRAFT = "draft"
EXPERT_STATUS_PUBLISHED = "published"
EXPERT_STATUS_ARCHIVED = "archived"
EXPERT_STATUSES = (
    EXPERT_STATUS_DRAFT,
    EXPERT_STATUS_PUBLISHED,
    EXPERT_STATUS_ARCHIVED,
)

TEAM_MODE_ROUTER = "router"
TEAM_MODE_PIPELINE = "pipeline"
TEAM_MODES = (TEAM_MODE_ROUTER, TEAM_MODE_PIPELINE)

#: Pipeline chains are capped to keep turn latency bounded.
MAX_PIPELINE_MEMBERS = 3

# ---------------------------------------------------------------------------
# Catalog (market) constants — the expert marketplace plane.
# ---------------------------------------------------------------------------

#: Visibility of a custom expert. ``org`` is visible to every employee
#: (subject to RBAC grants); ``private`` restricts the market listing and
#: the detail view to the owner. ``department`` / ``shared`` are reserved
#: for the future permission rollout (no schema change needed).
EXPERT_VISIBILITY_ORG = "org"
EXPERT_VISIBILITY_PRIVATE = "private"
EXPERT_VISIBILITIES = (EXPERT_VISIBILITY_ORG, EXPERT_VISIBILITY_PRIVATE)

#: Market sort modes surfaced by ``GET /api/xian/experts?sort=``.
EXPERT_SORT_COMPOSITE = "composite"
EXPERT_SORT_HOT = "hot"
EXPERT_SORT_NEW = "new"
EXPERT_SORTS = (EXPERT_SORT_COMPOSITE, EXPERT_SORT_HOT, EXPERT_SORT_NEW)

#: Bound skills per expert are capped to keep the injected frontmatter
#: (≈100-300 tokens each) a bounded share of the context window.
MAX_EXPERT_SKILLS = 8

#: Builtin category dictionary for the market tabs (single source of
#: truth for both the API ``/expert-categories`` endpoint and the builtin
#: seed below). Keys are stored in ``experts.category``.
EXPERT_CATEGORIES: List[Dict[str, str]] = [
    {"key": "general", "label": "通用", "icon": "fa-solid fa-layer-group"},
    {
        "key": "research",
        "label": "研究分析",
        "icon": "fa-solid fa-magnifying-glass-chart",
    },
    {"key": "writing", "label": "内容创作", "icon": "fa-solid fa-pen-nib"},
    {"key": "dev", "label": "技术工程", "icon": "fa-solid fa-code"},
    {"key": "data", "label": "数据分析", "icon": "fa-solid fa-chart-line"},
    {"key": "business", "label": "商业咨询", "icon": "fa-solid fa-briefcase"},
    {"key": "office", "label": "办公提效", "icon": "fa-solid fa-bolt"},
]

#: Member roles inside an expert team (``lead`` renders the 主理人 badge).
TEAM_MEMBER_ROLE_LEAD = "lead"
TEAM_MEMBER_ROLE_MEMBER = "member"
TEAM_MEMBER_ROLES = (TEAM_MEMBER_ROLE_LEAD, TEAM_MEMBER_ROLE_MEMBER)


def expert_agent_id(expert_id: str) -> str:
    """Runtime agent id for one published expert."""
    return f"expert_{expert_id}"


def expert_team_agent_id(team_id: str) -> str:
    """Runtime agent id for one published expert team supervisor."""
    return f"team_{team_id}"


class ExpertSkillBinding(BaseModel):
    """One skill attached to an expert (the shared registry is authoritative)."""

    expert_id: str = ""
    skill_name: str
    enabled: bool = True
    seq: int = 0


class ExpertRecord(BaseModel):
    """One managed expert (draft or published agent definition)."""

    id: str
    name: str
    icon: str = ""
    description: str = ""
    agent_spec: Dict[str, Any] = Field(default_factory=dict)
    status: str = EXPERT_STATUS_DRAFT
    version: int = 1
    owner_id: Optional[str] = None
    visibility: str = EXPERT_VISIBILITY_ORG
    is_builtin: bool = False
    title: str = ""
    category: str = "general"
    badge: str = ""
    tags: List[str] = Field(default_factory=list)
    system_prompt: str = ""
    usage_count: int = 0
    featured: bool = False
    #: "专家帮你做"任务模板 [{title, prompt}]（详情页点击即以 prompt
    #: 为 kickoff 召唤；管理端可编辑的运营位）
    sample_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    #: 使用案例 [{title, desc, tags}]（静态运营位，管理端可编辑）
    showcase: List[Dict[str, Any]] = Field(default_factory=list)
    # --- 数字员工档案列（20260830 能力层，见 docs/design/
    # --- 2026-08-30-digital-employee-capability-layer.md 决策 D1）---
    #: 部门（档案展示与统计维度；组织树关联为后续版本预留）
    department: str = ""
    #: 工作风格（如 ["耐心细致", "结果导向"]，档案卡标签行）
    work_styles: List[str] = Field(default_factory=list)
    #: 工作方式（如 ["7x24 值守", "定时巡检"]，档案卡标签行）
    work_modes: List[str] = Field(default_factory=list)
    #: 入职时间（None=未填）
    hire_date: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    #: Skill bindings (populated by the detail endpoint / publish chain,
    #: not a persisted column on ``experts``).
    skills: List[ExpertSkillBinding] = Field(default_factory=list)


class TeamMember(BaseModel):
    """One expert inside a team (ordered)."""

    expert_id: str
    role_hint: str = ""
    member_role: str = TEAM_MEMBER_ROLE_MEMBER
    seq: int = 0


class ExpertTeamRecord(BaseModel):
    """One expert team (multi-agent orchestration)."""

    id: str
    name: str
    description: str = ""
    mode: str = TEAM_MODE_ROUTER
    router_prompt: str = ""
    status: str = EXPERT_STATUS_DRAFT
    version: int = 1
    owner_id: Optional[str] = None
    category: str = "general"
    tags: List[str] = Field(default_factory=list)
    #: Reserved for the runtime orchestrator (parallel groups / DAG /
    #: per-member task templates). Read by a future RuntimeTeamOrchestrator.
    orchestration: Dict[str, Any] = Field(default_factory=dict)
    #: "任务示例"模板 [{title, prompt}]（详情页点击即以 prompt 为 goal
    #: 创建专家团 run；管理端可编辑的运营位）
    sample_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    #: 使用案例 [{title, desc, tags}]（静态运营位；与 team_runs 真实
    #: 交付投影"最近交付"分区并存）
    showcase: List[Dict[str, Any]] = Field(default_factory=list)
    members: List[TeamMember] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PublishedSnapshot(BaseModel):
    """One immutable published version of an expert."""

    expert_id: str
    version: int
    spec: Dict[str, Any] = Field(default_factory=dict)
    published_by: str = ""
    published_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class ExpertCreateBody(BaseModel):
    name: str
    icon: str = ""
    description: str = ""
    agent_spec: Dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    category: str = "general"
    badge: str = ""
    tags: List[str] = Field(default_factory=list)
    system_prompt: str = ""
    visibility: str = EXPERT_VISIBILITY_ORG
    skills: List[ExpertSkillBinding] = Field(default_factory=list)
    #: "专家帮你做"任务模板 / 使用案例（运营位，可空）
    sample_tasks: Optional[List[Dict[str, Any]]] = None
    showcase: Optional[List[Dict[str, Any]]] = None
    #: 数字员工档案字段（部门/工作风格/工作方式/入职时间）
    department: str = ""
    work_styles: Optional[List[str]] = None
    work_modes: Optional[List[str]] = None
    hire_date: Optional[datetime] = None


class ExpertUpdateBody(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    agent_spec: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    category: Optional[str] = None
    badge: Optional[str] = None
    tags: Optional[List[str]] = None
    system_prompt: Optional[str] = None
    visibility: Optional[str] = None
    #: "专家帮你做"任务模板 / 使用案例（传 list 整体替换；None=不修改）
    sample_tasks: Optional[List[Dict[str, Any]]] = None
    showcase: Optional[List[Dict[str, Any]]] = None
    #: 数字员工档案字段（None=不修改；work_styles/work_modes 传 list
    #: 整体替换；hire_date 传 None 语义为"不修改"，置空走置空表单字段
    #: ``hire_date_clear``）
    department: Optional[str] = None
    work_styles: Optional[List[str]] = None
    work_modes: Optional[List[str]] = None
    hire_date: Optional[datetime] = None
    hire_date_clear: bool = False


class ExpertSkillsBody(BaseModel):
    """Whole-list replacement of one expert's skill bindings."""

    skills: List[ExpertSkillBinding] = Field(default_factory=list)


class TeamMemberBody(BaseModel):
    expert_id: str
    role_hint: str = ""
    member_role: str = TEAM_MEMBER_ROLE_MEMBER
    seq: int = 0


class ExpertTeamCreateBody(BaseModel):
    name: str
    description: str = ""
    mode: str = TEAM_MODE_ROUTER
    router_prompt: str = ""
    category: str = "general"
    tags: List[str] = Field(default_factory=list)
    members: List[TeamMemberBody] = Field(default_factory=list)
    #: 运行时编排配置（OrchestrationSpec：nodes/policy/plan_note/
    #: runtime_enabled），管理端 workforce 编排编辑面写入；为空表示
    #: 不预置 DAG 模板，规划时走中央大脑 LLM 生成。
    orchestration: Optional[Dict[str, Any]] = None
    #: "任务示例"模板 / 使用案例（运营位，可空）
    sample_tasks: Optional[List[Dict[str, Any]]] = None
    showcase: Optional[List[Dict[str, Any]]] = None


class ExpertTeamUpdateBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    router_prompt: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    members: Optional[List[TeamMemberBody]] = None
    #: 运行时编排配置（同上）；传空 dict 表示清除模板（回到 LLM 规划）。
    orchestration: Optional[Dict[str, Any]] = None
    #: "任务示例"模板 / 使用案例（运营位，可空）
    sample_tasks: Optional[List[Dict[str, Any]]] = None
    showcase: Optional[List[Dict[str, Any]]] = None


# ---------------------------------------------------------------------------
# 数字员工能力层（20260830，StaffDeck 能力移植）
# 设计依据: docs/design/2026-08-30-digital-employee-capability-layer.md
# ---------------------------------------------------------------------------

#: 能力挂载资源类型（expert_resource_bindings.resource_type；
#: 技能绑定不在此列——expert_skills 是发布物化链的权威）
RESOURCE_TYPE_SOP = "sop"
RESOURCE_TYPE_KNOWLEDGE_BASE = "knowledge_base"
RESOURCE_TYPE_TOOL = "tool"
RESOURCE_TYPES = (
    RESOURCE_TYPE_SOP,
    RESOURCE_TYPE_KNOWLEDGE_BASE,
    RESOURCE_TYPE_TOOL,
)

#: 员工记忆分桶（expert_memories.kind）
MEMORY_KIND_PROFILE = "profile"
MEMORY_KIND_PREFERENCE = "preference"
MEMORY_KIND_FACT = "fact"
MEMORY_KINDS = (MEMORY_KIND_PROFILE, MEMORY_KIND_PREFERENCE, MEMORY_KIND_FACT)

#: SOP 状态机（sops.status；publish 写版本快照，archive 保留历史）
SOP_STATUS_DRAFT = "draft"
SOP_STATUS_PUBLISHED = "published"
SOP_STATUS_ARCHIVED = "archived"
SOP_STATUSES = (SOP_STATUS_DRAFT, SOP_STATUS_PUBLISHED, SOP_STATUS_ARCHIVED)

#: 定时任务状态（expert_scheduled_tasks.status）
TASK_STATUS_ACTIVE = "active"
TASK_STATUS_PAUSED = "paused"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_ARCHIVED = "archived"
TASK_STATUSES = (
    TASK_STATUS_ACTIVE,
    TASK_STATUS_PAUSED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_ARCHIVED,
)

#: 演进提案生命周期（evolution_proposals.status）
PROPOSAL_STATUS_DRAFT = "draft"
PROPOSAL_STATUS_READY_FOR_REVIEW = "ready_for_review"
PROPOSAL_STATUS_APPROVED = "approved"
PROPOSAL_STATUS_REJECTED = "rejected"
PROPOSAL_STATUS_PUBLISHED = "published"
PROPOSAL_STATUS_ROLLED_BACK = "rolled_back"
PROPOSAL_STATUSES = (
    PROPOSAL_STATUS_DRAFT,
    PROPOSAL_STATUS_READY_FOR_REVIEW,
    PROPOSAL_STATUS_APPROVED,
    PROPOSAL_STATUS_REJECTED,
    PROPOSAL_STATUS_PUBLISHED,
    PROPOSAL_STATUS_ROLLED_BACK,
)


class ResourceBinding(BaseModel):
    """One capability mounted on an expert (sop / knowledge_base / tool).

    技能绑定见 :class:`ExpertSkillBinding`（expert_skills 表，发布链权威）；
    本模型只承载 StaffDeck 式的另外三类挂载。``metadata`` 存挂载时名称
    快照，资源本体删除后列表仍可显示（防悬挂）。
    """

    expert_id: str = ""
    resource_type: str
    resource_id: str
    enabled: bool = True
    seq: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResourceBindingsBody(BaseModel):
    """Whole-list replacement of one expert's resource bindings (per type)."""

    bindings: List[ResourceBinding] = Field(default_factory=list)


class SopRecord(BaseModel):
    """One SOP process asset (StaffDeck 式经验流程的结构化载体)。

    节点 ``expected_outcome`` 是给 workforce Verifier 的验收要点；执行期
    SOP 只作为规划参考注入（决策 D3），绝不是硬状态机。
    """

    id: str
    name: str
    description: str = ""
    business_domain: str = ""
    #: 流程总目标（一句话，注入规划上下文的锚点）
    goal: str = ""
    #: 节点 [{id, title, instruction, expected_outcome, tools[]}]
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    #: 边 [{from, to, condition}]
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    #: 槽位 [{key, label, required, ask_prompt}]
    slots: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = SOP_STATUS_DRAFT
    version: int = 1
    owner_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SopCreateBody(BaseModel):
    name: str
    description: str = ""
    business_domain: str = ""
    goal: str = ""
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)
    slots: List[Dict[str, Any]] = Field(default_factory=list)


class SopUpdateBody(BaseModel):
    """Draft-only field updates (published SOPs go through versions)."""

    name: Optional[str] = None
    description: Optional[str] = None
    business_domain: Optional[str] = None
    goal: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    slots: Optional[List[Dict[str, Any]]] = None


class SopVersionRecord(BaseModel):
    """One immutable published version snapshot of a SOP."""

    sop_id: str
    version: int
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    change_note: str = ""
    published_by: Optional[str] = None
    created_at: Optional[datetime] = None


class MemoryRecord(BaseModel):
    """One bucketed long-term memory of an expert (towards a user)."""

    id: str
    expert_id: str
    #: ''=组织级公共记忆（所有用户共享）
    user_id: str = ""
    kind: str = MEMORY_KIND_FACT
    content: str
    #: 0~1，物化时按重要度+时间排序截断
    importance: float = 0.5
    #: 语义去重键（同 expert+user+kind 内唯一，upsert 锚点）
    dedup_key: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MemoryUpsertBody(BaseModel):
    """Create/update one memory (dedup_key empty = always insert)."""

    user_id: str = ""
    kind: str = MEMORY_KIND_FACT
    content: str
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    dedup_key: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ScheduledTaskRecord(BaseModel):
    """One expert scheduled task (projection; authority = CronManager)."""

    id: str
    expert_id: str
    name: str
    description: str = ""
    #: 触发时投给专家的任务指令
    task_prompt: str
    #: cron | once
    schedule_type: str = "cron"
    #: cron: {"cron": "0 9 * * 1-5"}；once: {"run_at": ISO8601}
    schedule_json: Dict[str, Any] = Field(default_factory=dict)
    timezone: str = "Asia/Shanghai"
    status: str = TASK_STATUS_ACTIVE
    #: CronManager 权威 job id（expert_task_<id>；空=尚未注册）
    cron_job_id: str = ""
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    #: succeeded | failed | running | ''
    last_status: str = ""
    run_count: int = 0
    owner_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ScheduledTaskCreateBody(BaseModel):
    name: str
    description: str = ""
    task_prompt: str
    schedule_type: str = "cron"
    schedule_json: Dict[str, Any] = Field(default_factory=dict)
    timezone: str = "Asia/Shanghai"


class ScheduledTaskUpdateBody(BaseModel):
    """None = 不修改（与专家编辑体同语义）。"""

    name: Optional[str] = None
    description: Optional[str] = None
    task_prompt: Optional[str] = None
    schedule_json: Optional[Dict[str, Any]] = None
    timezone: Optional[str] = None


class TaskRunRecord(BaseModel):
    """One execution record of a scheduled task (idempotent per trigger)."""

    id: str
    task_id: str
    expert_id: str
    #: 计划触发点（幂等锚；NULL=手动 run-now）
    scheduled_for: Optional[datetime] = None
    #: running | succeeded | failed
    status: str = "running"
    result_summary: str = ""
    error: str = ""
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class FeedbackBody(BaseModel):
    """One message rating (upsert per message+user)."""

    message_id: str
    session_id: str = ""
    expert_id: str = ""
    #: up | down
    rating: str
    comment: str = ""


class EvolutionProposal(BaseModel):
    """One feedback-driven change proposal (human review lifecycle)."""

    id: str
    expert_id: str
    title: str
    #: feedback | manual | audit
    trigger_type: str = "feedback"
    #: low | medium | high
    risk_level: str = "low"
    #: 改进假设（为什么这个变更能解决问题）
    hypothesis: str = ""
    #: 证据（反馈 id/消息摘录/统计数据）
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    #: 变更体 {target: sop|system_prompt|skills, ...diff}
    candidate: Dict[str, Any] = Field(default_factory=dict)
    status: str = PROPOSAL_STATUS_DRAFT
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class EvolutionCreateBody(BaseModel):
    expert_id: str
    title: str
    trigger_type: str = "manual"
    risk_level: str = "low"
    hypothesis: str = ""
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    candidate: Dict[str, Any] = Field(default_factory=dict)


class EvolutionReviewBody(BaseModel):
    """Approve/reject a proposal under review."""

    #: approve | reject
    action: str


class WorkRecord(BaseModel):
    """Aggregated work record of one expert (read-only view, D6).

    数据来源全部是既有权威表：任务留痕 team_runs/team_run_nodes、定时
    执行 expert_task_runs、反馈 message_feedback、动态 feed_events——
    本视图不建流水新表。
    """

    #: 统计窗口（天）
    days: int = 30
    #: 窗口内任务总数（team_runs + expert_task_runs）
    total_tasks: int = 0
    #: 窗口内成功任务数
    succeeded_tasks: int = 0
    #: 窗口内好评数 / 差评数 / 好评率（0~1，无反馈时 None）
    feedback_up: int = 0
    feedback_down: int = 0
    positive_rate: Optional[float] = None
    #: 按天活动密度 [{date: "2026-08-30", tasks: n, feedback: n}]
    by_day: List[Dict[str, Any]] = Field(default_factory=list)
    #: 最近事件时间线 [{kind, title, status, at}]（最多 50 条）
    timeline: List[Dict[str, Any]] = Field(default_factory=list)
