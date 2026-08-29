# -*- coding: utf-8 -*-
"""XianWork expert market: catalog, detail, summon, custom experts.

Read plane (P1): the market list (category / keyword / sort / mine
scope, ACL-filtered), expert & team detail with batched member views,
the builtin category dictionary, and the summon counter.

Write plane (P2): employees create their own experts (created published
— personal experts skip the two-step draft flow), edit them, replace
their skill bindings, and delete them (drafts physically, published
ones archived — history stays auditable). Visibility is enforced in
the list SQL and, for private experts, mirrored into an RBAC owner
grant so ``_enforce_expert_acl`` (when QWENPAW_RBAC_ENFORCE is on)
keeps forged X-Agent-Id headers out. Admins keep the full-power
``/api/admin/experts`` plane.
"""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request

from ...experts.models import (
    EXPERT_SORTS,
    EXPERT_STATUS_DRAFT,
    EXPERT_STATUS_PUBLISHED,
    EXPERT_VISIBILITIES,
    EXPERT_VISIBILITY_ORG,
    EXPERT_VISIBILITY_PRIVATE,
    EXPERT_CATEGORIES,
    ExpertCreateBody,
    ExpertRecord,
    ExpertSkillsBody,
    ExpertSkillBinding,
    ExpertUpdateBody,
    expert_agent_id,
    expert_team_agent_id,
)
from ...experts.publish import (
    _default_workspace_dir,
    archive_expert,
    publish_expert,
)
from ...experts.store import get_expert_store
from ...rbac.models import GrantRecord
from ...rbac.store import get_rbac_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experts", tags=["xian-experts"])

#: Custom-expert quota per user (workspaces live under WORKING_DIR/experts).
MAX_USER_EXPERTS = 20

#: 员工自建专家 agent_spec 的字段白名单（安全边界，非样式约束）。
#: AgentProfileConfig 含 mcp（stdio command = 服务端任意命令执行）、
#: channels、backend_settings、security 等平台级字段——员工 spec 任意
#: 透传并在同一请求里自动发布 = 权限提升入口。仅放行个性化与工具
#: 开关两域；渠道/MCP/后端等平台配置只能走 /api/admin/experts。
_AGENT_SPEC_ALLOWED_KEYS = {"language", "tools"}


def _sanitize_agent_spec(spec: object) -> dict:
    """把员工提交的 agent_spec 过滤为安全白名单形态（深净化）。

    - 仅保留 ``language`` 与 ``tools``；
    - ``tools`` 只接受 ``builtin_tools`` 的 ``{name: {enabled: bool}}``
      开关映射（内置工具本身受治理门约束），其余结构整体丢弃；
    - 非法输入统一回落到默认个性化值，不抛错（创建不因脏 spec 失败）。
    """
    # 非对象输入回落默认
    if not isinstance(spec, dict):
        return {"language": "zh"}
    # 第一层：字段白名单
    cleaned = {k: v for k, v in spec.items() if k in _AGENT_SPEC_ALLOWED_KEYS}
    # 第二层：tools 深净化（只留 builtin_tools 启用开关）
    tools = cleaned.get("tools")
    if isinstance(tools, dict) and isinstance(tools.get("builtin_tools"), dict):
        cleaned["tools"] = {
            "builtin_tools": {
                name: {"enabled": bool(cfg.get("enabled"))}
                if isinstance(cfg, dict)
                else {"enabled": False}
                for name, cfg in tools["builtin_tools"].items()
            }
        }
    else:
        # tools 缺失或结构非法：整体移除（继承 agent 默认工具）
        cleaned.pop("tools", None)
    # language 兜底
    if not isinstance(cleaned.get("language"), str) or not cleaned["language"]:
        cleaned["language"] = "zh"
    return cleaned


def _viewer(request: Request) -> str:
    return getattr(request.state, "user", None) or "local"


def _manager(request: Request):
    return getattr(request.app.state, "multi_agent_manager", None)


def _agent_visible(username: str, agent_id: str) -> bool:
    """Grant check: absent ACL = org-wide; present = role/user/team hit."""
    try:
        from ...users.store import get_user_store

        flat_role = get_user_store().get_user(username).role
    except Exception:  # pylint: disable=broad-except
        flat_role = ""
    try:
        return get_rbac_store().agent_allowed(
            username,
            flat_role=flat_role,
            agent_id=agent_id,
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning("expert ACL check failed for %s", agent_id)
        return False


def _expert_card(record: ExpertRecord) -> dict:
    """Market-card view (backward-compatible superset of the old shape)."""
    return {
        "id": record.id,
        "name": record.name,
        "icon": record.icon,
        "description": record.description,
        "version": record.version,
        "agent_id": expert_agent_id(record.id),
        # --- catalog fields (additive; old consumers ignore them) ---
        "status": record.status,
        "title": record.title,
        "category": record.category,
        "badge": record.badge,
        "tags": record.tags,
        "owner_id": record.owner_id,
        "visibility": record.visibility,
        "is_builtin": record.is_builtin,
        "usage_count": record.usage_count,
        "featured": record.featured,
        # 运营位（详情页「专家帮你做」/「使用案例」数据源）
        "sample_tasks": record.sample_tasks,
        "showcase": record.showcase,
        "updated_at": record.updated_at.isoformat()
        if record.updated_at
        else None,
    }


def _skill_bindable(skill_name: str) -> bool:
    """Bindable when the shared pool or the default workspace has it."""
    try:
        from ...agents.skill_system.pool_service import (
            read_skill_pool_manifest,
        )

        if skill_name in read_skill_pool_manifest().get("skills", {}):
            return True
    except Exception:  # pylint: disable=broad-except
        logger.debug("skill pool manifest unavailable", exc_info=True)
    default_dir = _default_workspace_dir()
    if default_dir is not None:
        from ...agents.skill_system.store import get_workspace_skills_dir

        return (get_workspace_skills_dir(default_dir) / skill_name).is_dir()
    return False


def _validate_skill_bindings(
    bindings: List[ExpertSkillBinding],
) -> List[ExpertSkillBinding]:
    """Reject names neither pool nor default workspace provides."""
    missing = [
        b.skill_name
        for b in bindings
        if not _skill_bindable(b.skill_name)
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"skills not found in the shared registry: {missing}",
        )
    return bindings


def _sync_owner_grant(record: ExpertRecord) -> None:
    """Mirror ``visibility`` into the RBAC ACL for this expert's agent.

    ``private`` → a grant restricted to the owner (so ENFORCE-mode
    ``_enforce_expert_acl`` admits the owner and rejects everyone
    else); ``org`` → drop a previous owner-only grant (absent grant =
    unrestricted). Hand-configured grants (roles/teams present) are
    never touched.
    """
    agent_id = expert_agent_id(record.id)
    rbac = get_rbac_store()
    if (
        record.visibility == EXPERT_VISIBILITY_PRIVATE
        and record.owner_id
    ):
        rbac.set_agent_grant(
            agent_id,
            GrantRecord(
                users=[record.owner_id],
                description=(
                    f"private expert owned by {record.owner_id}"
                ),
            ),
        )
        return
    grant = rbac.get_agent_grant(agent_id)
    if (
        grant is not None
        and record.owner_id
        and not grant.roles
        and not grant.teams
        and set(grant.users) == {record.owner_id}
    ):
        rbac.delete_agent_grant(agent_id)


async def _require_owned(
    store,
    expert_id: str,
    username: str,
) -> ExpertRecord:
    """Fetch an expert and enforce owner-only write access."""
    record = await store.get_expert(expert_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    if record.owner_id != username:
        raise HTTPException(
            status_code=403,
            detail="only the owner may modify this expert",
        )
    if record.is_builtin:
        raise HTTPException(
            status_code=403,
            detail="builtin experts cannot be modified here",
        )
    return record


# ---------------------------------------------------------------------------
# Read plane: market list / categories / detail / teams / summon counter
# ---------------------------------------------------------------------------


@router.get("")
async def list_experts(
    request: Request,
    category: str = "",
    q: str = "",
    sort: str = "",
    scope: str = "all",
) -> List[dict]:
    """Market list (published + org-visible or owned) or ``mine`` scope.

    Query params (all optional, old callers unaffected):
    - ``category``: category slug filter;
    - ``q``: ILIKE keyword over name / description / title;
    - ``sort``: ``composite`` (default) / ``hot`` / ``new``;
    - ``scope``: ``all`` (market, default) or ``mine`` (my experts,
      every status, no ACL filtering).
    """
    if sort and sort not in EXPERT_SORTS:
        raise HTTPException(
            status_code=400,
            detail=f"sort must be one of {EXPERT_SORTS}",
        )
    username = _viewer(request)
    store = get_expert_store()
    if scope == "mine":
        records = await store.list_expert_cards(
            owner=username,
            category=category,
            q=q,
            sort=sort,
        )
        return [_expert_card(r) for r in records]

    records = await store.list_expert_cards(
        status=EXPERT_STATUS_PUBLISHED,
        category=category,
        q=q,
        sort=sort,
        include_private_for=username,
    )
    return [
        _expert_card(r)
        for r in records
        if _agent_visible(username, expert_agent_id(r.id))
    ]


@router.get("/categories")
async def list_categories() -> List[dict]:
    """Builtin category dictionary (market tabs, single source of truth)."""
    return EXPERT_CATEGORIES


@router.get("/teams")
async def list_expert_teams(
    request: Request,
    category: str = "",
) -> List[dict]:
    """Published expert teams with batched member card views."""
    username = _viewer(request)
    store = get_expert_store()
    teams = await store.list_teams(
        status=EXPERT_STATUS_PUBLISHED,
        category=category,
    )
    # Five-step: one batched expert fetch, in-memory assembly.
    expert_ids = {m.expert_id for t in teams for m in t.members}
    by_id = {
        e.id: e
        for e in await store.list_expert_cards()
        if e.id in expert_ids
    }
    visible = []
    for team in teams:
        agent_id = expert_team_agent_id(team.id)
        if not _agent_visible(username, agent_id):
            continue
        members = []
        for member in team.members:
            expert = by_id.get(member.expert_id)
            if expert is None:
                continue
            members.append(
                {
                    "expert_id": expert.id,
                    "name": expert.name,
                    "title": expert.title,
                    "icon": expert.icon,
                    "role_hint": member.role_hint,
                    "member_role": member.member_role,
                }
            )
        visible.append(
            {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "mode": team.mode,
                "version": team.version,
                "agent_id": agent_id,
                "category": team.category,
                "tags": team.tags,
                "member_count": len(team.members),
                "members": members,
                # 运营位（详情页「任务示例」/「使用案例」数据源）
                "sample_tasks": team.sample_tasks,
                "showcase": team.showcase,
            }
        )
    return visible


@router.get("/{expert_id}")
async def get_expert_detail(expert_id: str, request: Request) -> dict:
    """Expert detail: card + persona + skill bindings + parent teams."""
    username = _viewer(request)
    store = get_expert_store()
    record = await store.get_expert(expert_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    is_owner = record.owner_id == username
    if record.status != EXPERT_STATUS_PUBLISHED and not is_owner:
        raise HTTPException(status_code=404, detail="Expert not found")
    if (
        record.status == EXPERT_STATUS_PUBLISHED
        and not is_owner
        and record.visibility != EXPERT_VISIBILITY_ORG
    ):
        raise HTTPException(status_code=403, detail="private expert")
    if (
        record.status == EXPERT_STATUS_PUBLISHED
        and not is_owner
        and not _agent_visible(username, expert_agent_id(expert_id))
    ):
        raise HTTPException(
            status_code=403,
            detail="No access to this expert",
        )

    skills = await store.list_skills(expert_id)
    teams = [
        {"id": t.id, "name": t.name, "mode": t.mode}
        for t in await store.list_teams(status=EXPERT_STATUS_PUBLISHED)
        if any(m.expert_id == expert_id for m in t.members)
    ]
    return {
        **_expert_card(record),
        "system_prompt": record.system_prompt,
        "skills": [s.model_dump() for s in skills],
        "teams": teams,
    }


@router.post("/{expert_id}/use")
async def mark_used(expert_id: str) -> dict:
    """Summon counter (fire-and-forget from the market card)."""
    count = await get_expert_store().bump_usage(expert_id)
    if count == 0:
        raise HTTPException(status_code=404, detail="Expert not found")
    return {
        "expert_id": expert_id,
        "agent_id": expert_agent_id(expert_id),
        "usage_count": count,
    }


# ---------------------------------------------------------------------------
# Write plane: custom experts (create-published / update / skills / delete)
# ---------------------------------------------------------------------------


@router.post("", status_code=201)
async def create_custom_expert(
    body: ExpertCreateBody,
    request: Request,
) -> dict:
    """Create a personal expert and publish it immediately.

    Personal experts skip the admin draft flow: create → bind skills →
    publish in one call. The owner gets an RBAC grant for private
    visibility so ENFORCE-mode ACLs admit them.
    """
    username = _viewer(request)
    store = get_expert_store()
    if await store.count_owned(username) >= MAX_USER_EXPERTS:
        raise HTTPException(
            status_code=400,
            detail=f"custom expert quota reached ({MAX_USER_EXPERTS})",
        )
    if body.visibility not in EXPERT_VISIBILITIES:
        raise HTTPException(
            status_code=400,
            detail=f"visibility must be one of {EXPERT_VISIBILITIES}",
        )

    record = await store.create_expert(
        name=body.name,
        icon=body.icon,
        description=body.description,
        # 安全白名单净化：mcp/channels 等平台级字段不允许员工自带发布
        agent_spec=_sanitize_agent_spec(body.agent_spec),
        owner_id=username,
        visibility=body.visibility,
        title=body.title,
        category=body.category,
        badge=body.badge,
        tags=list(body.tags),
        system_prompt=body.system_prompt,
    )
    if body.skills:
        await store.replace_skills(
            record.id,
            _validate_skill_bindings(body.skills),
        )
    try:
        updated = await publish_expert(
            record.id,
            published_by=username,
            manager=_manager(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _sync_owner_grant(updated)
    return await get_expert_detail(updated.id, request)


@router.patch("/{expert_id}")
async def update_custom_expert(
    expert_id: str,
    body: ExpertUpdateBody,
    request: Request,
) -> dict:
    """Edit a custom expert; published ones re-publish immediately."""
    username = _viewer(request)
    store = get_expert_store()
    record = await _require_owned(store, expert_id, username)
    if body.visibility is not None and body.visibility not in (
        EXPERT_VISIBILITIES
    ):
        raise HTTPException(
            status_code=400,
            detail=f"visibility must be one of {EXPERT_VISIBILITIES}",
        )

    updated = await store.update_expert(
        expert_id,
        name=body.name,
        icon=body.icon,
        description=body.description,
        # 安全白名单净化（None=不修改 spec，保持 update 语义）
        agent_spec=(
            _sanitize_agent_spec(body.agent_spec)
            if body.agent_spec is not None
            else None
        ),
        title=body.title,
        category=body.category,
        badge=body.badge,
        tags=list(body.tags) if body.tags is not None else None,
        system_prompt=body.system_prompt,
        visibility=body.visibility,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    if updated.status == EXPERT_STATUS_PUBLISHED:
        try:
            updated = await publish_expert(
                expert_id,
                published_by=username,
                manager=_manager(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _sync_owner_grant(updated)
    return await get_expert_detail(expert_id, request)


@router.put("/{expert_id}/skills")
async def replace_expert_skills(
    expert_id: str,
    body: ExpertSkillsBody,
    request: Request,
) -> dict:
    """Wholesale skill-binding replacement (max MAX_EXPERT_SKILLS).

    Published experts re-publish so the workspace skill set is
    reconciled (stale removed, missing installed) right away.
    """
    username = _viewer(request)
    store = get_expert_store()
    record = await _require_owned(store, expert_id, username)
    bindings = _validate_skill_bindings(body.skills)
    await store.replace_skills(expert_id, bindings)
    if record.status == EXPERT_STATUS_PUBLISHED:
        try:
            await publish_expert(
                expert_id,
                published_by=username,
                manager=_manager(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await get_expert_detail(expert_id, request)


@router.delete("/{expert_id}", status_code=204)
async def delete_custom_expert(expert_id: str, request: Request) -> None:
    """Delete a custom expert: drafts physically, published archived."""
    username = _viewer(request)
    store = get_expert_store()
    record = await _require_owned(store, expert_id, username)
    if record.status == EXPERT_STATUS_DRAFT:
        if not await store.delete_expert(expert_id):
            raise HTTPException(status_code=400, detail="delete failed")
        return
    await archive_expert(expert_id, manager=_manager(request))
    # The archived agent keeps a stale owner grant; drop ours only.
    agent_id = expert_agent_id(expert_id)
    grant = get_rbac_store().get_agent_grant(agent_id)
    if (
        grant is not None
        and not grant.roles
        and not grant.teams
        and record.owner_id
        and set(grant.users) == {record.owner_id}
    ):
        get_rbac_store().delete_agent_grant(agent_id)
