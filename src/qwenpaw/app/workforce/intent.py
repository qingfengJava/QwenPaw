# -*- coding: utf-8 -*-
"""双态入口的意图分类（simple / complex / clarify）。

分类策略（规则优先，节省成本）：

1. **规则信号**：多交付物词、跨专业词、编排动词、显式团队词等
   命中即判 complex；疑问澄清信号命中即判 clarify；
2. **LLM 兜底**：规则不确定时调 default agent（廉价与否由用户在
   agent profile 配置面决定——模型分级路由的 classifier 档）做
   一次结构化判定。

开关：``QWENPAW_WORKFORCE_AUTO_ESCALATE``（默认 **关闭**）。开启时
聊天发送前置判定 complex → 创建 team_run 并发可取消的确认卡片；
关闭时分类结果仅用于前端"建议升级"提示，绝不打扰直答。

@author qingfeng
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

#: 分类结果：简单问题（单专家流式直答）
INTENT_SIMPLE = "simple"
#: 分类结果：复杂任务（建议/自动升级为专家团任务）
INTENT_COMPLEX = "complex"
#: 分类结果：需要澄清（建议用户补充信息，仍按直答处理）
INTENT_CLARIFY = "clarify"

#: 自动升级总开关的环境变量名（默认关闭：杜绝误判打扰）
ENV_AUTO_ESCALATE = "QWENPAW_WORKFORCE_AUTO_ESCALATE"

#: 多交付物信号（一句话里要求多个正式产出物）
_MULTI_DELIVERABLE_RE = re.compile(
    r"(方案|设计|报告|分析|规划|架构|调研|文档|总结).{0,12}(和|及|并|、|还有|以及).{0,12}(方案|设计|报告|分析|规划|架构|调研|文档|总结|代码|原型)"
    r"|(完整|整体|全套|端到端).{0,8}(方案|技术方案|架构)"
    r"|同时.{0,20}(还要|需要|输出)"
)
#: 跨专业协作信号（明确需要多角色配合）
_CROSS_DOMAIN_RE = re.compile(
    r"(前端|后端|数据库|产品|测试|UI|算法).{0,16}(和|及|并|、|还有|以及|配合|协作).{0,16}(前端|后端|数据库|产品|测试|UI|算法|专家|一起)"
)
#: 编排动词信号（拆解/分工/多人/团队协作等编排语义）
_ORCHESTRATION_RE = re.compile(
    r"(拆解|分解|分工|分派|安排(多个|几位)|多人协作|团队(一起|协作|完成)|组建|牵头)"
)
#: 澄清信号（信息明显不足）
_CLARIFY_RE = re.compile(r"(帮我看看|怎么弄|怎么办|什么意思|行不行|可以吗)[?？]?$")


@dataclass
class IntentResult:
    """意图分类结果（附判定依据，供确认卡片与日志展示）。"""

    #: 分类值：INTENT_SIMPLE / INTENT_COMPLEX / INTENT_CLARIFY
    intent: str
    #: 判定依据（命中的规则名或 "llm"）
    reason: str


def auto_escalate_enabled() -> bool:
    """读取自动升级总开关（默认关闭）。"""
    # 环境变量显式开启才生效（"1"/"true"/"on" 不区分大小写）
    return os.environ.get(ENV_AUTO_ESCALATE, "").strip().lower() in ("1", "true", "on")


def classify_by_rules(message: str) -> Optional[IntentResult]:
    """规则分类：命中返回结果，未命中返回 None（交由 LLM 兜底）。"""
    # 去除首尾空白后匹配（保持原文不修改）
    text = message.strip()
    if not text:
        return IntentResult(INTENT_SIMPLE, "empty")
    # 多交付物信号 → 复杂任务
    if _MULTI_DELIVERABLE_RE.search(text):
        return IntentResult(INTENT_COMPLEX, "multi_deliverable")
    # 跨专业协作信号 → 复杂任务
    if _CROSS_DOMAIN_RE.search(text):
        return IntentResult(INTENT_COMPLEX, "cross_domain")
    # 编排动词信号 → 复杂任务
    if _ORCHESTRATION_RE.search(text):
        return IntentResult(INTENT_COMPLEX, "orchestration")
    # 澄清信号（短句求助） → 建议澄清（仍直答）
    if len(text) <= 24 and _CLARIFY_RE.search(text):
        return IntentResult(INTENT_CLARIFY, "clarify_signal")
    # 规则未命中 → None（LLM 兜底）
    return None


async def classify(message: str) -> IntentResult:
    """完整分类：规则优先 → LLM 兜底（default agent 一次结构化判定）。

    LLM 兜底仅在自动升级开启时消耗（关闭时规则未命中直接 simple，
    零额外成本）；通道异常降级为 simple（绝不因分类故障阻塞聊天）。
    """
    # 规则优先（零成本路径）
    ruled = classify_by_rules(message)
    if ruled is not None:
        return ruled
    # 自动升级关闭时：不消耗 LLM，保守按 simple 直答
    if not auto_escalate_enabled():
        return IntentResult(INTENT_SIMPLE, "rules_no_match_auto_off")
    # LLM 兜底（default agent；模型档位由用户配置面决定）
    try:
        # 延迟导入避免模块加载期依赖工具链
        from .delegator import call_expert_text

        prompt = (
            "# 意图分类（只输出一个词：simple 或 complex）\n"
            "判断下面这条用户消息是否属于需要多步骤、多交付物、多专业协作的"
            "复杂任务（complex），还是一句话可答的简单问题（simple）。\n\n"
            f"用户消息：{message}\n\n"
            "只输出 simple 或 complex，不要任何其他内容。"
        )
        reply, _session, _tokens = await call_expert_text(
            "default",
            prompt,
            session_id=None,
            timeout=60.0,
        )
        # 归一化取词（容忍模型输出前后噪声）
        word = reply.strip().lower()
        if "complex" in word:
            return IntentResult(INTENT_COMPLEX, "llm")
        return IntentResult(INTENT_SIMPLE, "llm")
    except Exception:  # noqa: BLE001 - 分类通道异常降级 simple（不阻塞聊天）
        logger.warning("意图分类 LLM 兜底失败，降级 simple", exc_info=True)
        return IntentResult(INTENT_SIMPLE, "llm_fallback_error")
