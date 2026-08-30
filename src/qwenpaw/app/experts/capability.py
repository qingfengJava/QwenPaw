# -*- coding: utf-8 -*-
"""Expert capability bindings: sop / knowledge_base / tool mounts.

数字员工能力挂载枢纽（StaffDeck agent_resource_bindings 的对应物）。
技能绑定不在本模块——``expert_skills`` 是发布物化链的权威，两者职责
在表注释中互相指认，禁止合并（见
docs/design/2026-08-30-digital-employee-capability-layer.md 决策 D2）。

正向：PUT 整表替换（幂等）；逆向：PUT 空数组=清空，专家删除时由
router 级联清理绑定行。
@author qingfeng
"""

from __future__ import annotations

import json
from typing import Dict, List

from sqlalchemy import text

from ..enterprise import current_tenant_id, require_enterprise_engine
from .models import RESOURCE_TYPES, ResourceBinding

_COLS = "expert_id, resource_type, resource_id, enabled, seq, metadata"


def _row_to_binding(row) -> ResourceBinding:
    """Map one binding row (metadata JSONB → dict)."""
    return ResourceBinding(
        expert_id=row.expert_id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        enabled=bool(row.enabled),
        seq=row.seq,
        metadata=row.metadata or {},
    )


class CapabilityStore:
    """CRUD over ``expert_resource_bindings``, tenant-scoped."""

    async def list_bindings(
        self,
        expert_id: str,
        resource_type: str = "",
    ) -> List[ResourceBinding]:
        """List one expert's bindings, optionally filtered by type.

        仅查必要列；按类型+seq 排序保证挂载顺序稳定。
        """
        engine = require_enterprise_engine()
        clauses = ["tenant_id = :tid", "expert_id = :eid"]
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "eid": expert_id,
        }
        if resource_type:
            clauses.append("resource_type = :rtype")
            params["rtype"] = resource_type
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _COLS + " FROM expert_resource_bindings "
                    "WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY resource_type, seq, resource_id"
                ),
                params,
            )
            return [_row_to_binding(r) for r in result]

    async def list_experts_for_resource(
        self,
        resource_type: str,
        resource_id: str,
    ) -> List[str]:
        """Expert ids mounting one resource (cascade / refcount helpers)."""
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT expert_id FROM expert_resource_bindings "
                    "WHERE tenant_id = :tid AND resource_type = :rtype "
                    "AND resource_id = :rid"
                ),
                {
                    "tid": current_tenant_id(),
                    "rtype": resource_type,
                    "rid": resource_id,
                },
            )
            return [r.expert_id for r in result]

    async def replace_bindings(
        self,
        expert_id: str,
        bindings: List[ResourceBinding],
    ) -> List[ResourceBinding]:
        """Wholesale replacement inside one transaction.

        - 未知 resource_type 直接丢弃（防御前端脏数据）；
        - (type, resource_id) 去重、seq 缺省按入参顺序补齐；
        - metadata 存挂载快照（name 等），由调用方填充。
        """
        seen: Dict[str, ResourceBinding] = {}
        for index, binding in enumerate(bindings):
            if binding.resource_type not in RESOURCE_TYPES:
                continue
            key = f"{binding.resource_type}:{binding.resource_id}"
            if key in seen:
                continue
            seen[key] = ResourceBinding(
                expert_id=expert_id,
                resource_type=binding.resource_type,
                resource_id=binding.resource_id,
                enabled=binding.enabled,
                seq=binding.seq or index,
                metadata=binding.metadata or {},
            )
        ordered = sorted(
            seen.values(),
            key=lambda b: (b.resource_type, b.seq, b.resource_id),
        )

        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM expert_resource_bindings "
                    "WHERE tenant_id = :tid AND expert_id = :eid"
                ),
                {"tid": tid, "eid": expert_id},
            )
            for binding in ordered:
                await conn.execute(
                    text(
                        "INSERT INTO expert_resource_bindings (tenant_id, "
                        "expert_id, resource_type, resource_id, enabled, "
                        "seq, metadata) VALUES (:tid, :eid, :rtype, :rid, "
                        ":enabled, :seq, CAST(:meta AS JSONB))"
                    ),
                    {
                        "tid": tid,
                        "eid": expert_id,
                        "rtype": binding.resource_type,
                        "rid": binding.resource_id,
                        "enabled": binding.enabled,
                        "seq": binding.seq,
                        "meta": json.dumps(binding.metadata or {}),
                    },
                )
        return ordered

    async def delete_expert_bindings(self, expert_id: str) -> int:
        """Cascade helper: drop every binding of one expert.

        逆向路径：专家删除/归档清空挂载（返回删除行数便于审计）。
        """
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM expert_resource_bindings "
                    "WHERE tenant_id = :tid AND expert_id = :eid"
                ),
                {"tid": current_tenant_id(), "eid": expert_id},
            )
            return result.rowcount or 0

    async def member_capability_snapshot(
        self,
        expert_ids: List[str],
    ) -> Dict[str, Dict[str, list]]:
        """Batched capability snapshot for workforce planning (P1 接线).

        返回 ``{expert_id: {"sops": [...], "kb_ids": [...],
        "tools": [...]}}``：
        - sops：已发布 SOP 的紧凑投影（name/goal/steps[{t,ok}]），
          供规划上下文与 TaskContract.sop_refs / Verifier rubric；
        - kb_ids：绑定的知识库 id（存在性过滤，kb 缺失静默剔除）；
        - tools：绑定的工具名。

        每类一次批查（ANY(:ids)），无 N+1；任何异常由调用方降级。
        """
        ids = [e for e in expert_ids if e]
        if not ids:
            return {}
        snapshot: Dict[str, Dict[str, list]] = {
            eid: {"sops": [], "kb_ids": [], "tools": []} for eid in ids
        }
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT expert_id, resource_type, resource_id FROM "
                        "expert_resource_bindings WHERE tenant_id = :tid "
                        "AND expert_id = ANY(:ids) AND enabled"
                    ),
                    {"tid": tid, "ids": ids},
                )
            ).all()
            sop_ids = sorted(
                {r.resource_id for r in rows if r.resource_type == "sop"},
            )
            sops = []
            if sop_ids:
                sops = (
                    await conn.execute(
                        text(
                            "SELECT id, name, goal, nodes FROM sops "
                            "WHERE tenant_id = :tid AND id = ANY(:ids) "
                            "AND status = 'published'"
                        ),
                        {"tid": tid, "ids": sop_ids},
                    )
                ).all()
        sop_index = {s.id: s for s in sops}
        for row in rows:
            bucket = snapshot.get(row.expert_id)
            if bucket is None:
                continue
            if row.resource_type == "tool":
                bucket["tools"].append(row.resource_id)
            elif row.resource_type == "knowledge_base":
                bucket["kb_ids"].append(row.resource_id)
            elif row.resource_type == "sop":
                sop = sop_index.get(row.resource_id)
                if sop is None:
                    continue
                # 紧凑投影：节点标题 + 验收要点（prompt 预算友好）
                steps = [
                    {
                        "t": (node or {}).get("title", ""),
                        "ok": (node or {}).get("expected_outcome", ""),
                    }
                    for node in (sop.nodes or [])
                    if isinstance(node, dict)
                ]
                bucket["sops"].append(
                    {
                        "name": sop.name,
                        "goal": sop.goal or "",
                        "steps": steps[:8],
                    },
                )
        # 知识库存在性过滤（kb 为可选子系统；缺失绑定静默剔除）
        if any(b["kb_ids"] for b in snapshot.values()):
            try:
                from ..kb.service import get_kb_service

                service = get_kb_service()
                for bucket in snapshot.values():
                    bucket["kb_ids"] = [
                        kb_id
                        for kb_id in bucket["kb_ids"]
                        if service.get_kb(kb_id) is not None
                    ]
            except Exception:  # noqa: BLE001 - kb 缺失不阻塞能力面
                pass
        return snapshot


_store: CapabilityStore | None = None


def get_capability_store() -> CapabilityStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = CapabilityStore()
    return _store
