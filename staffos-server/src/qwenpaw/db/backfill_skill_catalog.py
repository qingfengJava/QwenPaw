# -*- coding: utf-8 -*-
"""Skill PG plane startup backfill / reconcile / dedupe migration.

技能 PG 落库平面的启动闭环（alembic 0023/0024/0025 的运行时配套）：

- ``backfill_skill_catalog_pg``：把 ``skill_pool/skill.json`` 与
  ``workspaces/*/skill.json`` 幂等灌入 PG 三表（catalog/bindings/
  snapshots），含内置技能 -zh 变体中文映射回填；
- ``reconcile_skill_catalog_pg``：以文件为内容事实源对账 —— PG 有记录
  但文件缺失时从快照自动解压物化自愈（换环境恢复闭环），快照也缺失
  降级标 missing；文件与快照 hash 漂移以文件为准重打；
- ``dedupe_workspace_skill_copies``：引用化收尾去重迁移 —— workspace
  与池同名且内容一致的遗留拷贝删除转纯绑定，不一致保留为私有覆盖。

所有函数仅在 dual/pg 后端动作（json 零动作），任何 PG 异常只告警、
绝不阻塞启动（对齐 Provider 配置平面启动范式）。

@author qingfeng
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _origin_for_entry(entry: dict[str, Any], skill_name: str) -> str:
    """Resolve one workspace binding's origin (pool/builtin/private)."""
    origin = str(entry.get("origin", "") or "")
    if origin:
        return origin
    if entry.get("source") == "builtin":
        return "builtin"
    from ..agents.skill_system.store import read_skill_pool_manifest

    pool_entry = read_skill_pool_manifest().get("skills", {}).get(skill_name)
    if pool_entry is not None:
        return "pool"
    return "private"


async def backfill_skill_catalog_pg() -> dict[str, int]:
    """Idempotently backfill pool + workspace manifests into the PG plane.

    返回 ``{"catalog", "bindings", "snapshots"}`` 计数；json 后端或
    PG 不可用时返回全零（零动作）。
    """
    from ..agents.skill_system import catalog_store
    from ..agents.skill_system.registry import list_workspaces
    from ..agents.skill_system.store import (
        compute_skill_md_hash,
        get_workspace_skills_dir,
        read_skill_manifest,
        read_skill_pool_manifest,
        resolve_pool_skill_dir,
    )

    if not catalog_store.skill_pg_plane_available():
        return {"catalog": 0, "bindings": 0, "snapshots": 0}

    stats = {"catalog": 0, "bindings": 0, "snapshots": 0}

    manifest = read_skill_pool_manifest()
    for skill_name, entry in sorted(manifest.get("skills", {}).items()):
        if not isinstance(entry, dict):
            continue
        skill_dir = resolve_pool_skill_dir(skill_name)
        content_hash = (
            compute_skill_md_hash(skill_dir) if skill_dir is not None else ""
        )
        row = catalog_store.build_catalog_row(
            skill_name,
            entry,
            content_hash=content_hash,
        )
        # 人工编辑过的中文映射不参与 -zh 变体自动回填（与 schedule 同源）
        if (
            not row["display_name_zh"]
            and entry.get("source") == "builtin"
            and not entry.get("i18n_manual", False)
        ):
            zh = catalog_store.extract_zh_i18n(skill_name)
            row["display_name_zh"] = zh["display_name_zh"]
            row["description_zh"] = zh["description_zh"]
        await catalog_store.upsert_skill_catalog_pg(row)
        stats["catalog"] += 1
        if (
            entry.get("source") != "builtin"
            and not entry.get("external", False)
            and skill_dir is not None
        ):
            content_zip = catalog_store.pack_skill_dir_zip(skill_dir)
            if content_zip is not None:
                await catalog_store.upsert_skill_snapshot_pg(
                    "",
                    skill_name,
                    content_zip,
                    content_hash,
                )
                stats["snapshots"] += 1

    for ws in list_workspaces():
        agent_id = str(ws.get("agent_id", "") or "")
        if not agent_id:
            continue
        workspace_dir = Path(ws["workspace_dir"])
        ws_manifest = read_skill_manifest(workspace_dir)
        for skill_name, entry in sorted(ws_manifest.get("skills", {}).items()):
            if not isinstance(entry, dict):
                continue
            origin = _origin_for_entry(entry, skill_name)
            await catalog_store.upsert_agent_skill_binding_pg(
                agent_id,
                catalog_store.build_binding_row(
                    skill_name,
                    entry,
                    origin=origin,
                ),
            )
            stats["bindings"] += 1
            if origin == "private":
                private_dir = (
                    get_workspace_skills_dir(workspace_dir) / skill_name
                )
                if private_dir.is_dir():
                    content_zip = catalog_store.pack_skill_dir_zip(
                        private_dir,
                    )
                    if content_zip is not None:
                        await catalog_store.upsert_skill_snapshot_pg(
                            agent_id,
                            skill_name,
                            content_zip,
                            compute_skill_md_hash(private_dir),
                        )
                        stats["snapshots"] += 1
    return stats


async def reconcile_skill_catalog_pg() -> dict[str, int]:
    """Reconcile PG catalog against the file plane (self-heal on missing).

    对账规则（文件为内容事实源）：
    - PG 有记录但池文件缺失 + 快照存在 → 解压物化自愈（换环境闭环）；
    - PG 有记录但池文件缺失 + 快照缺失 → 标 ``content_hash=''``（missing）；
    - 文件与 catalog hash 漂移 → 以文件为准更新 catalog 并重打快照；
    - 文件有但 PG 无记录 → 回填 catalog 行。
    """
    from ..agents.skill_system import catalog_store
    from ..agents.skill_system.store import (
        compute_skill_md_hash,
        get_skill_pool_dir,
        read_skill_pool_manifest,
        resolve_pool_skill_dir,
        safe_skill_dir,
    )

    if not catalog_store.skill_pg_plane_available():
        return {
            "healed": 0,
            "restored": 0,
            "missing": 0,
            "resnapshotted": 0,
            "backfilled": 0,
        }

    stats = {
        "healed": 0,
        "restored": 0,
        "missing": 0,
        "resnapshotted": 0,
        "backfilled": 0,
    }
    rows = await catalog_store.load_skill_catalog_pg()
    pool_dir = get_skill_pool_dir()

    for row in rows:
        skill_name = row["skill_name"]
        skill_dir = resolve_pool_skill_dir(skill_name)
        if skill_dir is None and not row["external"]:
            snapshot = await catalog_store.load_skill_snapshot_pg(
                "",
                skill_name,
            )
            if snapshot is not None:
                target = safe_skill_dir(pool_dir, skill_name)
                if catalog_store.materialize_skill_from_zip(
                    snapshot["content_zip"],
                    target,
                ):
                    stats["healed"] += 1
                    # 自愈后回写池 manifest 条目（否则自愈技能
                    # “看得见装不了”：列表 missing、download 404）
                    if _restore_pool_manifest_entry(row):
                        stats["restored"] += 1
                    logger.info(
                        "skill '%s' materialized from PG snapshot",
                        skill_name,
                    )
                else:
                    stats["missing"] += 1
            else:
                stats["missing"] += 1
                await catalog_store.upsert_skill_catalog_pg(
                    {**row, "content_hash": ""},
                )
            continue
        if skill_dir is not None:
            current_hash = compute_skill_md_hash(skill_dir)
            if current_hash and current_hash != row["content_hash"]:
                updated = {**row, "content_hash": current_hash}
                await catalog_store.upsert_skill_catalog_pg(updated)
                if row["source"] != "builtin" and not row["external"]:
                    content_zip = catalog_store.pack_skill_dir_zip(skill_dir)
                    if content_zip is not None:
                        await catalog_store.upsert_skill_snapshot_pg(
                            "",
                            skill_name,
                            content_zip,
                            current_hash,
                        )
                stats["resnapshotted"] += 1

    known = {row["skill_name"] for row in rows}
    manifest = read_skill_pool_manifest()
    for skill_name, entry in sorted(manifest.get("skills", {}).items()):
        if skill_name in known or not isinstance(entry, dict):
            continue
        skill_dir = resolve_pool_skill_dir(skill_name)
        content_hash = (
            compute_skill_md_hash(skill_dir) if skill_dir is not None else ""
        )
        await catalog_store.upsert_skill_catalog_pg(
            catalog_store.build_catalog_row(
                skill_name,
                entry,
                content_hash=content_hash,
            ),
        )
        stats["backfilled"] += 1
    return stats


async def dedupe_workspace_skill_copies(
    *,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Dedupe legacy per-workspace skill copies into pure pool bindings.

    去重迁移（引用化收尾）：workspace ``skills/`` 下与池同名的遗留拷贝
    —— 内容与池一致 → 删除拷贝、绑定转 ``origin='pool'``（释放磁盘）；
    不一致 → 保留目录并标记 ``origin='private'``（员工自定义版本，绝不
    静默覆盖）。``dry_run=True`` 只出报告不动数据。
    """
    from ..agents.skill_system import catalog_store
    from ..agents.skill_system.registry import list_workspaces
    from ..agents.skill_system.store import (
        compute_skill_md_hash,
        default_workspace_manifest,
        get_workspace_skill_manifest_path,
        get_workspace_skills_dir,
        mutate_json,
        read_skill_manifest,
        resolve_pool_skill_dir,
    )

    report: dict[str, list[str]] = {
        "converted": [],
        "kept_private": [],
        "unchanged": [],
    }
    for ws in list_workspaces():
        agent_id = str(ws.get("agent_id", "") or "")
        if not agent_id:
            continue
        workspace_dir = Path(ws["workspace_dir"])
        skills_root = get_workspace_skills_dir(workspace_dir)
        manifest = read_skill_manifest(workspace_dir)
        for skill_name, entry in sorted(manifest.get("skills", {}).items()):
            if not isinstance(entry, dict):
                continue
            copy_dir = skills_root / skill_name
            if not (copy_dir / "SKILL.md").is_file():
                continue
            pool_dir = resolve_pool_skill_dir(skill_name)
            if pool_dir is None:
                report["unchanged"].append(f"{agent_id}/{skill_name}")
                continue
            key = f"{agent_id}/{skill_name}"
            if compute_skill_md_hash(copy_dir) != compute_skill_md_hash(
                pool_dir,
            ):
                # 内容不一致：视为员工私有覆盖，标记 origin=private
                if not dry_run:
                    _mark_workspace_origin(
                        workspace_dir,
                        skill_name,
                        "private",
                        mutate_json,
                        default_workspace_manifest,
                        get_workspace_skill_manifest_path,
                    )
                    catalog_store.schedule_agent_skill_sync(
                        agent_id,
                        skill_name,
                        entry,
                        origin="private",
                        private_dir=copy_dir,
                    )
                report["kept_private"].append(key)
                continue
            if dry_run:
                report["converted"].append(key)
                continue
            # 内容一致：删除遗留拷贝，转为池纯引用绑定
            shutil.rmtree(copy_dir, ignore_errors=True)
            _mark_workspace_origin(
                workspace_dir,
                skill_name,
                "pool",
                mutate_json,
                default_workspace_manifest,
                get_workspace_skill_manifest_path,
            )
            catalog_store.schedule_agent_skill_sync(
                agent_id,
                skill_name,
                entry,
                origin="pool",
            )
            report["converted"].append(key)
    return report


def _mark_workspace_origin(
    workspace_dir: Path,
    skill_name: str,
    origin: str,
    mutate_json: Any,
    default_workspace_manifest: Any,
    get_workspace_skill_manifest_path: Any,
) -> None:
    """Stamp ``origin`` onto one workspace manifest entry (best effort)."""

    def _patch(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if not isinstance(entry, dict):
            return False
        entry["origin"] = origin
        return True

    mutate_json(
        get_workspace_skill_manifest_path(workspace_dir),
        default_workspace_manifest(),
        _patch,
    )


async def run_skill_plane_bootstrap() -> dict[str, Any]:
    """Startup entry: backfill → reconcile → bindings → dedupe."""
    from ..agents.skill_system import catalog_store

    if not catalog_store.skill_pg_plane_available():
        return {}
    result: dict[str, Any] = {}
    result["backfill"] = await backfill_skill_catalog_pg()
    result["reconcile"] = await reconcile_skill_catalog_pg()
    result["bindings"] = await reconcile_agent_bindings_pg()
    result["dedupe"] = await dedupe_workspace_skill_copies()
    logger.info("Skill PG plane bootstrap completed: %s", result)
    return result


def _catalog_row_to_pool_entry(
    row: dict[str, Any],
    skill_dir: Path,
) -> dict[str, Any]:
    """Map one PG catalog row back into a pool manifest entry.

    ``build_catalog_row`` 的逆向映射（换环境自愈后回写 manifest 用）：
    metadata/requirements/updated_at 从物化后的目录重建（描述性字段，
    以文件为准），其余元数据从 catalog 行透传；空值键省略对齐既有
    entry 风格。
    """
    from ..agents.skill_system.store import build_skill_metadata

    metadata = build_skill_metadata(
        row["skill_name"],
        skill_dir,
        source=str(row["source"]),
        protected=bool(row["protected"]),
    )
    entry: dict[str, Any] = {
        "source": row["source"],
        "installed_from": row["installed_from"],
        "source_url": row["source_url"],
        "version_text": row["version_text"],
        "emoji": row["emoji"],
        "builtin_language": row["builtin_language"],
        "tags": row["tags"],
        "config": row["config"],
        "automation": row["automation"],
        "external": row["external"],
        "external_path": row["external_path"],
        "display_name_zh": row["display_name_zh"],
        "description_zh": row["description_zh"],
        "protected": row["protected"],
        "metadata": metadata,
        "requirements": metadata["requirements"],
        "updated_at": metadata["updated_at"],
    }
    return {
        key: value
        for key, value in entry.items()
        if value not in ("", None, [], {})
    }


def _restore_pool_manifest_entry(row: dict[str, Any]) -> bool:
    """Write one healed catalog row back into the pool manifest.

    仅在 manifest 缺条目时写入（文件平面已有条目则以文件为准，
    绝不覆盖）；写入成功返回 True。
    """
    from ..agents.skill_system.store import (
        mutate_pool_manifest,
        resolve_pool_skill_dir,
    )

    skill_dir = resolve_pool_skill_dir(row["skill_name"])
    if skill_dir is None:
        return False
    entry = _catalog_row_to_pool_entry(row, skill_dir)

    def _patch(payload: dict[str, Any]) -> bool:
        skills = payload.setdefault("skills", {})
        if row["skill_name"] in skills:
            return False
        skills[row["skill_name"]] = entry
        return True

    return mutate_pool_manifest(_patch) is not False


async def reconcile_agent_bindings_pg() -> dict[str, int]:
    """Restore workspace manifests + private skill bodies from PG bindings.

    换环境恢复闭环的员工侧：pg 平面绑定行权威 → workspace manifest
    缺条目时回写（治理“绑定在 PG 但列表为空”的管理/运行时割裂）；
    私有技能（origin=private）同时从快照物化技能体，否则该技能
    无法通过 ``_skill_dir_resolvable`` 注入运行时。manifest 已有
    条目一律不动（文件为准）。
    """
    from ..agents.skill_system import catalog_store
    from ..agents.skill_system.registry import (
        list_workspaces,
        resolve_builtin_skill_dir,
    )
    from ..agents.skill_system.store import (
        build_skill_metadata,
        default_workspace_manifest,
        get_workspace_skill_manifest_path,
        get_workspace_skills_dir,
        mutate_json,
        read_skill_manifest,
        resolve_pool_skill_dir,
        safe_skill_dir,
    )

    stats = {"restored": 0, "materialized": 0, "skipped": 0}
    for ws in list_workspaces():
        agent_id = str(ws.get("agent_id", "") or "")
        if not agent_id:
            continue
        workspace_dir = Path(ws["workspace_dir"])
        manifest = read_skill_manifest(workspace_dir)
        try:
            bindings = await catalog_store.load_agent_bindings_pg(agent_id)
        except Exception:  # noqa: BLE001 - PG plane must never break startup
            logger.warning(
                "agent bindings read failed for %s; skip restore",
                agent_id,
                exc_info=True,
            )
            continue
        for skill_name, binding in sorted(bindings.items()):
            if skill_name in manifest.get("skills", {}):
                continue
            origin = str(binding.get("origin", "pool") or "pool")
            skills_root = get_workspace_skills_dir(workspace_dir)
            if origin == "private":
                snapshot = await catalog_store.load_skill_snapshot_pg(
                    agent_id,
                    skill_name,
                )
                if snapshot is None:
                    stats["skipped"] += 1
                    continue
                target = safe_skill_dir(skills_root, skill_name)
                if not catalog_store.materialize_skill_from_zip(
                    snapshot["content_zip"],
                    target,
                ):
                    stats["skipped"] += 1
                    continue
                skill_dir = target
                source = "customized"
                stats["materialized"] += 1
            else:
                skill_dir = resolve_pool_skill_dir(skill_name)
                if skill_dir is None:
                    builtin_dir = resolve_builtin_skill_dir(skill_name)
                    skill_dir = Path(builtin_dir) if builtin_dir else None
                if skill_dir is None:
                    stats["skipped"] += 1
                    continue
                source = "builtin" if origin == "builtin" else "customized"
            metadata = build_skill_metadata(
                skill_name,
                skill_dir,
                source=source,
            )
            entry: dict[str, Any] = {
                "enabled": bool(binding.get("enabled", True)),
                "channels": binding.get("channels") or ["all"],
                "source": source,
                "config": binding.get("config") or {},
                "metadata": metadata,
                "requirements": metadata["requirements"],
                "updated_at": metadata["updated_at"],
                "origin": origin,
            }
            if binding.get("tags") is not None:
                entry["tags"] = binding["tags"]

            def _patch(
                payload: dict[str, Any],
                _name: str = skill_name,
                _entry: dict[str, Any] = entry,
            ) -> bool:
                skills = payload.setdefault("skills", {})
                if _name in skills:
                    return False
                skills[_name] = _entry
                return True

            mutate_json(
                get_workspace_skill_manifest_path(workspace_dir),
                default_workspace_manifest(),
                _patch,
            )
            stats["restored"] += 1
    return stats
