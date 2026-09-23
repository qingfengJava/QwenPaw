# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""知识本体平台 T1：org scope（组织级知识库）单元测试。

覆盖：scope 枚举扩展、create_kb org 分支、can_access / can_manage_space
的 org 判定矩阵（json+pg 双面 ACL 共用同一实现，单实现对双面断言）、
KbSpace↔KnowledgeBase 转换与 pg_store 行映射的 org_id 保真。
真实 PG DDL（0044 约束换血）由 PG 门控集成套件覆盖，不在本文件范围。

@author qingfeng
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from qwenpaw.app.kb import bindings as kb_bindings
from qwenpaw.app.kb.models import (
    SCOPE_ENTERPRISE,
    SCOPE_ORG,
    SCOPE_PERSONAL,
    SCOPE_TEAM,
    VALID_SCOPES,
    KbSpace,
    KnowledgeBase,
)
from qwenpaw.app.kb.pg_store import space_from_row
from qwenpaw.app.kb.service import KbService
from qwenpaw.db import write_gateway


@pytest.fixture(autouse=True)
def _json_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉住 json 后端（对齐 test_kb.py，防环境变量泄漏误走 pg 路径）。"""
    monkeypatch.setattr(
        write_gateway,
        "resolve_storage_backend",
        lambda: "json",
    )


@pytest.fixture
def service(tmp_path: "pytest.Path") -> KbService:
    return KbService(
        registry_path=tmp_path / "kb_registry.json",
        data_dir=tmp_path / "kb_data",
    )


# ---------------------------------------------------------------------------
# 枚举与模型校验
# ---------------------------------------------------------------------------


def test_scope_org_in_valid_scopes() -> None:
    assert SCOPE_ORG == "org"
    assert SCOPE_ORG in VALID_SCOPES
    # 既有三值不丢（零破坏演进）
    assert {SCOPE_PERSONAL, SCOPE_TEAM, SCOPE_ENTERPRISE} <= set(VALID_SCOPES)


def test_kb_space_accepts_org_scope() -> None:
    space = KbSpace(id="kb_org1", name="公司库", scope=SCOPE_ORG)
    assert space.scope == "org"
    # org_id 缺省落 default（租户边界语义）
    assert space.org_id == "default"


def test_kb_space_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError, match="scope"):
        KbSpace(id="kb_x", name="x", scope="department")


def test_knowledge_base_org_id_default() -> None:
    kb = KnowledgeBase(id="kb_y", name="y", scope=SCOPE_ORG)
    assert kb.org_id == "default"


# ---------------------------------------------------------------------------
# create_kb org 分支（json 面）
# ---------------------------------------------------------------------------


def test_create_kb_org_scope_default_org(service: KbService) -> None:
    kb = service.create_kb("公司制度库", scope=SCOPE_ORG)
    assert kb is not None
    assert kb.scope == SCOPE_ORG
    assert kb.org_id == "default"


def test_create_kb_org_scope_explicit_org(service: KbService) -> None:
    kb = service.create_kb(
        "ACME 库",
        scope=SCOPE_ORG,
        org_id="acme",
    )
    assert kb is not None and kb.org_id == "acme"
    # 读回保真（json registry 往返）
    loaded = service.get_kb(kb.id)
    assert loaded is not None and loaded.org_id == "acme"


def test_create_kb_empty_org_id_falls_back(service: KbService) -> None:
    kb = service.create_kb("空组织库", scope=SCOPE_ORG, org_id="  ")
    assert kb is not None and kb.org_id == "default"


# ---------------------------------------------------------------------------
# can_access org 矩阵
# ---------------------------------------------------------------------------


def _org_kb(service: KbService, org_id: str = "default") -> KnowledgeBase:
    kb = service.create_kb("组织库", scope=SCOPE_ORG, org_id=org_id)
    assert kb is not None
    return kb


def test_can_access_org_same_org_allowed(service: KbService) -> None:
    kb = _org_kb(service, "acme")
    assert service.can_access(kb, "alice", user_org="acme") is True


def test_can_access_org_other_org_denied(service: KbService) -> None:
    kb = _org_kb(service, "acme")
    assert service.can_access(kb, "mallory", user_org="other") is False


def test_can_access_org_no_username_denied(service: KbService) -> None:
    kb = _org_kb(service)
    assert service.can_access(kb, "", user_org="default") is False


def test_can_access_org_empty_caller_org_falls_to_default(
    service: KbService,
) -> None:
    # 调用侧未传 org：按 default 租户收敛（单租户部署语义）
    kb = _org_kb(service, "default")
    assert service.can_access(kb, "alice") is True
    other = _org_kb(service, "acme")
    assert service.can_access(other, "alice") is False


def test_can_access_org_grants_override(service: KbService) -> None:
    kb = _org_kb(service, "acme")
    service.update_grants(kb.id, users=["guest"])
    # 跨组织但命中显式 grants → 放行（grants 前置于 scope 语义）
    assert service.can_access(kb, "guest", user_org="other") is True


def test_can_access_org_admin_bypass(service: KbService) -> None:
    kb = _org_kb(service, "acme")
    assert service.can_access(kb, "root", flat_role="admin") is True


def test_accessible_kbs_org_filtering(service: KbService) -> None:
    acme = _org_kb(service, "acme")
    default_kb = _org_kb(service, "default")
    personal = service.create_kb(
        "私人库",
        scope=SCOPE_PERSONAL,
        owner_id="alice",
    )
    assert personal is not None

    visible = service.accessible_kbs("alice", user_org="acme")
    ids = {kb.id for kb in visible}
    assert acme.id in ids
    assert default_kb.id not in ids
    assert personal.id in ids


# ---------------------------------------------------------------------------
# KbSpace↔KnowledgeBase 转换与 pg 行映射的 org_id 保真
# ---------------------------------------------------------------------------


def test_space_kb_roundtrip_preserves_org(service: KbService) -> None:
    kb = _org_kb(service, "acme")
    space = service._kb_to_space(kb)
    assert space.org_id == "acme"
    back = service._space_to_kb(space)
    assert back.org_id == "acme"


def test_space_from_row_maps_org_id() -> None:
    row = {
        "id": "kb_org1",
        "name": "组织库",
        "description": "",
        "scope": "org",
        "owner_id": "",
        "team_id": "",
        "org_id": "acme",
        "grants": "{}",
        "embedding_model": "",
        "engine": "auto",
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
    }
    space = space_from_row(row)
    assert space.org_id == "acme"


def test_space_from_row_org_null_falls_default() -> None:
    row = {
        "id": "kb_legacy",
        "name": "存量库",
        "description": "",
        "scope": "enterprise",
        "owner_id": "",
        "team_id": "",
        "org_id": None,
        "grants": "{}",
        "embedding_model": "",
        "engine": "auto",
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
    }
    space = space_from_row(row)
    assert space.org_id == "default"


# ---------------------------------------------------------------------------
# can_manage_space org 分支（绑定管理权）
# ---------------------------------------------------------------------------


def _patch_space_shape(
    monkeypatch: pytest.MonkeyPatch,
    shape: kb_bindings.SpaceShape,
) -> None:
    async def _fake_load(space_id: str):
        return shape

    monkeypatch.setattr(
        kb_bindings,
        "_load_space_shape",
        _fake_load,
    )


def _patch_write_perm(
    monkeypatch: pytest.MonkeyPatch,
    allowed: bool,
) -> None:
    monkeypatch.setattr(
        kb_bindings,
        "_has_kb_write_perm",
        lambda username, flat_role: allowed,
    )


def test_manage_org_same_org_with_write_perm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_space_shape(
        monkeypatch,
        kb_bindings.SpaceShape(
            scope=SCOPE_ORG,
            owner_id="",
            team_id="",
            grant_roles=(),
            grant_users=(),
            grant_teams=(),
            org_id="acme",
        ),
    )
    _patch_write_perm(monkeypatch, True)
    import asyncio

    verdict = asyncio.run(
        kb_bindings.can_manage_space(
            "kb_org1",
            "alice",
            user_org="acme",
        ),
    )
    assert verdict is True


def test_manage_org_same_org_without_write_perm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_space_shape(
        monkeypatch,
        kb_bindings.SpaceShape(
            scope=SCOPE_ORG,
            owner_id="",
            team_id="",
            grant_roles=(),
            grant_users=(),
            grant_teams=(),
            org_id="acme",
        ),
    )
    _patch_write_perm(monkeypatch, False)
    import asyncio

    verdict = asyncio.run(
        kb_bindings.can_manage_space("kb_org1", "alice", user_org="acme"),
    )
    assert verdict is False


def test_manage_org_cross_org_denied_even_with_perm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_space_shape(
        monkeypatch,
        kb_bindings.SpaceShape(
            scope=SCOPE_ORG,
            owner_id="",
            team_id="",
            grant_roles=(),
            grant_users=(),
            grant_teams=(),
            org_id="acme",
        ),
    )
    _patch_write_perm(monkeypatch, True)
    import asyncio

    verdict = asyncio.run(
        kb_bindings.can_manage_space(
            "kb_org1",
            "alice",
            user_org="other",
        ),
    )
    assert verdict is False


def test_manage_org_grants_user_bypasses_org_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # grants 命中在 scope 语义之前：跨组织显式授权者仍可管理
    _patch_space_shape(
        monkeypatch,
        kb_bindings.SpaceShape(
            scope=SCOPE_ORG,
            owner_id="",
            team_id="",
            grant_roles=(),
            grant_users=("guest",),
            grant_teams=(),
            org_id="acme",
        ),
    )
    _patch_write_perm(monkeypatch, False)
    import asyncio

    verdict = asyncio.run(
        kb_bindings.can_manage_space("kb_org1", "guest", user_org="other"),
    )
    assert verdict is True
