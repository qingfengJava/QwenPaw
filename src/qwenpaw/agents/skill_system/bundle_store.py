# -*- coding: utf-8 -*-
"""Personal skill bundle PG plane (``agent_skill_bundles`` storage).

个人技能包 PG 落库平面（alembic ``0036``，psql twin: changelog
20260917/04）。承载双平面模型 S2 用户个人平面的私有技能——与共享技能
池/绑定平面（``catalog_store``）**刻意分离**：本模块只读写
``agent_skill_bundles`` 一张表，``owner_user_id`` 非空即个人技能，跨人
严格隔离。可见性/写权由上层 API 闸门判定（owner 本人 + 平台管理员），
本层只做纯数据存取，不含业务判断。

三态语义与 ``catalog_store`` 一致（共用 ``QWENPAW_STORAGE_BACKEND`` 开关）：

- ``json``（默认）：``bundle_pg_plane_available()`` 为 False，调用方跳过
  本平面（个人技能降级为不可用，共享技能不受影响）；
- ``dual``/``pg``：本平面为个人技能唯一权威源。

SQL 风格对齐 ``catalog_store``：async engine + 参数化 ``text()``，可选
``engine`` 注入（单测用 fake engine）；``files`` 全树以 ``CAST(:x AS JSONB)``
写入（规避 asyncpg 无法把 dict 直接编码进 JSONB 的陷阱）。权威读写异常
向上抛出交调用方处置（区别于 catalog_store 的 fire-and-forget 影子写）。

@author qingfeng
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from ...db import write_gateway
from ...db.base import DEFAULT_TENANT_ID

logger = logging.getLogger(__name__)

#: 个人技能物化根目录名（workspace 下隐藏目录，不进共享 skills/ 与 manifest）。
PERSONAL_SKILLS_DIRNAME = ".personal_skills"

#: owner_user_id 作为目录名前的白名单净化（防路径穿越/异常字符）。
_UNSAFE_DIR_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def bundle_pg_plane_available() -> bool:
    """True when the personal-skill plane should touch PG (dual/pg + DSN)."""
    return write_gateway.pg_write_available()


def _json_dumps(value: Any) -> str:
    """Serialize a JSONB payload (dict/list) to a compact JSON string."""
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: Any, default: Any) -> Any:
    """Parse a JSONB column back to dict/list, tolerating driver variance."""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _row_to_bundle(row: Any) -> dict[str, Any]:
    """Map one ``agent_skill_bundles`` row (tuple) to a plain dict."""
    return {
        "name": row[0],
        "files": _json_loads(row[1], {}),
        "enabled": bool(row[2]),
        "version": int(row[3] or 1),
        "department_id": row[4],
        "project_id": row[5],
    }


async def upsert_skill_bundle_pg(
    agent_id: str,
    owner_user_id: str,
    name: str,
    files: dict[str, Any],
    *,
    enabled: bool = True,
    version: int = 1,
    department_id: Optional[str] = None,
    project_id: Optional[str] = None,
    engine: Any = None,
) -> None:
    """Insert-or-update one personal skill bundle (owner-scoped).

    冲突键为 ``(tenant, agent, owner_user_id, name)``：同一用户在同一员工
    下技能名唯一，重复写入按内容覆盖并刷新 ``updated_at``。
    """
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agent_skill_bundles "
                "(tenant_id, agent_id, owner_user_id, name, files, "
                "enabled, version, department_id, project_id) "
                "VALUES (:tenant_id, :agent_id, :owner, :name, "
                "CAST(:files AS JSONB), :enabled, :version, :dept, :proj) "
                "ON CONFLICT (tenant_id, agent_id, owner_user_id, name) "
                "DO UPDATE SET files = EXCLUDED.files, "
                "enabled = EXCLUDED.enabled, "
                "version = EXCLUDED.version, "
                "department_id = EXCLUDED.department_id, "
                "project_id = EXCLUDED.project_id, "
                "updated_at = now()",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "owner": owner_user_id,
                "name": name,
                "files": _json_dumps(files),
                "enabled": bool(enabled),
                "version": int(version),
                "dept": department_id,
                "proj": project_id,
            },
        )


async def delete_skill_bundle_pg(
    agent_id: str,
    owner_user_id: str,
    name: str,
    engine: Any = None,
) -> bool:
    """Delete one personal skill bundle; True when a row was removed."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM agent_skill_bundles "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND owner_user_id = :owner AND name = :name",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "owner": owner_user_id,
                "name": name,
            },
        )
    return int(result.rowcount or 0) > 0


async def load_skill_bundle_pg(
    agent_id: str,
    owner_user_id: str,
    name: str,
    engine: Any = None,
) -> Optional[dict[str, Any]]:
    """Return one personal skill bundle dict, or None when absent."""
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT name, files, enabled, version, department_id, "
                "project_id FROM agent_skill_bundles "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND owner_user_id = :owner AND name = :name",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "owner": owner_user_id,
                "name": name,
            },
        )
        row = result.first()
    return _row_to_bundle(row) if row is not None else None


async def load_owner_bundles_pg(
    agent_id: str,
    owner_user_id: str,
    engine: Any = None,
) -> list[dict[str, Any]]:
    """Return every personal skill bundle owned by one user (name-sorted).

    个人技能平面严格 owner 作用域：本查询恒带 ``owner_user_id`` 谓词，
    天然不泄露他人个人技能（跨人隔离在数据层即成立）。
    """
    from sqlalchemy import text

    from ...db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT name, files, enabled, version, department_id, "
                "project_id FROM agent_skill_bundles "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND owner_user_id = :owner ORDER BY name",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "owner": owner_user_id,
            },
        )
        rows = result.all()
    return [_row_to_bundle(row) for row in rows]


# ---------------------------------------------------------------------------
# 物化：bundle 行 files 全树 → workspace/.personal_skills/{owner}/{skill}/
# ---------------------------------------------------------------------------


def sanitize_owner_dirname(owner_user_id: str) -> str:
    """把 owner_user_id 净化为安全的目录名（白名单外字符转 ``_``）。

    防路径穿越与平台异常字符：``.``/``..``/空串统一回退为 ``_anonymous``，
    确保物化目录恒在 ``.personal_skills`` 根内。
    """
    cleaned = _UNSAFE_DIR_CHARS.sub("_", (owner_user_id or "").strip())
    if not cleaned or cleaned in {".", ".."}:
        return "_anonymous"
    return cleaned


def get_personal_skills_dir(workspace_dir: Path, owner_user_id: str) -> Path:
    """返回某用户在某员工 workspace 下的个人技能物化根目录。"""
    return (
        Path(workspace_dir)
        / PERSONAL_SKILLS_DIRNAME
        / sanitize_owner_dirname(owner_user_id)
    )


def materialize_bundle_files(skill_dir: Path, files: dict[str, Any]) -> bool:
    """把一个 bundle 的 path→content 全树写盘；返回是否写出了 SKILL.md。

    安全：逐个相对路径净化，拒绝 ``..``/绝对路径/穿越出 skill_dir 的条目；
    仅写文本内容（个人技能 files 为 path→str 扁平映射）。幂等：重复物化
    覆盖同名文件。返回 False 表示无有效 SKILL.md（不构成可用技能）。
    """
    if not isinstance(files, dict) or not files:
        return False
    base_resolved = Path(skill_dir).resolve()
    wrote_skill_md = False
    for rel_path, content in files.items():
        normalized = str(rel_path).replace("\\", "/").strip()
        if not normalized or normalized.startswith("/"):
            continue
        if any(part == ".." for part in normalized.split("/")):
            continue
        dest = (Path(skill_dir) / normalized).resolve()
        if not dest.is_relative_to(base_resolved):
            continue
        if not isinstance(content, str):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        if normalized == "SKILL.md":
            wrote_skill_md = True
    return wrote_skill_md


def materialize_owner_bundles(
    workspace_dir: Path,
    owner_user_id: str,
    bundles: list[dict[str, Any]],
) -> Path:
    """把某用户的全部启用个人技能物化到 ``.personal_skills/{owner}/``。

    返回该用户的个人技能根目录（作为 SkillService overlay_dir 注入）。
    禁用行（enabled=False）跳过不物化；每个技能写入独立子目录。
    """
    owner_root = get_personal_skills_dir(workspace_dir, owner_user_id)
    owner_root.mkdir(parents=True, exist_ok=True)
    for bundle in bundles:
        if not bundle.get("enabled", True):
            continue
        name = str(bundle.get("name") or "").strip()
        if not name:
            continue
        skill_dir = owner_root / sanitize_owner_dirname(name)
        materialize_bundle_files(skill_dir, bundle.get("files") or {})
    return owner_root
