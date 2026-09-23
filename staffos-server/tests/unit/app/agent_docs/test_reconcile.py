# -*- coding: utf-8 -*-
"""Unit tests for agent docs startup reconciliation (Phase B)."""
# pylint: disable=protected-access
from pathlib import Path

import pytest

from qwenpaw.app.agent_docs import reconcile as agent_docs_reconcile
from qwenpaw.app.agent_docs.store import content_hash


class _MemStore:
    """内存版档案存储（get_document/upsert_document 协议）。"""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}

    async def get_document(self, agent_id, doc_type, *, environment=None):
        return self.rows.get((agent_id, doc_type))

    async def upsert_document(
        self,
        agent_id,
        doc_type,
        content,
        *,
        environment=None,
        updated_by=None,
    ):
        key = (agent_id, doc_type)
        chash = content_hash(content)
        if key in self.rows and self.rows[key]["content_hash"] == chash:
            return False
        self.rows[key] = {
            "agent_id": agent_id,
            "doc_type": doc_type,
            "environment": environment or "production",
            "content": content,
            "content_hash": chash,
            "version": self.rows.get(key, {}).get("version", 0) + 1,
        }
        return True


class _FakeRef:
    def __init__(self, workspace_dir: str) -> None:
        self.workspace_dir = workspace_dir


class _FakeAgentsConfig:
    def __init__(self, profiles: dict) -> None:
        self.profiles = profiles


class _FakeConfig:
    def __init__(self, profiles: dict) -> None:
        self.agents = _FakeAgentsConfig(profiles)


def _make_workspace(root: Path, agent_id: str, files: dict[str, str]) -> Path:
    workspace_dir = root / agent_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (workspace_dir / name).write_text(content, encoding="utf-8")
    return workspace_dir


@pytest.fixture
def reconcile_env(monkeypatch, tmp_path):
    """内存 store + 假配置 + tmp 工作区的对账环境。"""
    store = _MemStore()

    def _install(profiles: dict) -> None:
        monkeypatch.setattr(
            agent_docs_reconcile,
            "get_agent_docs_store",
            lambda: store,
        )
        monkeypatch.setattr(
            "qwenpaw.config.utils.load_config",
            lambda: _FakeConfig(profiles),
        )

    return store, _install, tmp_path


@pytest.mark.asyncio
async def test_reconcile_promotes_file_seed_to_pg(reconcile_env) -> None:
    """PG 无行 & 文件存在 → 回填种子（幂等 upsert）。"""
    store, install, tmp_path = reconcile_env
    ws = _make_workspace(
        tmp_path,
        "analyst",
        {"PROFILE.md": "# seed"},
    )
    install({"analyst": _FakeRef(str(ws))})

    stats = await agent_docs_reconcile.reconcile_agent_docs()
    assert stats["promote"] == 1
    assert store.rows[("analyst", "profile")]["content"] == "# seed"
    # 重复对账：内容一致 → 全部 skip（幂等）
    stats2 = await agent_docs_reconcile.reconcile_agent_docs()
    assert stats2["promote"] == 0
    assert stats2["skip"] == 4


@pytest.mark.asyncio
async def test_reconcile_pg_authority_overwrites_drifted_file(
    reconcile_env,
) -> None:
    """PG 有行 & 文件漂移 → 以 PG 覆盖文件（权威裁决）。"""
    store, install, tmp_path = reconcile_env
    ws = _make_workspace(tmp_path, "analyst", {"PROFILE.md": "# drifted"})
    store.rows[("analyst", "profile")] = {
        "content": "# authority",
        "content_hash": content_hash("# authority"),
    }
    install({"analyst": _FakeRef(str(ws))})

    stats = await agent_docs_reconcile.reconcile_agent_docs()
    assert stats["overwrite"] == 1
    assert (ws / "PROFILE.md").read_text(encoding="utf-8") == "# authority"


@pytest.mark.asyncio
async def test_reconcile_restores_missing_file_from_pg(reconcile_env) -> None:
    """PG 有行 & 文件缺失 → 以 PG 重建物化缓存（restore）。"""
    store, install, tmp_path = reconcile_env
    ws = _make_workspace(tmp_path, "analyst", {})
    store.rows[("analyst", "profile")] = {
        "content": "# cached",
        "content_hash": content_hash("# cached"),
    }
    install({"analyst": _FakeRef(str(ws))})

    stats = await agent_docs_reconcile.reconcile_agent_docs()
    assert stats["restore"] == 1
    assert (ws / "PROFILE.md").read_text(encoding="utf-8") == "# cached"


@pytest.mark.asyncio
async def test_reconcile_isolates_single_document_failure(
    reconcile_env,
    monkeypatch,
) -> None:
    """单文档异常隔离：其余文档对账继续，不阻断整体。"""
    store, install, tmp_path = reconcile_env
    ws = _make_workspace(tmp_path, "analyst", {"PROFILE.md": "# a"})
    install({"analyst": _FakeRef(str(ws))})

    original_get = _MemStore.get_document

    async def _boom(self, agent_id, doc_type, *, environment=None):
        if doc_type == "agents":
            raise RuntimeError("pg unavailable")
        return await original_get(self, agent_id, doc_type, environment=environment)

    monkeypatch.setattr(_MemStore, "get_document", _boom)

    stats = await agent_docs_reconcile.reconcile_agent_docs()
    # agents 文档异常被隔离，PROFILE.md 仍完成回填，其余 skip
    assert stats["promote"] == 1
    assert store.rows[("analyst", "profile")]["content"] == "# a"


@pytest.mark.asyncio
async def test_reconcile_noop_without_pg(monkeypatch) -> None:
    """无 PG（store 为 None）时静默返回空统计。"""
    monkeypatch.setattr(
        agent_docs_reconcile,
        "get_agent_docs_store",
        lambda: None,
    )
    assert await agent_docs_reconcile.reconcile_agent_docs() == {}
