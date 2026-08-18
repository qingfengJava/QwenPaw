# -*- coding: utf-8 -*-
"""Execution Engine：TaskContract 投影 → 委派成员专家 → ResultContract。

委派通道完全复用 ``agents/tools/agent_management.py`` 的既有 A2A
基础设施（HTTP 自环到本服务 ``/console/chat``，天然继承认证/限流/
Sandbox/治理门），不新建执行通道：

- 每个成员独立 ``session_id``（跨会话天然并发；返工轮复用以延续
  成员自己的上下文）；
- 并发准入由 ``ConcurrencyGate`` 的虚拟主体 ``team:{run_id}`` 承担
  （engine 层透传 owner，本模块不感知）；
- ResultContract 容错解析：剥代码围栏 → JSON → 校验失败一次格式化
  重试 → 降级为自由文本 + ``needs_review=True``，绝不阻塞链路。

@author qingfeng
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

from ..experts.models import expert_agent_id
from .contracts import (
    RepairContract,
    ResultContract,
    TaskContract,
    RESULT_STATUS_COMPLETED,
)

logger = logging.getLogger(__name__)

#: 单节点委派的默认等待上限（秒）；run 级时限由 RunPolicy 兜底
DELEGATE_TIMEOUT_S = 900.0

#: ResultContract JSON 输出指令（render_task_prompt 尾部注入）
_RESULT_SCHEMA_HINT = (
    '请在完成任务的回复最末尾，输出一个 ```json 代码块，内容为如下'
    "结构的 JSON（result_text 字段填你的完整正文产出，其余字段如实"
    "填写）：\n"
    "```json\n"
    '{\n'
    '  "status": "COMPLETED | PARTIAL | FAILED",\n'
    '  "result_text": "你的完整产出正文",\n'
    '  "decisions": ["你做出的关键决策"],\n'
    '  "assumptions": ["你自行假设的事项"],\n'
    '  "issues": ["未解决需上报的问题"],\n'
    '  "evidence": ["产出文件路径或引用"],\n'
    '  "confidence": 0.9\n'
    "}\n"
    "```\n"
    "JSON 块之外不要有任何多余内容跟在后面。"
)

#: 剥取 ```json 围栏或裸 JSON 对象的提取模式（贪心平衡由正则近似）
_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
#: 裸 JSON 对象（捕获组不可少：parse 取 group(1)；从首个 { 到最后
#: 一个 }，多段输出取整体最大跨度）
_BARE_JSON_RE = re.compile(r"(\{.*\})", re.DOTALL)


async def call_expert_text(
    to_agent: str,
    prompt: str,
    session_id: Optional[str] = None,
    timeout: float = DELEGATE_TIMEOUT_S,
    from_agent: str = "workforce",
) -> Tuple[str, str, int]:
    """底层通道：调一个已配置的专家 agent，返回 ``(回复文本, session_id,
    total_tokens)``。

    复用 agent_management 的请求构造与 SSE 收集（无工具上下文依赖，
    可在编排器协程中直接调用）；``to_agent`` 为运行时 agent 标识
    （如 ``expert_xxx`` / ``team_xxx``）。与既有收集器的差异：保留
    ``turn_usage`` 事件以采集本节点 token 消耗（run 级预算依据）。
    """
    # 延迟导入避免模块加载期引入 agent 工具链（保持 workforce 包轻）
    from ...agents.tools.agent_management import (
        build_agent_chat_request,
        parse_agent_sse_line,
        resolve_agent_api_base_url,
    )
    import httpx

    # 构造委派请求（from_agent=workforce 标识编排器来源；session 复用由入参决定）
    final_session_id, request_payload, _ = build_agent_chat_request(
        to_agent,
        prompt,
        session_id=session_id,
        from_agent=from_agent,
    )
    # 归一化本机 API 基址
    normalized = resolve_agent_api_base_url(None)
    # 逐行消费 SSE：记录最后一条非 usage 事件为回执，累加 usage 事件
    response_data: Optional[Dict[str, Any]] = None
    total_tokens = 0
    async with httpx.AsyncClient(
        base_url=normalized,
        timeout=httpx.Timeout(timeout),
    ) as client:
        # 请求头与既有收集器一致（X-Agent-Id 指定目标专家）
        from ...agents.tools.agent_management import _request_headers

        async with client.stream(
            "POST",
            "/console/chat",
            json=request_payload,
            headers=_request_headers(to_agent),
        ) as response:
            # 非 2xx 直接抛出（调用方按节点失败处理）
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                parsed = parse_agent_sse_line(line)
                if parsed is None:
                    continue
                # usage 事件累加 token（run 级预算依据）
                if parsed.get("type") == "turn_usage":
                    usage = parsed.get("usage") or parsed
                    total_tokens += int(usage.get("total_tokens", 0) or 0)
                else:
                    response_data = parsed
    # 无回执视为通道异常（调用方按节点失败处理）
    if response_data is None:
        raise RuntimeError(f"专家 [{to_agent}] 无响应（超时 {timeout}s）")
    # 提取纯文本内容（多模态块拼接为文本）
    from ...agents.tools.agent_management import extract_agent_text_content

    reply_text = extract_agent_text_content(response_data) or ""
    return reply_text, final_session_id, total_tokens


def render_task_prompt(
    contract: TaskContract,
    repair: Optional[RepairContract] = None,
) -> str:
    """把 TaskContract 投影为结构化委派 prompt（禁止聊天记录透传）。

    repair 非空时附加返工指令段（问题/期望修改/保留项/复验标准）；
    尾部固定注入 ResultContract JSON 输出指令。
    """
    # 上下文版本号显式告知（子员工知晓其依据的任务事实版本）
    lines = [f"# 任务委派（Task Contract · 上下文版本 v{contract.global_context.get('context_version', 1)}）"]
    # 全局背景段（不可变快照）
    lines.append("\n## 全局背景")
    for key, value in contract.global_context.items():
        if key == "context_version":
            continue
        lines.append(f"- {key}: {json.dumps(value, ensure_ascii=False, default=str)}")
    # 父决策段（必须遵守）
    if contract.parent_decision:
        lines.append("\n## 必须遵守的既定决策")
        for item in contract.parent_decision:
            lines.append(f"- {item}")
    # 上游产出摘要段（仅依赖节点，最小充分）
    if contract.upstream_summaries:
        lines.append("\n## 上游产出摘要（你的输入依据）")
        for node_key, summary in contract.upstream_summaries.items():
            label = summary.get("label", node_key)
            lines.append(f"### {label}（{node_key}，状态 {summary.get('status')}）")
            digest = summary.get("digest", "")
            lines.append(f"产出摘要：{digest}" if digest else "（无正文摘要）")
            for decision in summary.get("decisions", []):
                lines.append(f"- 其决策：{decision}")
            for issue in summary.get("issues", []):
                lines.append(f"- 其遗留问题：{issue}")
    # 依赖说明段
    if contract.dependencies:
        lines.append("\n## 依赖说明")
        for key, desc in contract.dependencies.items():
            lines.append(f"- {key}: {desc}")
    # 本节点任务段
    lines.append("\n## 你的任务")
    lines.append(contract.objective)
    # 期望产出段
    if contract.expected_output:
        lines.append("\n## 期望产出")
        for item in contract.expected_output:
            lines.append(f"- {item}")
    # 约束段
    if contract.constraints:
        lines.append("\n## 约束（硬性要求）")
        for item in contract.constraints:
            lines.append(f"- {item}")
    # 验收标准段
    if contract.quality_criteria:
        lines.append("\n## 验收标准（中央大脑将按此裁决）")
        for item in contract.quality_criteria:
            lines.append(f"- {item}")
    # 可用能力段（Skill=能力 / Tool=动作 严格区分）
    if contract.available_skills or contract.available_tools:
        lines.append("\n## 可用能力")
        if contract.available_skills:
            lines.append(f"- 技能（怎么做）: {', '.join(contract.available_skills)}")
        if contract.available_tools:
            lines.append(f"- 工具（用什么做）: {', '.join(contract.available_tools)}")
    # 返工指令段（仅返工轮注入）
    if repair is not None:
        lines.append("\n## 返工指令（第 %d 轮，前次产出未通过验收）" % repair.attempt)
        lines.append("### 验收发现的问题（必须逐条解决）")
        for issue in repair.issues:
            lines.append(f"- {issue}")
        lines.append("### 期望修改")
        for item in repair.expected_change:
            lines.append(f"- {item}")
        if repair.preserve:
            lines.append("### 需保留内容（不得破坏）")
            for item in repair.preserve:
                lines.append(f"- {item}")
        if repair.acceptance:
            lines.append("### 复验标准")
            for item in repair.acceptance:
                lines.append(f"- {item}")
    # 固定注入输出格式要求
    lines.append("\n## 输出要求")
    lines.append(_RESULT_SCHEMA_HINT)
    return "\n".join(lines)


def parse_result_contract(text: str, task_id: str) -> ResultContract:
    """从成员回复中容错解析 ResultContract。

    解析顺序：```json 围栏 → 裸 JSON → 降级（全文作为 result_text、
    ``needs_review=True``）。本函数纯同步、无副作用、绝不抛错。
    """
    # 优先提取围栏 JSON（约定输出格式）
    match = _JSON_FENCE_RE.search(text)
    if match is None:
        # 围栏缺失时退而求其次：首 { 到末 } 的最大跨度
        match = _BARE_JSON_RE.search(text)
    # 两种模式都没命中 → 直接降级
    if match is None:
        return ResultContract(
            task_id=task_id,
            status=RESULT_STATUS_COMPLETED,
            result_text=text,
            needs_review=True,
        )
    # 解析 JSON 并严格校验为 ResultContract（多余字段忽略，缺省字段取默认）
    try:
        data = json.loads(match.group(1))
        data.setdefault("task_id", task_id)
        return ResultContract.model_validate(data)
    except Exception:  # noqa: BLE001 - 解析失败必须降级而非中断
        # JSON 存在但非法 → 降级保留全文（验收器强裁）
        logger.warning("ResultContract 解析失败 task=%s，降级为自由文本", task_id)
        return ResultContract(
            task_id=task_id,
            status=RESULT_STATUS_COMPLETED,
            result_text=text,
            needs_review=True,
        )


async def delegate(
    expert_id: str,
    contract: TaskContract,
    repair: Optional[RepairContract] = None,
    session_id: Optional[str] = None,
    timeout: float = DELEGATE_TIMEOUT_S,
) -> Tuple[ResultContract, str]:
    """委派执行一个节点：渲染 prompt → 调成员专家 → 解析结果契约。

    返回 ``(ResultContract, session_id)``；session_id 由调用方回写
    节点行（返工轮传入同一 session 延续成员上下文）。本节点 token
    消耗填入 ``ResultContract.token_cost``（run 级预算依据）。
    """
    # 成员专家的运行时 agent 标识（expert_{id}，发布链已物化）
    to_agent = expert_agent_id(expert_id)
    # 渲染最小充分上下文投影 prompt（无聊天记录）
    prompt = render_task_prompt(contract, repair)
    # 走既有 A2A 通道执行（异常向上抛，由 engine 按节点失败处理）
    reply_text, final_session_id, total_tokens = await call_expert_text(
        to_agent,
        prompt,
        session_id=session_id,
        timeout=timeout,
    )
    # 容错解析结构化结果（解析失败自动降级 needs_review）
    result = parse_result_contract(reply_text, contract.task_id)
    # 回执 token 消耗写入结果契约（节点与 run 级预算累计依据）
    result.token_cost = total_tokens
    return result, final_session_id
