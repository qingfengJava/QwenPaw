# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for the backend-config-plane gate ``require_agent_manage``.

双平面模型的 manage 闸门判定顺序（任一命中即放行）：

1. RBAC 关闭（单机免认证部署）→ 直通，零行为变化；
2. flat admin → 直通（bootstrap 修复路径）；
3. 持有 ``agent:manage`` 角色权限（team_lead）→ 全员工直通；
4. ``agent_manage_grants`` 有行 → 按 grant 的 users/roles/teams 判定；
5. 无 grant 行 → 兜底 private 语义：仅创建者（治理行 owner，expert 形态
   回退 experts.owner_id）。

关键差异断言：manage 平面「无行 ≠ 不限制」（use 平面是无行不限制），
出厂默认最严，避免新员工被全员可改。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.employees.models import GovernanceRecord
from qwenpaw.app.rbac import deps as deps_mod
from qwenpaw.app.rbac.deps import (
    is_platform_admin,
    require_agent_manage,
    require_agent_manage_audited,
)
from qwenpaw.app.rbac.models import GrantRecord
from qwenpaw.app.rbac.store import RbacStore


@pytest.fixture
def store(tmp_path: Path) -> RbacStore:
    return RbacStore(tmp_path / "rbac.json")


def _request(
    user: str = "",
    agent_id: str = "expert_sales",
) -> SimpleNamespace:
    """最小 Request 替身：闸门只读 state.user / state.agent_id / url.path。"""
    return SimpleNamespace(
        state=SimpleNamespace(user=user, agent_id=agent_id),
        url=SimpleNamespace(path=f"/api/agents/{agent_id}/config"),
        method="PUT",
    )


def _header_request(
    user: str = "",
    agent_id: str = "",
    header_agent: str = "",
) -> SimpleNamespace:
    """顶层路径 + X-Agent-Id 头的请求替身（控制台写请求常规形态）。"""
    headers = {"X-Agent-Id": header_agent} if header_agent else {}
    return SimpleNamespace(
        state=SimpleNamespace(user=user, agent_id=agent_id),
        headers=headers,
        url=SimpleNamespace(path="/api/workspace/files"),
        method="PUT",
    )


def _patch_env(
    monkeypatch: pytest.MonkeyPatch,
    store: RbacStore,
    flat_role: str = "employee",
) -> None:
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "1")
    # deps 模块 import 时绑定了 get_rbac_store，必须 patch deps 的引用
    monkeypatch.setattr(deps_mod, "get_rbac_store", lambda: store)
    monkeypatch.setattr(
        deps_mod,
        "_resolve_flat_role",
        lambda _u: flat_role,
    )


class _FakeGovernanceStore:
    def __init__(self, record: GovernanceRecord | None = None):
        self._record = record

    async def get(self, agent_id: str):
        return self._record


class _FakeExpertStore:
    def __init__(self, expert):
        self._expert = expert

    async def get_expert(self, expert_id: str):
        return self._expert


def _patch_owner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    governance: GovernanceRecord | None = None,
    expert=None,
) -> None:
    monkeypatch.setattr(
        "qwenpaw.app.employees.store.get_employee_governance_store",
        lambda: _FakeGovernanceStore(governance),
    )
    monkeypatch.setattr(
        "qwenpaw.app.experts.store.get_expert_store",
        lambda: _FakeExpertStore(expert),
    )


# ---------------------------------------------------------------------------
# 档位 1-3：直通路径
# ---------------------------------------------------------------------------


async def test_gate_inert_when_enforcement_off(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 单机免认证部署：零行为变化，任何人任何员工直通
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "0")
    await require_agent_manage()(_request(user="eve"))


async def test_flat_admin_passes(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store, flat_role="admin")
    store.set_agent_manage_grant(
        "expert_sales",
        GrantRecord(users=["alice"]),
    )
    # admin 直通，不看 grant
    await require_agent_manage()(_request(user="root"))


async def test_team_lead_role_passes_all_agents(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    store.grant_role("eve", "team_lead")
    store.set_agent_manage_grant(
        "expert_sales",
        GrantRecord(users=["alice"]),
    )
    # 持有 agent:manage 角色权限 → 全员工直通（grant 不含 eve 也放行）
    await require_agent_manage()(_request(user="eve"))


async def test_missing_identity_denied(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    with pytest.raises(HTTPException) as excinfo:
        await require_agent_manage()(_request(user=""))
    assert excinfo.value.status_code == 403


async def test_missing_agent_scope_denied(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 无 agent 域路由且无头/活动员工可解析：fail closed 暴露装配错误
    _patch_env(monkeypatch, store)
    monkeypatch.setattr(
        deps_mod,
        "_resolve_request_agent_id",
        lambda _req: "",
    )
    with pytest.raises(HTTPException) as excinfo:
        await require_agent_manage()(_request(user="eve", agent_id=""))
    assert excinfo.value.status_code == 403


async def test_agent_id_resolved_from_header_for_top_level_write(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 控制台写请求常规形态：顶层路径无 state.agent_id，靠 X-Agent-Id 头
    _patch_env(monkeypatch, store)
    store.set_agent_manage_grant(
        "expert_sales",
        GrantRecord(users=["alice"]),
    )
    # 头解析出 expert_sales → alice 命中 grant 放行
    await require_agent_manage()(
        _header_request(user="alice", header_agent="expert_sales"),
    )
    # 同一头，非授权用户被拒（闸门确实拿到了头里的 agent 并判权）
    with pytest.raises(HTTPException) as excinfo:
        await require_agent_manage()(
            _header_request(user="eve", header_agent="expert_sales"),
        )
    assert excinfo.value.status_code == 403


# ---------------------------------------------------------------------------
# 档位 4：manage grant 行判定
# ---------------------------------------------------------------------------


async def test_grant_row_allows_listed_user(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    store.set_agent_manage_grant(
        "expert_sales",
        GrantRecord(users=["alice"]),
    )
    await require_agent_manage()(_request(user="alice"))
    with pytest.raises(HTTPException) as excinfo:
        await require_agent_manage()(_request(user="eve"))
    assert excinfo.value.status_code == 403


async def test_grant_row_allows_dept_team_member(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    store.upsert_team("dept:sales", ["alice"])
    store.set_agent_manage_grant(
        "expert_sales",
        GrantRecord(teams=["dept:sales"]),
    )
    await require_agent_manage()(_request(user="alice"))
    with pytest.raises(HTTPException):
        await require_agent_manage()(_request(user="bob"))


# ---------------------------------------------------------------------------
# 档位 5：无 grant 行的兜底 private 语义
# ---------------------------------------------------------------------------


async def test_no_grant_row_falls_back_to_governance_owner(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    _patch_owner(
        monkeypatch,
        governance=GovernanceRecord(
            agent_id="expert_sales",
            owner_id="alice",
        ),
    )
    await require_agent_manage()(_request(user="alice"))
    # 无行 ≠ 不限制：非创建者必须被拒（与 use 平面语义相反）
    with pytest.raises(HTTPException) as excinfo:
        await require_agent_manage()(_request(user="eve"))
    assert excinfo.value.status_code == 403


async def test_no_grant_row_falls_back_to_expert_owner(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 无治理行的 expert：回退 experts.owner_id（创建者）
    _patch_env(monkeypatch, store)
    _patch_owner(
        monkeypatch,
        governance=None,
        expert=SimpleNamespace(owner_id="carol"),
    )
    await require_agent_manage()(_request(user="carol"))
    with pytest.raises(HTTPException):
        await require_agent_manage()(_request(user="eve"))


async def test_no_grant_row_native_agent_denies_everyone(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 原生 agent 无 owner 概念：无 grant 行时仅 admin/team_lead 可配
    _patch_env(monkeypatch, store)
    _patch_owner(monkeypatch, governance=None, expert=None)
    with pytest.raises(HTTPException):
        await require_agent_manage()(_request(user="eve", agent_id="default"))


async def test_owner_lookup_failure_fails_closed(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 存储抖动不得放宽闸门（fail closed）
    _patch_env(monkeypatch, store)

    class _BrokenStore:
        async def get(self, agent_id: str):
            raise RuntimeError("db down")

    monkeypatch.setattr(
        "qwenpaw.app.employees.store.get_employee_governance_store",
        lambda: _BrokenStore(),
    )
    with pytest.raises(HTTPException):
        await require_agent_manage()(_request(user="alice"))


# ---------------------------------------------------------------------------
# require_agent_manage_audited（闸判 + 审计留痕委派）
# ---------------------------------------------------------------------------


async def test_audited_gate_delegates_and_records_on_pass(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    store.set_agent_manage_grant(
        "expert_sales",
        GrantRecord(users=["alice"]),
    )
    recorded: list[str] = []
    # 隔离真实审计 I/O：只验证“过闸后触发了带 action 的留痕”接线
    monkeypatch.setattr(
        deps_mod,
        "_record_gate_audit",
        lambda _req, action: recorded.append(action),
    )
    dep = require_agent_manage_audited("config.channels.write")
    await dep(_request(user="alice"))
    assert recorded == ["config.channels.write"]


async def test_audited_gate_denies_and_skips_audit(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    recorded: list[str] = []
    monkeypatch.setattr(
        deps_mod,
        "_record_gate_audit",
        lambda _req, action: recorded.append(action),
    )
    # 无 grant 行且无 owner 兜底 → 内闸 403，审计不写（仅过闸才留痕）
    monkeypatch.setattr(
        deps_mod,
        "_fallback_manage_owner",
        lambda _agent: _async_empty(),
    )
    with pytest.raises(HTTPException) as excinfo:
        await require_agent_manage_audited("x")(_request(user="eve"))
    assert excinfo.value.status_code == 403
    assert recorded == []


async def _async_empty() -> str:
    return ""


# ---------------------------------------------------------------------------
# is_platform_admin — 个人资产（S2）owner+admin 判定（区别于 manage_allowed）
# ---------------------------------------------------------------------------


def test_is_platform_admin_false_for_empty_identity(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    assert is_platform_admin("") is False


def test_is_platform_admin_true_for_flat_admin(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store, flat_role="admin")
    assert is_platform_admin("root") is True


def test_is_platform_admin_true_for_platform_admin_role(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    store.grant_role("ops", "platform_admin")
    # PERM_ALL 通配覆盖 admin:platform
    assert is_platform_admin("ops") is True


def test_is_platform_admin_false_for_team_lead(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    store.grant_role("lead", "team_lead")
    # 关键区分：team_lead 持 agent:manage（管员工共享面）但无
    # admin:platform，不介入他人个人资产隐私边界
    assert is_platform_admin("lead") is False


def test_is_platform_admin_false_for_plain_employee(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    assert is_platform_admin("eve") is False


# ---------------------------------------------------------------------------
# resolve_agent_doc_write_plane — 档案写平面分流（T11 个人档案草稿）
# 管理权 → shared（共享行）；仅使用授权 → personal（本人草稿行）；
# 非白名单文件（allow_personal=False）与无使用授权的用户 → 403。
# ---------------------------------------------------------------------------


async def test_doc_write_plane_off_returns_shared(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 单机免认证部署：直通共享平面（零行为变化）
    monkeypatch.setenv("QWENPAW_RBAC_ENFORCE", "0")
    plane = await deps_mod.resolve_agent_doc_write_plane(
        _request(user="eve"),
        allow_personal=True,
    )
    assert plane == "shared"


async def test_doc_write_plane_manage_returns_shared_with_audit(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    store.set_agent_manage_grant(
        "expert_sales",
        GrantRecord(users=["alice"]),
    )
    recorded: list[str] = []
    # 隔离真实审计 I/O：只验证过闸（shared 平面）触发了留痕接线
    monkeypatch.setattr(
        deps_mod,
        "_record_gate_audit",
        lambda _req, action: recorded.append(action),
    )
    plane = await deps_mod.resolve_agent_doc_write_plane(
        _request(user="alice"),
        allow_personal=True,
        audit_action="workspace.files.write",
    )
    assert plane == "shared"
    assert recorded == ["workspace.files.write"]


async def test_doc_write_plane_use_grant_returns_personal(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 无管理权（无 manage grant 行 + 无 owner 兜底）但 use 平面无行=不限制
    # → 普通使用者写白名单档案文件落本人草稿行（不触共享行）
    _patch_env(monkeypatch, store)
    monkeypatch.setattr(
        deps_mod,
        "_fallback_manage_owner",
        lambda _agent: _async_empty(),
    )
    recorded: list[str] = []
    monkeypatch.setattr(
        deps_mod,
        "_record_gate_audit",
        lambda _req, action: recorded.append(action),
    )
    plane = await deps_mod.resolve_agent_doc_write_plane(
        _request(user="eve"),
        allow_personal=True,
        audit_action="workspace.files.write",
    )
    assert plane == "personal"
    # 个人草稿不算共享配置写：不写治理审计
    assert recorded == []


async def test_doc_write_plane_use_grant_denied_for_non_whitelist(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 仅使用授权但目标非白名单文件（allow_personal=False）→ 403
    _patch_env(monkeypatch, store)
    monkeypatch.setattr(
        deps_mod,
        "_fallback_manage_owner",
        lambda _agent: _async_empty(),
    )
    with pytest.raises(HTTPException) as excinfo:
        await deps_mod.resolve_agent_doc_write_plane(
            _request(user="eve"),
            allow_personal=False,
        )
    assert excinfo.value.status_code == 403


async def test_doc_write_plane_no_use_grant_denied(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # use 平面 grant 行不含此人 → 无使用授权 → 403（个人草稿也不给写）
    _patch_env(monkeypatch, store)
    monkeypatch.setattr(
        deps_mod,
        "_fallback_manage_owner",
        lambda _agent: _async_empty(),
    )
    store.set_agent_grant(
        "expert_sales",
        GrantRecord(users=["alice"]),
    )
    with pytest.raises(HTTPException) as excinfo:
        await deps_mod.resolve_agent_doc_write_plane(
            _request(user="eve"),
            allow_personal=True,
        )
    assert excinfo.value.status_code == 403


async def test_doc_write_plane_missing_identity_denied(
    store: RbacStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_env(monkeypatch, store)
    with pytest.raises(HTTPException) as excinfo:
        await deps_mod.resolve_agent_doc_write_plane(
            _request(user=""),
            allow_personal=True,
        )
    assert excinfo.value.status_code == 403
