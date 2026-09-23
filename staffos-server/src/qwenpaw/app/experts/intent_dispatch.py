# -*- coding: utf-8 -*-
"""Multi-expert intent dispatch (P5：渠道多员工意图分发的内核).

给定一条入站消息与候选数字员工名单，LLM 分类出最合适的承接员工
（StaffDeck 渠道自动分发的对应物，与具体渠道解耦——任何渠道适配器
或上游网关都可调用）：

- **粘性保护**：进行中的会话默认留在当前员工（当前员工在候选中即
  stay，除非置信度极高）；显式指定的 current_expert 触发该保护；
- **置信度阈值**：低置信度回落默认员工（或不切换），绝不瞎猜路由；
- **降级**：LLM 通道异常/解析失败 → 返回 None（调用方回落默认员工），
  分发故障绝不阻塞消息主链路。

渠道接线（P5 收尾批次）：在各渠道适配器收到文本消息后、路由到默认
agent 之前调用 ``dispatch_expert_intent``；本文件先交付内核 + API，
渠道适配器逐一接线由后续批次完成（改动面涉及 18 渠道 registry）。
@author qingfeng
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 切换阈值（SOP/会话进行中的粘性场景由调用方用 sticky_threshold）
CONFIDENT_THRESHOLD = 0.75
STICKY_THRESHOLD = 0.9

_JSON_FENCE_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"(\{.*\})", re.DOTALL)


class DispatchCandidate:
    """One candidate expert for intent dispatch.

    用轻量 dataclass 而非 ExpertRecord——调用方（渠道侧）通常只有
    市场卡片投影（id/name/title/description），避免重列加载。
    """

    __slots__ = ("expert_id", "name", "title", "description")

    def __init__(
        self,
        expert_id: str,
        name: str,
        title: str = "",
        description: str = "",
    ):
        self.expert_id = expert_id
        self.name = name
        self.title = title
        self.description = description


async def dispatch_expert_intent(
    text: str,
    candidates: List[DispatchCandidate],
    current_expert_id: str = "",
    sticky: bool = False,
) -> Optional[Dict[str, Any]]:
    """Classify one inbound message to the best expert.

    返回 ``{"expert_id", "confidence", "reason", "stay": bool}``；
    无法判断（候选 <2 / 通道异常 / 低置信度）时返回 None——调用方
    保持现有路由（默认员工），分发永不阻塞消息主链路。

    Args:
        text: 入站消息文本。
        candidates: 候选数字员工（渠道挂载名单）。
        current_expert_id: 当前会话承接员工（粘性保护对象）。
        sticky: True 时启用粘性阈值（进行中会话更难被抢走）。
    """
    usable = [c for c in candidates if c.expert_id]
    if len(usable) < 2:
        return None
    threshold = STICKY_THRESHOLD if sticky else CONFIDENT_THRESHOLD
    roster = "\n".join(
        f"- id={c.expert_id} 名字={c.name} 岗位={c.title or '未填'} "
        f"职责={c.description[:80]}"
        for c in usable
    )
    current_line = (
        f"\n当前会话正由 id={current_expert_id} 承接（若本次消息仍属于其职责，选它）。\n"
        if current_expert_id
        else ""
    )
    prompt = (
        "# 渠道消息分发（你是调度器）\n\n"
        "以下是一条用户消息和可选的数字员工名单，请选出最适合承接的员工。\n\n"
        f"用户消息：{text[:500]}\n"
        f"{current_line}"
        f"候选名单：\n{roster}\n\n"
        "输出一个 ```json 代码块：\n"
        "```json\n"
        "{\n"
        '  "expert_id": "最合适候选的 id（必须来自名单；都不合适则填 stay）",\n'
        '  "confidence": 0到1的小数,\n'
        '  "reason": "一句话理由"\n'
        "}\n"
        "```\n"
    )
    try:
        choice = await _classify(prompt)
    except Exception:  # noqa: BLE001 - 分类器异常同样降级不切换
        logger.debug("意图分发分类器异常（降级不切换）", exc_info=True)
        return None
    if choice is None:
        return None
    expert_id = str(choice.get("expert_id") or "").strip()
    confidence = _to_confidence(choice.get("confidence"))
    reason = str(choice.get("reason") or "")
    # stay / 低置信度 / 未知候选 → 保持现有路由
    if (
        expert_id in ("stay", "", "none")
        or confidence < threshold
        or expert_id not in {c.expert_id for c in usable}
    ):
        return None
    # 粘性保护：从当前员工切走需要更高的置信度
    if (
        sticky
        and current_expert_id
        and expert_id != current_expert_id
        and confidence < STICKY_THRESHOLD
    ):
        return None
    return {
        "expert_id": expert_id,
        "confidence": confidence,
        "reason": reason,
        "stay": expert_id == current_expert_id,
    }


async def _classify(prompt: str) -> Optional[Dict[str, Any]]:
    """LLM 通道（复用 workforce 委派；异常返回 None 降级）。"""
    try:
        from ..workforce.delegator import call_expert_text

        # 分发器人格用默认 agent（不绑定具体专家，避免循环路由）
        reply, _session, _tokens = await call_expert_text(
            "default",
            prompt,
            session_id=None,
        )
    except Exception:  # noqa: BLE001 - 分发通道故障降级
        logger.debug("意图分发 LLM 通道异常（降级不切换）", exc_info=True)
        return None
    match = _JSON_FENCE_RE.search(reply) or _BARE_JSON_RE.search(reply)
    if match is None:
        return None
    import json

    try:
        return json.loads(match.group(1))
    except Exception:  # noqa: BLE001 - 解析失败降级
        return None


def _to_confidence(value: Any) -> float:
    """Confidence coercion (model outputs may be '0.9' / 90 / 0.9)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1:  # 百分制容错
        number = number / 100
    return max(0.0, min(1.0, number))
