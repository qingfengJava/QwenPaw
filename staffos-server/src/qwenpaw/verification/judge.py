# -*- coding: utf-8 -*-
"""独立验收器的模型通道：一次结构化裁决调用。

L2 数字员工没有 A2A 委派上下文，验收必须走「同进程、独立模型调用」：
复用 ``agents.model_factory`` 造模型（与自动标题生成同路径，token 自然
计入本会话额度），复用 ``utils.model_response`` 消费流式/非流式回执，
再交给 :func:`qwenpaw.verification.kernel.parse_verdict` 出裁决。

失败纪律与 L1 完全一致：无模型、超时、通道异常一律 ESCALATE（升级人工
复核），绝不因验收器故障给出 PASS。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .kernel import VERDICT_ESCALATE, Verdict, parse_verdict

logger = logging.getLogger(__name__)

#: 裁决调用的默认等待上限（秒）；验收是增强不是主链路，不宜长挂
DEFAULT_JUDGE_TIMEOUT_SECONDS = 60


async def judge_text(
    prompt: str,
    *,
    agent_id: str,
    agent_config: Any = None,
    model_slot: Any = None,
    timeout: float = DEFAULT_JUDGE_TIMEOUT_SECONDS,
) -> str:
    """用独立模型通道跑一次裁决，返回回复原文。

    ``model_slot`` 为员工级验收模型档（``AgentProfileConfig.verifier_model``）；
    未配置时沿用员工默认模型——独立性来自「独立上下文 + 验收器人格」，
    而非必须换一个模型。

    Raises:
        RuntimeError: 模型不可用或通道异常（调用方按 ESCALATE 处置）。
        asyncio.TimeoutError: 超过 ``timeout``。
    """
    # 延迟导入：避免 verification 包在模块加载期拉起 model_factory 重依赖
    from agentscope.message import Msg, TextBlock

    from ..agents.model_factory import create_model_and_formatter_async
    from ..utils.model_response import consume_model_response

    # 造模型（model_slot_override 为空即回落到员工默认档）
    model, _formatter = await create_model_and_formatter_async(
        agent_id=agent_id,
        model_slot_override=model_slot,
        agent_config=agent_config,
    )
    # 单轮裁决输入：系统人格 + 验收 prompt
    messages = [
        Msg(
            name="system",
            role="system",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "你是严格的任务验收器。只依据给定标准判断产出是否达标，"
                        "不美化、不替执行方辩解，且必须按要求的 JSON 结构输出。"
                    ),
                ),
            ],
        ),
        Msg(
            name="user",
            role="user",
            content=[TextBlock(type="text", text=prompt)],
        ),
    ]
    # 有界等待：超时向上抛，由 judge() 收敛为 ESCALATE
    return await asyncio.wait_for(
        consume_model_response(model, messages),
        timeout=timeout,
    )


async def judge(
    prompt: str,
    *,
    task_id: str,
    attempt: int,
    acceptance: Optional[list[str]] = None,
    agent_id: str,
    agent_config: Any = None,
    model_slot: Any = None,
    timeout: float = DEFAULT_JUDGE_TIMEOUT_SECONDS,
) -> Verdict:
    """执行一次独立验收裁决：模型通道 → 容错解析 → Verdict。

    本函数是 L2 验收门的唯一出口，绝不抛异常：任何通道故障都转成
    ``ESCALATE`` 裁决，交由调用方决定放行还是提示用户。
    """
    try:
        # 走独立通道取裁决原文
        reply = await judge_text(
            prompt,
            agent_id=agent_id,
            agent_config=agent_config,
            model_slot=model_slot,
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # 超时不阻塞主链路，按无法裁决处理
        logger.warning("独立验收超时（%ss）task=%s", timeout, task_id)
        return Verdict(
            VERDICT_ESCALATE,
            reason=f"验收器超时（{timeout}s），无法裁决",
        )
    except Exception as exc:  # noqa: BLE001 - 验收通道异常一律升级人工
        logger.warning("独立验收通道异常 task=%s: %s", task_id, exc)
        return Verdict(
            VERDICT_ESCALATE,
            reason=f"验收器不可用: {exc}",
        )
    # 解析裁决（解析失败在 kernel 内收敛为 ESCALATE）
    return parse_verdict(
        reply,
        task_id=task_id,
        attempt=attempt,
        acceptance=acceptance or [],
    )
