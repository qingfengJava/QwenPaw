# -*- coding: utf-8 -*-
"""Context Engine：上下文束的构建 / 投影 / 版本化（Context Protocol）。

本模块实现"上下文无偏差"的三条硬规则：

1. **版本化事实**：ContextBundle 是节点间与跨用户传递的唯一介质；
   全局决策变更 / 澄清答复 / 移交时 bump 版本，后续节点契约引用
   新版本号——子员工拿到的是"明确版本的任务事实"，不是聊天记录。
2. **最小充分上下文（Minimum Sufficient Context）**：每节点只获得
   自己依赖的上游 ResultContract 摘要投影，禁止全量透传。
3. **摘要防膨胀**：execution_ctx 中每个上游节点只保留状态、决策、
   假设、问题、证据与截断的结果摘要，Token 用量有界。

@author qingfeng
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import (
    ContextBundle,
    DagNode,
    ResultContract,
)

#: 上游结果摘要中 result_digest 的最大字符数（防上下文膨胀）
_DIGEST_MAX_CHARS = 800

#: 版本历史轨迹的保留上限（有界防膨胀；更早轨迹以 feed 事件留痕）
_MAX_HISTORY_ENTRIES = 20


def build_initial_bundle(
    goal: str,
    team_name: str,
    member_roster: List[Dict[str, str]],
    initiator_id: str,
    project: Optional[Dict[str, Any]] = None,
) -> ContextBundle:
    """构建 run 的初始上下文束（版本 1，规划阶段的输入）。

    member_roster 由调用方从 ExpertStore 读取并投影为
    ``[{"expert_id", "name", "title", "role_hint"}]`` 轻量结构——
    只带身份与角色，不带 agent_spec（避免上下文污染）。
    """
    # Global 段：业务背景与全局约束（随规划演进追加决策）
    global_ctx: Dict[str, Any] = {
        "team": team_name,
        "business_goal": (project or {}).get("description", ""),
    }
    # 挂项目的 run 记录项目标识与名称（跨用户移交的权限锚点）
    if project:
        global_ctx["project"] = {"id": project.get("id"), "name": project.get("name")}
    # Task 段：原始需求与发起人（澄清答复会追加到此段）
    task_ctx: Dict[str, Any] = {
        "goal": goal,
        "initiator": initiator_id,
        "roster": member_roster,
    }
    # Execution 段初始为空（节点完成后逐个追加摘要）
    return ContextBundle(
        global_ctx=global_ctx,
        task_ctx=task_ctx,
        execution_ctx={},
        version=1,
    )


def bump(bundle: ContextBundle, reason: str = "") -> ContextBundle:
    """返回版本 +1 的新束（不可变语义：原束保留，新束引用）。

    reason 记入版本历史轨迹（V1→V2 的演进原因可追溯）；调用方
    负责把新束持久化回 team_runs.context_bundle，并由
    ``run_store.bump_context_version`` 单点递增持久层版本号。
    """
    # 记录版本变更轨迹（旧版本号 + 业务原因），有界保留
    history = list(bundle.history)
    history.append({"version": bundle.version, "reason": reason})
    # 模型拷贝：递增版本号 + 追加历史（其余段落按引用共享，未变更）
    return bundle.model_copy(
        update={
            "version": bundle.version + 1,
            "history": history[-_MAX_HISTORY_ENTRIES:],
        }
    )


def record_version_change(bundle: ContextBundle, reason: str) -> ContextBundle:
    """原地记录版本变更轨迹（引擎的就地束同步路径专用）。

    与 ``bump`` 的差异：不创建新对象、不递增版本号——引擎在并行
    节点共享同一束对象（外部引用需就地可见），由调用方自行执行
    ``bundle.version += 1`` 并持久化。
    """
    # 原地追加轨迹（旧版本号 + 业务原因），有界保留
    history = list(bundle.history)
    history.append({"version": bundle.version, "reason": reason})
    bundle.history = history[-_MAX_HISTORY_ENTRIES:]
    return bundle


def summarize_result(result: ResultContract) -> Dict[str, Any]:
    """把一份 ResultContract 压缩为有界摘要（execution_ctx 的条目）。

    保留验收与对齐所需的最小充分信息：状态、决策、假设、问题、
    证据与截断的结果文本——丢弃冗长正文，Token 用量可控。
    """
    # 结果正文优先取结构化 result 的 JSON 文本，其次纯文本产出
    digest = ""
    if result.result:
        digest = str(result.result)
    elif result.result_text:
        digest = result.result_text
    # 截断到上限（中段省略标记，保留首尾）
    if len(digest) > _DIGEST_MAX_CHARS:
        head = digest[: _DIGEST_MAX_CHARS // 2]
        tail = digest[-_DIGEST_MAX_CHARS // 3 :]
        digest = f"{head}\n…（已截断）…\n{tail}"
    # 摘要结构固定，下游节点按 key 取用
    return {
        "status": result.status,
        "decisions": list(result.decisions),
        "assumptions": list(result.assumptions),
        "issues": list(result.issues),
        "evidence": list(result.evidence),
        "digest": digest,
    }


def record_upstream_result(
    bundle: ContextBundle,
    node_key: str,
    node_label: str,
    result: ResultContract,
) -> ContextBundle:
    """把一个已完成节点的结果摘要写入 execution_ctx（原地段更新）。

    node_label 为人类可读的节点名（如专家名+目标），供下游 prompt
    与 RunDetail 展示；写入不 bump 版本（版本只在全局决策变更时 bump）。
    """
    # 复制后追加摘要（保持束的更新路径单一）
    updated = bundle.model_copy(deep=False)
    updated.execution_ctx = dict(bundle.execution_ctx)
    # 摘要条目附带节点展示名，下游无需回查 DAG
    updated.execution_ctx[node_key] = {
        "label": node_label,
        **summarize_result(result),
    }
    return updated


def upstream_summaries(
    bundle: ContextBundle,
    node: DagNode,
) -> Dict[str, Any]:
    """取某节点的依赖上游摘要投影（仅 deps 声明的节点，最小充分）。

    返回 ``{node_key: summary}``；依赖未完成的节点不会出现在结果中
    （引擎保证只在依赖满足后才构建契约）。
    """
    # 只投影 deps 内的条目（并行分支互不可见，避免噪声）
    return {
        dep: bundle.execution_ctx[dep]
        for dep in node.deps
        if dep in bundle.execution_ctx
    }
