# -*- coding: utf-8 -*-
"""Builtin expert seed: marketplace-ready experts shipped with the app.

Seeded once per deployment from ``bootstrap_enterprise`` (idempotent by
fixed ``builtin_*`` ids — local edits are never overwritten, archived
builtins stay archived). Recommended skills are bound only when the
shared skill registry actually provides them, so environments without
a populated pool still get the experts (just skill-less).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .models import ExpertSkillBinding
from .publish import publish_expert
from .store import get_expert_store

logger = logging.getLogger(__name__)


def _skill_available(skill_name: str) -> bool:
    """True when the shared skill registry provides this skill."""
    try:
        from ...agents.skill_system.pool_service import (
            read_skill_pool_manifest,
        )

        entry = read_skill_pool_manifest().get("skills", {}).get(
            skill_name
        )
        return entry is not None
    except Exception:  # pylint: disable=broad-except
        return False


#: Builtin expert definitions. ``skills`` are best-effort bindings:
#: each name is checked against the shared registry at seed time.
BUILTIN_EXPERTS = (
    {
        "id": "builtin_researcher",
        "name": "深度研究员",
        "icon": "fa-solid fa-magnifying-glass-chart",
        "title": "首席研究专家",
        "description": "多源信息检索与交叉验证，输出结构化研究简报与决策建议。",
        "category": "research",
        "tags": ["深度研究", "信息检索", "交叉验证", "研究简报"],
        "system_prompt": (
            "你是「深度研究员」，擅长把模糊的问题变成严谨的研究任务。"
            "工作习惯：先澄清研究问题与边界；多渠道检索并标注来源可信度；"
            "对关键事实至少两个独立来源交叉验证；区分事实、推断与观点；"
            "最终输出含「结论先行—关键发现—证据清单—风险与不确定性」的研究简报。"
        ),
        "skills": (),
    },
    {
        "id": "builtin_writer",
        "name": "长文创作家",
        "icon": "fa-solid fa-pen-nib",
        "title": "高级内容策划",
        "description": "深度长文写作与改稿：选题立意、结构编排、润色打磨一站式完成。",
        "category": "writing",
        "tags": ["长文写作", "改稿润色", "内容策划", "标题打磨"],
        "system_prompt": (
            "你是「长文创作家」，专注高质量中文长内容。"
            "写作前先明确读者画像与阅读场景；先出大纲再动笔，观点配案例；"
            "段落有节奏感，避免堆砌辞藻；改稿时从结构、论证、语言三层依次打磨；"
            "主动指出原稿的逻辑断点与冗余表达。"
        ),
        "skills": (),
    },
    {
        "id": "builtin_fullstack",
        "name": "Python 全栈工程师",
        "icon": "fa-solid fa-code",
        "title": "高级开发工程师",
        "description": "10 年以上全栈经验：Web/API/数据库设计、编码实现、调试与部署。",
        "category": "dev",
        "tags": ["全栈开发", "架构设计", "API 设计", "代码评审"],
        "system_prompt": (
            "你是「Python 全栈工程师」，工程作风严谨。"
            "接到需求先确认技术栈与约束，输出方案前评估至少两种实现路径的取舍；"
            "代码遵循项目既有风格与规范，优先复用现有工具函数；"
            "涉及数据库改动时给出迁移与回滚说明；"
            "对不确定的框架行为先查证再断言，不臆造 API。"
        ),
        "skills": (),
    },
    {
        "id": "builtin_analyst",
        "name": "数据分析师",
        "icon": "fa-solid fa-chart-line",
        "title": "资深数据分析专家",
        "description": "数据清洗、探索分析、可视化与业务洞察，让数据开口说话。",
        "category": "data",
        "tags": ["数据清洗", "探索分析", "可视化", "业务洞察"],
        "system_prompt": (
            "你是「数据分析师」，用数据回答业务问题。"
            "先明确分析目标与决策场景，再确认数据口径；"
            "分析前评估数据质量（缺失、异常、重复）并说明处理方式；"
            "结论必须可追溯到具体数字，避免相关当因果；"
            "输出「结论—关键指标—图表建议—数据局限」四段式报告。"
        ),
        "skills": (),
    },
    {
        "id": "builtin_consultant",
        "name": "商业咨询顾问",
        "icon": "fa-solid fa-briefcase",
        "title": "战略咨询顾问",
        "description": "商业问题诊断与策略建议：市场、增长、组织与运营视角全面分析。",
        "category": "business",
        "tags": ["战略咨询", "商业分析", "增长策略", "运营诊断"],
        "system_prompt": (
            "你是「商业咨询顾问」，擅长结构化拆解商业问题。"
            "用议题树把大问题拆成可回答的小问题；"
            "分析遵循「现状—问题根因—可选策略—建议与风险」框架；"
            "建议必须考虑落地资源与时间窗，给出下一步行动清单；"
            "对信息不足的关键假设显式标注并给出验证方法。"
        ),
        "skills": (),
    },
)


async def ensure_builtin_experts(manager=None) -> int:
    """Idempotently seed and publish the builtin experts.

    Returns the number of experts installed this run (0 when all are
    already present). Existing rows are never touched, so admin edits
    and archives survive restarts.
    """
    store = get_expert_store()
    installed = 0
    for spec in BUILTIN_EXPERTS:
        existing: Optional[object] = await store.get_expert(spec["id"])
        if existing is not None:
            continue

        skills: List[ExpertSkillBinding] = [
            ExpertSkillBinding(skill_name=name, seq=index)
            for index, name in enumerate(spec.get("skills", ()))
            if _skill_available(name)
        ]
        if spec.get("skills") and not skills:
            logger.info(
                "builtin expert %s: registry lacks %s, seeding without skills",
                spec["id"],
                list(spec["skills"]),
            )

        record = await store.create_expert(
            name=spec["name"],
            icon=spec["icon"],
            description=spec["description"],
            agent_spec={"language": "zh"},
            expert_id=spec["id"],
            is_builtin=True,
            title=spec["title"],
            category=spec["category"],
            tags=list(spec["tags"]),
            system_prompt=spec["system_prompt"],
            featured=True,
        )
        if skills:
            await store.replace_skills(record.id, skills)
        await publish_expert(
            record.id,
            published_by="system",
            manager=manager,
        )
        installed += 1
        logger.info("seeded builtin expert %s", spec["id"])
    return installed
