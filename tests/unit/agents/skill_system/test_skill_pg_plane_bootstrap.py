# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access  # noqa: E501
"""Skill PG plane bootstrap unit tests (backfill/reconcile/bindings).

换环境恢复闭环的纯单测（不连真实 PG）：
- ``purge_pool_skill_pg``：删除路径同步清理三行（catalog/池快照/级联绑定）；
- ``schedule_pool_skill_sync`` 的 ``i18n_manual`` 回填拦截（人工清空可持久化）；
- ``_restore_pool_manifest_entry``：快照自愈后回写池 manifest（缺条目才写）；
- ``reconcile_agent_bindings_pg``：员工绑定 → manifest 恢复 + 私有技能物化；
- ``run_skill_plane_bootstrap``：阶段顺序与 json 后端零动作。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from qwenpaw.agents.skill_system import catalog_store
from qwenpaw.agents.skill_system import registry as skill_registry
from qwenpaw.agents.skill_system import store as skill_store
from qwenpaw.db import backfill_skill_catalog


def _write_skill_dir(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\nbody\n",
        encoding="utf-8",
    )


def _enable_pg_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the dual backend + DSN so the plane believes PG is usable."""
    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
    monkeypatch.setenv(
        "QWENPAW_PG_DSN",
        "postgresql+asyncpg://u:p@localhost:5432/db",
    )
    from qwenpaw.db import write_gateway

    write_gateway.reset_backend_cache()


def _disable_pg_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    from qwenpaw.db import write_gateway

    write_gateway.reset_backend_cache()


# ------------------------------------------------------------------ #
# purge_pool_skill_pg：删除路径同步清理
# ------------------------------------------------------------------ #


def test_purge_pool_skill_pg_removes_all_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []

    async def fake_catalog(name: str, engine: object = None) -> None:
        calls.append(("catalog", name))

    async def fake_snapshot(
        owner: str,
        name: str,
        engine: object = None,
    ) -> None:
        calls.append(("snapshot", owner, name))

    async def fake_bindings(name: str, engine: object = None) -> int:
        calls.append(("bindings", name))
        return 3

    monkeypatch.setattr(catalog_store, "delete_skill_catalog_pg", fake_catalog)
    monkeypatch.setattr(
        catalog_store,
        "delete_skill_snapshot_pg",
        fake_snapshot,
    )
    monkeypatch.setattr(
        catalog_store,
        "delete_bindings_for_skill_pg",
        fake_bindings,
    )

    removed = asyncio.run(catalog_store.purge_pool_skill_pg("demo"))

    assert removed == 3
    assert calls == [
        ("catalog", "demo"),
        ("snapshot", "", "demo"),
        ("bindings", "demo"),
    ]


# ------------------------------------------------------------------ #
# i18n_manual：人工编辑中文映射后不再自动回填
# ------------------------------------------------------------------ #


def test_schedule_pool_skill_sync_respects_i18n_manual(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_pg_plane(monkeypatch)

    ops: list = []
    monkeypatch.setattr(catalog_store, "_schedule", lambda op: ops.append(op))

    upserted: list[dict] = []

    async def fake_upsert(row: dict, engine: object = None) -> None:
        upserted.append(row)

    monkeypatch.setattr(catalog_store, "upsert_skill_catalog_pg", fake_upsert)
    monkeypatch.setattr(
        catalog_store,
        "extract_zh_i18n",
        lambda name: {"display_name_zh": "自动名", "description_zh": "自动述"},
    )

    # 人工编辑标记：zh 被清空后不得被 -zh 变体自动回填
    catalog_store.schedule_pool_skill_sync(
        "demo",
        {"source": "builtin", "display_name_zh": "", "i18n_manual": True},
        None,
    )
    asyncio.run(ops[-1]())
    assert upserted[-1]["display_name_zh"] == ""

    # 无标记：维持自动回填行为
    catalog_store.schedule_pool_skill_sync(
        "demo",
        {"source": "builtin", "display_name_zh": ""},
        None,
    )
    asyncio.run(ops[-1]())
    assert upserted[-1]["display_name_zh"] == "自动名"
    assert upserted[-1]["description_zh"] == "自动述"


# ------------------------------------------------------------------ #
# _restore_pool_manifest_entry：自愈后回写池 manifest
# ------------------------------------------------------------------ #


def _base_catalog_row(name: str) -> dict:
    return {
        "skill_name": name,
        "source": "customized",
        "installed_from": "github",
        "source_url": "https://example.com/s",
        "version_text": "1.0.0",
        "emoji": "",
        "builtin_language": "",
        "tags": ["t"],
        "config": {},
        "automation": {},
        "external": False,
        "external_path": "",
        "content_hash": "h",
        "display_name_zh": "",
        "description_zh": "",
        "protected": False,
    }


def _seed_pool_manifest(manifest_path: Path, skills: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "skill-pool-manifest.v1",
                "version": 0,
                "skills": skills,
                "builtin_skill_names": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_restore_pool_manifest_entry_writes_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = tmp_path / "pool" / "demo"
    _write_skill_dir(skill_dir, "demo")
    manifest_path = tmp_path / "skill.json"
    _seed_pool_manifest(manifest_path, {})
    monkeypatch.setattr(
        skill_store,
        "get_pool_skill_manifest_path",
        lambda: manifest_path,
    )
    monkeypatch.setattr(
        skill_store,
        "resolve_pool_skill_dir",
        lambda name: skill_dir,
    )

    assert (
        backfill_skill_catalog._restore_pool_manifest_entry(
            _base_catalog_row("demo"),
        )
        is True
    )

    entry = json.loads(manifest_path.read_text(encoding="utf-8"))["skills"][
        "demo"
    ]
    assert entry["source"] == "customized"
    assert entry["installed_from"] == "github"
    assert entry["version_text"] == "1.0.0"
    assert entry["tags"] == ["t"]
    assert entry["metadata"]  # 从物化目录重建的描述性元数据


def test_restore_pool_manifest_entry_keeps_existing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = tmp_path / "pool" / "demo"
    _write_skill_dir(skill_dir, "demo")
    manifest_path = tmp_path / "skill.json"
    existing = {"source": "customized", "keep": True}
    _seed_pool_manifest(manifest_path, {"demo": existing})
    monkeypatch.setattr(
        skill_store,
        "get_pool_skill_manifest_path",
        lambda: manifest_path,
    )
    monkeypatch.setattr(
        skill_store,
        "resolve_pool_skill_dir",
        lambda name: skill_dir,
    )

    assert (
        backfill_skill_catalog._restore_pool_manifest_entry(
            _base_catalog_row("demo"),
        )
        is False
    )
    entry = json.loads(manifest_path.read_text(encoding="utf-8"))["skills"][
        "demo"
    ]
    assert entry == existing  # 文件为准，绝不覆盖


# ------------------------------------------------------------------ #
# reconcile_agent_bindings_pg：绑定恢复 + 私有技能物化
# ------------------------------------------------------------------ #


def test_reconcile_agent_bindings_restores_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_pg_plane(monkeypatch)

    ws_dir = tmp_path / "workspaces" / "a1"
    ws_dir.mkdir(parents=True)
    monkeypatch.setattr(
        skill_registry,
        "list_workspaces",
        lambda: [{"agent_id": "a1", "workspace_dir": str(ws_dir)}],
    )

    pool_dir = tmp_path / "pool" / "doc"
    _write_skill_dir(pool_dir, "doc")
    monkeypatch.setattr(
        skill_store,
        "resolve_pool_skill_dir",
        lambda name: pool_dir if name == "doc" else None,
    )

    private_src = tmp_path / "private_body"
    _write_skill_dir(private_src, "my_skill")
    content_zip = catalog_store.pack_skill_dir_zip(private_src)
    assert content_zip is not None

    async def fake_bindings(
        agent_id: str,
        engine: object = None,
    ) -> dict:
        return {
            "doc": {
                "origin": "pool",
                "enabled": True,
                "channels": ["all"],
                "config": {},
                "tags": None,
            },
            "my_skill": {
                "origin": "private",
                "enabled": True,
                "channels": ["console"],
                "config": {"K": "V"},
                "tags": None,
            },
        }

    async def fake_snapshot(
        owner: str,
        name: str,
        engine: object = None,
    ) -> dict:
        return {"content_zip": content_zip, "content_hash": "h"}

    monkeypatch.setattr(
        catalog_store,
        "load_agent_bindings_pg",
        fake_bindings,
    )
    monkeypatch.setattr(
        catalog_store,
        "load_skill_snapshot_pg",
        fake_snapshot,
    )

    stats = asyncio.run(backfill_skill_catalog.reconcile_agent_bindings_pg())

    assert stats["restored"] == 2
    assert stats["materialized"] == 1
    assert stats["skipped"] == 0

    payload = json.loads(
        (ws_dir / "skill.json").read_text(encoding="utf-8"),
    )
    restored = payload["skills"]
    assert restored["doc"]["origin"] == "pool"
    assert restored["doc"]["source"] == "customized"
    assert restored["doc"]["enabled"] is True
    assert restored["my_skill"]["origin"] == "private"
    assert restored["my_skill"]["channels"] == ["console"]
    assert restored["my_skill"]["config"] == {"K": "V"}
    # 私有技能体必须物化，否则运行时 _skill_dir_resolvable 失败
    assert (ws_dir / "skills" / "my_skill" / "SKILL.md").exists()


def test_reconcile_agent_bindings_keeps_existing_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_pg_plane(monkeypatch)

    ws_dir = tmp_path / "workspaces" / "a1"
    ws_dir.mkdir(parents=True)
    (ws_dir / "skill.json").write_text(
        json.dumps(
            {
                "schema_version": "workspace-skill-manifest.v1",
                "version": 0,
                "skills": {
                    "doc": {"source": "customized", "enabled": False},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        skill_registry,
        "list_workspaces",
        lambda: [{"agent_id": "a1", "workspace_dir": str(ws_dir)}],
    )

    async def fake_bindings(
        agent_id: str,
        engine: object = None,
    ) -> dict:
        return {
            "doc": {
                "origin": "pool",
                "enabled": True,
                "channels": ["all"],
                "config": {},
                "tags": None,
            },
        }

    monkeypatch.setattr(
        catalog_store,
        "load_agent_bindings_pg",
        fake_bindings,
    )

    stats = asyncio.run(backfill_skill_catalog.reconcile_agent_bindings_pg())

    assert stats["restored"] == 0
    payload = json.loads(
        (ws_dir / "skill.json").read_text(encoding="utf-8"),
    )
    # 文件为准：已有条目的 enabled=False 不被 PG 行覆盖
    assert payload["skills"]["doc"]["enabled"] is False


# ------------------------------------------------------------------ #
# run_skill_plane_bootstrap：阶段顺序 + json 零动作
# ------------------------------------------------------------------ #


def test_run_skill_plane_bootstrap_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_pg_plane(monkeypatch)

    order: list[str] = []

    async def fake_backfill() -> dict:
        order.append("backfill")
        return {}

    async def fake_reconcile() -> dict:
        order.append("reconcile")
        return {}

    async def fake_bindings() -> dict:
        order.append("bindings")
        return {}

    async def fake_dedupe(**kwargs: object) -> dict:
        order.append("dedupe")
        return {}

    monkeypatch.setattr(
        backfill_skill_catalog,
        "backfill_skill_catalog_pg",
        fake_backfill,
    )
    monkeypatch.setattr(
        backfill_skill_catalog,
        "reconcile_skill_catalog_pg",
        fake_reconcile,
    )
    monkeypatch.setattr(
        backfill_skill_catalog,
        "reconcile_agent_bindings_pg",
        fake_bindings,
    )
    monkeypatch.setattr(
        backfill_skill_catalog,
        "dedupe_workspace_skill_copies",
        fake_dedupe,
    )

    result = asyncio.run(backfill_skill_catalog.run_skill_plane_bootstrap())

    assert order == ["backfill", "reconcile", "bindings", "dedupe"]
    assert set(result) == {"backfill", "reconcile", "bindings", "dedupe"}


def test_run_skill_plane_bootstrap_json_backend_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_pg_plane(monkeypatch)
    assert asyncio.run(backfill_skill_catalog.run_skill_plane_bootstrap()) == {}
