# -*- coding: utf-8 -*-
"""PG persistence for experts / expert teams / published snapshots."""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from .models import (
    EXPERT_SORT_HOT,
    EXPERT_SORT_NEW,
    EXPERT_STATUS_ARCHIVED,
    EXPERT_STATUS_DRAFT,
    EXPERT_STATUS_PUBLISHED,
    MAX_EXPERT_SKILLS,
    MAX_PIPELINE_MEMBERS,
    TEAM_MODES,
    TEAM_MODE_PIPELINE,
    ExpertRecord,
    ExpertSkillBinding,
    ExpertTeamRecord,
    PublishedSnapshot,
    TeamMember,
)

logger = logging.getLogger(__name__)

_EXPERT_COLS = (
    "id, name, icon, description, agent_spec, status, version, "
    "owner_id, visibility, is_builtin, title, category, badge, tags, "
    "system_prompt, usage_count, featured, sample_tasks, showcase, "
    "created_at, updated_at"
)
_EXPERT_CARD_COLS = (
    "id, name, icon, description, status, version, owner_id, "
    "visibility, is_builtin, title, category, badge, tags, "
    "usage_count, featured, sample_tasks, showcase, created_at, updated_at"
)
_TEAM_COLS = (
    "id, name, description, mode, router_prompt, status, version, "
    "owner_id, category, tags, orchestration, sample_tasks, showcase, "
    "created_at, updated_at"
)

# Composite ordering for the market list: builtins first, then heat,
# then recency. Kept here (not in SQL literals) so the router and tests
# share one definition.
_ORDER_COMPOSITE = "is_builtin DESC, usage_count DESC, updated_at DESC"
_ORDER_HOT = "usage_count DESC, updated_at DESC"
_ORDER_NEW = "created_at DESC"


def _row_to_expert(row) -> ExpertRecord:
    return ExpertRecord(
        id=row.id,
        name=row.name,
        icon=row.icon or "",
        description=row.description or "",
        agent_spec=row.agent_spec or {},
        status=row.status,
        version=row.version,
        owner_id=row.owner_id,
        visibility=row.visibility or "org",
        is_builtin=bool(row.is_builtin),
        title=row.title or "",
        category=row.category or "general",
        badge=row.badge or "",
        tags=list(row.tags or []),
        system_prompt=row.system_prompt or "",
        usage_count=row.usage_count or 0,
        featured=bool(row.featured),
        sample_tasks=list(row.sample_tasks or []),
        showcase=list(row.showcase or []),
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
        owner_id=row.owner_id,
        category=row.category or "general",
        tags=list(row.tags or []),
        orchestration=row.orchestration or {},
        sample_tasks=list(row.sample_tasks or []),
        showcase=list(row.showcase or []),
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
        expert_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        visibility: str = "org",
        is_builtin: bool = False,
        title: str = "",
        category: str = "general",
        badge: str = "",
        tags: Optional[List[str]] = None,
        system_prompt: str = "",
        featured: bool = False,
        sample_tasks: Optional[List[dict]] = None,
        showcase: Optional[List[dict]] = None,
    ) -> ExpertRecord:
        tid = current_tenant_id()
        expert_id = expert_id or new_id("exp")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO experts (tenant_id, id, name, icon, "
                    "description, agent_spec, status, version, owner_id, "
                    "visibility, is_builtin, title, category, badge, tags, "
                    "system_prompt, featured, sample_tasks, showcase) VALUES "
                    "(:tid, :id, :name, :icon, :desc, "
                    "CAST(:spec AS JSONB), :status, 1, :owner, :vis, "
                    ":builtin, :title, :category, :badge, "
                    "CAST(:tags AS JSONB), :prompt, :featured, "
                    "CAST(:tasks AS JSONB), CAST(:cases AS JSONB)) RETURNING "
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
                    "owner": owner_id,
                    "vis": visibility,
                    "builtin": is_builtin,
                    "title": title,
                    "category": category,
                    "badge": badge,
                    "tags": json.dumps(tags or []),
                    "prompt": system_prompt,
                    "featured": featured,
                    "tasks": json.dumps(sample_tasks or []),
                    "cases": json.dumps(showcase or []),
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

    def _expert_query(
        self,
        cols: str,
        status: Optional[str],
        category: str,
        q: str,
        sort: str,
        owner: str,
        include_private_for: Optional[str],
    ) -> tuple[str, dict]:
        """Shared WHERE/ORDER builder for expert list queries."""
        clauses = ["tenant_id = :tid"]
        params: dict = {"tid": current_tenant_id()}
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if owner:
            clauses.append("owner_id = :owner")
            params["owner"] = owner
        elif include_private_for is not None:
            clauses.append("(visibility = 'org' OR owner_id = :pv_owner)")
            params["pv_owner"] = include_private_for
        if category:
            clauses.append("category = :category")
            params["category"] = category
        if q:
            clauses.append(
                "(name ILIKE :kw OR description ILIKE :kw "
                "OR title ILIKE :kw)"
            )
            params["kw"] = f"%{q}%"
        if sort == EXPERT_SORT_HOT:
            order = _ORDER_HOT
        elif sort == EXPERT_SORT_NEW:
            order = _ORDER_NEW
        else:
            order = _ORDER_COMPOSITE
        sql = (
            f"SELECT {cols} FROM experts WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY {order}"
        )
        return sql, params

    async def list_experts(
        self,
        status: Optional[str] = None,
        category: str = "",
        q: str = "",
        sort: str = "",
        owner: str = "",
        include_private_for: Optional[str] = None,
    ) -> List[ExpertRecord]:
        """List experts with market filters.

        Args:
            status: exact status filter (``published`` for the market).
            category: category slug filter (empty = all).
            q: ILIKE keyword over name / description / title.
            sort: ``composite`` (default) / ``hot`` / ``new``.
            owner: only experts owned by this username (``mine`` scope).
            include_private_for: when set together with ``status`` the
                visibility clause widens to "org-visible OR owned by this
                user" so private experts still show for their owner.
        """
        engine = require_enterprise_engine()
        sql, params = self._expert_query(
            _EXPERT_COLS, status, category, q, sort, owner,
            include_private_for,
        )
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            return [_row_to_expert(r) for r in result]

    async def list_expert_cards(
        self,
        status: Optional[str] = None,
        category: str = "",
        q: str = "",
        sort: str = "",
        owner: str = "",
        include_private_for: Optional[str] = None,
    ) -> List[ExpertRecord]:
        """Market-card listing without the heavy ``agent_spec`` /
        ``system_prompt`` columns (same filters as ``list_experts``)."""
        engine = require_enterprise_engine()
        sql, params = self._expert_query(
            _EXPERT_CARD_COLS, status, category, q, sort, owner,
            include_private_for,
        )
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params)
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
        if fields.get("title") is not None:
            sets.append("title = :title")
            params["title"] = fields["title"]
        if fields.get("category") is not None:
            sets.append("category = :category")
            params["category"] = fields["category"]
        if fields.get("badge") is not None:
            sets.append("badge = :badge")
            params["badge"] = fields["badge"]
        if fields.get("tags") is not None:
            sets.append("tags = CAST(:tags AS JSONB)")
            params["tags"] = json.dumps(fields["tags"])
        if fields.get("system_prompt") is not None:
            sets.append("system_prompt = :prompt")
            params["prompt"] = fields["system_prompt"]
        if fields.get("visibility") is not None:
            sets.append("visibility = :vis")
            params["vis"] = fields["visibility"]
        # 运营位双字段：显式传 None 表示不修改；传 list（含空 list）
        # 表示整体替换。
        if fields.get("sample_tasks") is not None:
            sets.append("sample_tasks = CAST(:tasks AS JSONB)")
            params["tasks"] = json.dumps(fields["sample_tasks"])
        if fields.get("showcase") is not None:
            sets.append("showcase = CAST(:cases AS JSONB)")
            params["cases"] = json.dumps(fields["showcase"])
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
        category: str = "general",
        tags: Optional[List[str]] = None,
        owner_id: Optional[str] = None,
        orchestration: Optional[dict] = None,
        sample_tasks: Optional[List[dict]] = None,
        showcase: Optional[List[dict]] = None,
        team_id: Optional[str] = None,
    ) -> ExpertTeamRecord:
        if mode not in TEAM_MODES:
            mode = "router"
        tid = current_tenant_id()
        team_id = team_id or new_id("team")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO expert_teams (tenant_id, id, name, "
                    "description, mode, router_prompt, status, version, "
                    "owner_id, category, tags, orchestration, "
                    "sample_tasks, showcase) VALUES "
                    "(:tid, :id, :name, :desc, :mode, :rp, :status, 1, "
                    ":owner, :category, CAST(:tags AS JSONB), "
                    "CAST(:orch AS JSONB), CAST(:tasks AS JSONB), "
                    "CAST(:cases AS JSONB))"
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
                    "owner": owner_id,
                    "category": category,
                    "tags": json.dumps(tags or []),
                    "orch": json.dumps(orchestration or {}),
                    "tasks": json.dumps(sample_tasks or []),
                    "cases": json.dumps(showcase or []),
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
                        "team_id, expert_id, role_hint, member_role, seq) "
                        "VALUES (:tid, :team, :expert, :hint, :mrole, :seq)"
                    ),
                    {
                        "tid": tid,
                        "team": team_id,
                        "expert": member.expert_id,
                        "hint": member.role_hint,
                        "mrole": member.member_role,
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
                    member_role=member.member_role,
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
                "SELECT expert_id, role_hint, member_role, seq FROM "
                "expert_team_members WHERE tenant_id = :tid "
                "AND team_id = :team ORDER BY seq"
            ),
            {"tid": current_tenant_id(), "team": team_id},
        )
        return [
            TeamMember(
                expert_id=r.expert_id,
                role_hint=r.role_hint or "",
                member_role=r.member_role or "member",
                seq=r.seq,
            )
            for r in result
        ]

    async def _load_members_for_teams(
        self,
        conn,
        team_ids: List[str],
    ) -> dict[str, List[TeamMember]]:
        """Batched member load for many teams (fixes the N+1 in lists)."""
        if not team_ids:
            return {}
        result = await conn.execute(
            text(
                "SELECT team_id, expert_id, role_hint, member_role, seq "
                "FROM expert_team_members WHERE tenant_id = :tid "
                "AND team_id = ANY(:teams) ORDER BY seq"
            ),
            {"tid": current_tenant_id(), "teams": list(team_ids)},
        )
        grouped: dict[str, List[TeamMember]] = {}
        for r in result:
            grouped.setdefault(r.team_id, []).append(
                TeamMember(
                    expert_id=r.expert_id,
                    role_hint=r.role_hint or "",
                    member_role=r.member_role or "member",
                    seq=r.seq,
                ),
            )
        return grouped

    async def list_teams(
        self,
        status: Optional[str] = None,
        category: str = "",
    ) -> List[ExpertTeamRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            clauses = ["t.tenant_id = :tid"]
            params: dict = {"tid": current_tenant_id()}
            if status:
                clauses.append("t.status = :status")
                params["status"] = status
            if category:
                clauses.append("t.category = :category")
                params["category"] = category
            result = await conn.execute(
                text(
                    "SELECT t.id, t.name, t.description, t.mode, "
                    "t.router_prompt, t.status, t.version, "
                    "t.owner_id, t.category, t.tags, t.orchestration, "
                    "t.sample_tasks, t.showcase, "
                    "t.created_at, t.updated_at "
                    "FROM expert_teams t WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY t.updated_at DESC"
                ),
                params,
            )
            rows = list(result)
            # One batched query for every team's members (five-step:
            # collect ids, single ANY() fetch, in-memory grouping).
            grouped = await self._load_members_for_teams(
                conn,
                [r.id for r in rows],
            )
            return [_row_to_team(r, grouped.get(r.id, [])) for r in rows]

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
        if fields.get("category") is not None:
            sets.append("category = :category")
            params["category"] = fields["category"]
        if fields.get("tags") is not None:
            sets.append("tags = CAST(:tags AS JSONB)")
            params["tags"] = json.dumps(fields["tags"])
        # 运行时编排配置（管理端 workforce 编辑面）：显式传 None 表示
        # 不修改；传 dict（含空 dict）表示整体替换。
        if fields.get("orchestration") is not None:
            sets.append("orchestration = CAST(:orch AS JSONB)")
            params["orch"] = json.dumps(fields["orchestration"])
        # 运营位双字段（同语义：None 不修改，list 整体替换）
        if fields.get("sample_tasks") is not None:
            sets.append("sample_tasks = CAST(:tasks AS JSONB)")
            params["tasks"] = json.dumps(fields["sample_tasks"])
        if fields.get("showcase") is not None:
            sets.append("showcase = CAST(:cases AS JSONB)")
            params["cases"] = json.dumps(fields["showcase"])
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
                            "team_id, expert_id, role_hint, member_role, seq) "
                            "VALUES (:tid, :team, :expert, :hint, :mrole, :seq)"
                        ),
                        {
                            "tid": current_tenant_id(),
                            "team": team_id,
                            "expert": member.expert_id,
                            "hint": member.role_hint,
                            "mrole": member.member_role,
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
            # Skill bindings follow the draft (published experts keep
            # their workspace; history stays in published_experts).
            await conn.execute(
                text(
                    "DELETE FROM expert_skills WHERE tenant_id = :tid "
                    "AND expert_id = :id"
                ),
                {"tid": current_tenant_id(), "id": expert_id},
            )
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

    # ------------------------------------------------------------------
    # skill bindings (expert_skills)
    # ------------------------------------------------------------------

    async def list_skills(
        self,
        expert_id: str,
    ) -> List[ExpertSkillBinding]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT expert_id, skill_name, enabled, seq FROM "
                    "expert_skills WHERE tenant_id = :tid "
                    "AND expert_id = :eid ORDER BY seq, skill_name"
                ),
                {"tid": current_tenant_id(), "eid": expert_id},
            )
            return [
                ExpertSkillBinding(
                    expert_id=r.expert_id,
                    skill_name=r.skill_name,
                    enabled=bool(r.enabled),
                    seq=r.seq,
                )
                for r in result
            ]

    async def replace_skills(
        self,
        expert_id: str,
        bindings: List[ExpertSkillBinding],
    ) -> List[ExpertSkillBinding]:
        """Wholesale replacement inside one transaction (delete+insert,
        same pattern as team member updates). Caps at MAX_EXPERT_SKILLS
        and de-duplicates by skill_name."""
        seen: dict[str, ExpertSkillBinding] = {}
        for index, binding in enumerate(bindings):
            if binding.skill_name in seen:
                continue
            seen[binding.skill_name] = ExpertSkillBinding(
                expert_id=expert_id,
                skill_name=binding.skill_name,
                enabled=binding.enabled,
                seq=binding.seq or index,
            )
        ordered = sorted(seen.values(), key=lambda b: (b.seq, b.skill_name))
        ordered = ordered[:MAX_EXPERT_SKILLS]

        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM expert_skills WHERE tenant_id = :tid "
                    "AND expert_id = :eid"
                ),
                {"tid": current_tenant_id(), "eid": expert_id},
            )
            for binding in ordered:
                await conn.execute(
                    text(
                        "INSERT INTO expert_skills (tenant_id, expert_id, "
                        "skill_name, enabled, seq) VALUES "
                        "(:tid, :eid, :skill, :enabled, :seq)"
                    ),
                    {
                        "tid": current_tenant_id(),
                        "eid": expert_id,
                        "skill": binding.skill_name,
                        "enabled": binding.enabled,
                        "seq": binding.seq,
                    },
                )
        return ordered

    async def enabled_skill_names(self, expert_id: str) -> List[str]:
        """Ordered enabled skill names — the publish-time materialization set."""
        bindings = await self.list_skills(expert_id)
        return [b.skill_name for b in bindings if b.enabled]

    async def bump_usage(self, expert_id: str) -> int:
        """Atomic summon-counter increment; returns the new value."""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE experts SET usage_count = usage_count + 1 "
                    "WHERE tenant_id = :tid AND id = :id "
                    "RETURNING usage_count"
                ),
                {"tid": current_tenant_id(), "id": expert_id},
            )
            row = result.first()
            return row.usage_count if row else 0

    async def count_owned(self, owner_id: str) -> int:
        """Custom-expert quota check (excludes archived history)."""
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT count(*) AS n FROM experts WHERE "
                    "tenant_id = :tid AND owner_id = :owner "
                    "AND status <> :archived"
                ),
                {
                    "tid": current_tenant_id(),
                    "owner": owner_id,
                    "archived": EXPERT_STATUS_ARCHIVED,
                },
            )
            return int(result.scalar() or 0)


_store: Optional[ExpertStore] = None


def get_expert_store() -> ExpertStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = ExpertStore()
    return _store
