# -*- coding: utf-8 -*-
"""治理态 → 运行期鉴权面的投影（RBAC ``agent_grants`` + experts 兼容镜像）。

设计要点（为什么投影而不是改运行期）：

- 运行期鉴权链路（``workspace._assert_agent_grant`` / ``agent_context``）早已
  消费 RBAC ``agent_grants``，且部门已通过 :mod:`..orgs.service` 镜像为
  ``dept:{path}`` team；治理面只要把「可见范围」翻译成 grant 的 teams /
  users 列表，即可零改动复用整套鉴权，且部门成员增减由既有 team 镜像自动生效。
- 子树继承在**写入时展开**为具体 team 名列表（运行期 ``_grant_allows`` 是精确
  匹配，不做前缀判断），新建部门时由 :func:`refresh_for_new_department`
  对"授权了祖先部门"的员工重投影补齐。
- ``experts.visibility`` / ``experts.department`` 两列降级为**派生镜像**
  （derived mirror）：仅为兼容既有专家市场读路径，唯一写入者是本模块。

@author qingfeng
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Sequence

from ..experts.store import get_expert_store
from ..orgs.models import DepartmentRecord
from ..orgs.service import DEPT_TEAM_PREFIX
from ..rbac.models import GrantRecord
from ..rbac.store import get_rbac_store
from .models import (
    EMPLOYEE_KIND_EXPERT,
    VISIBILITY_DEPARTMENT,
    VISIBILITY_ORG,
    VISIBILITY_PRIVATE,
    GovernanceRecord,
)
from .store import get_employee_governance_store

logger = logging.getLogger(__name__)


def department_path_index(
    departments: Sequence[DepartmentRecord],
) -> Dict[str, str]:
    """构建 ``department_id → path`` 内存索引（投影与展开共用）。"""
    return {item.id: item.path for item in departments}


def department_name_index(
    departments: Sequence[DepartmentRecord],
) -> Dict[str, str]:
    """构建 ``department_id → name`` 内存索引（VO 组装用）。"""
    return {item.id: item.name for item in departments}


def selected_department_ids(
    record: GovernanceRecord,
) -> List[str]:
    """治理行的「生效部门集合」= 归属部门 ∪ 授权部门（去重保序）。"""
    ordered: List[str] = []
    candidates: Iterable[Optional[str]] = [
        record.department_id,
        *record.granted_departments,
    ]
    for department_id in candidates:
        if department_id and department_id not in ordered:
            ordered.append(department_id)
    return ordered


def expand_department_subtree(
    department_ids: Sequence[str],
    path_by_id: Dict[str, str],
) -> List[str]:
    """把选中部门展开为「自身 + 全部后代」的部门 id 列表。

    后代判定用物化路径前缀（``path/`` 开头），因此授权父部门天然覆盖子部门，
    与"部门及其下属团队可用"的企业语义一致。
    """
    expanded: List[str] = []
    for department_id in department_ids:
        path = path_by_id.get(department_id)
        if not path:
            continue
        if department_id not in expanded:
            expanded.append(department_id)
        for child_id, child_path in path_by_id.items():
            if (
                child_id not in expanded
                and child_path.startswith(f"{path}/")
            ):
                expanded.append(child_id)
    return expanded


def grant_for_record(
    record: GovernanceRecord,
    departments: Sequence[DepartmentRecord],
) -> Optional[GrantRecord]:
    """把一条治理记录翻译成 RBAC grant；返回 ``None`` 表示应删除 grant。"""
    # 全员共享：无 grant 即不限制（运行期 ``_grant_allows`` 的既有语义）
    if record.visibility == VISIBILITY_ORG:
        return None
    # 仅创建者：只放行归属人（无归属人时退化为仅 admin 可用，诚实反映配置缺陷）
    if record.visibility == VISIBILITY_PRIVATE:
        return GrantRecord(
            users=[record.owner_id] if record.owner_id else [],
            description=f"数字员工治理投影 · 仅创建者可用（{record.agent_id}）",
        )
    # 部门专属：归属 ∪ 授权展开子树 → 对应的部门镜像 team 集合
    path_by_id = department_path_index(departments)
    selected = selected_department_ids(record)
    subtree = expand_department_subtree(selected, path_by_id)
    teams = [f"{DEPT_TEAM_PREFIX}{path_by_id[item]}" for item in subtree]
    names = "、".join(
        department_name_index(departments).get(item, item) for item in selected
    )
    return GrantRecord(
        teams=teams,
        users=[record.owner_id] if record.owner_id else [],
        description=f"数字员工治理投影 · 部门专属（{names}）",
    )


def write_grant(
    record: GovernanceRecord,
    grant: Optional[GrantRecord],
) -> None:
    """落库投影结果：grant 为空即解除限制，否则整体替换。"""
    rbac = get_rbac_store()
    if grant is None:
        rbac.delete_agent_grant(record.agent_id)
        return
    rbac.set_agent_grant(record.agent_id, grant)


async def mirror_expert_columns(record: GovernanceRecord) -> None:
    """镜像到 ``experts`` 两列（derived mirror，兼容既有市场读路径）。

    非 expert 形态（原生 agent / team）无 experts 行可镜像，直接返回；
    ``department`` 列是历史自由文本，镜像为部门名称保持展示可用。
    """
    if record.entity_kind != EMPLOYEE_KIND_EXPERT or not record.entity_id:
        return
    from ..orgs.service import get_org_service

    departments = await get_org_service().list_departments()
    name_by_id = department_name_index(departments)
    # 镜像语义：可见性原样落列，部门列写归属部门名（未归属写空串）
    await get_expert_store().update_expert(
        record.entity_id,
        visibility=record.visibility,
        department=name_by_id.get(record.department_id or "", ""),
    )


async def project(record: GovernanceRecord) -> None:
    """一条治理记录的全量投影（RBAC grant + experts 镜像列）。"""
    from ..orgs.service import get_org_service

    departments = await get_org_service().list_departments()
    # 先落鉴权投影：这是运行期唯一消费面，失败必须显式抛出
    write_grant(record, grant_for_record(record, departments))
    # experts 镜像列失败不阻断治理写入（权威已在 employee_governance 落库）
    try:
        await mirror_expert_columns(record)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "governance mirror failed for %s",
            record.agent_id,
            exc_info=True,
        )


async def refresh_for_new_department(new_department: DepartmentRecord) -> int:
    """新建部门后重投影「授权了其祖先部门」的员工，补齐子树 ACL。

    Returns 受影响并重投影的员工数。
    """
    ancestor_paths = _ancestor_paths(new_department.path)
    records = [
        record
        for record in await get_employee_governance_store().list_all()
        if record.visibility == VISIBILITY_DEPARTMENT
    ]
    if not records:
        return 0
    from ..orgs.service import get_org_service

    departments = await get_org_service().list_departments()
    path_by_id = department_path_index(departments)
    refreshed = 0
    for record in records:
        selected_paths = {
            path_by_id.get(item, "")
            for item in selected_department_ids(record)
        }
        # 只重投影授权了祖先（不含自身，自身已在创建前投影过）的行
        if selected_paths & set(ancestor_paths[:-1]):
            await project(record)
            refreshed += 1
    return refreshed


async def refresh_for_removed_department(removed_path: str) -> int:
    """部门删除后重投影「授权了其祖先部门」的员工，剔除失效的 team。

    子树继承在治理写入时已展开成具体 team 名，所以删掉一个子部门后，授权了
    其父部门的员工 grant 里仍会留着那个已不存在的 ``dept:{path}``。运行期它
    人无法命中（team 记录已随部门删除），但 ACL 清单不该养幽灵引用。

    Returns 被重投影的员工数。
    """
    if not removed_path:
        return 0
    ancestor_paths = set(_ancestor_paths(removed_path)[:-1])
    if not ancestor_paths:
        return 0
    records = [
        record
        for record in await get_employee_governance_store().list_all()
        if record.visibility == VISIBILITY_DEPARTMENT
    ]
    if not records:
        return 0
    from ..orgs.service import get_org_service

    path_by_id = department_path_index(
        await get_org_service().list_departments(),
    )
    refreshed = 0
    for record in records:
        selected_paths = {
            path_by_id.get(item, "")
            for item in selected_department_ids(record)
        }
        if selected_paths & ancestor_paths:
            await project(record)
            refreshed += 1
    return refreshed


async def clear_department_reference(department_id: str) -> int:
    """部门删除后清理治理引用，避免悬空 ACL（归属置空、授权列表剔除）。

    Returns 被清理的治理行数。
    """
    store = get_employee_governance_store()
    records = await store.list_all()
    cleared = 0
    for record in records:
        # 引用未命中该部门则跳过（绝大多数行零写）
        if (
            record.department_id != department_id
            and department_id not in record.granted_departments
        ):
            continue
        granted = [
            item
            for item in record.granted_departments
            if item != department_id
        ]
        # 归属部门正是被删部门时置空，否则保留
        department = (
            None
            if record.department_id == department_id
            else record.department_id
        )
        visibility = record.visibility
        # 部门专属却再无生效部门 → 回落全员共享，避免员工被 ACL 锁死
        if (
            visibility == VISIBILITY_DEPARTMENT
            and not department
            and not granted
        ):
            visibility = VISIBILITY_ORG
        updated = await store.upsert(
            agent_id=record.agent_id,
            entity_kind=record.entity_kind,
            entity_id=record.entity_id,
            department_id=department,
            visibility=visibility,
            granted_departments=granted,
            owner_id=record.owner_id,
            updated_by="department_cleanup",
        )
        await project(updated)
        cleared += 1
    return cleared


def _ancestor_paths(path: str) -> List[str]:
    """物化路径拆成祖先链（末段为自身），如 ``a/b/c`` → [a, a/b, a/b/c]。"""
    segments = [item for item in (path or "").split("/") if item]
    return ["/".join(segments[: index + 1]) for index in range(len(segments))]


__all__ = [
    "clear_department_reference",
    "department_name_index",
    "department_path_index",
    "expand_department_subtree",
    "grant_for_record",
    "mirror_expert_columns",
    "project",
    "refresh_for_new_department",
    "refresh_for_removed_department",
    "selected_department_ids",
    "write_grant",
]
