# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for cron API scope helpers (S2 personal-ownership plane).

覆盖双平面模型的定时任务作用域逻辑：

- ``_job_visible``：list 过滤（共享任务全员、个人任务仅 owner/平台管理员）；
- ``_ensure_visible``：详情/状态/历史对不可见个人任务按 404 处理；
- ``_authorize_job_write``：写/删/暂停/手动执行三档鉴权（平台管理员直通 /
  个人任务仅 owner 本人 / 共享任务员工级管理授权）；
- ``create_job``：业务用户强制落 owner=本人（无法伪建共享/他人任务），
  管理者按提交决定归属。

RBAC 关闭（无 PG/无认证单机）时全部直通，行为零变化。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from qwenpaw.app.crons import api as cron_api
from tests.unit.app.conftest import make_cron_job_spec


def _req(user: str):
    """伪造带 ``state.user`` 的 Request（helper 只读该属性）。"""
    return SimpleNamespace(state=SimpleNamespace(user=user))


def _spec(owner: str | None = None):
    """构造带 owner 归属的任务规格（model_copy 免重复校验）。"""
    return make_cron_job_spec(job_id="j1").model_copy(
        update={"owner_user_id": owner},
    )


def _rbac(monkeypatch, enabled: bool = True, admin: bool = False):
    """统一打桩 RBAC 开关与平台管理员判定。"""
    monkeypatch.setattr(
        cron_api, "rbac_enforcement_enabled", lambda: enabled,
    )
    monkeypatch.setattr(cron_api, "is_platform_admin", lambda u: admin)


# ---------------------------------------------------------------------------
# _job_visible — list 过滤可见性
# ---------------------------------------------------------------------------


def test_visible_everything_when_rbac_disabled(monkeypatch):
    _rbac(monkeypatch, enabled=False)
    # RBAC 关闭：他人个人任务也可见（单机零变化）
    assert cron_api._job_visible(_spec("bob"), "alice", False) is True


def test_shared_job_visible_to_all(monkeypatch):
    _rbac(monkeypatch, enabled=True)
    assert cron_api._job_visible(_spec(None), "alice", False) is True


def test_personal_job_visible_only_to_owner(monkeypatch):
    _rbac(monkeypatch, enabled=True)
    assert cron_api._job_visible(_spec("alice"), "alice", False) is True
    assert cron_api._job_visible(_spec("bob"), "alice", False) is False


def test_personal_job_visible_to_platform_admin(monkeypatch):
    _rbac(monkeypatch, enabled=True)
    assert cron_api._job_visible(_spec("bob"), "root", True) is True


def test_no_viewer_not_restricted(monkeypatch):
    _rbac(monkeypatch, enabled=True)
    # 认证开启但无身份（理论边界）：不在此收紧，交由写闸门拦截
    assert cron_api._job_visible(_spec("bob"), "", False) is True


# ---------------------------------------------------------------------------
# _ensure_visible — 详情/状态/历史 404 语义
# ---------------------------------------------------------------------------


def test_ensure_visible_allows_owner(monkeypatch):
    _rbac(monkeypatch, enabled=True, admin=False)
    # 不抛异常即通过
    cron_api._ensure_visible(_spec("alice"), "alice")


def test_ensure_visible_404_for_other_personal(monkeypatch):
    _rbac(monkeypatch, enabled=True, admin=False)
    with pytest.raises(HTTPException) as exc:
        cron_api._ensure_visible(_spec("bob"), "alice")
    assert exc.value.status_code == 404


def test_ensure_visible_admin_sees_other_personal(monkeypatch):
    _rbac(monkeypatch, enabled=True, admin=True)
    cron_api._ensure_visible(_spec("bob"), "root")


# ---------------------------------------------------------------------------
# _authorize_job_write — 写/删/暂停三档鉴权
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_write_passthrough_when_rbac_disabled(monkeypatch):
    _rbac(monkeypatch, enabled=False)
    # 无身份也直通（单机零变化）
    await cron_api._authorize_job_write(_req(""), "a1", _spec("bob"))


@pytest.mark.asyncio
async def test_authorize_write_no_identity_403(monkeypatch):
    _rbac(monkeypatch, enabled=True)
    with pytest.raises(HTTPException) as exc:
        await cron_api._authorize_job_write(_req(""), "a1", _spec(None))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_authorize_write_platform_admin_passthrough(monkeypatch):
    _rbac(monkeypatch, enabled=True, admin=True)
    await cron_api._authorize_job_write(_req("root"), "a1", _spec("bob"))


@pytest.mark.asyncio
async def test_authorize_write_personal_only_owner(monkeypatch):
    _rbac(monkeypatch, enabled=True, admin=False)

    async def _manage(user, agent_id):
        # 即便对他人个人任务持有员工管理权，也不放行（隐私边界）
        return True

    monkeypatch.setattr(cron_api, "manage_allowed", _manage)
    # owner 本人通过
    await cron_api._authorize_job_write(_req("alice"), "a1", _spec("alice"))
    # 他人被拒（team_lead 亦不介入他人个人资产）
    with pytest.raises(HTTPException) as exc:
        await cron_api._authorize_job_write(_req("bob"), "a1", _spec("alice"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_authorize_write_shared_requires_manage(monkeypatch):
    _rbac(monkeypatch, enabled=True, admin=False)
    granted = {"alice"}

    async def _manage(user, agent_id):
        return user in granted

    monkeypatch.setattr(cron_api, "manage_allowed", _manage)
    # 持员工级管理授权 → 通过
    await cron_api._authorize_job_write(_req("alice"), "a1", _spec(None))
    # 无管理授权 → 403
    with pytest.raises(HTTPException) as exc:
        await cron_api._authorize_job_write(_req("carol"), "a1", _spec(None))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# create_job — server 端归属分配
# ---------------------------------------------------------------------------


def _patch_create_env(monkeypatch, *, manage: bool, dept: str | None):
    async def _agent_id(request):
        return "a1"

    async def _manage(user, agent_id):
        return manage

    async def _dept(owner):
        return dept if owner else None

    monkeypatch.setattr(cron_api, "_agent_id_for", _agent_id)
    monkeypatch.setattr(cron_api, "manage_allowed", _manage)
    monkeypatch.setattr(cron_api, "_resolve_owner_department", _dept)


@pytest.mark.asyncio
async def test_create_job_business_user_forced_to_self(monkeypatch):
    _rbac(monkeypatch, enabled=True, admin=False)
    _patch_create_env(monkeypatch, manage=False, dept="/root/eng")

    mgr = AsyncMock()
    # 业务用户 bob 试图伪建共享任务（提交 owner=None）
    created = await cron_api.create_job(
        make_cron_job_spec(job_id=None), _req("bob"), mgr=mgr,
    )

    # 强制落 owner=本人 + 部门快照，无法伪建共享/他人任务
    assert created.owner_user_id == "bob"
    assert created.department_id == "/root/eng"
    assert created.project_id is None
    assert created.id  # server 生成 id
    mgr.create_or_replace_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_job_manager_can_create_shared(monkeypatch):
    _rbac(monkeypatch, enabled=True, admin=False)
    _patch_create_env(monkeypatch, manage=True, dept="/root/eng")

    mgr = AsyncMock()
    # 管理者提交 owner=None → 员工共享任务（不强制归属本人）
    created = await cron_api.create_job(
        make_cron_job_spec(job_id=None), _req("lead"), mgr=mgr,
    )

    assert created.owner_user_id is None
    assert created.department_id is None
    mgr.create_or_replace_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_job_rbac_off_keeps_submitted_owner(monkeypatch):
    _rbac(monkeypatch, enabled=False)
    _patch_create_env(monkeypatch, manage=False, dept="/root/eng")

    mgr = AsyncMock()
    # RBAC 关闭：不介入归属（单机零变化），沿用提交值（默认 None=共享）
    created = await cron_api.create_job(
        make_cron_job_spec(job_id=None), _req(""), mgr=mgr,
    )

    assert created.owner_user_id is None
    mgr.create_or_replace_job.assert_awaited_once()
