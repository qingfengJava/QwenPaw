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

硬约束：本文件只允许依赖 pydantic / 标准库，禁止 import 任何引擎
模块（import 方向单向：引擎 → 契约），保证契约可独立单测与跨层复用。

@author qingfeng
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

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
)

#: run 活跃态集合（进程重启时需扫描改写为 interrupted 的状态）
RUN_ACTIVE_STATUSES = (
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

#: 验收裁决：通过
VERDICT_PASS = "PASS"
#: 验收裁决：不通过（需返工）
VERDICT_FAIL = "FAIL"
#: 验收裁决：熔断升级人工（超限或验收器无法裁决）
VERDICT_ESCALATE = "ESCALATE"

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
    #: 本节点 token 消耗（委派器从回执 usage 统计，0=未采集）
    token_cost: int = 0


class RepairContract(BaseModel):
    """验收失败后的返工指令（对齐用户架构方案第二十节）。

    返工不是"重新给一个新 Prompt"，而是结构化的修复任务：明确
    问题、期望修改、需保留内容与复验标准，重跑时附加进上下文束。
    """

    #: 被返工的原节点标识
    original_task: str
    #: 问题清单（验收裁决发现的具体问题）
    issues: List[str] = Field(default_factory=list)
    #: 期望修改（每个问题对应的期望改动）
    expected_change: List[str] = Field(default_factory=list)
    #: 需保留内容（返工时不得破坏的已有产出）
    preserve: List[str] = Field(default_factory=list)
    #: 复验标准（返工后按此重新裁决）
    acceptance: List[str] = Field(default_factory=list)
    #: 返工轮次（第 N 次返工，用于熔断计数展示）
    attempt: int = 1


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
