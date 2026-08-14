# -*- coding: utf-8 -*-
"""Project service: CRUD, membership, kanban tasks, feed, project AI chat.

The project-level shared AI leverages the M1 ownership model: chats for
``project:{pid}`` carry that synthetic owner id, so the runtime's
per-owner memory view (``builder.user_view``) yields one shared memory
vault per project without touching the agent runtime. Members reach the
shared chat through the XianWork proxy route, never the raw chats API.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from ..events.bus import feed_topic, get_event_bus
from .models import (
    MEMBER_ROLES,
    PROJECT_EDITOR,
    PROJECT_OWNER,
    PROJECT_VIEWER,
    TASK_STATUSES,
    AIBinding,
    FeedEventView,
    ProjectMemberView,
    ProjectRecord,
    TaskRecord,
    role_at_least,
)

logger = logging.getLogger(__name__)

_PROJECT_COLS = (
    "id, department_id, name, description, status, ai_binding, "
    "template_tag, created_by, created_at, updated_at"
)
_TASK_COLS = (
    "id, project_id, title, description, status, assignee, creator, "
    "chat_id, sort_order, created_at, updated_at"
)

#: Synthetic owner prefix for project-shared chats (see module docstring).
PROJECT_OWNER_PREFIX = "project:"


def project_owner_id(project_id: str) -> str:
    """The trusted chat owner id for one project's shared conversations."""
    return f"{PROJECT_OWNER_PREFIX}{project_id}"


def is_project_owner_id(owner_id: str) -> bool:
    """True when *owner_id* names a project-shared principal."""
    return owner_id.startswith(PROJECT_OWNER_PREFIX)


def project_id_from_owner(owner_id: str) -> Optional[str]:
    """Extract the project id from a project owner id (else ``None``)."""
    if is_project_owner_id(owner_id):
        return owner_id[len(PROJECT_OWNER_PREFIX):]
    return None


def _row_to_project(row, member_role: str = "") -> ProjectRecord:
    binding = row.ai_binding or {}
    return ProjectRecord(
        id=row.id,
        department_id=row.department_id,
        name=row.name,
        description=row.description or "",
        status=row.status,
        ai_binding=AIBinding(
            kind=binding.get("kind", "expert"),
            ref_id=binding.get("ref_id", ""),
        ),
        template_tag=row.template_tag or "",
        created_by=row.created_by,
        member_role=member_role,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_task(row) -> TaskRecord:
    return TaskRecord(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        description=row.description or "",
        status=row.status,
        assignee=row.assignee,
        creator=row.creator,
        chat_id=row.chat_id,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_feed(row) -> FeedEventView:
    return FeedEventView(
        id=row.id,
        project_id=row.project_id,
        actor=row.actor,
        kind=row.kind,
        payload=row.payload or {},
        created_at=row.created_at,
    )


class ProjectService:
    """Project/task/feed operations scoped to the current tenant."""

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------

    async def create_project(
        self,
        name: str,
        created_by: str,
        description: str = "",
        department_id: Optional[str] = None,
        template_tag: str = "",
        ai_binding: Optional[AIBinding] = None,
    ) -> ProjectRecord:
        tid = current_tenant_id()
        pid = new_id("prj")
        binding = (ai_binding or AIBinding()).model_dump()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO projects (tenant_id, id, department_id, "
                    "name, description, ai_binding, template_tag, "
                    "created_by) VALUES (:tid, :id, :dept, :name, :desc, "
                    "CAST(:binding AS JSONB), :tag, :creator) RETURNING "
                    + _PROJECT_COLS
                ),
                {
                    "tid": tid,
                    "id": pid,
                    "dept": department_id,
                    "name": name,
                    "desc": description,
                    "binding": json.dumps(binding),
                    "tag": template_tag,
                    "creator": created_by,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO project_members (tenant_id, project_id, "
                    "username, role) VALUES (:tid, :pid, :user, :role)"
                ),
                {"tid": tid, "pid": pid, "user": created_by, "role": PROJECT_OWNER},
            )
            record = _row_to_project(result.one(), PROJECT_OWNER)
        await self.record_feed(
            record.id,
            actor=created_by,
            kind="project_created",
            payload={"name": record.name},
        )
        return record

    async def list_projects(
        self,
        username: Optional[str] = None,
        templates_only: bool = False,
    ) -> List[ProjectRecord]:
        """Projects visible in the tenant, annotated with the caller role.

        WorkBuddy semantics: projects are org-visible; membership is what
        grants write access (enforced per-operation elsewhere).
        """
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            clauses = ["p.tenant_id = :tid"]
            if templates_only:
                clauses.append("p.template_tag <> ''")
            result = await conn.execute(
                text(
                    "SELECT p.id, p.department_id, p.name, p.description, "
                    "p.status, p.ai_binding, p.template_tag, p.created_by, "
                    "p.created_at, p.updated_at, m.role AS member_role "
                    "FROM projects p "
                    "LEFT JOIN project_members m "
                    "ON m.tenant_id = p.tenant_id "
                    "AND m.project_id = p.id AND m.username = :user "
                    "WHERE " + " AND ".join(clauses) + " "
                    "ORDER BY p.updated_at DESC"
                ),
                {"tid": tid, "user": username or ""},
            )
            return [
                _row_to_project(r, getattr(r, "member_role", "") or "")
                for r in result
            ]

    async def get_project(
        self,
        project_id: str,
        username: Optional[str] = None,
    ) -> Optional[ProjectRecord]:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _PROJECT_COLS + " FROM projects "
                    "WHERE tenant_id = :tid AND id = :pid"
                ),
                {"tid": tid, "pid": project_id},
            )
            row = result.first()
            if row is None:
                return None
            role = ""
            if username:
                member = await conn.execute(
                    text(
                        "SELECT role FROM project_members "
                        "WHERE tenant_id = :tid AND project_id = :pid "
                        "AND username = :user"
                    ),
                    {"tid": tid, "pid": project_id, "user": username},
                )
                mrow = member.first()
                role = mrow.role if mrow else ""
            return _row_to_project(row, role)

    async def member_role(self, project_id: str, username: str) -> str:
        """The caller's role in one project ("" when not a member)."""
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT role FROM project_members "
                    "WHERE tenant_id = :tid AND project_id = :pid "
                    "AND username = :user"
                ),
                {"tid": tid, "pid": project_id, "user": username},
            )
            row = result.first()
            return row.role if row else ""

    async def update_project(
        self,
        project_id: str,
        **fields,
    ) -> Optional[ProjectRecord]:
        """Update whitelisted project fields (name/desc/status/binding)."""
        tid = current_tenant_id()
        sets = []
        params: dict = {"tid": tid, "pid": project_id}
        if fields.get("name") is not None:
            sets.append("name = :name")
            params["name"] = fields["name"]
        if fields.get("description") is not None:
            sets.append("description = :desc")
            params["desc"] = fields["description"]
        if fields.get("status") is not None:
            sets.append("status = :status")
            params["status"] = fields["status"]
        if fields.get("department_id") is not None:
            sets.append("department_id = :dept")
            params["dept"] = fields["department_id"]
        if fields.get("ai_binding") is not None:
            sets.append("ai_binding = CAST(:binding AS JSONB)")
            params["binding"] = json.dumps(
                fields["ai_binding"].model_dump(),
            )
        if not sets:
            return await self.get_project(project_id)
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE projects SET " + ", ".join(sets)
                    + ", updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :pid RETURNING " + _PROJECT_COLS
                ),
                params,
            )
            row = result.first()
            return _row_to_project(row) if row else None

    async def delete_project(self, project_id: str) -> bool:
        """Delete a project with its members/tasks/feed (owner-only gate
        is enforced by the router; the delete itself is cascade-by-hand
        inside one transaction)."""
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            for table in ("tasks", "feed_events", "project_members"):
                await conn.execute(
                    text(
                        f"DELETE FROM {table} WHERE tenant_id = :tid "
                        "AND project_id = :pid"
                    ),
                    {"tid": tid, "pid": project_id},
                )
            result = await conn.execute(
                text(
                    "DELETE FROM projects WHERE tenant_id = :tid "
                    "AND id = :pid"
                ),
                {"tid": tid, "pid": project_id},
            )
            return result.rowcount > 0

    # ------------------------------------------------------------------
    # members
    # ------------------------------------------------------------------

    async def list_members(self, project_id: str) -> List[ProjectMemberView]:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT project_id, username, role "
                    "FROM project_members WHERE tenant_id = :tid "
                    "AND project_id = :pid ORDER BY role, username"
                ),
                {"tid": tid, "pid": project_id},
            )
            return [
                ProjectMemberView(
                    project_id=r.project_id,
                    username=r.username,
                    role=r.role,
                )
                for r in result
            ]

    async def upsert_member(
        self,
        project_id: str,
        username: str,
        role: str,
    ) -> bool:
        if role not in MEMBER_ROLES:
            return False
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            exists = await conn.execute(
                text(
                    "SELECT 1 FROM projects WHERE tenant_id = :tid "
                    "AND id = :pid"
                ),
                {"tid": tid, "pid": project_id},
            )
            if exists.first() is None:
                return False
            await conn.execute(
                text(
                    "INSERT INTO project_members (tenant_id, project_id, "
                    "username, role) VALUES (:tid, :pid, :user, :role) "
                    "ON CONFLICT (tenant_id, project_id, username) "
                    "DO UPDATE SET role = EXCLUDED.role, "
                    "updated_at = now()"
                ),
                {"tid": tid, "pid": project_id, "user": username, "role": role},
            )
        await self.record_feed(
            project_id,
            actor=username,
            kind="member_joined",
            payload={"role": role},
        )
        return True

    async def remove_member(self, project_id: str, username: str) -> bool:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM project_members "
                    "WHERE tenant_id = :tid AND project_id = :pid "
                    "AND username = :user AND role <> 'owner'"
                ),
                {"tid": tid, "pid": project_id, "user": username},
            )
            removed = result.rowcount > 0
        if removed:
            await self.record_feed(
                project_id,
                actor=username,
                kind="member_left",
                payload={},
            )
        return removed

    # ------------------------------------------------------------------
    # tasks (kanban)
    # ------------------------------------------------------------------

    async def create_task(
        self,
        project_id: str,
        creator: str,
        title: str,
        description: str = "",
        status: str = "todo",
        assignee: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> TaskRecord:
        if status not in TASK_STATUSES:
            status = "todo"
        tid = current_tenant_id()
        task_id = new_id("task")
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            tail = await conn.execute(
                text(
                    "SELECT coalesce(max(sort_order), 0) AS m FROM tasks "
                    "WHERE tenant_id = :tid AND project_id = :pid "
                    "AND status = :status"
                ),
                {"tid": tid, "pid": project_id, "status": status},
            )
            tail_row = tail.first()
            sort_order = (tail_row.m if tail_row else 0) + 1
            result = await conn.execute(
                text(
                    "INSERT INTO tasks (tenant_id, id, project_id, title, "
                    "description, status, assignee, creator, chat_id, "
                    "sort_order) VALUES (:tid, :id, :pid, :title, :desc, "
                    ":status, :assignee, :creator, :chat_id, :sort) "
                    "RETURNING " + _TASK_COLS
                ),
                {
                    "tid": tid,
                    "id": task_id,
                    "pid": project_id,
                    "title": title,
                    "desc": description,
                    "status": status,
                    "assignee": assignee,
                    "creator": creator,
                    "chat_id": chat_id,
                    "sort": sort_order,
                },
            )
            record = _row_to_task(result.one())
        await self.record_feed(
            project_id,
            actor=creator,
            kind="task_created",
            payload={
                "task_id": record.id,
                "title": record.title,
                "assignee": record.assignee,
                "status": record.status,
            },
        )
        return record

    async def list_tasks(
        self,
        project_id: str,
        assignee: Optional[str] = None,
    ) -> List[TaskRecord]:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            clauses = [
                "tenant_id = :tid",
                "project_id = :pid",
            ]
            params: dict = {"tid": tid, "pid": project_id}
            if assignee:
                clauses.append("assignee = :assignee")
                params["assignee"] = assignee
            result = await conn.execute(
                text(
                    "SELECT " + _TASK_COLS + " FROM tasks WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY status, sort_order, created_at"
                ),
                params,
            )
            return [_row_to_task(r) for r in result]

    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _TASK_COLS + " FROM tasks "
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": tid, "id": task_id},
            )
            row = result.first()
            return _row_to_task(row) if row else None

    async def update_task(
        self,
        task_id: str,
        actor: str,
        project_id_of_task: Optional[str] = None,
        **fields,
    ) -> Optional[TaskRecord]:
        """Update whitelisted task fields; emits a board feed event."""
        sets = []
        params: dict = {"tid": current_tenant_id(), "id": task_id}
        if fields.get("title") is not None:
            sets.append("title = :title")
            params["title"] = fields["title"]
        if fields.get("description") is not None:
            sets.append("description = :desc")
            params["desc"] = fields["description"]
        if fields.get("status") is not None:
            if fields["status"] not in TASK_STATUSES:
                raise ValueError(f"status must be one of {TASK_STATUSES}")
            sets.append("status = :status")
            params["status"] = fields["status"]
        if "assignee" in fields and fields["assignee"] is not None:
            sets.append("assignee = :assignee")
            params["assignee"] = fields["assignee"]
        if fields.get("sort_order") is not None:
            sets.append("sort_order = :sort")
            params["sort"] = fields["sort_order"]
        if not sets:
            return await self.get_task(task_id)
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE tasks SET " + ", ".join(sets)
                    + ", updated_at = now() WHERE tenant_id = :tid "
                    "AND id = :id RETURNING " + _TASK_COLS
                ),
                params,
            )
            row = result.first()
        record = _row_to_task(row) if row else None
        if record is not None:
            await self.record_feed(
                record.project_id,
                actor=actor,
                kind="task_status" if "status" in params else "task_updated",
                payload={
                    "task_id": record.id,
                    "title": record.title,
                    "status": record.status,
                    "assignee": record.assignee,
                },
            )
        return record

    async def delete_task(self, task_id: str) -> bool:
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM tasks WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": current_tenant_id(), "id": task_id},
            )
            return result.rowcount > 0

    # ------------------------------------------------------------------
    # feed
    # ------------------------------------------------------------------

    async def record_feed(
        self,
        project_id: str,
        actor: str,
        kind: str,
        payload: dict,
    ) -> None:
        """Persist one feed event and broadcast it on the event bus."""
        tid = current_tenant_id()
        engine = enterprise_engine_or_none()
        event = {
            "project_id": project_id,
            "actor": actor,
            "kind": kind,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if engine is not None:
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO feed_events (tenant_id, "
                            "project_id, actor, kind, payload) VALUES "
                            "(:tid, :pid, :actor, :kind, "
                            "CAST(:payload AS JSONB))"
                        ),
                        {
                            "tid": tid,
                            "pid": project_id,
                            "actor": actor,
                            "kind": kind,
                            "payload": json.dumps(payload),
                        },
                    )
            except Exception:  # pylint: disable=broad-except
                logger.warning(
                    "feed persist failed (project=%s)",
                    project_id,
                    exc_info=True,
                )
        try:
            await get_event_bus().publish(feed_topic(tid, project_id), event)
        except Exception:  # pylint: disable=broad-except
            logger.debug("feed broadcast failed", exc_info=True)

    async def list_feed(
        self,
        project_id: str,
        before_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[FeedEventView]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            clauses = [
                "tenant_id = :tid",
                "project_id = :pid",
            ]
            params: dict = {
                "tid": current_tenant_id(),
                "pid": project_id,
                "limit": min(max(limit, 1), 200),
            }
            if before_id:
                clauses.append("id < :before")
                params["before"] = before_id
            result = await conn.execute(
                text(
                    "SELECT id, project_id, actor, kind, payload, "
                    "created_at FROM feed_events WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY id DESC LIMIT :limit"
                ),
                params,
            )
            return [_row_to_feed(r) for r in result]


def enterprise_engine_or_none():
    """Local alias to keep the feed path usable without PG."""
    from ..enterprise import enterprise_engine

    return enterprise_engine()


_service: Optional[ProjectService] = None


def get_project_service() -> ProjectService:
    """Process-wide singleton (stateless; engine is shared per DSN)."""
    global _service  # pylint: disable=global-statement
    if _service is None:
        _service = ProjectService()
    return _service
