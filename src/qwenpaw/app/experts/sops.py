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
import logging
from typing import Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from ..agent_docs.store import environment_for_agent
from .models import (
    SOP_ENVIRONMENT_DRAFT,
    SOP_ENVIRONMENT_PRODUCTION,
    SOP_STATUS_ARCHIVED,
    SOP_STATUS_DRAFT,
    SOP_STATUS_PUBLISHED,
    SopRecord,
    SopVersionRecord,
)

logger = logging.getLogger(__name__)

_COLS = (
    "id, name, description, business_domain, goal, nodes, edges, slots, "
    "status, version, owner_id, environment, created_at, updated_at"
)

_LIGHT_COLS = (
    "id, name, description, business_domain, goal, status, version, "
    "owner_id, environment, created_at, updated_at"
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
        environment=getattr(row, "environment", SOP_ENVIRONMENT_PRODUCTION),
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
        environment: str = SOP_ENVIRONMENT_PRODUCTION,
    ) -> SopRecord:
        """Insert one SOP row in the given environment.

        默认写 production（兼容旧调用面）；UI/AI 新建草稿时显式传
        ``environment='draft'``，promote 后才进线上。
        """
        tid = current_tenant_id()
        sop_id = sop_id or new_id("sop")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO sops (tenant_id, id, name, description, "
                    "business_domain, goal, nodes, edges, slots, status, "
                    "version, owner_id, environment) VALUES (:tid, :id, "
                    ":name, :desc, :domain, :goal, CAST(:nodes AS JSONB), "
                    "CAST(:edges AS JSONB), CAST(:slots AS JSONB), "
                    ":status, 1, :owner, :env) RETURNING " + _COLS
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
                    "env": environment,
                },
            )
            record = _row_to_sop(result.one())
        # 提交后双通道广播（sop 级全量快照 + 员工级轻量索引，面板跟随）
        await broadcast_sop_event("created", record)
        return record

    async def get_sop(
        self,
        sop_id: str,
        environment: str = SOP_ENVIRONMENT_PRODUCTION,
    ) -> Optional[SopRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _COLS + " FROM sops "
                    "WHERE tenant_id = :tid AND id = :id "
                    "AND environment = :env"
                ),
                {
                    "tid": current_tenant_id(),
                    "id": sop_id,
                    "env": environment,
                },
            )
            row = result.first()
            return _row_to_sop(row) if row else None

    async def list_sops(
        self,
        status: str = "",
        owner_id: str = "",
        q: str = "",
        full: bool = False,
        environment: str = SOP_ENVIRONMENT_PRODUCTION,
    ) -> List[SopRecord]:
        """List SOPs in one environment (light projection by default)."""
        engine = require_enterprise_engine()
        clauses = ["tenant_id = :tid", "environment = :env"]
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "env": environment,
        }
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if owner_id:
            clauses.append("owner_id = :owner")
            params["owner"] = owner_id
        if q:
            clauses.append("(name ILIKE :kw OR description ILIKE :kw)")
            params["kw"] = f"%{q}%"
        cols = _COLS if full else _LIGHT_COLS
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT "
                    + cols
                    + " FROM sops WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY updated_at DESC"
                ),
                params,
            )
            return [_row_to_sop(r, light=not full) for r in result]

    async def update_sop(
        self,
        sop_id: str,
        environment: str = SOP_ENVIRONMENT_PRODUCTION,
        **fields,
    ) -> Optional[SopRecord]:
        """Update content fields of one environment row.

        环境隔离语义：草稿行（environment=draft）随便改，不污染线上；
        线上行（production）仅 archived 拒绝编辑。运行时按 agent 环境读
        对应行现值，「发布/promote」才把草稿行升为线上新版本写快照。
        """
        current = await self.get_sop(sop_id, environment=environment)
        if current is None:
            return None
        if current.status == SOP_STATUS_ARCHIVED:
            raise ValueError("archived SOPs cannot be edited")

        sets = []
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "id": sop_id,
            "env": environment,
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
                    "AND id = :id AND environment = :env RETURNING " + _COLS
                ),
                params,
            )
            row = result.first()
            record = _row_to_sop(row) if row else None
        if record is not None:
            # 提交后双通道广播（画布重绘 + 面板跟随）
            await broadcast_sop_event("updated", record)
        return record

    async def publish_sop(
        self,
        sop_id: str,
        published_by: str = "",
        change_note: str = "",
    ) -> Optional[SopRecord]:
        """Publish the production row: version+1 + immutable snapshot.

        保留旧语义（直接发布线上行）供演进提案/回滚链路复用；
        工作台草稿发布走 :meth:`promote_sop`（draft→production）。
        """
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE sops SET status = :status, "
                    "version = version + 1, updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id "
                    "AND environment = :env AND status <> :archived "
                    "RETURNING " + _COLS
                ),
                {
                    "tid": tid,
                    "id": sop_id,
                    "status": SOP_STATUS_PUBLISHED,
                    "archived": SOP_STATUS_ARCHIVED,
                    "env": SOP_ENVIRONMENT_PRODUCTION,
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
        # 提交后双通道广播（画布重绘 + 面板跟随）
        await broadcast_sop_event("published", record)
        return record

    async def promote_sop(
        self,
        sop_id: str,
        published_by: str = "",
        change_note: str = "",
    ) -> Optional[SopRecord]:
        """Promote the draft row into the production row (publish gate).

        对齐 agent_documents 的 promote 语义：读草稿行内容，UPSERT 到
        production 行（已存在则 version+1，否则 version=1），写不可变
        版本快照。草稿行保留作为后续可编辑工作副本（与线上分叉即
        “有未发布变更”）。无草稿行时退回直接发布 production 行。
        """
        engine = require_enterprise_engine()
        tid = current_tenant_id()
        async with engine.begin() as conn:
            draft = await conn.execute(
                text(
                    "SELECT " + _COLS + " FROM sops WHERE tenant_id = :tid "
                    "AND id = :id AND environment = :draft"
                ),
                {"tid": tid, "id": sop_id, "draft": SOP_ENVIRONMENT_DRAFT},
            )
            draft_row = draft.first()
            if draft_row is None:
                # 无草稿行（存量 production-only SOP）：退回直接发布
                return await self.publish_sop(
                    sop_id,
                    published_by=published_by,
                    change_note=change_note,
                )
            draft_record = _row_to_sop(draft_row)
            # 取当前 production 行版本号（不存在则 0，首次 promote 为 v1）
            prod = await conn.execute(
                text(
                    "SELECT version FROM sops WHERE tenant_id = :tid "
                    "AND id = :id AND environment = :prod"
                ),
                {
                    "tid": tid,
                    "id": sop_id,
                    "prod": SOP_ENVIRONMENT_PRODUCTION,
                },
            )
            prod_row = prod.first()
            next_version = (prod_row.version + 1) if prod_row else 1
            result = await conn.execute(
                text(
                    "INSERT INTO sops (tenant_id, id, name, description, "
                    "business_domain, goal, nodes, edges, slots, status, "
                    "version, owner_id, environment) VALUES (:tid, :id, "
                    ":name, :desc, :domain, :goal, CAST(:nodes AS JSONB), "
                    "CAST(:edges AS JSONB), CAST(:slots AS JSONB), "
                    ":status, :version, :owner, :prod) "
                    "ON CONFLICT (tenant_id, id, environment) DO UPDATE SET "
                    "name = EXCLUDED.name, description = EXCLUDED.description, "
                    "business_domain = EXCLUDED.business_domain, "
                    "goal = EXCLUDED.goal, nodes = EXCLUDED.nodes, "
                    "edges = EXCLUDED.edges, slots = EXCLUDED.slots, "
                    "status = EXCLUDED.status, version = EXCLUDED.version, "
                    "owner_id = EXCLUDED.owner_id, updated_at = now() "
                    "RETURNING " + _COLS
                ),
                {
                    "tid": tid,
                    "id": sop_id,
                    "name": draft_record.name,
                    "desc": draft_record.description,
                    "domain": draft_record.business_domain,
                    "goal": draft_record.goal,
                    "nodes": json.dumps(draft_record.nodes),
                    "edges": json.dumps(draft_record.edges),
                    "slots": json.dumps(draft_record.slots),
                    "status": SOP_STATUS_PUBLISHED,
                    "version": next_version,
                    "owner": draft_record.owner_id,
                    "prod": SOP_ENVIRONMENT_PRODUCTION,
                },
            )
            row = result.first()
            if row is None:
                return None
            record = _row_to_sop(row)
            # promote 即快照（同版本幂等）
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
        # 提交后双通道广播（画布重绘 + 面板跟随）
        await broadcast_sop_event("published", record)
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
                    "environment = :env AND status <> :archived "
                    "RETURNING " + _COLS
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
                    "env": SOP_ENVIRONMENT_PRODUCTION,
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
        # 提交后双通道广播（回滚即发布语义，画布重绘 + 面板跟随）
        await broadcast_sop_event("published", record)
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
                    "AND environment = :env AND status <> :archived "
                    "RETURNING " + _COLS
                ),
                {
                    "tid": tid,
                    "id": sop_id,
                    "archived": SOP_STATUS_ARCHIVED,
                    "env": SOP_ENVIRONMENT_PRODUCTION,
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

    async def duplicate_sop(
        self,
        sop_id: str,
        target_expert_id: str,
        new_sop_id: Optional[str] = None,
        environment: str = SOP_ENVIRONMENT_DRAFT,
    ) -> Optional[SopRecord]:
        """Copy one SOP as a fresh draft owned by the target expert.

        复制式复用（用户决策）：副本是全新资产（新 id、draft、
        version=1），只复制业务内容，不复制绑定、不复制版本链。
        源行优先取草稿行（工作台可见态），无则取 production 行。
        """
        source = await self.get_sop(
            sop_id,
            environment=SOP_ENVIRONMENT_DRAFT,
        ) or await self.get_sop(
            sop_id,
            environment=SOP_ENVIRONMENT_PRODUCTION,
        )
        if source is None:
            return None
        return await self.create_sop(
            name=source.name,
            description=source.description,
            business_domain=source.business_domain,
            goal=source.goal,
            nodes=source.nodes,
            edges=source.edges,
            slots=source.slots,
            owner_id=target_expert_id,
            sop_id=new_sop_id,
            environment=environment,
        )

    async def archive_sop(self, sop_id: str) -> Optional[SopRecord]:
        """Archive both environment rows (published history stays auditable)."""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE sops SET status = :status, updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :id "
                    "AND environment = :env RETURNING " + _COLS
                ),
                {
                    "tid": current_tenant_id(),
                    "id": sop_id,
                    "status": SOP_STATUS_ARCHIVED,
                    "env": SOP_ENVIRONMENT_PRODUCTION,
                },
            )
            row = result.first()
            # 归档时一并丢弃草稿行（线上已归档，草稿无继续编辑意义）
            await conn.execute(
                text(
                    "DELETE FROM sops WHERE tenant_id = :tid AND id = :id "
                    "AND environment = :draft"
                ),
                {
                    "tid": current_tenant_id(),
                    "id": sop_id,
                    "draft": SOP_ENVIRONMENT_DRAFT,
                },
            )
            return _row_to_sop(row) if row else None

    async def delete_sop(self, sop_id: str) -> bool:
        """Physical delete both environment rows + version rows.

        router 层保证只对无绑定 SOP 调用；draft 与 production 一并物理删。
        """
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
                    "DELETE FROM sops WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": tid, "id": sop_id},
            )
            return result.rowcount > 0

    async def ensure_draft_row(
        self,
        sop_id: str,
    ) -> Optional[SopRecord]:
        """Return the editable draft row, forking from production if absent.

        存量 SOP（仅 production 行）首次进画布编辑时调用：把线上行内容
        复制一份到 draft 行作为工作副本，返回草稿。无 production 行时
        返回 None（SOP 不存在）。
        """
        draft = await self.get_sop(
            sop_id,
            environment=SOP_ENVIRONMENT_DRAFT,
        )
        if draft is not None:
            return draft
        source = await self.get_sop(
            sop_id,
            environment=SOP_ENVIRONMENT_PRODUCTION,
        )
        if source is None:
            return None
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO sops (tenant_id, id, name, description, "
                    "business_domain, goal, nodes, edges, slots, status, "
                    "version, owner_id, environment) VALUES (:tid, :id, "
                    ":name, :desc, :domain, :goal, CAST(:nodes AS JSONB), "
                    "CAST(:edges AS JSONB), CAST(:slots AS JSONB), "
                    ":status, 1, :owner, :draft) "
                    "ON CONFLICT (tenant_id, id, environment) DO UPDATE SET "
                    "name = EXCLUDED.name, description = EXCLUDED.description, "
                    "business_domain = EXCLUDED.business_domain, "
                    "goal = EXCLUDED.goal, nodes = EXCLUDED.nodes, "
                    "edges = EXCLUDED.edges, slots = EXCLUDED.slots, "
                    "updated_at = now() RETURNING " + _COLS
                ),
                {
                    "tid": current_tenant_id(),
                    "id": sop_id,
                    "name": source.name,
                    "desc": source.description,
                    "domain": source.business_domain,
                    "goal": source.goal,
                    "nodes": json.dumps(source.nodes),
                    "edges": json.dumps(source.edges),
                    "slots": json.dumps(source.slots),
                    "status": SOP_STATUS_DRAFT,
                    "owner": source.owner_id,
                    "draft": SOP_ENVIRONMENT_DRAFT,
                },
            )
            row = result.first()
            return _row_to_sop(row) if row else None


async def broadcast_sop_event(action: str, record: SopRecord) -> None:
    """Broadcast one SOP write on both live topics (canvas + panel follows).

    双通道广播（AI 边画、画布边变、面板跟随）：
    - sop 级 topic 携带全量 nodes/edges/slots，SopFlowCanvas 订阅后
      直接 setNodes 重绘；
    - 员工级 topic 只发轻量索引事件（不含图数据）：AI 新建时前端尚
      不知 sop_id，面板经此感知 created 后自动打开画布/刷新列表。
    广播失败绝不影响写主链路（画布/列表下次从 PG 取现值）。
    """
    try:
        from ..events.bus import get_event_bus, sop_expert_topic, sop_topic

        tid = current_tenant_id()
        await get_event_bus().publish(
            sop_topic(tid, record.id),
            {
                "action": action,
                "sop_id": record.id,
                "environment": record.environment,
                "version": record.version,
                "name": record.name,
                "goal": record.goal,
                "nodes": record.nodes,
                "edges": record.edges,
                "slots": record.slots,
            },
        )
        if record.owner_id:
            await get_event_bus().publish(
                sop_expert_topic(tid, record.owner_id),
                {
                    "action": action,
                    "sop_id": record.id,
                    "name": record.name,
                    "environment": record.environment,
                    "version": record.version,
                    "owner_id": record.owner_id,
                },
            )
    except Exception:  # pylint: disable=broad-except
        logger.warning("sop %s event publish failed", record.id, exc_info=True)


_store: SopStore | None = None


def get_sop_store() -> SopStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = SopStore()
    return _store


def sop_environment_for_agent(agent_id: str) -> str:
    """Map a running agent id to the SOP environment it should read.

    复用 agent_documents 的 ``__draft`` 后缀约定：工作台调试实例
    （``expert_{id}__draft``）读 draft 行，线上实例读 production 行。
    """
    return environment_for_agent(agent_id)
