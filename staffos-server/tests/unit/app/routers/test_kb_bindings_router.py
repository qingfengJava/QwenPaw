# -*- coding: utf-8 -*-
"""M6-7: kb-bindings 路由端点形状单测（TestClient，零 PG 零真认证）。

覆盖 401/403/404/201/200/204 语义与 body 形状；bindings 层逻辑由
``tests/unit/app/kb/test_bindings.py`` 覆盖，真库往返由集成门控覆盖。

@author qingfeng
"""

# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from qwenpaw.app.kb import bindings
from qwenpaw.app.routers.agents import router as agents_router

_AGENTS = "qwenpaw.app.routers.agents"


def _app_with_user(username: str | None) -> FastAPI:
    """构造带「认证中间件」的测试 app：会话用户挂 request.state。"""
    application = FastAPI()

    @application.middleware("http")
    async def _inject_user(request: Request, call_next):
        request.state.user = username
        return await call_next(request)

    application.include_router(agents_router, prefix="/api")
    return application


@pytest.fixture()
def client() -> Any:
    """alice 会话的 TestClient（测试内按需重建以切换身份）。"""
    return TestClient(_app_with_user("alice"))


@pytest.fixture(autouse=True)
def _agent_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent 恒存在（存在性分支单独用例显式改写）。"""

    def _load(agent_id: str):
        del agent_id
        return object()

    monkeypatch.setattr(f"{_AGENTS}.load_agent_config", _load)


def _patch_manage(
    monkeypatch: pytest.MonkeyPatch,
    result: Any,
) -> None:
    """can_manage_space 打桩（True/False/None 三态）。"""

    async def _manage(space_id: str, username: str, **kwargs: Any):
        del space_id, username, kwargs
        return result

    monkeypatch.setattr(bindings, "can_manage_space", _manage)


# ---------------------------------------------------------------------------
# PUT（绑定）
# ---------------------------------------------------------------------------


def test_put_requires_user() -> None:
    """未登录绑定 → 401。"""
    client = TestClient(_app_with_user(None))

    resp = client.put(
        "/api/agents/analyst/kb-bindings",
        json={"space_id": "kb_a"},
    )

    assert resp.status_code == 401


def test_put_missing_agent_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent 不存在 → 404（先于权限判定）。"""

    def _load(agent_id: str):
        del agent_id
        raise ValueError("agent not found")

    monkeypatch.setattr(f"{_AGENTS}.load_agent_config", _load)
    client = TestClient(_app_with_user("alice"))

    resp = client.put(
        "/api/agents/ghost/kb-bindings",
        json={"space_id": "kb_a"},
    )

    assert resp.status_code == 404


def test_put_missing_space_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """库不存在 → 404（can_manage_space None 哨兵）。"""
    _patch_manage(monkeypatch, None)
    client = TestClient(_app_with_user("alice"))

    resp = client.put(
        "/api/agents/analyst/kb-bindings",
        json={"space_id": "kb_x"},
    )

    assert resp.status_code == 404


def test_put_without_manage_right_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无管理权 → 403，且不触发绑定写入。"""
    _patch_manage(monkeypatch, False)
    called: list[str] = []

    async def _bind(**kwargs: Any):
        called.append(kwargs["space_id"])
        return True

    monkeypatch.setattr(bindings, "bind_agent_kb", _bind)
    client = TestClient(_app_with_user("alice"))

    resp = client.put(
        "/api/agents/analyst/kb-bindings",
        json={"space_id": "kb_a"},
    )

    assert resp.status_code == 403
    assert called == []


def test_put_bind_created_201_and_idempotent_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """首次绑定 201；重复绑定 200，两路径统一返回既有行完整字段。"""
    _patch_manage(monkeypatch, True)
    bound: list[str] = []

    async def _bind(**kwargs: Any):
        bound.append(kwargs["space_id"])
        return True

    async def _rows(agent_id: str):
        del agent_id
        if not bound:
            return []
        return [
            {
                "agent_id": "analyst",
                "space_id": "kb_a",
                "space_name": "孕产知识库",
                "scope": "personal",
                "granted_by": "alice",
                "remark": "孕产",
                "created_at": "2026-09-18T00:00:00+00:00",
            },
        ]

    monkeypatch.setattr(bindings, "bind_agent_kb", _bind)
    monkeypatch.setattr(bindings, "list_bindings", _rows)
    client = TestClient(_app_with_user("alice"))

    first = client.put(
        "/api/agents/analyst/kb-bindings",
        json={"space_id": "kb_a", "remark": "孕产"},
    )
    second = client.put(
        "/api/agents/analyst/kb-bindings",
        json={"space_id": "kb_a"},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert bound == ["kb_a"]
    # 两路径统一形状：绑定行完整字段 + created 布尔（前端不按状态码分叉）
    assert first.json()["created"] is True
    assert first.json()["space_name"] == "孕产知识库"
    assert second.json()["created"] is False
    assert second.json()["granted_by"] == "alice"
    assert second.json()["space_name"] == "孕产知识库"


def test_put_storage_failure_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """预检通过但存储写失败 → 503（基础设施故障不伪装成 403）。"""
    _patch_manage(monkeypatch, True)

    async def _bind(**kwargs: Any):
        del kwargs
        return False

    async def _rows(agent_id: str):
        # 首次绑定路径：既有行为空 → 走写入 → 写失败 503
        del agent_id
        return []

    monkeypatch.setattr(bindings, "bind_agent_kb", _bind)
    monkeypatch.setattr(bindings, "list_bindings", _rows)
    client = TestClient(_app_with_user("alice"))

    resp = client.put(
        "/api/agents/analyst/kb-bindings",
        json={"space_id": "kb_a"},
    )

    assert resp.status_code == 503


def test_put_concurrent_unbind_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """写后读回为空（并发解绑窗口）→ 409，绝不 fallthrough 谎报 bound。"""
    _patch_manage(monkeypatch, True)

    async def _bind(**kwargs: Any):
        del kwargs
        return True

    async def _rows(agent_id: str):
        # 判定与写后读回都返空：模拟「判定为首次绑定，写入后又被并发解绑」
        del agent_id
        return []

    monkeypatch.setattr(bindings, "bind_agent_kb", _bind)
    monkeypatch.setattr(bindings, "list_bindings", _rows)
    client = TestClient(_app_with_user("alice"))

    resp = client.put(
        "/api/agents/analyst/kb-bindings",
        json={"space_id": "kb_a"},
    )

    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET（列表）
# ---------------------------------------------------------------------------


def test_get_lists_bindings_with_space_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET 返回绑定行（含名称/scope/授权人），未登录 401。"""

    async def _listed(agent_id: str):
        del agent_id
        return [
            {
                "agent_id": "analyst",
                "space_id": "kb_a",
                "space_name": "孕产知识库",
                "scope": "personal",
                "granted_by": "alice",
                "remark": "",
                "created_at": "2026-09-18T00:00:00+00:00",
            },
        ]

    monkeypatch.setattr(bindings, "list_bindings", _listed)
    client = TestClient(_app_with_user("alice"))
    anon = TestClient(_app_with_user(None))

    ok = client.get("/api/agents/analyst/kb-bindings")
    denied = anon.get("/api/agents/analyst/kb-bindings")

    assert ok.status_code == 200
    assert ok.json()[0]["space_name"] == "孕产知识库"
    assert ok.json()[0]["granted_by"] == "alice"
    assert denied.status_code == 401


# ---------------------------------------------------------------------------
# DELETE（解绑）
# ---------------------------------------------------------------------------


def test_delete_unbinds_with_manage_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解绑：有管理权 204 → 行删除；重复解绑 404；越权 403。"""
    state = {"bound": True}

    async def _manage(space_id: str, username: str, **kwargs: Any):
        del space_id, kwargs
        return True if username == "alice" else False

    async def _unbind(agent_id: str, space_id: str) -> bool:
        del agent_id, space_id
        if state["bound"]:
            state["bound"] = False
            return True
        return False

    monkeypatch.setattr(bindings, "can_manage_space", _manage)
    monkeypatch.setattr(bindings, "unbind_agent_kb", _unbind)
    client = TestClient(_app_with_user("alice"))
    intruder = TestClient(_app_with_user("bob"))

    first = client.delete("/api/agents/analyst/kb-bindings/kb_a")
    again = client.delete("/api/agents/analyst/kb-bindings/kb_a")
    denied = intruder.delete("/api/agents/analyst/kb-bindings/kb_a")

    assert first.status_code == 204
    assert again.status_code == 404
    assert denied.status_code == 403


def test_delete_missing_space_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """解绑时库不存在 → 404。"""
    _patch_manage(monkeypatch, None)
    client = TestClient(_app_with_user("alice"))

    resp = client.delete("/api/agents/analyst/kb-bindings/kb_x")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# admin 删库回收接线（P2：json 态绑定行随删库同步回收）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_delete_kb_reaps_json_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """admin 删库成功后须调用 json 态绑定回收（直调路由函数验证接线）。"""
    from qwenpaw.app.routers.admin import kb as admin_kb

    deleted: list[str] = []

    class _Svc:
        def delete_kb(self, kb_id: str) -> bool:
            del kb_id
            return True

    async def _reap(kb_id: str) -> int:
        deleted.append(kb_id)
        return 1

    monkeypatch.setattr(admin_kb, "get_kb_service", lambda: _Svc())
    monkeypatch.setattr(admin_kb, "delete_space_bindings", _reap)

    await admin_kb.delete_kb("kb_a")

    assert deleted == ["kb_a"]
