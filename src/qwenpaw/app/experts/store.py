# -*- coding: utf-8 -*-
"""PG persistence for experts / expert teams / published snapshots."""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from .models import (
    EXPERT_STATUS_ARCHIVED,
    EXPERT_STATUS_DRAFT,
    EXPERT_STATUS_PUBLISHED,
    MAX_PIPELINE_MEMBERS,
    TEAM_MODES,
    TEAM_MODE_PIPELINE,
    ExpertRecord,
    ExpertTeamRecord,
    PublishedSnapshot,
    TeamMember,
)

logger = logging.getLogger(__name__)

_EXPERT_COLS = (
    "id, name, icon, description, agent_spec, status, version, "
    "created_at, updated_at"
)
_TEAM_COLS = (
    "id, name, description, mode, router_prompt, status, version, "
    "created_at, updated_at"
)


def _row_to_expert(row) -> ExpertRecord:
    return ExpertRecord(
        id=row.id,
        name=row.name,
        icon=row.icon or "",
        description=row.description or "",
        agent_spec=row.agent_spec or {},
        status=row.status,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_team(row, members: List[TeamMember]) -> ExpertTeamRecord:
    return ExpertTeamRecord(
        id=row.id,
        name=row.name,
        description=row.description or "",
        mode=row.mode,
        router_prompt=row.router_prompt or "",
        status=row.status,
        version=row.version,
        members=members,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ExpertStore:
    """CRUD over the expert PG tables, tenant-scoped."""

    # ------------------------------------------------------------------
    # experts
    # ------------------------------------------------------------------

    async def create_expert(
        self,
        name: str,
        icon: str = "",
        description: str = "",
        agent_spec: Optional[dict] = None,
    ) -> ExpertRecord:
        tid = current_tenant_id()
        expert_id = new_id("exp")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO experts (tenant_id, id, name, icon, "
                    "description, agent_spec, status, version) VALUES "
                    "(:tid, :id, :name, :icon, :desc, "
                    "CAST(:spec AS JSONB), :status, 1) RETURNING "
                    + _EXPERT_COLS
                ),
                {
                    "tid": tid,
                    "id": expert_id,
                    "name": name,
                    "icon": icon,
                    "desc": description,
                    "spec": json.dumps(agent_spec or {}),
                    "status": EXPERT_STATUS_DRAFT,
                },
            )
            return _row_to_expert(result.one())

    async def get_expert(self, expert_id: str) -> Optional[ExpertRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _EXPERT_COLS + " FROM experts "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": current_tenant_id(), "id": expert_id},
            )
            row = result.first()
            return _row_to_expert(row) if row else None

    async def list_experts(
        self,
        status: Optional[str] = None,
    ) -> List[ExpertRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            clauses = ["tenant_id = :tid"]
            params: dict = {"tid": current_tenant_id()}
            if status:
                clauses.append("status = :status")
                params["status"] = status
            result = await conn.execute(
                text(
                    "SELECT " + _EXPERT_COLS + " FROM experts WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY updated_at DESC"
                ),
                params,
            )
            return [_row_to_expert(r) for r in result]

    async def update_expert(
        self,
        expert_id: str,
        **fields,
    ) -> Optional[ExpertRecord]:
        sets = []
        params: dict = {
            "tid": current_tenant_id(),
            "id": expert_id,
        }
        if fields.get("name") is not None:
            sets.append("name = :name")
            params["name"] = fields["name"]
        if fields.get("icon") is not None:
            sets.append("icon = :icon")
            params["icon"] = fields["icon"]
        if fields.get("description") is not None:
            sets.append("description = :desc")
            params["desc"] = fields["description"]
        if fields.get("agent_spec") is not None:
            sets.append("agent_spec = CAST(:spec AS JSONB)")
            params["spec"] = json.dumps(fields["agent_spec"])
        if not sets:
            return await self.get_expert(expert_id)
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE experts SET " + ", ".join(sets)
                    + ", updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :id RETURNING " + _EXPERT_COLS
                ),
                params,
            )
            row = result.first()
            return _row_to_expert(row) if row else None

    async def set_expert_status(
        self,
        expert_id: str,
        status: str,
        bump_version: bool = False,
    ) -> Optional[ExpertRecord]:
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            fragment = ", version = version + 1" if bump_version else ""
            result = await conn.execute(
                text(
                    "UPDATE experts SET status = :status" + fragment
                    + ", updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :id RETURNING " + _EXPERT_COLS
                ),
                {
                    "tid": current_tenant_id(),
                    "id": expert_id,
                    "status": status,
                },
            )
            row = result.first()
            return _row_to_expert(row) if row else None

    # ------------------------------------------------------------------
    # published snapshots (immutable, additive)
    # ------------------------------------------------------------------

    async def insert_snapshot(
        self,
        expert_id: str,
        version: int,
        spec: dict,
        published_by: str,
    ) -> None:
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO published_experts (tenant_id, expert_id, "
                    "version, spec, published_by) VALUES (:tid, :eid, "
                    ":version, CAST(:spec AS JSONB), :by) ON CONFLICT "
                    "(tenant_id, expert_id, version) DO NOTHING"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "version": version,
                    "spec": json.dumps(spec),
                    "by": published_by,
                },
            )

    async def latest_snapshot(
        self,
        expert_id: str,
    ) -> Optional[PublishedSnapshot]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT expert_id, version, spec, published_by, "
                    "published_at FROM published_experts "
                    "WHERE tenant_id = :tid AND expert_id = :eid "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"tid": current_tenant_id(), "eid": expert_id},
            )
            row = result.first()
            if row is None:
                return None
            return PublishedSnapshot(
                expert_id=row.expert_id,
                version=row.version,
                spec=row.spec or {},
                published_by=row.published_by,
                published_at=row.published_at,
            )

    # ------------------------------------------------------------------
    # expert teams
    # ------------------------------------------------------------------

    async def create_team(
        self,
        name: str,
        description: str = "",
        mode: str = "router",
        router_prompt: str = "",
        members: Optional[List[TeamMember]] = None,
    ) -> ExpertTeamRecord:
        if mode not in TEAM_MODES:
            mode = "router"
        tid = current_tenant_id()
        team_id = new_id("team")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO expert_teams (tenant_id, id, name, "
                    "description, mode, router_prompt, status, version) "
                    "VALUES (:tid, :id, :name, :desc, :mode, :rp, :status, 1)"
                    " RETURNING " + _TEAM_COLS
                ),
                {
                    "tid": tid,
                    "id": team_id,
                    "name": name,
                    "desc": description,
                    "mode": mode,
                    "rp": router_prompt,
                    "status": EXPERT_STATUS_DRAFT,
                },
            )
            row = result.one()
            team_members = []
            for index, member in enumerate(
                self._validate_members(members or [], mode),
            ):
                await conn.execute(
                    text(
                        "INSERT INTO expert_team_members (tenant_id, "
                        "team_id, expert_id, role_hint, seq) VALUES "
                        "(:tid, :team, :expert, :hint, :seq)"
                    ),
                    {
                        "tid": tid,
                        "team": team_id,
                        "expert": member.expert_id,
                        "hint": member.role_hint,
                        "seq": member.seq or index,
                    },
                )
                team_members.append(member)
            return _row_to_team(row, team_members)

    @staticmethod
    def _validate_members(
        members: List[TeamMember],
        mode: str,
    ) -> List[TeamMember]:
        """Ordered, de-duplicated; pipeline additionally length-capped."""
        seen = set()
        unique: List[TeamMember] = []
        for index, member in enumerate(members):
            if member.expert_id in seen:
                continue
            seen.add(member.expert_id)
            unique.append(
                TeamMember(
                    expert_id=member.expert_id,
                    role_hint=member.role_hint,
                    seq=member.seq or index,
                ),
            )
        unique.sort(key=lambda m: m.seq)
        if mode == TEAM_MODE_PIPELINE:
            unique = unique[:MAX_PIPELINE_MEMBERS]
        return unique

    async def get_team(self, team_id: str) -> Optional[ExpertTeamRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _TEAM_COLS + " FROM expert_teams "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": current_tenant_id(), "id": team_id},
            )
            row = result.first()
            if row is None:
                return None
            members = await self._load_members(conn, team_id)
            return _row_to_team(row, members)

    async def _load_members(self, conn, team_id: str) -> List[TeamMember]:
        result = await conn.execute(
            text(
                "SELECT expert_id, role_hint, seq FROM "
                "expert_team_members WHERE tenant_id = :tid "
                "AND team_id = :team ORDER BY seq"
            ),
            {"tid": current_tenant_id(), "team": team_id},
        )
        return [
            TeamMember(
                expert_id=r.expert_id,
                role_hint=r.role_hint or "",
                seq=r.seq,
            )
            for r in result
        ]

    async def list_teams(
        self,
        status: Optional[str] = None,
    ) -> List[ExpertTeamRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            clauses = ["t.tenant_id = :tid"]
            params: dict = {"tid": current_tenant_id()}
            if status:
                clauses.append("t.status = :status")
                params["status"] = status
            result = await conn.execute(
                text(
                    "SELECT t.id, t.name, t.description, t.mode, "
                    "t.router_prompt, t.status, t.version, "
                    "t.created_at, t.updated_at "
                    "FROM expert_teams t WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY t.updated_at DESC"
                ),
                params,
            )
            teams = []
            for row in result:
                members = await self._load_members(conn, row.id)
                teams.append(_row_to_team(row, members))
            return teams

    async def update_team(
        self,
        team_id: str,
        **fields,
    ) -> Optional[ExpertTeamRecord]:
        sets = []
        params: dict = {"tid": current_tenant_id(), "id": team_id}
        if fields.get("name") is not None:
            sets.append("name = :name")
            params["name"] = fields["name"]
        if fields.get("description") is not None:
            sets.append("description = :desc")
            params["desc"] = fields["description"]
        if fields.get("mode") is not None:
            if fields["mode"] not in TEAM_MODES:
                raise ValueError(f"mode must be one of {TEAM_MODES}")
            sets.append("mode = :mode")
            params["mode"] = fields["mode"]
        if fields.get("router_prompt") is not None:
            sets.append("router_prompt = :rp")
            params["rp"] = fields["router_prompt"]
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            if sets:
                await conn.execute(
                    text(
                        "UPDATE expert_teams SET " + ", ".join(sets)
                        + ", updated_at = now() WHERE tenant_id = :tid "
                        "AND id = :id"
                    ),
                    params,
                )
            if fields.get("members") is not None:
                mode = fields.get("mode") or "router"
                await conn.execute(
                    text(
                        "DELETE FROM expert_team_members "
                        "WHERE tenant_id = :tid AND team_id = :id"
                    ),
                    {"tid": current_tenant_id(), "id": team_id},
                )
                for index, member in enumerate(
                    self._validate_members(fields["members"], mode),
                ):
                    await conn.execute(
                        text(
                            "INSERT INTO expert_team_members (tenant_id, "
                            "team_id, expert_id, role_hint, seq) VALUES "
                            "(:tid, :team, :expert, :hint, :seq)"
                        ),
                        {
                            "tid": current_tenant_id(),
                            "team": team_id,
                            "expert": member.expert_id,
                            "hint": member.role_hint,
                            "seq": member.seq or index,
                        },
                    )
        return await self.get_team(team_id)

    async def set_team_status(
        self,
        team_id: str,
        status: str,
        bump_version: bool = False,
    ) -> Optional[ExpertTeamRecord]:
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            fragment = ", version = version + 1" if bump_version else ""
            await conn.execute(
                text(
                    "UPDATE expert_teams SET status = :status" + fragment
                    + ", updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :id"
                ),
                {
                    "tid": current_tenant_id(),
                    "id": team_id,
                    "status": status,
                },
            )
        return await self.get_team(team_id)

    async def delete_team(self, team_id: str) -> bool:
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM expert_team_members "
                    "WHERE tenant_id = :tid AND team_id = :id"
                ),
                {"tid": current_tenant_id(), "id": team_id},
            )
            result = await conn.execute(
                text(
                    "DELETE FROM expert_teams WHERE tenant_id = :tid "
                    "AND id = :id"
                ),
                {"tid": current_tenant_id(), "id": team_id},
            )
            return result.rowcount > 0

    async def delete_expert(self, expert_id: str) -> bool:
        """Drafts only: published/archived experts are part of history."""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM experts WHERE tenant_id = :tid "
                    "AND id = :id AND status = :draft"
                ),
                {
                    "tid": current_tenant_id(),
                    "id": expert_id,
                    "draft": EXPERT_STATUS_DRAFT,
                },
            )
            return result.rowcount > 0


_store: Optional[ExpertStore] = None


def get_expert_store() -> ExpertStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = ExpertStore()
    return _store
