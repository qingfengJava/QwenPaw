# -*- coding: utf-8 -*-
"""Unit tests for the skill PG catalog plane (catalog_store).

三态行为矩阵（json 零动作 / dual 影子 / pg 权威）+ manifest→row 字段
映射完整性 + 快照 zip 打包/物化闭环。PG 不可用环境下所有调度函数
必须静默零动作（json 后端硬门槛）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.agents.skill_system import catalog_store


# ------------------------------------------------------------------ #
# row builders（逐字段映射，禁止部分拷贝）
# ------------------------------------------------------------------ #


def test_build_catalog_row_maps_all_fields() -> None:
    entry = {
        "source": "builtin",
        "installed_from": "github",
        "source_url": "https://example.com/skill",
        "version_text": "1.2.0",
        "emoji": "📄",
        "builtin_language": "zh",
        "tags": ["docs"],
        "config": {"ENV_A": "1"},
        "automation": {"auto_sync": {"enabled": True}},
        "external": False,
        "external_path": "",
        "display_name_zh": "文档读取",
        "description_zh": "读取并总结文本文件",
        "protected": True,
    }
    row = catalog_store.build_catalog_row("demo", entry, content_hash="abc")
    assert row["skill_name"] == "demo"
    assert row["source"] == "builtin"
    assert row["installed_from"] == "github"
    assert row["source_url"] == "https://example.com/skill"
    assert row["version_text"] == "1.2.0"
    assert row["emoji"] == "📄"
    assert row["builtin_language"] == "zh"
    assert row["tags"] == ["docs"]
    assert row["config"] == {"ENV_A": "1"}
    assert row["automation"] == {"auto_sync": {"enabled": True}}
    assert row["external"] is False
    assert row["content_hash"] == "abc"
    assert row["display_name_zh"] == "文档读取"
    assert row["description_zh"] == "读取并总结文本文件"
    assert row["protected"] is True


def test_build_catalog_row_defaults_for_missing_keys() -> None:
    row = catalog_store.build_catalog_row("bare", {"source": "customized"})
    assert row["tags"] == []
    assert row["config"] == {}
    assert row["automation"] == {}
    assert row["display_name_zh"] == ""
    assert row["description_zh"] == ""
    assert row["content_hash"] == ""
    assert row["external"] is False


def test_build_binding_row_maps_fields() -> None:
    entry = {
        "enabled": False,
        "channels": ["console"],
        "config": {"K": "V"},
        "tags": ["t1"],
    }
    row = catalog_store.build_binding_row("demo", entry, origin="pool")
    assert row["skill_name"] == "demo"
    assert row["origin"] == "pool"
    assert row["enabled"] is False
    assert row["channels"] == ["console"]
    assert row["config"] == {"K": "V"}
    assert row["tags"] == ["t1"]


def test_build_binding_row_defaults() -> None:
    row = catalog_store.build_binding_row("demo", {}, origin="private")
    assert row["enabled"] is True
    assert row["channels"] == ["all"]
    assert row["config"] == {}
    assert row["tags"] is None


# ------------------------------------------------------------------ #
# 三态后端：json 零动作硬门槛
# ------------------------------------------------------------------ #


def test_json_backend_schedules_nothing(monkeypatch) -> None:
    """json（默认）后端下所有调度函数必须早退、零 PG 触碰。"""
    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
    monkeypatch.delenv("QWENPAW_PG_DSN", raising=False)
    # 重置统一写网关的后端缓存（M2 收敛后判定缓存位于 db.write_gateway）
    from qwenpaw.db import write_gateway

    write_gateway.reset_backend_cache()

    calls: list[str] = []

    def _spy_schedule(operation, *, domain="pg") -> None:  # noqa: ANN001
        calls.append("scheduled")

    monkeypatch.setattr(write_gateway, "submit_shadow_write", _spy_schedule)

    catalog_store.schedule_pool_skill_sync(
        "demo",
        {"source": "customized"},
        None,
    )
    catalog_store.schedule_pool_skill_delete("demo")
    catalog_store.schedule_agent_skill_sync("agent1", "demo", {})
    catalog_store.schedule_agent_skill_delete("agent1", "demo")
    assert calls == []
    assert catalog_store.skill_pg_plane_available() is False


def test_pg_plane_available_requires_dsn(monkeypatch) -> None:
    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "dual")
    monkeypatch.setenv("QWENPAW_PG_DSN", "")
    from qwenpaw.db import write_gateway

    write_gateway.reset_backend_cache()
    assert catalog_store.skill_pg_plane_available() is False

    monkeypatch.setenv(
        "QWENPAW_PG_DSN",
        "postgresql+asyncpg://u:p@localhost:5432/db",
    )
    write_gateway.reset_backend_cache()
    assert catalog_store.skill_pg_plane_available() is True


# ------------------------------------------------------------------ #
# 快照 zip 打包 / 物化闭环
# ------------------------------------------------------------------ #


def test_pack_and_materialize_roundtrip(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo_skill"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo_skill\ndescription: demo\n---\n\nbody\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")
    # OS 伪影必须被排除
    (skill_dir / "Thumbs.db").write_text("junk", encoding="utf-8")

    content_zip = catalog_store.pack_skill_dir_zip(skill_dir)
    assert content_zip is not None

    target = tmp_path / "restored" / "demo_skill"
    assert catalog_store.materialize_skill_from_zip(content_zip, target)
    assert (target / "SKILL.md").exists()
    assert (target / "scripts" / "run.py").exists()
    assert not (target / "Thumbs.db").exists()


def test_pack_missing_dir_returns_none(tmp_path: Path) -> None:
    assert catalog_store.pack_skill_dir_zip(tmp_path / "nope") is None


def test_materialize_rejects_zip_without_skill_md(tmp_path: Path) -> None:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("readme.txt", "no skill here")
    target = tmp_path / "restored"
    assert (
        catalog_store.materialize_skill_from_zip(buffer.getvalue(), target)
        is False
    )


# ------------------------------------------------------------------ #
# JSONB 防御性解析（脏数据绝不阻塞读路径）
# ------------------------------------------------------------------ #


def test_json_loads_defensive() -> None:
    assert catalog_store._json_loads(None, []) == []  # noqa: SLF001
    assert catalog_store._json_loads("[1]", []) == [1]  # noqa: SLF001
    assert catalog_store._json_loads("bad{", {"a": 1}) == {  # noqa: SLF001
        "a": 1,
    }
    assert catalog_store._json_loads({"x": 1}, {}) == {  # noqa: SLF001
        "x": 1,
    }


# ------------------------------------------------------------------ #
# zh i18n 提取（内置 -zh 变体；非内置返回空串）
# ------------------------------------------------------------------ #


def test_extract_zh_i18n_unknown_skill_returns_empty() -> None:
    result = catalog_store.extract_zh_i18n("no-such-builtin-skill")
    assert result == {"display_name_zh": "", "description_zh": ""}


def test_extract_zh_i18n_builtin_variant() -> None:
    """内置技能（如 docx）应从 -zh 变体提取官方中文映射。"""
    result = catalog_store.extract_zh_i18n("docx")
    # 打包内置存在 docx-zh 变体时必须有非空中文描述
    from qwenpaw.agents.skill_system.registry import (
        _get_packaged_builtin_registry,  # noqa: SLF001
    )

    registry = _get_packaged_builtin_registry()
    if "docx" in registry and "zh" in registry["docx"]:
        assert result["description_zh"]
        assert result["display_name_zh"]
    else:  # pragma: no cover - 环境无内置包时降级断言
        assert result == {"display_name_zh": "", "description_zh": ""}
