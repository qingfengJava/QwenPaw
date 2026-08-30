# -*- coding: utf-8 -*-
"""SOP process assets: CRUD, versioned publishing, rollback.

SOP 是"经验流程资产"（StaffDeck SkillCard 的结构化对应物），绑定到
数字员工后在 workforce 规划期作为参考蓝图注入、在验收期提供
``expected_outcome`` 要点——**绝不作为硬状态机执行**（决策 D3，见
docs/design/2026-08-30-digital-employee-capability-layer.md）。

版本语义（与 published_experts 快照模式一致）：
- publish: version+1 并写 sop_versions 不可变快照；
- rollback: 取历史快照发布为更高新版本（不篡改历史）；
- delete: 仅 draft 可物理删，published 走 archived（审计优先）。
@author qingfeng
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from .models import (
    SOP_STATUS_ARCHIVED,
    SOP_STATUS_DRAFT,
    SOP_STATUS_PUBLISHED,
    SopRecord,
    SopVersionRecord,
)

_COLS = (
    "id, name, description, business_domain, goal, nodes, edges, slots, "
    "status, version, owner_id, created_at, updated_at"
)

_LIGHT_COLS = (
    "id, name, description, business_domain, goal, status, version, "
    "owner_id, created_at, updated_at"
)


def _snapshot_of(record: SopRecord) -> dict:
    """Full-field snapshot dict for one SOP (version payload)."""
    return {
        "name": record.name,
        "description": record.description,
        "business_domain": record.business_domain,
        "goal": record.goal,
        "nodes": record.nodes,
        "edges": record.edges,
        "slots": record.slots,
    }


def _row_to_sop(row, *, light: bool = False) -> SopRecord:
    """Map one sops row (light 投影跳过重 JSONB 列，同 experts 卡片法)."""
    return SopRecord(
        id=row.id,
        name=row.name,
        description=row.description or "",
        business_domain=row.business_domain or "",
        goal="" if light else (row.goal or ""),
        nodes=[] if light else list(row.nodes or []),
        edges=[] if light else list(row.edges or []),
        slots=[] if light else list(row.slots or []),
        status=row.status,
        version=row.version,
        owner_id=row.owner_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SopStore:
    """CRUD + version chain over ``sops`` / ``sop_versions``."""

    async def create_sop(
        self,
        name: str,
        description: str = "",
        business_domain: str = "",
        goal: str = "",
        nodes: Optional[List[dict]] = None,
        edges: Optional[List[dict]] = None,
        slots: Optional[List[dict]] = None,
        owner_id: Optional[str] = None,
        sop_id: Optional[str] = None,
    ) -> SopRecord:
        """Insert a draft SOP (version=1, no snapshot until publish)."""
        tid = current_tenant_id()
        sop_id = sop_id or new_id("sop")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO sops (tenant_id, id, name, description, "
                    "business_domain, goal, nodes, edges, slots, status, "
                    "version, owner_id) VALUES (:tid, :id, :name, :desc, "
                    ":domain, :goal, CAST(:nodes AS JSONB), "
                    "CAST(:edges AS JSONB), CAST(:slots AS JSONB), "
                    ":status, 1, :owner) RETURNING " + _COLS
                ),
                {
                    "tid": tid,
                    "id": sop_id,
                    "name": name,
                    "desc": description,
                    "domain": business_domain,
                    "goal": goal,
                    "nodes": json.dumps(nodes or []),
                    "edges": json.dumps(edges or []),
                    "slots": json.dumps(slots or []),
                    "status": SOP_STATUS_DRAFT,
                    "owner": owner_id,
                },
            )
            return _row_to_sop(result.one())

    async def get_sop(self, sop_id: str) -> Optional[SopRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _COLS + " FROM sops "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": current_tenant_id(), "id": sop_id},
            )
            row = result.first()
            return _row_to_sop(row) if row else None

    async def list_sops(
        self,
        status: str = "",
        owner_id: str = "",
        q: str = "",
    ) -> List[SopRecord]:
        """List SOPs (light projection for list pages)."""
        engine = require_enterprise_engine()
        clauses = ["tenant_id = :tid"]
        params: Dict[str, object] = {"tid": current_tenant_id()}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if owner_id:
            clauses.append("owner_id = :owner")
            params["owner"] = owner_id
        if q:
            clauses.append("(name ILIKE :kw OR description ILIKE :kw)")
            params["kw"] = f"%{q}%"
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT "
                    + _LIGHT_COLS
                    + " FROM sops WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY updated_at DESC"
                ),
                params,
            )
            return [_row_to_sop(r, light=True) for r in result]

    async def update_sop(self, sop_id: str, **fields) -> Optional[SopRecord]:
        """Draft-only field update (published SOPs mutate via versions).

        任何字段改动都会把已发布 SOP 打回 draft 语义之外的状态保护：
        published/archived 直接拒绝，避免"绕过版本链改线上资产"。
        """
        current = await self.get_sop(sop_id)
        if current is None:
            return None
        if current.status != SOP_STATUS_DRAFT:
            raise ValueError("only draft SOPs can be edited directly")

        sets = []
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "id": sop_id,
        }
        if fields.get("name") is not None:
            sets.append("name = :name")
            params["name"] = fields["name"]
        if fields.get("description") is not None:
            sets.append("description = :desc")
            params["desc"] = fields["description"]
        if fields.get("business_domain") is not None:
            sets.append("business_domain = :domain")
            params["domain"] = fields["business_domain"]
        if fields.get("goal") is not None:
            sets.append("goal = :goal")
            params["goal"] = fields["goal"]
        if fields.get("nodes") is not None:
            sets.append("nodes = CAST(:nodes AS JSONB)")
            params["nodes"] = json.dumps(fields["nodes"])
        if fields.get("edges") is not None:
            sets.append("edges = CAST(:edges AS JSONB)")
            params["edges"] = json.dumps(fields["edges"])
        if fields.get("slots") is not None:
            sets.append("slots = CAST(:slots AS JSONB)")
            params["slots"] = json.dumps(fields["slots"])
        if not sets:
            return current
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE sops SET "
                    + ", ".join(sets)
                    + ", updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :id RETURNING " + _COLS
                ),
                params,
            )
            row = result.first()
            return _row_to_sop(row) if row else None

    async def publish_sop(
        self,
        sop_id: str,
        published_by: str = "",
        change_note: str = "",
    ) -> Optional[SopRecord]:
        """Publish: version+1 + immutable snapshot (idempotent-safe)."""
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE sops SET status = :status, "
                    "version = version + 1, updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id "
                    "AND status <> :archived RETURNING " + _COLS
                ),
                {
                    "tid": tid,
                    "id": sop_id,
                    "status": SOP_STATUS_PUBLISHED,
                    "archived": SOP_STATUS_ARCHIVED,
                },
            )
            row = result.first()
            if row is None:
                return None
            record = _row_to_sop(row)
            # 发布即快照（ON CONFLICT DO NOTHING 保证同版本幂等）
            await conn.execute(
                text(
                    "INSERT INTO sop_versions (tenant_id, sop_id, version, "
                    "snapshot, change_note, published_by) VALUES "
                    "(:tid, :sid, :version, CAST(:snapshot AS JSONB), "
                    ":note, :by) ON CONFLICT (tenant_id, sop_id, version) "
                    "DO NOTHING"
                ),
                {
                    "tid": tid,
                    "sid": sop_id,
                    "version": record.version,
                    "snapshot": json.dumps(_snapshot_of(record)),
                    "note": change_note,
                    "by": published_by,
                },
            )
            return record

    async def rollback_sop(
        self,
        sop_id: str,
        to_version: int,
        published_by: str = "",
    ) -> Optional[SopRecord]:
        """Rollback: restore a historical snapshot as a NEW higher version.

        不改写历史版本行——回滚本身也是一次发布（审计优先）。
        """
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            snap = await conn.execute(
                text(
                    "SELECT snapshot FROM sop_versions WHERE "
                    "tenant_id = :tid AND sop_id = :sid AND version = :v"
                ),
                {"tid": tid, "sid": sop_id, "v": to_version},
            )
            snap_row = snap.first()
            if snap_row is None:
                return None
            snapshot = snap_row.snapshot or {}
            result = await conn.execute(
                text(
                    "UPDATE sops SET name = :name, description = :desc, "
                    "business_domain = :domain, goal = :goal, "
                    "nodes = CAST(:nodes AS JSONB), "
                    "edges = CAST(:edges AS JSONB), "
                    "slots = CAST(:slots AS JSONB), status = :status, "
                    "version = version + 1, updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id AND "
                    "status <> :archived RETURNING " + _COLS
                ),
                {
                    "tid": tid,
                    "id": sop_id,
                    "name": snapshot.get("name", ""),
                    "desc": snapshot.get("description", ""),
                    "domain": snapshot.get("business_domain", ""),
                    "goal": snapshot.get("goal", ""),
                    "nodes": json.dumps(snapshot.get("nodes", [])),
                    "edges": json.dumps(snapshot.get("edges", [])),
                    "slots": json.dumps(snapshot.get("slots", [])),
                    "status": SOP_STATUS_PUBLISHED,
                    "archived": SOP_STATUS_ARCHIVED,
                },
            )
            row = result.first()
            if row is None:
                return None
            record = _row_to_sop(row)
            await conn.execute(
                text(
                    "INSERT INTO sop_versions (tenant_id, sop_id, version, "
                    "snapshot, change_note, published_by) VALUES "
                    "(:tid, :sid, :version, CAST(:snapshot AS JSONB), "
                    ":note, :by) ON CONFLICT (tenant_id, sop_id, version) "
                    "DO NOTHING"
                ),
                {
                    "tid": tid,
                    "sid": sop_id,
                    "version": record.version,
                    "snapshot": json.dumps(_snapshot_of(record)),
                    "note": f"rollback to v{to_version}",
                    "by": published_by,
                },
            )
            return record

    async def publish_new_version(
        self,
        sop_id: str,
        nodes: Optional[List[dict]] = None,
        edges: Optional[List[dict]] = None,
        slots: Optional[List[dict]] = None,
        goal: Optional[str] = None,
        change_note: str = "",
        published_by: str = "",
    ) -> Optional[SopRecord]:
        """Publish a NEW version from explicit content (演进提案专用).

        与 ``update_sop``（仅草稿）和 ``rollback_sop``（恢复历史）互补：
        演进提案的 SOP 候选经此进入版本链——不改历史、不做草稿中转，
        发布即快照（审计优先，与 rollback 同一语义家族）。
        """
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            sets = ["version = version + 1", "updated_at = now()"]
            params: Dict[str, object] = {"tid": tid, "id": sop_id}
            if nodes is not None:
                sets.append("nodes = CAST(:nodes AS JSONB)")
                params["nodes"] = json.dumps(nodes)
            if edges is not None:
                sets.append("edges = CAST(:edges AS JSONB)")
                params["edges"] = json.dumps(edges)
            if slots is not None:
                sets.append("slots = CAST(:slots AS JSONB)")
                params["slots"] = json.dumps(slots)
            if goal is not None:
                sets.append("goal = :goal")
                params["goal"] = goal
            result = await conn.execute(
                text(
                    "UPDATE sops SET "
                    + ", ".join(sets)
                    + " WHERE tenant_id = :tid AND id = :id "
                    "AND status <> :archived RETURNING " + _COLS
                ),
                {
                    "tid": tid,
                    "id": sop_id,
                    "archived": SOP_STATUS_ARCHIVED,
                },
            )
            row = result.first()
            if row is None:
                return None
            record = _row_to_sop(row)
            await conn.execute(
                text(
                    "INSERT INTO sop_versions (tenant_id, sop_id, version, "
                    "snapshot, change_note, published_by) VALUES "
                    "(:tid, :sid, :version, CAST(:snapshot AS JSONB), "
                    ":note, :by) ON CONFLICT (tenant_id, sop_id, version) "
                    "DO NOTHING"
                ),
                {
                    "tid": tid,
                    "sid": sop_id,
                    "version": record.version,
                    "snapshot": json.dumps(_snapshot_of(record)),
                    "note": change_note,
                    "by": published_by,
                },
            )
            return record

    async def list_versions(self, sop_id: str) -> List[SopVersionRecord]:
        """Version history, newest first."""
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT sop_id, version, snapshot, change_note, "
                    "published_by, created_at FROM sop_versions WHERE "
                    "tenant_id = :tid AND sop_id = :sid "
                    "ORDER BY version DESC"
                ),
                {"tid": current_tenant_id(), "sid": sop_id},
            )
            return [
                SopVersionRecord(
                    sop_id=r.sop_id,
                    version=r.version,
                    snapshot=r.snapshot or {},
                    change_note=r.change_note or "",
                    published_by=r.published_by,
                    created_at=r.created_at,
                )
                for r in result
            ]

    async def archive_sop(self, sop_id: str) -> Optional[SopRecord]:
        """Archive (published history stays auditable)."""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE sops SET status = :status, updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id RETURNING " + _COLS
                ),
                {
                    "tid": current_tenant_id(),
                    "id": sop_id,
                    "status": SOP_STATUS_ARCHIVED,
                },
            )
            row = result.first()
            return _row_to_sop(row) if row else None

    async def delete_sop(self, sop_id: str) -> bool:
        """Drafts only: physical delete plus its version rows."""
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM sop_versions WHERE tenant_id = :tid "
                    "AND sop_id = :sid"
                ),
                {"tid": tid, "sid": sop_id},
            )
            result = await conn.execute(
                text(
                    "DELETE FROM sops WHERE tenant_id = :tid AND id = :id "
                    "AND status = :draft"
                ),
                {"tid": tid, "id": sop_id, "draft": SOP_STATUS_DRAFT},
            )
            return result.rowcount > 0


_store: SopStore | None = None


def get_sop_store() -> SopStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = SopStore()
    return _store
