# -*- coding: utf-8 -*-
"""团队配置 schema：版本适配、严格校验与跨字段验证（T1）。

本模块是 expert_teams.orchestration JSONB 的版本化读写入口：

- v1：既有宽松语义（未知字段忽略，兼容存量模板）；
- v2：严格语义（未知字段拒绝、不支持版本拒绝、预算必须有限）；
- ``validate_publishable_team``：发布前跨字段校验（唯一 lead、必需
  成员、模板 DAG、风险控制），供预检与发布链共用。

硬约束：只依赖 pydantic / 标准库 / workforce.contracts（纯配置层，
无 DB / 引擎依赖），保证可独立单测。

@author qingfeng
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from ..workforce.contracts import DagPlan, OrchestrationSpec, RunPolicy, validate_dag
from .models import ExpertTeamRecord, TEAM_MEMBER_ROLE_LEAD

#: 配置 schema 版本：v1=存量宽松 / v2=严格（未知字段拒绝）
TEAM_CONFIG_SCHEMA_V1 = "v1"
TEAM_CONFIG_SCHEMA_V2 = "v2"

#: 支持的版本全集（其余一律拒绝，不做静默升级）
SUPPORTED_TEAM_CONFIG_VERSIONS = (TEAM_CONFIG_SCHEMA_V1, TEAM_CONFIG_SCHEMA_V2)


class OrchestrationSpecV2(OrchestrationSpec):
    """v2 严格配置：未知字段拒绝（拦截前端/模板漂移）。

    在 v1 全部语义之上收紧两点：

    - ``model_config.extra="forbid"``：orchestration 里出现 schema
      未定义的字段直接报错，不再静默忽略（配置页拼错的 policy 键
      会在保存时暴露，而不是运行期被吞）；
    - ``schema_version`` 锁定 "v2"（防 v1 载荷借 v2 通道绕过严格校验）。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=TEAM_CONFIG_SCHEMA_V2)

    #: 计划批准门（T3）：开启后每次物化的计划挂起等待人工批准
    #:（decisions 通道 approve_plan 放行；重规划/澄清后旧批准失效）
    require_plan_approval: bool = False


def parse_team_orchestration(payload: Optional[Dict[str, Any]]) -> OrchestrationSpec:
    """版本适配入口：按 schema_version 选择宽松/严格解析（读唯一入口）。

    - 无版本标记 / v1 → :class:`OrchestrationSpec`（存量数据兼容）；
    - v2 → :class:`OrchestrationSpecV2`（未知字段拒绝）；
    - 其他版本 → ValueError（不支持静默升级）。
    """
    # 空载荷按 v1 空配置处理（历史团队 orchestration={}）
    if not payload:
        return OrchestrationSpec()
    version = str(payload.get("schema_version") or TEAM_CONFIG_SCHEMA_V1)
    # 未登记版本直接拒绝（不做猜测式兼容）
    if version not in SUPPORTED_TEAM_CONFIG_VERSIONS:
        raise ValueError(
            f"不支持的团队配置 schema_version: {version}"
            f"（支持: {', '.join(SUPPORTED_TEAM_CONFIG_VERSIONS)}）",
        )
    # v2 严格校验（未知字段/漂移在此拦截）
    if version == TEAM_CONFIG_SCHEMA_V2:
        return OrchestrationSpecV2.model_validate(payload)
    # v1 宽松校验（存量数据兼容）
    return OrchestrationSpec.model_validate(payload)


def _lead_ids(team: ExpertTeamRecord) -> List[str]:
    """团队内标记为 lead 的成员 ID 清理（去重保持顺序）。"""
    seen: set = set()
    leads: List[str] = []
    for member in team.members:
        if member.member_role == TEAM_MEMBER_ROLE_LEAD and member.expert_id not in seen:
            seen.add(member.expert_id)
            leads.append(member.expert_id)
    return leads


def validate_publishable_team(
    team: ExpertTeamRecord,
    *,
    require_finite_budget: bool = False,
) -> List[str]:
    """发布前跨字段校验：返回问题清单（空=可发布）。

    校验项（对齐计划第五/八节）：

    1. 至少一名成员；
    2. 恰有一名有效 lead（0 或多 lead 均不可发布）；
    3. orchestration 版本受支持且模板 DAG 合法（含 final 节点检查
       交由规划器，此处只校验图结构与模板字段）；
    4. v2 配置下预算策略必须是有限值（不继承 0=无限作为新团队默认）。

    本函数只读不写，供 ``POST /{team_id}/validate`` 预检与发布链共用。
    """
    issues: List[str] = []
    # 1. 成员下限
    if not team.members:
        issues.append("团队至少需要一名成员")
        return issues
    # 2. 唯一 lead
    leads = _lead_ids(team)
    if not leads:
        issues.append("团队必须指定一名 lead（主理人）成员")
    elif len(leads) > 1:
        issues.append(
            f"团队只能有一名 lead，当前 {len(leads)} 名: {', '.join(leads)}",
        )
    # 3. 配置版本与模板 DAG（orchestration 非空时才校验）
    if team.orchestration:
        try:
            spec = parse_team_orchestration(team.orchestration)
        except Exception as exc:  # noqa: BLE001 - 配置非法即问题清单一项
            issues.append(f"orchestration 配置非法: {exc}")
            return issues
        # 模板节点存在时校验图结构（成员存在性由能力投影另行核对）
        if spec.nodes:
            try:
                validate_dag(DagPlan(nodes=spec.nodes))
            except ValueError as exc:
                issues.append(f"orchestration 模板 DAG 非法: {exc}")
        # 4. v2 预算有限性（v1 存量不追溯）
        if isinstance(spec, OrchestrationSpecV2) and spec.policy is not None:
            policy: RunPolicy = spec.policy
            if require_finite_budget and policy.max_total_tokens <= 0:
                issues.append(
                    "v2 正式团队必须配置有限 token 预算"
                    "（orchestration.policy.max_total_tokens > 0）",
                )
        # 5. v2 团队成员版本绑定必须显式指定（P2 两级发布；仅发布
        # 链强制——草稿阶段未绑定是合法中间态，绑定缺失会让运行时
        # 版本核验直接跳过，快照语义失真）
        version = str(team.orchestration.get("schema_version") or "")
        if (
            require_finite_budget
            and version == TEAM_CONFIG_SCHEMA_V2
        ):
            unbound = [
                m.expert_id for m in team.members if not m.expert_version
            ]
            if unbound:
                issues.append(
                    "v2 团队每个成员必须显式绑定发布版本（expert_version）: "
                    + ", ".join(unbound),
                )
    return issues


def summarize_team_config(team: ExpertTeamRecord) -> Dict[str, Any]:
    """配置摘要（metadata 接口的字典口径；不泄露凭据类字段）。"""
    leads = _lead_ids(team)
    spec: Dict[str, Any] = {}
    if team.orchestration:
        try:
            parsed = parse_team_orchestration(team.orchestration)
            spec = parsed.model_dump()
        except Exception:  # noqa: BLE001 - 非法配置摘要为空，问题走 validate
            spec = {}
    return {
        "schema_version": str(
            (team.orchestration or {}).get("schema_version")
            or TEAM_CONFIG_SCHEMA_V1,
        ),
        "member_count": len(team.members),
        "lead_expert_ids": leads,
        "has_template": bool(spec.get("nodes")),
        "fast_chain_enabled": bool(spec.get("fast_nodes")),
        "runtime_enabled": bool(spec.get("runtime_enabled", True)),
        "policy": spec.get("policy"),
    }


def resolve_effective_config(team: ExpertTeamRecord) -> Dict[str, Any]:
    """统一有效配置解析：合并默认值与团队自定义，返回运行时可直接消费的配置。

    此函数是“有效配置”的唯一入口：

    - 解析 orchestration（版本适配）；
    - 缺失字段用引擎默认值填充（RunPolicy 默认值）；
    - 返回字典包含 schema_version、解析后的 spec、最终生效的 policy、
      以及成员投影（lead/members 分离）。

    与 ``summarize_team_config`` 的区别：后者是元数据摘要（轻量、前端
    枚举用），本函数是运行时完整配置投影（引擎消费用）。
    """
    spec_dict: Dict[str, Any] = {}
    if team.orchestration:
        try:
            parsed_spec = parse_team_orchestration(team.orchestration)
            spec_dict = parsed_spec.model_dump()
        except Exception:  # noqa: BLE001 - 非法配置返回空 spec
            spec_dict = {}

    # 有效 policy：解析结果 > 引擎默认
    effective_policy = spec_dict.get("policy") or RunPolicy().model_dump()

    leads = _lead_ids(team)
    member_ids = [m.expert_id for m in team.members]

    return {
        "schema_version": str(
            (team.orchestration or {}).get("schema_version")
            or TEAM_CONFIG_SCHEMA_V1,
        ),
        "spec": spec_dict,
        "policy": effective_policy,
        "runtime_enabled": spec_dict.get("runtime_enabled", True),
        "lead_expert_ids": leads,
        "member_expert_ids": member_ids,
        "has_template": bool(spec_dict.get("nodes")),
        "fast_chain_enabled": bool(spec_dict.get("fast_nodes")),
    }


__all__ = [
    "OrchestrationSpecV2",
    "SUPPORTED_TEAM_CONFIG_VERSIONS",
    "TEAM_CONFIG_SCHEMA_V1",
    "TEAM_CONFIG_SCHEMA_V2",
    "parse_team_orchestration",
    "resolve_effective_config",
    "summarize_team_config",
    "validate_publishable_team",
]
