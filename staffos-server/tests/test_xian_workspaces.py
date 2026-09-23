# -*- coding: utf-8 -*-
"""XianWork workspaces API + console upload workspace landing tests.

Covers the plan item "后端 pytest": workspaces CRUD / ownership
isolation (404, never 403) / bind-unbind persistence into
``chats.meta.runtime_context.project_dir`` / server-side sidebar
grouping (including Windows path case folding via ``_dir_key``) /
open-folder / and the console ``/console/upload`` contract —
``chat_id`` lands files under the chat's effective project directory
in ``media/`` and answers an absolute ``file://`` URI, while the
legacy no-``chat_id`` behavior (bare ``stored_name`` in the channel
media_dir, PG ``media_files`` double-write) stays unchanged.

PostgreSQL is replaced by an in-memory aiosqlite engine (StaticPool,
one shared connection) so the async handlers run against real SQL.
All HTTP calls go through ``httpx.AsyncClient`` over the ASGI
transport: handlers must share the pytest-asyncio event loop with the
engine, otherwise aiosqlite connections would jump loops.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from qwenpaw.app.chats.models import ChatSpec
from qwenpaw.app.routers import console as console_module
from qwenpaw.app.routers.xian import workspaces as ws_module
from qwenpaw.config import config as config_module
from qwenpaw.db.models_workspaces import XianWorkspaceRow


# ══════════════════════════════════ fakes ══════════════════════════════════


class FakeChatManager:
    """In-memory ChatManager subset built on real ChatSpec objects."""

    def __init__(self) -> None:
        self.chats: dict[str, ChatSpec] = {}

    def add(self, chat: ChatSpec) -> ChatSpec:
        self.chats[chat.id] = chat
        return chat

    async def list_chats(self, user_id=None, channel=None, archived=None):
        result = []
        for chat in self.chats.values():
            if channel is not None and chat.channel != channel:
                continue
            if archived is False and chat.archived_at is not None:
                continue
            if archived is True and chat.archived_at is None:
                continue
            result.append(chat)
        return result

    async def get_chat(self, chat_id: str):
        return self.chats.get(chat_id)

    async def set_project_dir(self, chat_id: str, project_dir):
        chat = self.chats.get(chat_id)
        if chat is None:
            return None
        meta = dict(chat.meta)
        runtime_context = dict(meta.get("runtime_context") or {})
        if project_dir is None:
            runtime_context.pop("project_dir", None)
        else:
            runtime_context["project_dir"] = project_dir
        if runtime_context:
            meta["runtime_context"] = runtime_context
        else:
            meta.pop("runtime_context", None)
        chat.meta = meta
        return chat


class FakeConsoleChannel:
    def __init__(self, media_dir: Path) -> None:
        self.media_dir = media_dir


class FakeChannelManager:
    def __init__(self, console_channel: FakeConsoleChannel) -> None:
        self._console = console_channel

    async def get_channel(self, name: str):
        return self._console if name == "console" else None


class FakeAgentWorkspace:
    def __init__(
        self,
        chat_manager,
        channel_manager=None,
        workspace_dir: Path | None = None,
        agent_id: str = "test-agent",
    ) -> None:
        self.chat_manager = chat_manager
        self.channel_manager = channel_manager
        self.workspace_dir = workspace_dir
        self.agent_id = agent_id


def make_chat(
    name: str,
    *,
    owner: str = "alice",
    channel: str = "console",
    status: str = "idle",
    project_dir: str | None = None,
    age_seconds: float = 0.0,
) -> ChatSpec:
    meta: dict = {}
    if project_dir is not None:
        meta["runtime_context"] = {"project_dir": project_dir}
    return ChatSpec(
        name=name,
        session_id=f"{channel}:{owner}",
        user_id=owner,
        owner_id=owner,
        channel=channel,
        status=status,
        meta=meta,
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    )


# ═════════════════════════════════ fixtures ═════════════════════════════════


@pytest.fixture
async def engine():
    """Shared in-memory SQLite standing in for the PostgreSQL engine.

    ``StaticPool`` keeps exactly one connection so the memory database
    survives across ``engine.connect()`` blocks; ``now()`` is registered
    on that connection because the rename SQL uses
    ``updated_at = now()`` (PostgreSQL function without a SQLite
    builtin). The connect event cannot be used here: aiosqlite's
    adapted connection only exposes the async ``create_function``
    coroutine, so we grab the single pooled connection directly.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.connect() as conn:
        fairy = await conn.get_raw_connection()
        adapted = fairy.dbapi_connection
        await adapted._connection.create_function(
            "now",
            0,
            lambda: datetime.now(timezone.utc).isoformat(),
        )

    async with engine.begin() as conn:
        await conn.run_sync(XianWorkspaceRow.__table__.create, checkfirst=True)
    yield engine
    await engine.dispose()


def _build_app(router, state: dict) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request: Request, call_next):
        if state["user"] is not None:
            request.state.user = state["user"]
        return await call_next(request)

    app.include_router(router)
    return app


@pytest.fixture
async def ws_env(monkeypatch, engine):
    """Workspaces router mounted with PG/chat-manager deps faked."""
    state = {"user": None, "workspace": None}

    async def fake_get_agent(request: Request):
        return state["workspace"]

    monkeypatch.setattr(ws_module, "require_enterprise_engine", lambda: engine)
    monkeypatch.setattr(ws_module, "current_tenant_id", lambda: "default")
    monkeypatch.setattr(ws_module, "get_agent_for_request", fake_get_agent)

    transport = httpx.ASGITransport(app=_build_app(ws_module.router, state))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield SimpleNamespace(client=client, state=state)


@pytest.fixture
async def upload_env(monkeypatch, tmp_path):
    """Console /upload mounted with channel + config + PG-blob faked."""
    channel_media = tmp_path / "channel_media"
    channel_media.mkdir()
    workspace_dir = tmp_path / "agent-workspace"
    chat_manager = FakeChatManager()
    workspace = FakeAgentWorkspace(
        chat_manager=chat_manager,
        channel_manager=FakeChannelManager(FakeConsoleChannel(channel_media)),
        workspace_dir=workspace_dir,
    )
    state = {"user": None}

    async def fake_get_agent(request: Request):
        return workspace

    def fake_load_agent_config(agent_id):
        # Real loader is sync (called via asyncio.to_thread in the handler).
        return SimpleNamespace(project_dir=None)

    saved: list[dict] = []

    async def fake_save_media_blob(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(console_module, "get_agent_for_request", fake_get_agent)
    monkeypatch.setattr(config_module, "load_agent_config", fake_load_agent_config)
    monkeypatch.setattr(console_module, "save_media_blob", fake_save_media_blob)

    transport = httpx.ASGITransport(app=_build_app(console_module.router, state))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield SimpleNamespace(
            client=client,
            state=state,
            workspace=workspace,
            chat_manager=chat_manager,
            channel_media=channel_media,
            workspace_dir=workspace_dir,
            saved=saved,
        )


# ═══════════════════════════════ helpers ═══════════════════════════════════


async def _create_workspace(env, dir_path, *, name: str = "我的空间", create: bool = False):
    return await env.client.post(
        "/workspaces",
        json={"name": name, "dir_path": str(dir_path), "create": create},
    )


def _use_workspace(env, chat_manager, workspace_dir=None):
    env.state["workspace"] = FakeAgentWorkspace(
        chat_manager=chat_manager,
        workspace_dir=workspace_dir,
    )


async def _listing(env, include_chats: bool = False) -> dict:
    resp = await env.client.get(
        "/workspaces",
        params={"include_chats": "true"} if include_chats else None,
    )
    assert resp.status_code == 200
    return resp.json()


async def _upload(env, *, chat_id: str | None = None, content: bytes = b"png-bytes"):
    data = {} if chat_id is None else {"chat_id": chat_id}
    return await env.client.post(
        "/console/upload",
        files={"file": ("shot.png", content, "image/png")},
        data=data,
    )


# ═════════════════════════════ workspaces CRUD ═════════════════════════════


async def test_create_registers_existing_dir(ws_env, tmp_path):
    target = tmp_path / "proj"
    target.mkdir()

    resp = await _create_workspace(ws_env, target, name="项目甲")
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "项目甲"
    assert Path(body["dir_path"]) == target.resolve()

    listing = await _listing(ws_env)
    assert [w["name"] for w in listing["workspaces"]] == ["项目甲"]
    assert listing["unbound_chats"] == []


async def test_create_missing_dir_with_flag_creates_it(ws_env, tmp_path):
    target = tmp_path / "deep" / "nested"

    resp = await _create_workspace(ws_env, target, create=True)
    assert resp.status_code == 201
    assert target.is_dir()


async def test_create_missing_dir_without_flag_400(ws_env, tmp_path):
    resp = await _create_workspace(ws_env, tmp_path / "ghost")
    assert resp.status_code == 400
    assert "does not exist" in resp.json()["detail"]


async def test_create_file_path_400(ws_env, tmp_path):
    target = tmp_path / "plain.txt"
    target.write_text("not a dir")

    resp = await _create_workspace(ws_env, target)
    assert resp.status_code == 400
    assert "not a directory" in resp.json()["detail"].lower()


async def test_create_duplicate_dir_409(ws_env, tmp_path):
    target = tmp_path / "dup"
    target.mkdir()

    assert (await _create_workspace(ws_env, target)).status_code == 201
    resp = await _create_workspace(ws_env, target, name="重复注册")
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]


async def test_create_rejects_system_root_403(ws_env):
    root = Path(Path.cwd().anchor)
    resp = await _create_workspace(ws_env, root)
    assert resp.status_code == 403


async def test_create_rejects_home_403(ws_env):
    resp = await _create_workspace(ws_env, "~")
    assert resp.status_code == 403
    assert "Home directory" in resp.json()["detail"]


async def test_rename_workspace(ws_env, tmp_path):
    target = tmp_path / "renamable"
    target.mkdir()
    ws = (await _create_workspace(ws_env, target)).json()

    resp = await ws_env.client.patch(
        f"/workspaces/{ws['id']}",
        json={"name": "新名字"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "新名字"
    assert body["dir_path"] == ws["dir_path"]  # display name only


async def test_rename_missing_404(ws_env):
    resp = await ws_env.client.patch(
        "/workspaces/nonexistent",
        json={"name": "x"},
    )
    assert resp.status_code == 404


async def test_delete_unbinds_chats_and_keeps_disk(ws_env, tmp_path):
    target = tmp_path / "keep-on-disk"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    chat = make_chat("绑定任务", owner="alice", project_dir=ws["dir_path"])
    mgr = FakeChatManager()
    mgr.add(chat)
    _use_workspace(ws_env, mgr, workspace_dir=tmp_path / "fallback")

    resp = await ws_env.client.delete(f"/workspaces/{ws['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "unbound_chats": 1}

    assert target.is_dir()  # 磁盘目录绝不删除
    assert "project_dir" not in mgr.chats[chat.id].meta.get("runtime_context", {})
    listing = await _listing(ws_env)
    assert listing["workspaces"] == []


# ═══════════════════════════ ownership isolation ═══════════════════════════


async def test_owner_isolation_404(ws_env, tmp_path):
    target = tmp_path / "only-alice"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    ws_env.state["user"] = "bob"
    listing = await _listing(ws_env)
    assert listing["workspaces"] == []

    resp = await ws_env.client.patch(
        f"/workspaces/{ws['id']}",
        json={"name": "hijack"},
    )
    assert resp.status_code == 404  # never 403: existence stays hidden
    assert (await ws_env.client.delete(f"/workspaces/{ws['id']}")).status_code == 404
    resp = await ws_env.client.put(
        f"/workspaces/{ws['id']}/chats",
        json={"chat_ids": []},
    )
    assert resp.status_code == 404

    # A different owner may register the same directory: the unique key
    # is (tenant, owner, dir_path).
    resp = await _create_workspace(ws_env, target, name="bob 的空间")
    assert resp.status_code == 201


# ═══════════════════════════ bind / unbind ═════════════════════════════════


async def test_bind_unbind_persists_meta(ws_env, tmp_path):
    target = tmp_path / "docs"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    chat = make_chat("任务A", owner="alice")
    mgr = FakeChatManager()
    mgr.add(chat)
    _use_workspace(ws_env, mgr, workspace_dir=tmp_path / "fallback")

    resp = await ws_env.client.put(
        f"/workspaces/{ws['id']}/chats",
        json={"chat_ids": [chat.id]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"bound": 1}
    assert (
        mgr.chats[chat.id].meta["runtime_context"]["project_dir"]
        == ws["dir_path"]
    )

    listing = await _listing(ws_env, include_chats=True)
    assert listing["workspaces"][0]["chats_count"] == 1
    assert [c["id"] for c in listing["workspaces"][0]["chats"]] == [chat.id]
    assert listing["unbound_chats"] == []

    resp = await ws_env.client.delete(f"/workspaces/{ws['id']}/chats/{chat.id}")
    assert resp.status_code == 200
    assert resp.json() == {"unbound": True}
    assert "project_dir" not in mgr.chats[chat.id].meta.get("runtime_context", {})

    listing = await _listing(ws_env, include_chats=True)
    assert listing["workspaces"][0]["chats_count"] == 0
    assert [c["id"] for c in listing["unbound_chats"]] == [chat.id]


async def test_bind_foreign_chat_silently_dropped(ws_env, tmp_path):
    target = tmp_path / "alice-only"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    bob_chat = make_chat("bob 的任务", owner="bob")
    mgr = FakeChatManager()
    mgr.add(bob_chat)
    _use_workspace(ws_env, mgr, workspace_dir=tmp_path / "fallback")

    resp = await ws_env.client.put(
        f"/workspaces/{ws['id']}/chats",
        json={"chat_ids": [bob_chat.id]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"bound": 0}
    assert "runtime_context" not in bob_chat.meta


async def test_bind_running_chat_409(ws_env, tmp_path):
    target = tmp_path / "busy-bind"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    chat = make_chat("运行中", owner="alice", status="running")
    mgr = FakeChatManager()
    mgr.add(chat)
    _use_workspace(ws_env, mgr, workspace_dir=tmp_path / "fallback")

    resp = await ws_env.client.put(
        f"/workspaces/{ws['id']}/chats",
        json={"chat_ids": [chat.id]},
    )
    assert resp.status_code == 409
    assert "in progress" in resp.json()["detail"]


async def test_unbind_running_chat_409(ws_env, tmp_path):
    target = tmp_path / "busy-unbind"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    chat = make_chat("运行中", owner="alice", status="running")
    mgr = FakeChatManager()
    mgr.add(chat)
    _use_workspace(ws_env, mgr, workspace_dir=tmp_path / "fallback")

    resp = await ws_env.client.delete(f"/workspaces/{ws['id']}/chats/{chat.id}")
    assert resp.status_code == 409


# ═══════════════════════ sidebar grouping (server-side) ═════════════════════


async def test_grouping_separates_and_orders(ws_env, tmp_path):
    target = tmp_path / "grouped"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    mgr = FakeChatManager()
    bound_older = mgr.add(
        make_chat("空间内旧", owner="alice", project_dir=ws["dir_path"], age_seconds=90),
    )
    unbound_newest = mgr.add(make_chat("无目录最新", owner="alice", age_seconds=0))
    stranger_dir = mgr.add(
        make_chat(
            "其他目录",
            owner="alice",
            project_dir=str(tmp_path / "elsewhere"),
            age_seconds=30,
        ),
    )
    unbound_older = mgr.add(make_chat("无目录较旧", owner="alice", age_seconds=60))
    _use_workspace(ws_env, mgr, workspace_dir=tmp_path / "fallback")

    listing = await _listing(ws_env, include_chats=True)

    assert listing["workspaces"][0]["chats_count"] == 1
    assert [c["id"] for c in listing["workspaces"][0]["chats"]] == [
        bound_older.id,
    ]
    # updated_at desc: newest first, regardless of project_dir presence
    assert [c["id"] for c in listing["unbound_chats"]] == [
        unbound_newest.id,
        stranger_dir.id,
        unbound_older.id,
    ]

    # include_chats=false stays lightweight: no chat_manager round-trip,
    # so no chats array and the count stays an unused 0 placeholder (the
    # sidebar's only consumption path is includeChats=true).
    plain = await _listing(ws_env)
    assert plain["workspaces"][0]["chats_count"] == 0
    assert "chats" not in plain["workspaces"][0]
    assert plain["unbound_chats"] == []


@pytest.mark.skipif(os.name != "nt", reason="case folding is Windows normcase")
async def test_grouping_windows_case_fold(ws_env, tmp_path):
    target = tmp_path / "casedir"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    # Same directory typed with swapped case: os.path.normcase folds it.
    variant = ws["dir_path"].swapcase()
    chat = make_chat("大小写变体", owner="alice", project_dir=variant)
    mgr = FakeChatManager()
    mgr.add(chat)
    _use_workspace(ws_env, mgr, workspace_dir=tmp_path / "fallback")

    listing = await _listing(ws_env, include_chats=True)
    assert [c["id"] for c in listing["workspaces"][0]["chats"]] == [chat.id]
    assert listing["unbound_chats"] == []


# ══════════════════════════════ open folder ════════════════════════════════


async def test_open_folder_opens(ws_env, tmp_path, monkeypatch):
    target = tmp_path / "openme"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()

    opened: list = []
    if sys.platform == "win32":
        monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    else:
        monkeypatch.setattr(
            ws_module.subprocess,
            "run",
            lambda *args, **kwargs: opened.append(args),
        )

    resp = await ws_env.client.post(f"/workspaces/{ws['id']}/open-folder")
    assert resp.status_code == 200
    assert resp.json() == {"opened": True, "path": ws["dir_path"]}
    assert opened and ws["dir_path"] in str(opened[0])


async def test_open_folder_missing_dir_409(ws_env, tmp_path):
    target = tmp_path / "vanishing"
    target.mkdir()
    ws_env.state["user"] = "alice"
    ws = (await _create_workspace(ws_env, target)).json()
    target.rmdir()  # user removed it on disk after registering

    resp = await ws_env.client.post(f"/workspaces/{ws['id']}/open-folder")
    assert resp.status_code == 409
    assert "Directory missing" in resp.json()["detail"]


# ══════════════════════ console upload: chat_id landing ═════════════════════


async def test_upload_without_chat_id_legacy_behavior(upload_env):
    resp = await _upload(upload_env)
    assert resp.status_code == 200
    body = resp.json()

    # Legacy contract: bare stored_name + channel media_dir landing.
    assert body["url"] == body["stored_name"]
    assert (upload_env.channel_media / body["stored_name"]).is_file()
    assert (upload_env.channel_media / body["stored_name"]).read_bytes() == b"png-bytes"

    # PG media_files double-write still happens (durable recall copy).
    assert upload_env.saved and upload_env.saved[0]["stored_name"] == body["stored_name"]
    assert upload_env.saved[0]["data"] == b"png-bytes"


async def test_upload_with_bound_chat_lands_in_workspace(upload_env):
    ws_dir = upload_env.workspace_dir / "d-workspace"
    chat = make_chat("绑定会话", project_dir=str(ws_dir))
    upload_env.chat_manager.add(chat)

    resp = await _upload(upload_env, chat_id=chat.id)
    assert resp.status_code == 200
    body = resp.json()

    expected = (ws_dir / "media" / body["stored_name"]).resolve()
    assert expected.is_file()
    assert expected.read_bytes() == b"png-bytes"
    # Absolute file:// URI: the channel ref resolver skips "://" texts.
    assert "://" in body["url"]
    assert body["url"] == expected.as_uri()
    assert upload_env.saved and upload_env.saved[0]["stored_name"] == body["stored_name"]


async def test_upload_with_chat_without_binding_uses_workspace_dir(upload_env):
    chat = make_chat("无绑定会话")
    upload_env.chat_manager.add(chat)

    resp = await _upload(upload_env, chat_id=chat.id)
    assert resp.status_code == 200
    body = resp.json()

    # resolve_effective_project_dir falls back to the agent workspace.
    expected = (upload_env.workspace_dir / "media" / body["stored_name"]).resolve()
    assert expected.is_file()
    assert body["url"] == expected.as_uri()


async def test_upload_unknown_chat_404(upload_env):
    resp = await _upload(upload_env, chat_id="no-such-chat")
    assert resp.status_code == 404


async def test_upload_foreign_chat_404(upload_env):
    upload_env.state["user"] = "alice"
    bob_chat = make_chat("bob 的会话", owner="bob")
    upload_env.chat_manager.add(bob_chat)

    resp = await _upload(upload_env, chat_id=bob_chat.id)
    assert resp.status_code == 404  # never 403: existence stays hidden
