# -*- coding: utf-8 -*-
"""Unit tests for expert identity startup reconciliation (T14)."""
# pylint: disable=protected-access
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.agent_docs import reconcile as agent_docs_reconcile


class _FakeExpertStore:
    """list_experts 协议的最小假 store。"""

    def __init__(self, records) -> None:
        self.records = records
        self.status_seen = None

    async def list_experts(self, status=None, **_kwargs):
        self.status_seen = status
        return self.records


class _BrokenExpertStore:
    """查询即抛错的假 store（模拟 schema 未就绪）。"""

    async def list_experts(self, status=None, **_kwargs):
        raise RuntimeError("enterprise schema pending")


def _record(expert_id="e1", name="分析师", description="分析专家"):
    return SimpleNamespace(id=expert_id, name=name, description=description)


def _write_agent_json(root: Path, expert_id: str, payload: dict) -> Path:
    ws = root / expert_id
    ws.mkdir(parents=True, exist_ok=True)
    path = ws / "agent.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _install_env(monkeypatch, tmp_path, records, store=None):
    store = store or _FakeExpertStore(records)
    monkeypatch.setattr(
        agent_docs_reconcile,
        "enterprise_engine",
        lambda: object(),
    )
    monkeypatch.setattr(
        agent_docs_reconcile,
        "get_expert_store",
        lambda: store,
    )
    monkeypatch.setattr(
        agent_docs_reconcile,
        "_expert_workspace_dir",
        lambda expert_id: tmp_path / expert_id,
    )
    return store


def _install_fake_mutate(monkeypatch, tmp_path, *, fail_for=()):
    """假 mutate_agent_config：内存改身份列并写回 agent.json。"""
    calls: list[str] = []

    def fake_mutate(agent_id, mutator):
        calls.append(agent_id)
        if agent_id in fail_for:
            raise RuntimeError("config store unavailable")
        expert_id = agent_id.removeprefix("expert_")
        path = tmp_path / expert_id / "agent.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        obj = SimpleNamespace(
            id=data.get("id"),
            name=data.get("name"),
            description=data.get("description"),
        )
        mutator(obj)
        data["id"] = obj.id
        data["name"] = obj.name
        data["description"] = obj.description
        path.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "qwenpaw.config.config.mutate_agent_config",
        fake_mutate,
    )
    return calls


@pytest.mark.asyncio
async def test_clean_identity_no_repair(monkeypatch, tmp_path) -> None:
    """agent.json 身份列与 experts 一致 → clean，零写入。"""
    _install_env(monkeypatch, tmp_path, [_record()])
    _write_agent_json(
        tmp_path,
        "e1",
        {"id": "expert_e1", "name": "分析师", "description": "分析专家"},
    )
    calls = _install_fake_mutate(monkeypatch, tmp_path)

    stats = await agent_docs_reconcile.reconcile_expert_identities()

    assert stats == {
        "experts": 1,
        "clean": 1,
        "repaired": 0,
        "skipped": 0,
        "failed": 0,
    }
    assert calls == []


@pytest.mark.asyncio
async def test_empty_description_normalized(monkeypatch, tmp_path) -> None:
    """专家 description 空串与 agent.json 缺省归一，不误报漂移。"""
    _install_env(monkeypatch, tmp_path, [_record(description="")])
    _write_agent_json(tmp_path, "e1", {"id": "expert_e1", "name": "分析师"})
    calls = _install_fake_mutate(monkeypatch, tmp_path)

    stats = await agent_docs_reconcile.reconcile_expert_identities()

    assert stats["clean"] == 1
    assert calls == []


@pytest.mark.asyncio
async def test_drift_repaired_with_warning(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    """id/name/description 漂移 → WARN + 以 experts 为准修复（幂等）。"""
    _install_env(monkeypatch, tmp_path, [_record()])
    path = _write_agent_json(
        tmp_path,
        "e1",
        {"id": "expert_other", "name": "旧名", "description": "旧简介"},
    )
    calls = _install_fake_mutate(monkeypatch, tmp_path)

    with caplog.at_level("WARNING"):
        stats = await agent_docs_reconcile.reconcile_expert_identities()

    assert stats["repaired"] == 1
    assert calls == ["expert_e1"]
    repaired_payload = json.loads(path.read_text(encoding="utf-8"))
    assert repaired_payload["id"] == "expert_e1"
    assert repaired_payload["name"] == "分析师"
    assert repaired_payload["description"] == "分析专家"
    assert any(
        "identity drift repaired" in record.getMessage()
        for record in caplog.records
    )

    # 幂等：修复后再跑 → clean，零再写
    caplog.clear()
    again = await agent_docs_reconcile.reconcile_expert_identities()
    assert again["clean"] == 1
    assert again["repaired"] == 0
    assert calls == ["expert_e1"]


@pytest.mark.asyncio
async def test_missing_workspace_skipped(monkeypatch, tmp_path) -> None:
    """工作区/agent.json 缺失 → skipped，不触发修复。"""
    _install_env(monkeypatch, tmp_path, [_record()])
    calls = _install_fake_mutate(monkeypatch, tmp_path)

    stats = await agent_docs_reconcile.reconcile_expert_identities()

    assert stats["skipped"] == 1
    assert calls == []


@pytest.mark.asyncio
async def test_corrupt_json_failed_without_repair(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    """agent.json 不可解析 → failed + WARN，不进入修复。"""
    _install_env(monkeypatch, tmp_path, [_record()])
    ws = tmp_path / "e1"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "agent.json").write_text("{not json", encoding="utf-8")
    calls = _install_fake_mutate(monkeypatch, tmp_path)

    with caplog.at_level("WARNING"):
        stats = await agent_docs_reconcile.reconcile_expert_identities()

    assert stats["failed"] == 1
    assert calls == []
    assert any(
        "cannot read agent.json" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_repair_failure_isolated(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    """修复异常 → failed + WARN；其余专家照常修复。"""
    _install_env(
        monkeypatch,
        tmp_path,
        [_record("e1"), _record("e2", name="N2", description="D2")],
    )
    _write_agent_json(
        tmp_path,
        "e1",
        {"id": "expert_e1", "name": "旧名", "description": "D"},
    )
    _write_agent_json(
        tmp_path,
        "e2",
        {"id": "expert_e2", "name": "旧名", "description": "D"},
    )
    calls = _install_fake_mutate(
        monkeypatch,
        tmp_path,
        fail_for={"expert_e1"},
    )

    with caplog.at_level("WARNING"):
        stats = await agent_docs_reconcile.reconcile_expert_identities()

    assert stats["failed"] == 1
    assert stats["repaired"] == 1
    assert sorted(calls) == ["expert_e1", "expert_e2"]
    assert any(
        "repair failed" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_only_published_experts_scanned(monkeypatch, tmp_path) -> None:
    """扫描以 status=published 过滤（draft/archived 不参与）。"""
    store = _install_env(monkeypatch, tmp_path, [])
    _install_fake_mutate(monkeypatch, tmp_path)

    await agent_docs_reconcile.reconcile_expert_identities()

    assert store.status_seen == "published"


@pytest.mark.asyncio
async def test_noop_without_pg(monkeypatch) -> None:
    """enterprise 平面不可用（无 DSN）→ 静默返回空 dict。"""
    monkeypatch.setattr(
        agent_docs_reconcile,
        "enterprise_engine",
        lambda: None,
    )
    called = False

    def _boom():
        nonlocal called
        called = True
        raise AssertionError("store must not be touched")

    monkeypatch.setattr(agent_docs_reconcile, "get_expert_store", _boom)

    assert await agent_docs_reconcile.reconcile_expert_identities() == {}
    assert called is False


@pytest.mark.asyncio
async def test_store_unavailable_returns_empty(
    monkeypatch,
    tmp_path,
    caplog,
) -> None:
    """store 查询异常（schema 未就绪等）→ WARN + 空 dict。"""
    _install_env(
        monkeypatch,
        tmp_path,
        [],
        store=_BrokenExpertStore(),
    )

    with caplog.at_level("WARNING"):
        stats = await agent_docs_reconcile.reconcile_expert_identities()

    assert stats == {}
    assert any(
        "store unavailable" in record.getMessage()
        for record in caplog.records
    )
