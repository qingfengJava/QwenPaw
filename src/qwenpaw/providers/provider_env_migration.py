# -*- coding: utf-8 -*-
"""One-shot provider config plane bootstrap (file snapshots + env keys → PG).

在 ``QWENPAW_STORAGE_BACKEND`` 为 ``dual``/``pg`` 时，应用启动后台阶段
执行一次：

1. **文件快照 → PG**：把内存中全部 provider（内置/自定义/插件）整包
   快照 upsert 进 ``provider_configs``（api_key 由 provider_store 统一
   Fernet 加密提升入列）；
2. **active 槽位 → PG**：active_llm 写入 ``model_active_slots``；
3. **env Key 迁移**：仍缺 Key 的厂商按约定环境变量名
   （``{ID大写下划线}_API_KEY`` + 少量别名）从 ``os.environ``（含控制台
   环境变量菜单注入值）取 Key 写入配置；
4. **pg 后端权威读**：从 PG 刷回内存（文件与 env 灌入后的最终态）。

幂等：manifest（``SECRET_DIR/.provider_pg_migrated.json``）成功后落盘，
重复启动直接跳过（pg 后端仍执行第 4 步权威读）。任何一步失败不写
manifest，下次启动自动重试；文件平面始终权威/可用，绝不阻塞启动。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..constant import SECRET_DIR
from . import provider_store
from .provider_model_state import PROVIDER_SNAPSHOT_SCHEMA_VERSION

if TYPE_CHECKING:
    from .provider_manager import ProviderManager

logger = logging.getLogger(__name__)

#: manifest 文件名（落在 SECRET_DIR，参照 backfill_history 范式）
MANIFEST_NAME = ".provider_pg_migrated.json"

#: manifest 版本：投影结构变化时 +1，旧 manifest 自动重跑全量导入
MANIFEST_VERSION = 3

#: 少数厂商的 API Key 环境变量别名（约定名之外的历史习惯）
_PROVIDER_ENV_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "azure-openai": ("AZURE_OPENAI_API_KEY",),
    "zhipu-cn": ("ZHIPU_API_KEY", "ZHIPU_APIKEY"),
    "zhipu-intl": ("ZHIPU_API_KEY", "ZHIPU_APIKEY"),
    "zhipu-cn-codingplan": ("ZHIPU_API_KEY", "ZHIPU_APIKEY"),
    "zhipu-intl-codingplan": ("ZHIPU_API_KEY", "ZHIPU_APIKEY"),
}


def _candidate_env_keys(provider_id: str) -> tuple[str, ...]:
    """Return candidate API key env names for one provider id."""
    aliases = _PROVIDER_ENV_KEY_ALIASES.get(provider_id, ())
    conventional = (f"{provider_id.upper().replace('-', '_')}_API_KEY",)
    # 别名在前（历史习惯优先），约定名兜底；去重保序
    seen: dict[str, None] = {}
    for name in (*aliases, *conventional):
        seen.setdefault(name, None)
    return tuple(seen)


def _provider_dump(
    provider: Any,
    *,
    is_builtin: bool,
) -> dict[str, Any]:
    """Serialize one provider for the PG plane (plain dump + schema ver)."""
    dump = provider.model_dump(exclude={"models_syncing"})
    dump.setdefault(
        "snapshot_schema_version",
        PROVIDER_SNAPSHOT_SCHEMA_VERSION,
    )
    dump["is_builtin"] = is_builtin
    return dump


def _iter_all_providers(manager: "ProviderManager"):
    """Yield ``(provider, is_builtin)`` for every registered provider."""
    for provider in manager.builtin_providers.values():
        yield provider, True
    for provider in manager.custom_providers.values():
        yield provider, False
    for registration in manager.plugin_providers.values():
        yield registration["info"], False


def _manifest_path() -> Path:
    return SECRET_DIR / MANIFEST_NAME


def _file_snapshot_path(provider_id: str) -> Path | None:
    """Locate the file-plane snapshot json for one provider (or None)."""
    for sub in ("builtin", "custom", "plugin"):
        candidate = SECRET_DIR / "providers" / sub / f"{provider_id}.json"
        if candidate.is_file():
            return candidate
    return None


def _file_plane_key_fallback(provider_id: str) -> str:
    """Return the decrypted API key from the file plane ("" if absent).

    兕底防御：内存 dump 丢失 key（如 PG 权威读后又被意外清空）时，
    文件平面往往仍保有最后一次正确密文；导入时用它补空，避免把空
    key 覆盖进 PG 造成凭据丢失。
    """
    path = _file_snapshot_path(provider_id)
    if path is None:
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    cipher = str(data.get("api_key") or "")
    if not cipher.strip():
        return ""
    from ..security.secret_store import decrypt

    try:
        return decrypt(cipher)
    except Exception:  # noqa: BLE001 - 解密失败视为无 key
        return ""


async def _import_file_plane_to_pg(manager: "ProviderManager") -> int:
    """Upsert every in-memory provider snapshot + model rows + slot into PG."""
    count = 0
    for provider, is_builtin in _iter_all_providers(manager):
        dump = _provider_dump(provider, is_builtin=is_builtin)
        # 兕底：内存丢 key 而文件平面仍有时，用文件值补空（绝不覆盖已有）
        pid = str(dump.get("id") or "")
        if (
            dump.get("require_api_key", True)
            and not str(dump.get("api_key") or "").strip()
        ):
            fallback = _file_plane_key_fallback(pid)
            if fallback:
                dump["api_key"] = fallback
                logger.info(
                    "Provider config plane: restored missing API key for "
                    "'%s' from the file plane fallback.",
                    pid,
                )
        await provider_store.upsert_provider_snapshot_pg(dump)
        # 行级模型投影：每厂商每模型一行（参数独立）
        await provider_store.sync_provider_models_pg(
            str(dump.get("id") or ""),
            provider_store.build_model_rows(dump),
        )
        count += 1
    active = manager.active_model
    if active and active.provider_id and active.model:
        await provider_store.save_active_slot_pg(
            provider_store.ACTIVE_SLOT_LLM,
            active.provider_id,
            active.model,
        )
    return count


async def _migrate_env_keys(manager: "ProviderManager") -> list[str]:
    """Fill missing provider API keys from conventional env vars."""
    migrated: list[str] = []
    for provider, _is_builtin in _iter_all_providers(manager):
        # 只补"需要 key 且尚未配置"的厂商；已有配置一律不覆盖
        if not provider.require_api_key or provider.api_key:
            continue
        for env_name in _candidate_env_keys(provider.id):
            value = os.environ.get(env_name, "")
            if not value:
                continue
            # 走标准保存链路：文件平面 + 内存提交 + PG 影子一次完成
            await manager.save_provider_config_async(
                provider.id,
                provider.model_copy(update={"api_key": value}),
            )
            migrated.append(provider.id)
            logger.info(
                "Migrated API key for provider '%s' from env %s "
                "(stored encrypted).",
                provider.id,
                env_name,
            )
            break
    return migrated


async def run_provider_config_migration(
    manager: "ProviderManager",
) -> bool:
    """Run the one-shot provider config plane bootstrap.

    Returns ``True`` when the plane is ready (fresh migration done or
    manifest already present). Never raises: callers treat any failure
    as "file plane remains authoritative this run".
    """
    if not provider_store.pg_provider_plane_available():
        return False

    backend = provider_store.provider_storage_backend()
    manifest = _manifest_path()

    manifest_version = 0
    if manifest.is_file():
        try:
            existing = json.loads(
                manifest.read_text(encoding="utf-8"),
            )
            manifest_version = int(
                existing.get("version") or 0,
            ) if isinstance(existing, dict) else 0
        except (OSError, ValueError):
            manifest_version = 0

    if manifest_version >= MANIFEST_VERSION:
        # 已迁移过：pg 后端仍需每次启动从 PG 刷回内存（权威读）
        if backend == provider_store._BACKEND_PG:  # noqa: SLF001
            try:
                restored = await manager.load_providers_from_pg()
                logger.info(
                    "Provider config plane: restored %d providers from PG.",
                    restored,
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Provider config plane: PG authoritative read failed; "
                    "falling back to file-loaded state.",
                    exc_info=True,
                )
        return True
    # manifest 缺失或版本过旧（如新增行级模型投影）：重跑全量导入

    try:
        imported = await _import_file_plane_to_pg(manager)
        env_migrated = await _migrate_env_keys(manager)
        if backend == provider_store._BACKEND_PG:  # noqa: SLF001
            restored = await manager.load_providers_from_pg()
            logger.info(
                "Provider config plane: %d providers restored from PG "
                "(authoritative read).",
                restored,
            )
    except Exception:  # noqa: BLE001 - 表未就绪/PG 抖动：下次启动重试
        logger.warning(
            "Provider config plane bootstrap failed; will retry on next "
            "startup. File plane remains authoritative.",
            exc_info=True,
        )
        return False

    payload = {
        "version": MANIFEST_VERSION,
        "done_at": datetime.now(timezone.utc).isoformat(),
        "imported_providers": imported,
        "env_key_migrated": env_migrated,
        "backend": backend,
    }
    try:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        logger.warning(
            "Failed to write provider config plane manifest %s; "
            "migration will rerun next startup (idempotent).",
            manifest,
            exc_info=True,
        )
    logger.info(
        "Provider config plane bootstrap done: %d providers imported, "
        "%d env keys migrated (backend=%s).",
        imported,
        len(env_migrated),
        backend,
    )
    return True
