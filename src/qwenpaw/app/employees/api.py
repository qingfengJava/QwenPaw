# -*- coding: utf-8 -*-
"""数字员工注册表与治理 API（控制台唯一数据面）。

路由前缀 ``/agents/registry``：与运行时 agent 平面同域，但**必须在
``agents_router`` 之前注册**——``GET /agents/{agentId}`` 是动态段，晚注册会
把 ``/agents/registry`` 吞成 ``agentId="registry"``（见 routers/__init__.py）。

- 读：``GET /agents/registry`` 聚合 agent / expert / team 三形态 + 治理态 +
  部门名，非管理员视角自动收敛为「可见即可用」；
- 写：``PUT /agents/registry/{agentId}/governance`` 与
  ``POST /agents/registry/governance/batch``（admin 面，写权威表并投影鉴权）。

@author qingfeng
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..rbac import PERM_ADMIN_ORGS, require_perm
from .models import (
    DigitalEmployeeVO,
    GovernanceBatchUpdateBody,
    GovernanceUpdateBody,
)
from .projection import GrantProjectionError
from .registry import build_registry
from .service import (
    EmployeeNotFoundError,
    GovernanceValidationError,
    get_employee_governance_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agents/registry",
    tags=["employee-registry"],
)


def _actor(request: Request) -> str:
    """治理操作人（AuthMiddleware 注入身份，未认证部署回落 local）。"""
    return getattr(request.state, "user", None) or "local"


@router.get(
    "",
    response_model=List[DigitalEmployeeVO],
    summary="数字员工注册表",
    description="按形态（智能体/专家团/工作流）与部门、可见性聚合的列表数据面",
)
async def list_employee_registry(
    request: Request,
    kind: str = Query("", description="all | agents | agent | expert | team"),
    department_id: str = Query("", description="按归属部门筛选"),
    visibility: str = Query("", description="org | department | private"),
    status: str = Query("", description="生命周期：draft | published | archived"),
    q: str = Query("", description="名称/职称/描述/标签模糊匹配"),
    unassigned: bool = Query(
        False,
        description="true 时只返回未归属部门的员工",
    ),
) -> List[DigitalEmployeeVO]:
    """注册表读接口（非管理员视角自动收敛为可见即可用）。"""
    return await build_registry(
        request,
        kind=kind,
        department_id=department_id,
        visibility=visibility,
        status=status,
        q=q,
        unassigned=unassigned,
    )


@router.put(
    "/{agent_id}/governance",
    response_model=DigitalEmployeeVO,
    summary="设置数字员工的归属部门与可见范围",
    dependencies=[Depends(require_perm(PERM_ADMIN_ORGS))],
)
async def set_employee_governance(
    agent_id: str,
    body: GovernanceUpdateBody,
    request: Request,
) -> DigitalEmployeeVO:
    """写入单个员工的治理态（权威表 + RBAC 鉴权投影 + experts 兼容镜像）。"""
    try:
        await get_employee_governance_service().apply(
            agent_id,
            body,
            _actor(request),
            request,
        )
    except EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GovernanceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GrantProjectionError as exc:
        # 治理行已落库但鉴权投影未生效：不能当作成功返回，也不能静默
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    rows = await build_registry(request)
    return _pick_row(rows, agent_id)


@router.post(
    "/governance/batch",
    response_model=List[DigitalEmployeeVO],
    summary="批量治理数字员工",
    dependencies=[Depends(require_perm(PERM_ADMIN_ORGS))],
)
async def set_employee_governance_batch(
    body: GovernanceBatchUpdateBody,
    request: Request,
) -> List[DigitalEmployeeVO]:
    """把同一套治理态套用到多个员工（表格视图批量操作）。"""
    try:
        written = await get_employee_governance_service().apply_batch_body(
            body,
            _actor(request),
            request,
        )
    except EmployeeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GovernanceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GrantProjectionError as exc:
        # 同上：鉴权投影失败必须显式暴露（503，提示重试）
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    rows = await build_registry(request)
    # 按写入顺序回显，未命中的行静默跳过（极端并发下员工可能已被删除）
    written_ids = {record.agent_id for record in written}
    return [row for row in rows if row.agent_id in written_ids]


def _pick_row(
    rows: List[DigitalEmployeeVO],
    agent_id: str,
) -> DigitalEmployeeVO:
    """从注册表取回指定员工的最新行（治理写入后的回显）。"""
    for row in rows:
        if row.agent_id == agent_id:
            return row
    raise HTTPException(
        status_code=404,
        detail=f"数字员工不存在或已下架: {agent_id}",
    )
