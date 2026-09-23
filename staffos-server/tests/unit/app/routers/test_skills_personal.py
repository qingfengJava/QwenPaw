# -*- coding: utf-8 -*-
"""T8d：个人技能（S2）路由端点 + SkillSpec 投影。

覆盖：``_build_personal_skill_specs`` 纯投影；``GET/POST/DELETE
/skills/personal``（owner 恒为会话用户，无认证/无 PG 平面降级）；
``GET /skills`` 合并个人技能；``POST /skills/personal/{name}/promote``
（管理闸门 + 复用共享创建链路，按前缀拆分 files）。
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app.routers.skills import (
    _build_personal_skill_specs,
)
from qwenpaw.app.routers.skills import (
    router as skills_router,
)

_BUNDLE = "qwenpaw.agents.skill_system.bundle_store"


def _app_with_user(username: str | None) -> FastAPI:
    """构造带「认证中间件」的测试 app：把会话用户挂到 request.state。"""
    application = FastAPI()
    application.state.multi_agent_manager = MagicMock(name="ManagerStub")

    @application.middleware("http")
    async def _inject_user(request: Request, call_next):
        request.state.user = username
        return await call_next(request)

    application.include_router(skills_router, prefix="/api")
    return application


@pytest.fixture
def fake_workspace(tmp_path: Path):
    workspace = MagicMock(name="Workspace")
    workspace.workspace_dir = str(tmp_path)
    workspace.agent_id = "default"
    return workspace


@pytest.fixture
def patch_get_agent(fake_workspace):
    with patch(
        "qwenpaw.app.agent_context.get_agent_for_request",
        new=AsyncMock(return_value=fake_workspace),
    ) as patched:
        yield patched


# ---------------------------------------------------------------------------
# _build_personal_skill_specs（纯投影）
# ---------------------------------------------------------------------------


def test_build_personal_specs_projects_source_and_enabled() -> None:
    bundles = [
        {
            "name": "s1",
            "enabled": True,
            "files": {"SKILL.md": "---\ndescription: hello\n---\n# s1"},
        },
        {"name": "s2", "enabled": False, "files": {}},
    ]

    specs = _build_personal_skill_specs(bundles)

    assert len(specs) == 2
    assert specs[0].name == "s1"
    assert specs[0].source == "personal"
    assert specs[0].enabled is True
    assert specs[0].description == "hello"
    assert specs[1].name == "s2"
    assert specs[1].enabled is False


def test_build_personal_specs_empty() -> None:
    assert _build_personal_skill_specs([]) == []


# ---------------------------------------------------------------------------
# GET /skills/personal
# ---------------------------------------------------------------------------


def test_list_personal_no_user_returns_empty(patch_get_agent) -> None:
    client = TestClient(_app_with_user(None))

    resp = client.get("/api/skills/personal")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_personal_returns_own_bundles(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    bundle = {"name": "s1", "enabled": True, "files": {"SKILL.md": "# s1"}}
    with patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.load_owner_bundles_pg",
        new=AsyncMock(return_value=[bundle]),
    ):
        resp = client.get("/api/skills/personal")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "s1"
    assert body[0]["source"] == "personal"


# ---------------------------------------------------------------------------
# POST /skills/personal
# ---------------------------------------------------------------------------


def test_save_personal_no_user_401(patch_get_agent) -> None:
    client = TestClient(_app_with_user(None))

    resp = client.post(
        "/api/skills/personal",
        json={"name": "s1", "files": {"SKILL.md": "# s1"}},
    )

    assert resp.status_code == 401


def test_save_personal_no_pg_503(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    with patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=False,
    ):
        resp = client.post(
            "/api/skills/personal",
            json={"name": "s1", "files": {"SKILL.md": "# s1"}},
        )

    assert resp.status_code == 503


def test_save_personal_missing_skill_md_400(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    with patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ):
        resp = client.post(
            "/api/skills/personal",
            json={"name": "s1", "files": {"other.txt": "x"}},
        )

    assert resp.status_code == 400


def test_save_personal_success_upserts_and_materializes(
    patch_get_agent,
    tmp_path,
) -> None:
    client = TestClient(_app_with_user("alice"))
    upsert = AsyncMock(return_value=None)
    materialize = MagicMock(return_value=tmp_path / ".personal_skills")
    with patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.upsert_skill_bundle_pg",
        new=upsert,
    ), patch(
        f"{_BUNDLE}.materialize_owner_bundles",
        new=materialize,
    ), patch(
        "qwenpaw.app.routers.skills._resolve_owner_department",
        new=AsyncMock(return_value=None),
    ), patch(
        "qwenpaw.app.routers.skills.schedule_agent_reload",
    ):
        resp = client.post(
            "/api/skills/personal",
            json={
                "name": "s1",
                "files": {"SKILL.md": "# s1"},
                "enabled": True,
            },
        )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"saved": True, "name": "s1"}
    upsert.assert_awaited_once()
    materialize.assert_called_once()


# ---------------------------------------------------------------------------
# DELETE /skills/personal/{name}
# ---------------------------------------------------------------------------


def test_delete_personal_404_when_missing(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    with patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.delete_skill_bundle_pg",
        new=AsyncMock(return_value=False),
    ):
        resp = client.delete("/api/skills/personal/s1")

    assert resp.status_code == 404


def test_delete_personal_success(patch_get_agent, tmp_path) -> None:
    client = TestClient(_app_with_user("alice"))
    with patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.delete_skill_bundle_pg",
        new=AsyncMock(return_value=True),
    ), patch(
        f"{_BUNDLE}.get_personal_skills_dir",
        return_value=tmp_path / ".personal_skills" / "alice",
    ), patch(
        "qwenpaw.app.routers.skills.schedule_agent_reload",
    ):
        resp = client.delete("/api/skills/personal/s1")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "name": "s1"}


# ---------------------------------------------------------------------------
# GET /skills 合并个人技能
# ---------------------------------------------------------------------------


def test_list_skills_merges_personal(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    bundle = {"name": "s1", "enabled": True, "files": {"SKILL.md": "# s1"}}
    with patch(
        "qwenpaw.app.routers.skills._build_workspace_skill_specs",
        return_value=[],
    ), patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.load_owner_bundles_pg",
        new=AsyncMock(return_value=[bundle]),
    ):
        resp = client.get("/api/skills")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["source"] == "personal"


# ---------------------------------------------------------------------------
# POST /skills/personal/{name}/promote
# ---------------------------------------------------------------------------


def test_promote_404_when_bundle_missing(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    with patch(
        "qwenpaw.app.rbac.deps.rbac_enforcement_enabled",
        return_value=False,
    ), patch(
        "qwenpaw.app.rbac.deps._record_gate_audit",
        return_value=None,
    ), patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.load_skill_bundle_pg",
        new=AsyncMock(return_value=None),
    ):
        resp = client.post("/api/skills/personal/s1/promote")

    assert resp.status_code == 404


def test_promote_success_maps_files_to_create_skill(
    patch_get_agent,
) -> None:
    client = TestClient(_app_with_user("alice"))
    bundle = {
        "name": "s1",
        "enabled": True,
        "files": {
            "SKILL.md": "# s1",
            "references/r.md": "ref",
            "scripts/x.py": "print(1)",
        },
    }
    svc = MagicMock()
    svc.return_value.create_skill.return_value = "s1"
    with patch(
        "qwenpaw.app.rbac.deps.rbac_enforcement_enabled",
        return_value=False,
    ), patch(
        "qwenpaw.app.rbac.deps._record_gate_audit",
        return_value=None,
    ), patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.load_skill_bundle_pg",
        new=AsyncMock(return_value=bundle),
    ), patch(
        "qwenpaw.app.routers.skills.SkillService",
        new=svc,
    ), patch(
        "qwenpaw.app.routers.skills.schedule_agent_reload",
    ):
        resp = client.post("/api/skills/personal/s1/promote")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"promoted": True, "name": "s1"}
    kwargs = svc.return_value.create_skill.call_args.kwargs
    assert kwargs["content"] == "# s1"
    assert kwargs["references"] == {"r.md": "ref"}
    assert kwargs["scripts"] == {"x.py": "print(1)"}


# ---------------------------------------------------------------------------
# POST /skills/refresh 合并个人技能（与列表一致）
# ---------------------------------------------------------------------------


def test_refresh_skills_merges_personal(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    bundle = {"name": "s1", "enabled": True, "files": {"SKILL.md": "# s1"}}
    with patch(
        "qwenpaw.app.routers.skills._build_workspace_skill_specs",
        return_value=[],
    ), patch(
        "qwenpaw.app.routers.skills.reconcile_workspace_manifest",
    ), patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.load_owner_bundles_pg",
        new=AsyncMock(return_value=[bundle]),
    ):
        resp = client.post("/api/skills/refresh")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["source"] == "personal"


def test_refresh_skills_no_user_keeps_shared_only(patch_get_agent) -> None:
    client = TestClient(_app_with_user(None))
    with patch(
        "qwenpaw.app.routers.skills._build_workspace_skill_specs",
        return_value=[],
    ), patch(
        "qwenpaw.app.routers.skills.reconcile_workspace_manifest",
    ):
        resp = client.post("/api/skills/refresh")

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /skills/personal/{name} 详情携带完整 files（编辑/启停无损回存）
# ---------------------------------------------------------------------------


def test_get_personal_skill_returns_files(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    bundle = {
        "name": "s1",
        "enabled": True,
        "files": {
            "SKILL.md": "---\ndescription: hello\n---\n# s1",
            "references/r.md": "ref",
        },
    }
    with patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.load_skill_bundle_pg",
        new=AsyncMock(return_value=bundle),
    ):
        resp = client.get("/api/skills/personal/s1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "s1"
    assert body["source"] == "personal"
    assert body["files"]["SKILL.md"].startswith("---")
    assert body["files"]["references/r.md"] == "ref"


def test_get_personal_skill_404(patch_get_agent) -> None:
    client = TestClient(_app_with_user("alice"))
    with patch(
        f"{_BUNDLE}.bundle_pg_plane_available",
        return_value=True,
    ), patch(
        f"{_BUNDLE}.load_skill_bundle_pg",
        new=AsyncMock(return_value=None),
    ):
        resp = client.get("/api/skills/personal/missing")

    assert resp.status_code == 404
