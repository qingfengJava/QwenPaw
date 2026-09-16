# -*- coding: utf-8 -*-
"""Digital-employee registry & governance domain.

一个页面管住全部数字员工的两个治理维度：**归属部门**（谁的人）与
**可见范围**（谁能看见并使用）。三种形态（原生智能体 / 数字员工专家 /
专家团）在 :mod:`.registry` 聚合为统一注册表面，治理态由 :mod:`.service`
唯一写入、经 :mod:`.projection` 投影到 RBAC ``agent_grants``，运行期鉴权
链路零改动。工作流为外部平台对接预留形态（``EMPLOYEE_KIND_WORKFLOW``）。

@author qingfeng
"""
from .models import (
    EMPLOYEE_KINDS,
    EMPLOYEE_KIND_AGENT,
    EMPLOYEE_KIND_EXPERT,
    EMPLOYEE_KIND_TEAM,
    EMPLOYEE_KIND_WORKFLOW,
    VISIBILITIES,
    VISIBILITY_DEPARTMENT,
    VISIBILITY_ORG,
    VISIBILITY_PRIVATE,
    DigitalEmployeeVO,
    GovernanceBatchUpdateBody,
    GovernanceRecord,
    GovernanceUpdateBody,
    TeamMemberVO,
    employee_kind_of,
)
from .registry import build_registry, load_sources
from .service import (
    EmployeeGovernanceService,
    EmployeeNotFoundError,
    GovernanceValidationError,
    get_employee_governance_service,
)
from .store import EmployeeGovernanceStore, get_employee_governance_store

__all__ = [
    "DigitalEmployeeVO",
    "EMPLOYEE_KINDS",
    "EMPLOYEE_KIND_AGENT",
    "EMPLOYEE_KIND_EXPERT",
    "EMPLOYEE_KIND_TEAM",
    "EMPLOYEE_KIND_WORKFLOW",
    "EmployeeGovernanceService",
    "EmployeeGovernanceStore",
    "EmployeeNotFoundError",
    "GovernanceBatchUpdateBody",
    "GovernanceRecord",
    "GovernanceUpdateBody",
    "GovernanceValidationError",
    "TeamMemberVO",
    "VISIBILITIES",
    "VISIBILITY_DEPARTMENT",
    "VISIBILITY_ORG",
    "VISIBILITY_PRIVATE",
    "build_registry",
    "employee_kind_of",
    "get_employee_governance_service",
    "get_employee_governance_store",
    "load_sources",
]
