# -*- coding: utf-8 -*-
"""Skill PG catalog plane (``skill_catalog`` / ``agent_skill_bindings`` /
``skill_content_snapshots`` storage).

技能系统 PG 落库平面（alembic ``0023``/``0024``/``0025``，psql twin:
changelog 20260911/01）。三态语义与 ``provider_store`` 完全一致
（共用 ``QWENPAW_STORAGE_BACKEND`` 开关）：

- ``json``（默认）：不触碰 PG，读写均走本地 manifest（现状行为）；
- ``dual``：manifest 权威 + 本平面影子双写（fire-and-forget，失败仅告警），
  读取不查本平面；
- ``pg``：本平面权威读（空表/异常回退 manifest 存量兼容），写路径
  manifest 降级备份 + 本平面权威写（调度式最终一致）。

设计理念（用户强调的最高准绳）：技能是数据资产，PG 是唯一权威源；
文件目录只承担运行时热路径（AgentScope 要求真实目录），任何文件丢失
（换服务器/误删）都可通过 ``skill_content_snapshots`` 快照启动自愈。

manifest entry → catalog 行字段映射表（禁止部分拷贝，逐字段对齐）：
``source``/``installed_from``/``source_url``/``version_text``/``emoji``/
``builtin_language``/``tags``/``config``/``automation``/``external``/
``external_path``/``content_hash``/``display_name_zh``/``description_zh``/
``protected``。

SQL 风格对齐 ``provider_store``：async engine + 参数化 ``text()``，
任何 PG 异常只告警、绝不阻塞业务路径。

@author qingfeng
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from ...db.base import DEFAULT_TENANT_ID
from ...providers import provider_store
from ...providers.provider_store import pg_provider_plane_available

logger = logging.getLogger(__name__)

# 快照 zip 体积上限（与 store._MAX_ZIP_BYTES 对齐：200MB）
_MAX_SNAPSHOT_BYTES = 200 * 1024 * 1024

# 打包快照时排除的 OS/缓存伪影（与 store._IGNORED_SKILL_ARTIFACTS 对齐）
_SNAPSHOT_IGNORED = {
    "__pycache__",
    "__MACOSX",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}


# ---------------------------------------------------------------------------
# 三态后端判定（与 provider 平面同源）
# ---------------------------------------------------------------------------


def skill_storage_backend() -> str:
    """Return the resolved skill storage backend (json/dual/pg)."""
    return provider_store.provider_storage_backend()


def skill_pg_plane_available() -> bool:
    """True when the skill plane should touch PG (dual/pg + DSN set)."""
    return pg_provider_plane_available()


def _schedule(operation: Callable[[], Awaitable[Any]]) -> None:
    """Fire-and-forget a PG write without blocking or failing the caller."""
    provider_store.schedule_pg_write(operation)


def _json_dumps(value: Any) -> str:
    """Serialize a JSONB payload (list/dict) to a compact JSON string."""
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# manifest entry → PG row builders（逐字段映射，禁止部分拷贝）
# ---------------------------------------------------------------------------


def build_catalog_row(
    skill_name: str,
    entry: dict[str, Any],
    *,
    content_hash: str = "",
) -> dict[str, Any]:
    """Build one ``skill_catalog`` row payload from a pool manifest entry.

    *entry* 为 ``skill_pool/skill.json`` 的条目 dict（顶层即 metadata
    展开 + external/installed_from/config/tags/automation 等附加键）；
    *content_hash* 由调用方按 ``compute_skill_md_hash`` 提供（空串表示
    待对账/内容丢失）。
    """
    return {
        "skill_name": skill_name,
        "source": str(entry.get("source", "customized") or "customized"),
        "installed_from": str(entry.get("installed_from", "") or ""),
        "source_url": str(entry.get("source_url", "") or ""),
        "version_text": str(entry.get("version_text", "") or ""),
        "emoji": str(entry.get("emoji", "") or ""),
        "builtin_language": str(entry.get("builtin_language", "") or ""),
        "tags": entry.get("tags") if entry.get("tags") is not None else [],
        "config": entry.get("config") if isinstance(entry.get("config"), dict) else {},
        "automation": (
            entry.get("automation")
            if isinstance(entry.get("automation"), dict)
            else {}
        ),
        "external": bool(entry.get("external", False)),
        "external_path": str(entry.get("external_path", "") or ""),
        "content_hash": content_hash,
        "display_name_zh": str(entry.get("display_name_zh", "") or ""),
        "description_zh": str(entry.get("description_zh", "") or ""),
        "protected": bool(entry.get("protected", False)),
    }


def build_binding_row(
    skill_name: str,
    entry: dict[str, Any],
    *,
    origin: str = "pool",
) -> dict[str, Any]:
    """Build one ``agent_skill_bindings`` row payload from a ws entry.

    *entry* 为 ``workspaces/{agent}/skill.json`` 的条目 dict
    （enabled/channels/config/tags）；*origin* 由调用方按装配来源提供
    （pool/builtin/private）。
    """
    return {
        "skill_name": skill_name,
        "origin": origin,
        "enabled": bool(entry.get("enabled", True)),
        "channels": entry.get("channels") or ["all"],
        "config": entry.get("config") if isinstance(entry.get("config"), dict) else {},
        "tags": entry.get("tags"),
    }


# ---------------------------------------------------------------------------
# skill_catalog PG ops
# ---------------------------------------------------------------------------


async def upsert_skill_catalog_pg(row: dict[str, Any], engine: Any = None) -> None:
    """Upsert one skill pool catalog row (authoritative or shadow)."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO skill_catalog "
                "(tenant_id, skill_name, source, installed_from, source_url, "
                "version_text, emoji, builtin_language, tags, config, "
                "automation, external, external_path, content_hash, "
                "display_name_zh, description_zh, protected) "
                "VALUES (:tenant_id, :skill_name, :source, :installed_from, "
                ":source_url, :version_text, :emoji, :builtin_language, "
                ":tags, :config, :automation, :external, :external_path, "
                ":content_hash, :display_name_zh, :description_zh, :protected) "
                "ON CONFLICT (tenant_id, skill_name) DO UPDATE SET "
                "source = EXCLUDED.source, "
                "installed_from = EXCLUDED.installed_from, "
                "source_url = EXCLUDED.source_url, "
                "version_text = EXCLUDED.version_text, "
                "emoji = EXCLUDED.emoji, "
                "builtin_language = EXCLUDED.builtin_language, "
                "tags = EXCLUDED.tags, "
                "config = EXCLUDED.config, "
                "automation = EXCLUDED.automation, "
                "external = EXCLUDED.external, "
                "external_path = EXCLUDED.external_path, "
                "content_hash = EXCLUDED.content_hash, "
                "display_name_zh = EXCLUDED.display_name_zh, "
                "description_zh = EXCLUDED.description_zh, "
                "protected = EXCLUDED.protected, "
                "updated_at = now()",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "skill_name": row["skill_name"],
                "source": row["source"],
                "installed_from": row["installed_from"],
                "source_url": row["source_url"],
                "version_text": row["version_text"],
                "emoji": row["emoji"],
                "builtin_language": row["builtin_language"],
                "tags": _json_dumps(row["tags"]),
                "config": _json_dumps(row["config"]),
                "automation": _json_dumps(row["automation"]),
                "external": row["external"],
                "external_path": row["external_path"],
                "content_hash": row["content_hash"],
                "display_name_zh": row["display_name_zh"],
                "description_zh": row["description_zh"],
                "protected": row["protected"],
            },
        )


async def delete_skill_catalog_pg(skill_name: str, engine: Any = None) -> None:
    """Delete one catalog row (pool skill removed)."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM skill_catalog "
                "WHERE tenant_id = :tenant_id AND skill_name = :skill_name",
            ),
            {"tenant_id": DEFAULT_TENANT_ID, "skill_name": skill_name},
        )


async def load_skill_catalog_pg(engine: Any = None) -> list[dict[str, Any]]:
    """Return all catalog rows (pg authoritative read)."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT skill_name, source, installed_from, source_url, "
                "version_text, emoji, builtin_language, tags, config, "
                "automation, external, external_path, content_hash, "
                "display_name_zh, description_zh, protected "
                "FROM skill_catalog WHERE tenant_id = :tenant_id "
                "ORDER BY skill_name",
            ),
            {"tenant_id": DEFAULT_TENANT_ID},
        )
        rows = result.all()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "skill_name": row[0],
                "source": row[1] or "customized",
                "installed_from": row[2] or "",
                "source_url": row[3] or "",
                "version_text": row[4] or "",
                "emoji": row[5] or "",
                "builtin_language": row[6] or "",
                "tags": _json_loads(row[7], []),
                "config": _json_loads(row[8], {}),
                "automation": _json_loads(row[9], {}),
                "external": bool(row[10]),
                "external_path": row[11] or "",
                "content_hash": row[12] or "",
                "display_name_zh": row[13] or "",
                "description_zh": row[14] or "",
                "protected": bool(row[15]),
            },
        )
    return out


def _json_loads(raw: Any, default: Any) -> Any:
    """Parse a JSONB column defensively (dirty data never breaks reads)."""
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("skill plane JSONB column is not valid JSON; ignored")
            return default
    return default


# ---------------------------------------------------------------------------
# agent_skill_bindings PG ops
# ---------------------------------------------------------------------------


async def upsert_agent_skill_binding_pg(
    agent_id: str,
    row: dict[str, Any],
    engine: Any = None,
) -> None:
    """Upsert one agent skill binding row (装配/启停/改配置)."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agent_skill_bindings "
                "(tenant_id, agent_id, skill_name, origin, enabled, "
                "channels, config, tags) "
                "VALUES (:tenant_id, :agent_id, :skill_name, :origin, "
                ":enabled, :channels, :config, :tags) "
                "ON CONFLICT (tenant_id, agent_id, skill_name) DO UPDATE SET "
                "origin = EXCLUDED.origin, "
                "enabled = EXCLUDED.enabled, "
                "channels = EXCLUDED.channels, "
                "config = EXCLUDED.config, "
                "tags = EXCLUDED.tags, "
                "updated_at = now()",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "skill_name": row["skill_name"],
                "origin": row["origin"],
                "enabled": row["enabled"],
                "channels": _json_dumps(row["channels"]),
                "config": _json_dumps(row["config"]),
                "tags": (
                    _json_dumps(row["tags"]) if row["tags"] is not None else None
                ),
            },
        )


async def delete_agent_skill_binding_pg(
    agent_id: str,
    skill_name: str,
    engine: Any = None,
) -> None:
    """Delete one agent skill binding row (卸载技能)."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM agent_skill_bindings "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND skill_name = :skill_name",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "skill_name": skill_name,
            },
        )


async def delete_bindings_for_skill_pg(
    skill_name: str,
    engine: Any = None,
) -> int:
    """Cascade-unbind every agent referencing a removed pool skill."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM agent_skill_bindings "
                "WHERE tenant_id = :tenant_id AND skill_name = :skill_name",
            ),
            {"tenant_id": DEFAULT_TENANT_ID, "skill_name": skill_name},
        )
    return int(result.rowcount or 0)


async def count_skill_bindings_pg(
    skill_name: str,
    engine: Any = None,
) -> int:
    """Return how many agents currently bind one pool skill (影响面)."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM agent_skill_bindings "
                "WHERE tenant_id = :tenant_id AND skill_name = :skill_name",
            ),
            {"tenant_id": DEFAULT_TENANT_ID, "skill_name": skill_name},
        )
        row = result.first()
    return int(row[0]) if row is not None else 0


async def load_agent_bindings_pg(
    agent_id: str,
    engine: Any = None,
) -> dict[str, dict[str, Any]]:
    """Return one agent's bindings keyed by skill name (pg authoritative).

    返回条目为 workspace manifest entry 同构 dict（enabled/channels/
    config/tags/origin），供 ``resolve_effective_skills`` 与前端直接消费。
    """
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT skill_name, origin, enabled, channels, config, tags "
                "FROM agent_skill_bindings "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id",
            ),
            {"tenant_id": DEFAULT_TENANT_ID, "agent_id": agent_id},
        )
        rows = result.all()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[row[0]] = {
            "origin": row[1] or "pool",
            "enabled": bool(row[2]),
            "channels": _json_loads(row[3], ["all"]),
            "config": _json_loads(row[4], {}),
            "tags": _json_loads(row[5], None),
        }
    return out


# ---------------------------------------------------------------------------
# skill_content_snapshots PG ops（内容冷备/换环境自愈源）
# ---------------------------------------------------------------------------


async def upsert_skill_snapshot_pg(
    owner_agent_id: str,
    skill_name: str,
    content_zip: bytes,
    content_hash: str,
    engine: Any = None,
) -> None:
    """Upsert one skill content snapshot (zip cold backup)."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO skill_content_snapshots "
                "(tenant_id, owner_agent_id, skill_name, content_zip, "
                "content_hash) "
                "VALUES (:tenant_id, :owner_agent_id, :skill_name, "
                ":content_zip, :content_hash) "
                "ON CONFLICT (tenant_id, owner_agent_id, skill_name) "
                "DO UPDATE SET content_zip = EXCLUDED.content_zip, "
                "content_hash = EXCLUDED.content_hash, updated_at = now()",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "owner_agent_id": owner_agent_id,
                "skill_name": skill_name,
                "content_zip": content_zip,
                "content_hash": content_hash,
            },
        )


async def load_skill_snapshot_pg(
    owner_agent_id: str,
    skill_name: str,
    engine: Any = None,
) -> dict[str, Any] | None:
    """Return one snapshot ``{"content_zip", "content_hash"}`` or None."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT content_zip, content_hash FROM skill_content_snapshots "
                "WHERE tenant_id = :tenant_id "
                "AND owner_agent_id = :owner_agent_id "
                "AND skill_name = :skill_name",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "owner_agent_id": owner_agent_id,
                "skill_name": skill_name,
            },
        )
        row = result.first()
    if row is None:
        return None
    return {"content_zip": bytes(row[0]), "content_hash": row[1] or ""}


async def delete_skill_snapshot_pg(
    owner_agent_id: str,
    skill_name: str,
    engine: Any = None,
) -> None:
    """Delete one snapshot row (skill removed)."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM skill_content_snapshots "
                "WHERE tenant_id = :tenant_id "
                "AND owner_agent_id = :owner_agent_id "
                "AND skill_name = :skill_name",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "owner_agent_id": owner_agent_id,
                "skill_name": skill_name,
            },
        )


# ---------------------------------------------------------------------------
# zip 打包 / 物化（快照冷备与换环境自愈的工具函数）
# ---------------------------------------------------------------------------


def pack_skill_dir_zip(skill_dir: Path) -> bytes | None:
    """Pack one skill directory into a zip byte string (cold backup).

    排除 OS 缓存伪影；超过 200MB 上限返回 None（不写快照，仅告警）。
    目录不存在或打包失败返回 None（调用方降级跳过，不阻塞业务）。
    """
    if not skill_dir.is_dir():
        return None
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(skill_dir.rglob("*")):
                rel = path.relative_to(skill_dir)
                if any(part in _SNAPSHOT_IGNORED for part in rel.parts):
                    continue
                if path.is_file():
                    zf.write(path, rel.as_posix())
        data = buffer.getvalue()
    except OSError:
        logger.warning(
            "Failed to pack skill snapshot for %s",
            skill_dir,
            exc_info=True,
        )
        return None
    if len(data) > _MAX_SNAPSHOT_BYTES:
        logger.warning(
            "Skill snapshot for %s exceeds 200MB; skipped",
            skill_dir,
        )
        return None
    return data


def materialize_skill_from_zip(content_zip: bytes, target_dir: Path) -> bool:
    """Materialize one skill directory from a snapshot zip (self-heal).

    复用 ``store._extract_and_validate_zip`` 同源防护（zip slip / symlink
    拒绝）+ 安全扫描；物化失败返回 False（调用方降级标 missing）。
    """
    import shutil
    import tempfile

    from ...security.skill_scanner import scan_skill_directory
    from .store import (
        _extract_and_validate_zip,  # noqa: SLF001 - 同源安全防护复用
        copy_skill_dir,
    )

    tmp_dir = Path(tempfile.mkdtemp(prefix="qwenpaw_skill_heal_"))
    try:
        _extract_and_validate_zip(content_zip, tmp_dir)
        entries = [p for p in tmp_dir.iterdir() if p.name not in _SNAPSHOT_IGNORED]
        extract_root = (
            entries[0]
            if len(entries) == 1 and entries[0].is_dir()
            else tmp_dir
        )
        if not (extract_root / "SKILL.md").exists():
            logger.warning(
                "Skill snapshot zip has no SKILL.md; skip materialize %s",
                target_dir,
            )
            return False
        scan_skill_directory(extract_root, skill_name=target_dir.name)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        copy_skill_dir(extract_root, target_dir)
        return True
    except Exception:  # noqa: BLE001 - self-heal must never break startup
        logger.warning(
            "Failed to materialize skill snapshot into %s",
            target_dir,
            exc_info=True,
        )
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 中文映射提取（内置技能 -zh 变体 → display_name_zh/description_zh）
# ---------------------------------------------------------------------------


def extract_zh_i18n(skill_name: str) -> dict[str, str]:
    """Extract Chinese display name/description from the packaged -zh variant.

    内置技能自带 ``{name}-zh`` 语言变体（``BUILTIN_SKILL_LANGUAGES``），
    其 frontmatter 的 name/description 即官方中文映射；非内置技能或
    变体缺失返回空串（前端回退英文 + 人工补全引导）。
    """
    try:
        from .registry import resolve_builtin_skill_dir
        from .store import read_skill_frontmatter_from_dir

        zh_dir = resolve_builtin_skill_dir(skill_name, preferred_language="zh")
        if not zh_dir:
            return {"display_name_zh": "", "description_zh": ""}
        post = read_skill_frontmatter_from_dir(Path(zh_dir), skill_name)
        return {
            "display_name_zh": str(post.get("name", "") or "").strip(),
            "description_zh": str(post.get("description", "") or "").strip(),
        }
    except Exception:  # noqa: BLE001 - i18n extraction must never break sync
        logger.warning(
            "Failed to extract zh i18n for builtin skill %s",
            skill_name,
            exc_info=True,
        )
        return {"display_name_zh": "", "description_zh": ""}


# ---------------------------------------------------------------------------
# 三态统一写入口（业务路径唯一接触面，fire-and-forget 永不阻塞）
# ---------------------------------------------------------------------------


def schedule_pool_skill_sync(
    skill_name: str,
    entry: dict[str, Any],
    skill_dir: Path | None,
) -> None:
    """Schedule catalog upsert + content snapshot for one pool skill.

    dual/pg 模式写 PG（json 零动作）；快照仅非内置技能写入
    （内置随安装包分发，重装即恢复）。i18n 缺失时自动从 -zh 变体回填。
    """
    if not skill_pg_plane_available():
        return

    async def _op() -> None:
        from .store import compute_skill_md_hash

        content_hash = (
            compute_skill_md_hash(skill_dir) if skill_dir is not None else ""
        )
        row = build_catalog_row(skill_name, entry, content_hash=content_hash)
        # 人工编辑过的中文映射不参与 -zh 变体自动回填（清空意图可持久化）
        if (
            not row["display_name_zh"]
            and entry.get("source") == "builtin"
            and not entry.get("i18n_manual", False)
        ):
            zh = extract_zh_i18n(skill_name)
            row["display_name_zh"] = zh["display_name_zh"]
            row["description_zh"] = zh["description_zh"]
        await upsert_skill_catalog_pg(row)
        # 内置技能不写快照（随安装包分发）；外部目录技能不可打包
        if entry.get("source") != "builtin" and not entry.get("external", False):
            if skill_dir is not None:
                content_zip = pack_skill_dir_zip(skill_dir)
                if content_zip is not None:
                    await upsert_skill_snapshot_pg(
                        "",
                        skill_name,
                        content_zip,
                        content_hash,
                    )

    _schedule(_op)


async def purge_pool_skill_pg(skill_name: str) -> int:
    """Synchronously delete one pool skill's PG rows; return unbound count.

    删除路径专用同步版（区别于写路径的 fire-and-forget）：列表 overlay
    紧随删除之后读 PG，异步删除会与同步读产生竞态（已删技能以 missing
    复活）。任何 PG 异常由调用方决定是否告警吞掉（文件平面为主）。
    """
    await delete_skill_catalog_pg(skill_name)
    await delete_skill_snapshot_pg("", skill_name)
    removed = await delete_bindings_for_skill_pg(skill_name)
    return removed


def schedule_pool_skill_delete(skill_name: str) -> None:
    """Schedule catalog/snapshot delete + binding cascade-unbind."""
    if not skill_pg_plane_available():
        return

    async def _op() -> None:
        removed = await purge_pool_skill_pg(skill_name)
        if removed:
            logger.info(
                "Cascade-unbound %d agent binding(s) for removed skill %s",
                removed,
                skill_name,
            )

    _schedule(_op)


def schedule_agent_skill_sync(
    agent_id: str,
    skill_name: str,
    entry: dict[str, Any],
    *,
    origin: str = "pool",
    private_dir: Path | None = None,
) -> None:
    """Schedule binding upsert (+ private skill snapshot) for one agent.

    *private_dir* 非空表示员工私有技能（origin=private），同时写私有
    快照（换环境自愈源）；池引用技能只写绑定行（零拷贝）。
    """
    if not skill_pg_plane_available():
        return

    async def _op() -> None:
        await upsert_agent_skill_binding_pg(
            agent_id,
            build_binding_row(skill_name, entry, origin=origin),
        )
        if private_dir is not None:
            from .store import compute_skill_md_hash

            content_zip = pack_skill_dir_zip(private_dir)
            if content_zip is not None:
                await upsert_skill_snapshot_pg(
                    agent_id,
                    skill_name,
                    content_zip,
                    compute_skill_md_hash(private_dir),
                )

    _schedule(_op)


def schedule_agent_skill_delete(agent_id: str, skill_name: str) -> None:
    """Schedule binding delete (+ private snapshot delete)."""
    if not skill_pg_plane_available():
        return

    async def _op() -> None:
        await delete_agent_skill_binding_pg(agent_id, skill_name)
        await delete_skill_snapshot_pg(agent_id, skill_name)

    _schedule(_op)
