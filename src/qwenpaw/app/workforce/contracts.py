# -*- coding: utf-8 -*-
"""Workforce 契约层：两级 Harness 的结构化数据协议。

本模块是"企业级数字员工平台"的宪法层（Harness Runtime
Specification 的数据载体），定义中央大脑（L1 Workforce ReAct）与
子员工（L2 Employee Harness）之间传递的全部结构化对象：

- :class:`TaskContract`    中央大脑交给子员工的"任务事实"
- :class:`ResultContract`  子员工结构化回传的执行结果
- :class:`RepairContract`  验收失败后的返工指令
- :class:`HandoverContract` 跨用户数字员工移交契约
- :class:`DagPlan` / :class:`DagNode` 任务图（Plan-then-Execute 的产物）
- :class:`ContextBundle`   版本化的全局任务事实（Context Fabric）
- :class:`RunPolicy`       熔断策略（纯计数器，不依赖模型自觉）
- :class:`OrchestrationSpec` expert_teams.orchestration JSONB 的 schema

硬约束：本文件只允许依赖 pydantic / 标准库 / ``verification.kernel``
（纯契约层，无引擎依赖），禁止 import 任何引擎模块（import 方向单向：
引擎 → 契约），保证契约可独立单测与跨层复用。裁决常量与返工指令字段
集以 ``verification.kernel`` 为单一来源，本文件只保留 L1 专属字段。

@author qingfeng
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from ...verification.kernel import (
    FAILURE_KIND_DEPENDENCY_CHANGED,
    FAILURE_KIND_REPAIRABLE,
    FAILURE_KIND_STRUCTURAL,
    RepairBrief,
    VERDICT_ESCALATE,
    VERDICT_FAIL,
    VERDICT_PASS,
)

# ---------------------------------------------------------------------------
# 状态常量（run 级 / 节点级状态机，与 team_runs / team_run_nodes 表对齐）
# ---------------------------------------------------------------------------

#: run 级状态：规划中（读模板或调用中央大脑生成 DagPlan）
RUN_STATUS_PLANNING = "planning"
#: run 级状态：等待用户澄清（需求不明时挂起，不消耗执行预算）
RUN_STATUS_AWAITING_CONFIRM = "awaiting_confirm"
#: run 级状态：执行中（波次拓扑调度子员工）
RUN_STATUS_RUNNING = "running"
#: run 级状态：验收中（节点级验收或全局汇总验收）
RUN_STATUS_VERIFYING = "verifying"
#: run 级状态：返工中（存在节点正在按 RepairContract 重跑）
RUN_STATUS_REPAIRING = "repairing"
#: run 级状态：汇总中（全部节点完成后中央大脑产出最终结果）
RUN_STATUS_AGGREGATING = "aggregating"
#: run 级终态：成功完成
RUN_STATUS_DONE = "done"
#: run 级终态：失败（不可恢复错误，如 DAG 非法、全部成员不可用）
RUN_STATUS_FAILED = "failed"
#: run 级终态：熔断升级人工（Human Escalation，等待人工裁决）
RUN_STATUS_ESCALATED = "escalated"
#: run 级终态：用户取消
RUN_STATUS_CANCELED = "canceled"
#: run 级状态：进程中断（启动恢复扫描将 running 改写为此状态，可续跑）
RUN_STATUS_INTERRUPTED = "interrupted"
#: run 级状态：用户暂停（协作暂停，非终态；resume 从持久视图恢复）
RUN_STATUS_PAUSED = "paused"

#: run 状态全集（用于路由校验与测试断言）
RUN_STATUSES = (
    RUN_STATUS_PLANNING,
    RUN_STATUS_AWAITING_CONFIRM,
    RUN_STATUS_RUNNING,
    RUN_STATUS_VERIFYING,
    RUN_STATUS_REPAIRING,
    RUN_STATUS_AGGREGATING,
    RUN_STATUS_DONE,
    RUN_STATUS_FAILED,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_CANCELED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_PAUSED,
)

#: run 活跃态集合（进程重启时需扫描改写为 interrupted 的状态）
RUN_ACTIVE_STATUSES = (
    RUN_STATUS_PLANNING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_VERIFYING,
    RUN_STATUS_REPAIRING,
    RUN_STATUS_AGGREGATING,
)

#: 启动恢复扫描范围：重启后可能仍存在在途引擎工作的状态。
#: awaiting_confirm 刻意排除——该状态本无在途任务（挂起等用户澄清），
#: 若被改写为 interrupted，澄清答复接口（只接受 awaiting_confirm）
#: 将永久 409，澄清流程在重启后彻底死锁。
RUN_INTERRUPTIBLE_STATUSES = (
    RUN_STATUS_PLANNING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_VERIFYING,
    RUN_STATUS_REPAIRING,
    RUN_STATUS_AGGREGATING,
)

#: 节点状态：待执行（依赖未满足）
NODE_STATUS_PENDING = "pending"
#: 节点状态：已委派（委派请求已发出）
NODE_STATUS_DELEGATED = "delegated"
#: 节点状态：执行中
NODE_STATUS_RUNNING = "running"
#: 节点状态：验收中
NODE_STATUS_VERIFYING = "verifying"
#: 节点状态：返工中（按 RepairContract 重跑）
NODE_STATUS_REPAIRING = "repairing"
#: 节点终态：成功完成
NODE_STATUS_DONE = "done"
#: 节点终态：失败
NODE_STATUS_FAILED = "failed"

#: 节点活跃态集合（启动恢复时需重置回 pending 的中间状态）
NODE_ACTIVE_STATUSES = (
    NODE_STATUS_DELEGATED,
    NODE_STATUS_RUNNING,
    NODE_STATUS_VERIFYING,
    NODE_STATUS_REPAIRING,
)

#: 节点类型：普通任务节点
NODE_TYPE_TASK = "task"
#: 节点类型：返工节点（由 RepairContract 派生，附着在原节点 attempt 上）
NODE_TYPE_REPAIR = "repair"
#: 节点类型：集成节点（聚合上游产出）
NODE_TYPE_INTEGRATION = "integration"
#: 节点类型：最终汇总节点（中央大脑产出最终结果）
NODE_TYPE_FINAL = "final"
#: 节点类型：澄清节点（需求不明时向用户提问）
NODE_TYPE_CLARIFY = "clarify"

#: 验收裁决三态（VERDICT_PASS / VERDICT_FAIL / VERDICT_ESCALATE）单一来源为
#: ``verification.kernel``，本模块仅顶部 import 后 re-export，禁止在此重定义

#: ResultContract 的完成状态枚举
RESULT_STATUS_COMPLETED = "COMPLETED"
#: ResultContract 的失败状态枚举
RESULT_STATUS_FAILED = "FAILED"
#: ResultContract 的部分完成状态枚举（可验收但需注意）
RESULT_STATUS_PARTIAL = "PARTIAL"


# ---------------------------------------------------------------------------
# Context Fabric：版本化上下文束（节点间 / 跨用户传递的唯一介质）
# ---------------------------------------------------------------------------


class ContextBundle(BaseModel):
    """版本化的全局任务事实（禁止聊天记录透传，本对象是唯一传递介质）。

    全局决策（如技术选型确定）变更时 bump ``version``，后续所有节点
    契约引用新版本号——子员工拿到的是"一个明确版本的任务事实"，
    而不是"最新聊天记录"，从结构上杜绝信息偏差。
    """

    #: 全局上下文：项目背景、业务目标、已确定的全局决策（架构选型等）
    global_ctx: Dict[str, Any] = Field(default_factory=dict)
    #: 任务上下文：原始需求原文、澄清问答记录、发起人信息
    task_ctx: Dict[str, Any] = Field(default_factory=dict)
    #: 执行上下文：已完成节点的 ResultContract 摘要投影（node_key -> 摘要）
    execution_ctx: Dict[str, Any] = Field(default_factory=dict)
    #: 上下文版本号（单调递增；全局决策变更 / 澄清答复 / 移交时 +1）
    version: int = 1
    #: 版本历史轨迹 [{version, reason}]（有界：只保留最近 _MAX 条）
    #: ——V1→V4 的演进可追溯，每条记录版本变更的业务原因
    history: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 三大契约：Task / Result / Repair
# ---------------------------------------------------------------------------


class TaskContract(BaseModel):
    """中央大脑交给子员工的"任务事实"（对齐用户架构方案第七节）。

    委派器将其投影为结构化 prompt 发给成员专家；子员工只能看到
    本契约内容（最小充分上下文），看不到全局 DAG 与原始对话流。
    """

    #: 节点标识（与 team_run_nodes.node_key 一致）
    task_id: str
    # ---- 版本身份（协议05：任务契约记录完整版本向量；缺省兼容旧数据） ----
    #: 所属运行标识（team_runs.id；模板预览等场景允许为空）
    run_id: str = ""
    #: 计划修订版本（重规划递增；0=未登记）
    plan_revision: int = 0
    #: 指派修订版本（改派递增；0=未登记）
    assignment_revision: int = 0
    #: 需求基线修订版本（RequirementBrief.revision）
    requirement_revision: int = 0
    #: 引用的上下文束版本（ContextBundle.version）
    context_version: int = 0
    #: 业务责任人展示名（人工负责人或 Leader，非执行者）
    owner_display: str = ""
    #: 风险等级（高风险动作须另行审批，低风险契约不豁免治理）
    risk_level: Literal["low", "medium", "high"] = "low"
    #: 是否允许内部再拆分子任务（协议13：新团队默认关闭自由递归委派）
    allow_subtask_split: bool = False
    #: 本节点的目标（一句话说清"要完成什么"）
    objective: str
    #: 全局上下文不可变快照（含 context_version，引自 ContextBundle）
    global_context: Dict[str, Any] = Field(default_factory=dict)
    #: 父决策清单（中央大脑已确定、子员工必须遵守的决策）
    parent_decision: List[str] = Field(default_factory=list)
    #: 依赖说明（上游节点产出物与状态，供子员工对齐边界）
    dependencies: Dict[str, str] = Field(default_factory=dict)
    #: 期望产出清单（明确交付物）
    expected_output: List[str] = Field(default_factory=list)
    #: 约束条件（必须遵守的硬性要求）
    constraints: List[str] = Field(default_factory=list)
    #: 验收标准（中央大脑按此裁决 PASS/FAIL）
    quality_criteria: List[str] = Field(default_factory=list)
    #: 可用技能（来自 expert_skills 绑定，能力=Skill）
    available_skills: List[str] = Field(default_factory=list)
    #: 可用工具（成员专家 agent 已装配的工具，动作=Tool）
    available_tools: List[str] = Field(default_factory=list)
    #: 绑定 SOP 参考（能力挂载，20260830 P1）：[{name, goal,
    #: steps: [{t: 步骤, ok: 验收要点}]}]——经验路径参考而非硬状态机；
    #: 验收要点由规划器并入 quality_criteria，Verifier 裁决自动覆盖
    sop_refs: List[Dict[str, Any]] = Field(default_factory=list)
    #: 上游节点结果摘要投影（仅注入依赖节点的 ResultContract 摘要）
    upstream_summaries: Dict[str, Any] = Field(default_factory=dict)


class ResultContract(BaseModel):
    """子员工结构化回传的执行结果（对齐用户架构方案第十九节）。

    委派器要求成员专家按本 schema 输出 JSON；解析顺序为 ```json 围栏
    → 裸 JSON → 降级为自由文本 + ``needs_review=True``，绝不阻塞链路。
    """

    #: 对应的节点标识
    task_id: str = ""
    #: 执行状态：COMPLETED / PARTIAL / FAILED
    status: str = RESULT_STATUS_COMPLETED
    #: 结果正文（自由结构：文本、文件清单、结构化数据均可）
    result: Dict[str, Any] = Field(default_factory=dict)
    #: 结果正文之外的纯文本产出（模型自然语言回复，兜底承载）
    result_text: str = ""
    #: 证据（文件路径、引用来源等可核查痕迹）
    evidence: List[str] = Field(default_factory=list)
    #: 执行中做出的决策（供中央大脑审计与后续节点引用）
    decisions: List[str] = Field(default_factory=list)
    #: 假设（子员工自行假设、未与用户确认的事项）
    assumptions: List[str] = Field(default_factory=list)
    #: 遗留问题（未解决但需要上报的事项）
    issues: List[str] = Field(default_factory=list)
    #: 置信度（0~1，模型自评）
    confidence: float = 0.8
    #: 是否需要人工复核（解析降级 / 低置信度时置 True）
    needs_review: bool = False
    #: 本节点 token 消耗（委派器从回执 usage 统计；usage_reported=False
    #: 时该值为未知而非零，预算账本不得按 0 结算）
    token_cost: int = 0
    #: 回执是否携带真实 usage 采集（False=未知消耗，明示而非视为零）
    usage_reported: bool = False


class RepairContract(RepairBrief):
    """验收失败后的返工指令（对齐用户架构方案第二十节）。

    字段集以裁决内核 :class:`~qwenpaw.verification.kernel.RepairBrief` 为
    单一来源（L1/L2 共用），本类只额外把 ``original_task`` 收回必填：
    专家团节点级返工必须知道被返工的原节点。
    """

    #: 被返工的原节点标识（L1 硬约束：不允许缺省）
    original_task: str = Field(...)


class HandoverContract(BaseModel):
    """跨用户数字员工移交契约（项目组协同）。

    移交 = 以最新 ContextBundle 重建 TaskContract 指派目标用户的专家，
    ``context_version`` 延续不重置——A/B 双方看到同一份版本化事实。
    """

    #: 移交目标用户（必须是 project_members 成员）
    target_user_id: str
    #: 移交目标用户的专家 ID（expert_{id} 运行时标识的源）
    target_expert_id: str
    #: 移交说明（为什么移交给 TA、期望 TA 做什么）
    handover_note: str = ""
    #: 移交时携带的上下文版本（延续，不重置）
    context_version: int = 1


# ---------------------------------------------------------------------------
# 任务图：DagPlan / DagNode（Plan-then-Execute 的产物）
# ---------------------------------------------------------------------------


class DagNode(BaseModel):
    """DAG 中的一个节点（一次可委派的原子任务）。

    ``deps`` 为上游 node_key 列表；引擎按拓扑波次调度，同波次内
    受 RunPolicy.parallelism 限流并发执行。
    """

    #: 节点唯一标识（run 内唯一，如 "req-analysis" / "fe-design"）
    node_key: str
    #: 上游依赖节点（全部完成后本节点才可调度）
    deps: List[str] = Field(default_factory=list)
    #: 指派执行的专家 ID（experts.id；final/integration 可为空=中央大脑自执行）
    assignee_expert_id: str = ""
    #: 跨用户移交预留：指派给目标用户的专家（空=团队内成员）
    assignee_user_id: str = ""
    #: 节点类型：task / repair / integration / final / clarify
    #: （Literal 枚举：pydantic 严格校验，非法值直接拒绝而非静默修复）
    node_type: Literal[
        "task",
        "repair",
        "integration",
        "final",
        "clarify",
    ] = NODE_TYPE_TASK
    #: 节点目标（生成 TaskContract.objective 的种子）
    objective: str = ""
    #: 期望产出（生成 TaskContract.expected_output 的种子）
    expected_output: List[str] = Field(default_factory=list)
    #: 并行组标识（同组无依赖节点可并发；空=按拓扑自动分波）
    parallel_group: str = ""


class DagPlan(BaseModel):
    """一次专家团任务的完整任务图。

    由规划器产出：优先读取 expert_teams.orchestration 预置模板，
    无模板时中央大脑单次结构化 LLM 调用生成（Plan-then-Execute：
    规划一次，之后引擎纯代码驱动，LLM 仅在 verify/re-plan/clarify 触达）。
    """

    #: 全部节点（node_key 在 plan 内唯一）
    nodes: List[DagNode] = Field(default_factory=list)
    #: 规划说明（中央大脑的拆解思路，展示给用户）
    plan_note: str = ""
    #: 规划来源：orchestration（预置模板）/ llm（中央大脑生成）
    source: str = "orchestration"


def topological_waves(plan: DagPlan) -> List[List[str]]:
    """将 DAG 按依赖分层为可并发执行的波次列表。

    第 N 波包含所有依赖均落在前 N-1 波的节点；返回
    ``[[wave1_keys...], [wave2_keys...], ...]``。

    Raises:
        ValueError: 图中存在环、或 deps 引用了不存在的 node_key。
    """
    # 以 node_key 索引全部节点，便于依赖查表
    by_key = {node.node_key: node for node in plan.nodes}
    # 校验依赖引用存在性（悬空依赖直接报错，不静默忽略）
    for node in plan.nodes:
        for dep in node.deps:
            if dep not in by_key:
                raise ValueError(f"节点 {node.node_key} 依赖了不存在的节点: {dep}")
    # Kahn 分层：每轮摘取入度为 0 的节点作为一波
    waves: List[List[str]] = []
    placed = set()
    remaining = list(by_key.keys())
    # 防御上限：节点总数即最大波次数，超出说明有环
    while remaining:
        # 当前波：依赖全部已放置的节点
        ready = [k for k in remaining if all(d in placed for d in by_key[k].deps)]
        # 无任何节点可放置 → 存在环
        if not ready:
            raise ValueError(f"DAG 存在环，无法拓扑排序，涉事节点: {remaining}")
        # 固定顺序输出，保证波次内顺序稳定（可测试）
        ready.sort()
        waves.append(ready)
        # 标记已放置并从剩余集合移除
        placed.update(ready)
        remaining = [k for k in remaining if k not in set(ready)]
    return waves


def validate_dag(plan: DagPlan) -> List[List[str]]:
    """校验 DAG 合法性并返回波次分层（非法时抛 ValueError）。

    校验内容：node_key 唯一、依赖引用存在、无环；成员存在性检查
    在规划器层完成（需要读库，不属于纯图校验）。
    """
    # node_key 唯一性校验（重复 key 会导致主键冲突）
    keys = [node.node_key for node in plan.nodes]
    if len(keys) != len(set(keys)):
        raise ValueError("DAG 存在重复的 node_key")
    # 空图非法（至少要有 final 或一个 task 节点）
    if not keys:
        raise ValueError("DAG 不能为空")
    # 委托拓扑分层完成"引用存在 + 无环"校验
    return topological_waves(plan)


# ---------------------------------------------------------------------------
# 熔断策略：RunPolicy（纯计数器，不依赖模型自觉）
# ---------------------------------------------------------------------------


class RunPolicy(BaseModel):
    """run 级熔断策略（Human Escalation 的触发边界）。

    任一上限触发 → run 置 escalated 终态 + feed 事件 + 人工干预 API。
    刻意不用 loop/gates（那是 per-turn 停止门，语义不合 run 级返工计数）。
    """

    #: 单节点最大返工次数（repair_count 超限即熔断）
    max_repair_per_node: int = 3
    #: 全局最大重规划次数（replan_count 超限即熔断）
    max_replan: int = 2
    #: run 总时限（秒；0=不限）
    max_total_seconds: int = 3600
    #: run 总 token 预算（0=不限；聚合自 token_usage_events / 节点回执）
    max_total_tokens: int = 0
    #: 同波次最大并发委派数（叠加虚拟主体信号量的第二层限流）
    parallelism: int = 2


# ---------------------------------------------------------------------------
# orchestration JSONB schema：管理端预置 DAG 模板 + 默认策略
# ---------------------------------------------------------------------------


class OrchestrationSpec(BaseModel):
    """expert_teams.orchestration JSONB 的权威 schema（读写唯一入口）。

    管理端（console）团队编辑器产出本结构写入 expert_teams.orchestration
    （0009 迁移预留列）；规划器优先按本模板实例化 DagPlan，避免每次
    依赖 LLM 规划质量。schema 漂移由本 pydantic 模型单点拦截。
    """

    #: DAG 模板（node 定义；deps/assignee 同 DagNode）
    nodes: List[DagNode] = Field(default_factory=list)
    #: 快速链模板（小需求轻量路径；空=不支持快速模式，一律走标准链）。
    #: 规划器按意图规则选择：goal 命中复杂信号→标准链；未命中且本字段
    #: 非空→快速链（典型：跳过架构/QA 的短链，交付总监兜底把关）。
    fast_nodes: List[DagNode] = Field(default_factory=list)
    #: 默认熔断策略（创建 run 时未显式指定则使用）
    policy: Optional[RunPolicy] = None
    #: 规划说明模板
    plan_note: str = ""
    #: 是否启用运行时编排（False=回退提示词级团队，保持既有行为）
    runtime_enabled: bool = True


# ---------------------------------------------------------------------------
# 澄清对象：需求不明时的主动二次确认
# ---------------------------------------------------------------------------


class Clarification(BaseModel):
    """需求不明时中央大脑产出的澄清问题清单（run 置 awaiting_confirm）。

    用户答复（或超时保持挂起）后携带答复重入规划，bundle 版本 bump。
    """

    #: 澄清问题清单（每项是一个可直接回答的问题）
    questions: List[str] = Field(default_factory=list)
    #: 可选的快捷选项（每问一组候选答案，前端渲染成可点选项）
    options: Dict[str, List[str]] = Field(default_factory=dict)
    #: 用户答复记录（question -> answer；重入规划的输入）
    answers: Dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Harness Runtime Specification 协议对象（T-1 冻结）
#
# 本区段只承载 17 项运行协议的数据结构与纯函数（输入/输出/状态/失败语义），
# 不依赖任何引擎模块；协议到实现的接线分布在 planner/delegator/engine/
# run_store/harnesses 等既有模块（映射见计划第十四节）。
# ---------------------------------------------------------------------------

# ---- 协议01 Task Lifecycle：等待语义（v2 可恢复等待 ≠ 终态） ----

#: 等待原因：缺输入（依赖未满足）
WAIT_REASON_MISSING_INPUT = "missing_input"
#: 等待原因：需求待确认
WAIT_REASON_REQUIREMENT_CONFIRM = "requirement_confirm"
#: 等待原因：计划待批准
WAIT_REASON_PLAN_APPROVAL = "plan_approval"
#: 等待原因：风险动作待审批
WAIT_REASON_TOOL_APPROVAL = "tool_approval"
#: 等待原因：预算不足
WAIT_REASON_BUDGET = "budget"
#: 等待原因：质量升级人工
WAIT_REASON_QUALITY_ESCALATION = "quality_escalation"
#: 等待原因：员工版本漂移
WAIT_REASON_VERSION_DRIFT = "version_drift"
#: 等待原因：外部结果未知待核对
WAIT_REASON_UNKNOWN_RESULT = "unknown_result"

#: 等待原因全集（状态可恢复，等待即暂停派发并释放执行槽）
WAIT_REASONS = frozenset(
    {
        WAIT_REASON_MISSING_INPUT,
        WAIT_REASON_REQUIREMENT_CONFIRM,
        WAIT_REASON_PLAN_APPROVAL,
        WAIT_REASON_TOOL_APPROVAL,
        WAIT_REASON_BUDGET,
        WAIT_REASON_QUALITY_ESCALATION,
        WAIT_REASON_VERSION_DRIFT,
        WAIT_REASON_UNKNOWN_RESULT,
    },
)

# ---- 协议01/12：节点 v2 状态（在既有 pending..failed 上扩展） ----

#: 节点状态：已就绪（依赖满足、等待派发；v2）
NODE_STATUS_READY = "ready"
#: 节点状态：可恢复等待（配 wait_reason；v2，非终态）
NODE_STATUS_WAITING = "waiting"
#: 节点终态：已取消（v2）
NODE_STATUS_CANCELED = "canceled"
#: 节点终态：被新修订取代（重规划保留旧图时标记；v2）
NODE_STATUS_SUPERSEDED = "superseded"

# ---- 协议03 ReAct State Machine：L1 认知触发事件 ----

#: L1 认知触发：失败归因不明
REACT_TRIGGER_FAILURE_ATTRIBUTION = "failure_attribution"
#: L1 认知触发：依赖变化使当前计划失效
REACT_TRIGGER_DEPENDENCY_CHANGED = "dependency_changed"
#: L1 认知触发：需求/全局决策变化
REACT_TRIGGER_REQUIREMENT_CHANGED = "requirement_changed"
#: L1 认知触发：新信息使当前计划失效
REACT_TRIGGER_NEW_INFO = "new_info_invalidates_plan"

#: L1 认知触发全集：仅以下事件触发 Leader 重新思考；
#: 正常 DAG 推进不消耗认知调用（普通工具进度只推进事件序号）
REACT_TRIGGERS = frozenset(
    {
        REACT_TRIGGER_FAILURE_ATTRIBUTION,
        REACT_TRIGGER_DEPENDENCY_CHANGED,
        REACT_TRIGGER_REQUIREMENT_CHANGED,
        REACT_TRIGGER_NEW_INFO,
    },
)

# ---- 协议13 Memory：作用域与组织经验晋级顺序 ----

#: 记忆作用域：一次执行的短期状态
MEMORY_SCOPE_WORKING = "working"
#: 记忆作用域：本次委托的修订与产物
MEMORY_SCOPE_TASK = "task"
#: 记忆作用域：受用户/员工作用域隔离的持久偏好
MEMORY_SCOPE_EMPLOYEE = "employee"
#: 记忆作用域：受审核的稳定事实与组织经验
MEMORY_SCOPE_ORG = "org"

#: 组织经验进入共享知识的治理动作顺序（缺步即不得发布）
MEMORY_ORG_PROMOTION_STEPS = (
    "propose",
    "sanitize",
    "dedupe",
    "approve",
    "publish",
)


class RequirementBrief(BaseModel):
    """需求基线（协议04 规划输入；L1 需求确认的版本化产物）。

    聊天中的"只调研、不要下单"必须落入 ``exclusions`` /
    ``resource_scope`` 成为可校验的执行约束，而不是对话里的一句话。
    """

    #: 需求修订版本（澄清/范围变更递增）
    revision: int = 1
    #: 原始需求引用（聊天/工单/文档的定位标识）
    source_ref: str = ""
    #: 业务目标（一句话）
    business_goal: str = ""
    #: 范围：做什么
    scope: List[str] = Field(default_factory=list)
    #: 范围：明确不做什么（硬约束）
    exclusions: List[str] = Field(default_factory=list)
    #: 用户已提供的输入
    inputs: List[str] = Field(default_factory=list)
    #: 输入缺口（澄清问题的依据；清空后方可进入计划批准）
    input_gaps: List[str] = Field(default_factory=list)
    #: 交付物清单
    deliverables: List[str] = Field(default_factory=list)
    #: 验收标准（最终全局验收的尺子）
    acceptance: List[str] = Field(default_factory=list)
    #: 绝对期限（ISO 8601 字符串；空=未约定）
    deadline: str = ""
    #: 已识别风险
    risks: List[str] = Field(default_factory=list)
    #: 授权资源范围（可访问的业务资源/动作类型）
    resource_scope: List[str] = Field(default_factory=list)
    #: 未确认假设（不得作为已确认事实传播）
    unconfirmed_assumptions: List[str] = Field(default_factory=list)


class ContextVector(BaseModel):
    """五类上下文的版本向量（协议06）。

    Global/Task/Employee/Execution/Result 各自独立递增；
    普通工具进度只推进 execution_revision，不提升全局决策版本。
    """

    #: 全局决策版本
    global_revision: int = 1
    #: 任务事实版本
    task_revision: int = 1
    #: 员工能力投影版本
    employee_revision: int = 1
    #: 执行进度版本
    execution_revision: int = 1
    #: 结果事实版本
    result_revision: int = 1


class TrustedExecutionEnvelope(BaseModel):
    """服务端控制面可信载荷（协议02/16）。

    租户、发起人、委托范围与授权边界仅由服务端控制面生成与校验；
    模型输出、外部请求或成员回执不可覆盖其任何字段。与业务语义的
    "Execution Context"（执行到哪了）不是同一对象。
    """

    #: 租户标识（隔离硬边界）
    tenant_id: str
    #: 发起人用户标识
    initiator_user_id: str = ""
    #: 委托范围（允许的资源/动作类型）
    delegate_scope: List[str] = Field(default_factory=list)
    #: 团队标识
    team_id: str = ""
    #: 运行标识
    run_id: str = ""
    #: 节点标识
    node_key: str = ""
    #: 尝试标识
    attempt_id: str = ""
    #: 父会话/根执行标识
    root_session_id: str = ""
    #: 本次子执行标识（先落库、后启动成员）
    execution_id: str = ""
    #: 有效策略快照引用（不内联凭据）
    policy_snapshot_ref: str = ""
    #: 预算预留引用（调用前原子预留）
    budget_reservation_id: str = ""


class SkillSelection(BaseModel):
    """技能选择记录（协议07）：声明/候选/实载分开留痕。

    ``required`` 项缺失即阻塞派发；``selected=False`` 必须给出
    ``skip_reason``（非必需候选可跳过并解释）。
    """

    #: 技能标识
    skill_key: str
    #: 是否为任务必需
    required: bool = False
    #: 是否被实际选中
    selected: bool = False
    #: 未选原因（可解释性）
    skip_reason: str = ""
    #: 锁定的版本/内容指纹（切换阶段需重新选择并留痕）
    version: str = ""


def missing_required_skills(selections: Sequence[SkillSelection]) -> List[str]:
    """协议07：返回未选中的必需技能（非空即阻塞派发）。

    保证必需项不因候选排序/数量上限被静默裁掉。
    """
    # 只收集"必需且未选中"的技能键
    return [item.skill_key for item in selections if item.required and not item.selected]


class ToolObservation(BaseModel):
    """归一化工具回执（协议08）：区分传输/执行/业务效果三类成功。

    Observer 依赖本结构区分"查询返回空""执行失败""副作用未知"；
    ``usage_ref`` 为空表示用量未知（不得按零结算）。
    """

    #: 工具标识
    tool_key: str = ""
    #: 回执整体状态
    status: Literal["success", "warning", "error"] = "success"
    #: 传输层成功（HTTP/连接层面）
    transport_ok: bool = True
    #: 工具执行成功（区别于传输成功）
    executed: bool = False
    #: 业务效果确认（区别于执行成功；回执/核对依据）
    business_effect_confirmed: bool = False
    #: 一句话结果摘要
    summary: str = ""
    #: 证据/产物引用
    evidence_refs: List[str] = Field(default_factory=list)
    #: 错误类别（瞬时/权限/参数/下游…）
    error_category: str = ""
    #: 是否可安全重试（副作用未知时必须为 False）
    retryable: bool = False
    #: 副作用状态：无 / 已提交 / 未知
    side_effect_state: Literal["none", "committed", "unknown"] = "none"
    #: 计量事件引用（空=未知消耗）
    usage_ref: str = ""


class PlanRevision(BaseModel):
    """计划/需求/上下文修订记录（协议12）：重规划不删除旧图。

    ``invalid_scope`` 说明本次修订使哪些节点失效（可解释），未列入
    范围的已完成结果在输入指纹/验收标准仍满足时可复用。
    """

    #: 修订对象类型
    kind: Literal["requirement", "plan", "context"] = "plan"
    #: 新修订版本号
    revision: int = 1
    #: 变更原因（可解释性）
    reason: str = ""
    #: 被取代的旧版本（0=首发）
    superseded_revision: int = 0
    #: 本次修订的失效节点范围
    invalid_scope: List[str] = Field(default_factory=list)


class HumanDecision(BaseModel):
    """人工/授权决定（协议15）：绑定具体修订，过期批准不放行新内容。"""

    #: 决定标识（服务端登记的需求/计划/动作摘要绑定）
    decision_id: str
    #: 决定动作
    action: Literal[
        "confirm_requirement",
        "approve_plan",
        "approve_action",
        "resume",
        "cancel",
        "handover",
    ]
    #: 批准对象的期望修订版本（不匹配即拒绝）
    expected_revision: int = 0
    #: 审批备注
    comment: str = ""


def decision_matches(decision: HumanDecision, current_revision: int) -> bool:
    """协议15：批准对象版本与当前版本一致才有效（过期/重复批准拒绝）。"""
    # 期望版本与当前版本不一致即视为过期
    return decision.expected_revision == current_revision


class TraceLink(BaseModel):
    """Trace 关联（协议17）：团队运行 ↔ 员工执行 ↔ 观测 span。

    Trace 为 best-effort 观测：链路丢失不丢失业务账本（关键业务状态
    仍以 run/node/attempt 记录为权威）。
    """

    #: 团队运行标识
    team_run_id: str = ""
    #: 节点标识
    node_key: str = ""
    #: 尝试标识
    attempt_id: str = ""
    #: 员工 agent 运行标识
    agent_run_id: str = ""
    #: 员工会话标识
    session_id: str = ""
    #: 关联 span 标识清单
    span_ids: List[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    """治理裁决（协议16）：拒绝优先；ask 未决不视为 allow。"""

    #: 裁决值
    decision: Literal["allow", "deny", "ask"] = "ask"
    #: 裁决理由
    reason: str = ""
    #: 审计记录引用
    audit_ref: str = ""


def compose_policy_decisions(decisions: Sequence[PolicyDecision]) -> PolicyDecision:
    """协议16：多层治理裁决合成（平台→租户→团队→成员→任务）。

    顺序：任一层 deny 即 deny > 任一层 ask 即 ask > 全部 allow 即 allow；
    空输入保守返回 ask，不留裸放行。
    """
    # 拒绝优先：任一层拒绝直接返回该拒绝
    for item in decisions:
        if item.decision == "deny":
            return item
    # 其次询问：任一层要求审批即询问
    for item in decisions:
        if item.decision == "ask":
            return item
    # 全部允许 → 允许（返回首个 allow 携带其审计引用）
    for item in decisions:
        return item
    # 无任何治理输入时保守询问
    return PolicyDecision(decision="ask", reason="无治理输入，保守询问")


def min_positive_limit(*values: int) -> int:
    """协议16：多层有限上限取最小值（0=未配置层，忽略；全未配置返回 0）。

    预算与并发合成的统一口径：只能取各层有限上限中最小值，不能被
    某一层"未配置"放大。
    """
    # 过滤未配置（0/负值）的层
    positives = [value for value in values if value and value > 0]
    # 有配置层取最小，否则返回 0 表示无有效上限（由调用方决定默认值）
    return min(positives) if positives else 0
