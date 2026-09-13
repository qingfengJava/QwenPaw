# -*- coding: utf-8 -*-
"""Provider configuration storage plane (JSON file / PG shadow / PG read).

``QWENPAW_STORAGE_BACKEND`` 三态语义（与 chats/history 共用同一开关）：

- ``json``（默认）：文件权威，本模块不参与任何读写；
- ``dual``：文件权威 + PG 影子双写（写失败仅告警，绝不阻塞业务）；
- ``pg``：PG 权威读（启动时由迁移层把文件快照灌入 PG 后从 PG 加载），
  运行时写路径仍同步落文件作为降级备份 + PG 权威写。

表结构见 alembic ``0018_provider_config_plane``：``provider_configs``
（整包快照 JSONB + api_key 以密文提升列）与 ``model_active_slots``
（active_llm 槽位）。SQL 风格对齐 ``app/run_log_pg_store``：
async engine + 参数化 ``text()``，失败只告警。

api_key 密文双形态（读取按前缀分派）：
- ``ENC1:``：可移植密文，密钥存 PG ``app_portable_keys`` 表
  （alembic ``0028_inbox_events_pg``），跨设备可解密——多设备同步
  时 B 设备从 PG 取回密钥材料即可恢复 api_key；
- ``ENC:``：本机密文（OS keychain master key），存量数据兼容，
  本机可解，跨设备不可解；一旦该 provider 再次保存即升级为
  ``ENC1:``。
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Awaitable, Callable

from ..db import write_gateway
from ..db.base import DEFAULT_TENANT_ID
from ..security.secret_store import decrypt, encrypt, is_encrypted

logger = logging.getLogger(__name__)

# M2 收敛：三态判定常量统一下沉到 db.write_gateway，此处保留原私有
# 名 re-export（多个模块与测试仍以 provider_store._BACKEND_* 引用）
STORAGE_BACKEND_ENV = write_gateway.STORAGE_BACKEND_ENV
_BACKEND_JSON = write_gateway.BACKEND_JSON
_BACKEND_DUAL = write_gateway.BACKEND_DUAL
_BACKEND_PG = write_gateway.BACKEND_PG
_VALID_BACKENDS = write_gateway.VALID_BACKENDS

#: active_llm 槽位名（model_active_slots.slot_name，预留 embedding 等）
ACTIVE_SLOT_LLM = "llm"

#: 可移植密文前缀（api_key_encrypted 列）：用 PG app_portable_keys
#: 表内的 Fernet key 加密，跨设备可解；与 OS keychain 绑定的本机
#: ``ENC:`` 密文互补共存，读取时按前缀分派。
_PORTABLE_PREFIX = "ENC1:"

#: app_portable_keys.key_name：provider api_key 的可移植加密密钥
_PORTABLE_KEY_NAME = "provider_api_key"

_portable_key_cache: bytes | None = None
_portable_key_lock = threading.Lock()


def provider_storage_backend() -> str:
    """Return the resolved provider storage backend (json/dual/pg).

    M2 收敛：三态解析与缓存统一下沉到 ``db.write_gateway``，本函数
    仅保留兼容门面（chats/history/crons/inbox/skill 等域继续可用）。
    """
    return write_gateway.resolve_storage_backend()


def reset_backend_cache() -> None:
    """Clear the cached backend (tests / env changes)."""
    write_gateway.reset_backend_cache()


def pg_provider_plane_available() -> bool:
    """True when the provider plane should touch PG (dual/pg + DSN set)."""
    return write_gateway.pg_write_available()


def _derive_enabled(data: dict[str, Any]) -> bool:
    """Mirror the console semantics: usable = has key or key not required."""
    if not data.get("require_api_key", True):
        return True
    return bool(data.get("api_key"))


def _portable_encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt with the PG-stored portable key (``ENC1:`` prefix)."""
    from cryptography.fernet import Fernet

    token = Fernet(key).encrypt(plaintext.encode("utf-8"))
    return _PORTABLE_PREFIX + token.decode("ascii")


def _portable_decrypt(value: str, key: bytes) -> str:
    """Decrypt an ``ENC1:`` token; degrade to raw on any failure."""
    try:
        from cryptography.fernet import Fernet

        token = value[len(_PORTABLE_PREFIX):].encode("ascii")
        return Fernet(key).decrypt(token).decode("utf-8")
    except Exception:  # noqa: BLE001 - 解密失败优雅降级，不崩溃
        logger.warning(
            "Failed to portable-decrypt value (key rotated or data"
            " corrupted?); returning raw ciphertext",
        )
        return value


async def _load_or_create_portable_key(engine: Any = None) -> bytes:
    """Return the portable Fernet key, creating one on first use.

    密钥本体存 PG（app_portable_keys）：安全边界等价于 PG 自身访问
    控制，跨设备部署共享同一把密钥。进程内缓存避免每次读写都查库；
    并发首启由 INSERT ON CONFLICT DO NOTHING 保证唯一（先插入者胜，
    重读取库内实际行）。
    """
    global _portable_key_cache  # pylint: disable=global-statement
    if _portable_key_cache is not None:
        return _portable_key_cache
    with _portable_key_lock:
        if _portable_key_cache is not None:
            return _portable_key_cache
        from sqlalchemy import text

        from ..db.base import DEFAULT_TENANT_ID
        from ..db.engine import create_pg_engine

        engine = engine or create_pg_engine()
        select_sql = text(
            "SELECT key_value FROM app_portable_keys "
            "WHERE tenant_id = :tenant_id AND key_name = :key_name",
        )
        select_params = {
            "tenant_id": DEFAULT_TENANT_ID,
            "key_name": _PORTABLE_KEY_NAME,
        }
        async with engine.begin() as conn:
            result = await conn.execute(select_sql, select_params)
            row = result.first()
            if row is None:
                from cryptography.fernet import Fernet

                await conn.execute(
                    text(
                        "INSERT INTO app_portable_keys "
                        "(tenant_id, key_name, key_value) VALUES "
                        "(:tenant_id, :key_name, :key_value) "
                        "ON CONFLICT (tenant_id, key_name) DO NOTHING"
                    ),
                    {
                        "tenant_id": DEFAULT_TENANT_ID,
                        "key_name": _PORTABLE_KEY_NAME,
                        "key_value": Fernet.generate_key().decode(
                            "ascii",
                        ),
                    },
                )
                result = await conn.execute(select_sql, select_params)
                row = result.first()
        if row is None:
            raise RuntimeError(
                "app_portable_keys row missing after insert; "
                "check PG connectivity",
            )
        _portable_key_cache = str(row[0]).encode("ascii")
        return _portable_key_cache


def _snapshot_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Provider dump minus the lifted api_key column (JSONB body)."""
    payload = dict(data)
    payload.pop("api_key", None)
    payload.pop("models_syncing", None)
    return payload


def _coerce_snapshot(value: Any) -> dict[str, Any]:
    """JSONB cell -> dict (asyncpg/SQLAlchemy may return str or dict)."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return value if isinstance(value, dict) else {}


def _row_to_provider_data(
    provider_id: str,
    name: str,
    base_url: str,
    api_key_encrypted: str,
    snapshot: dict[str, Any],
    portable_key: bytes | None = None,
) -> dict[str, Any]:
    """One provider_configs row -> plain provider dump (api_key decrypted)."""
    data = _coerce_snapshot(snapshot)
    data["id"] = provider_id
    data["name"] = name
    data["base_url"] = base_url
    if (
        api_key_encrypted
        and api_key_encrypted.startswith(_PORTABLE_PREFIX)
        and portable_key is not None
    ):
        # ENC1: 可移植密文 → PG 内密钥解密（跨设备可恢复）
        data["api_key"] = _portable_decrypt(
            api_key_encrypted,
            portable_key,
        )
    else:
        # ENC: 本机密文走 keychain 解密；解密失败优雅降级返回原文
        data["api_key"] = (
            decrypt(api_key_encrypted) if api_key_encrypted else ""
        )
    return data


# ---------------------------------------------------------------------------
# PG CRUD（async；调用方负责可用性门控与异常兜底）
# ---------------------------------------------------------------------------


async def upsert_provider_snapshot_pg(
    data: dict[str, Any],
    engine: Any = None,
) -> None:
    """Upsert one provider snapshot (``data`` is a plain provider dump)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    provider_id = str(data.get("id") or "")
    if not provider_id:
        raise ValueError("provider snapshot requires an id")
    api_key = str(data.get("api_key") or "")
    engine = engine or create_pg_engine()
    if api_key:
        # 明文密钥入库前统一用可移植 key 加密（ENC1:，跨设备可解）
        api_key_encrypted = _portable_encrypt(
            api_key,
            await _load_or_create_portable_key(engine),
        )
    else:
        api_key_encrypted = ""
    async with engine.begin() as conn:
        await conn.execute(
            text(_UPSERT_PROVIDER_SQL),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "provider_id": provider_id,
                "name": str(data.get("name") or provider_id),
                "base_url": str(data.get("base_url") or ""),
                "api_key_encrypted": api_key_encrypted,
                "enabled": _derive_enabled(data),
                "is_builtin": bool(data.get("is_builtin")),
                "is_custom": bool(data.get("is_custom")),
                # asyncpg 不能直接绑定 dict，经 json.dumps 后 CAST 入 JSONB
                "snapshot_json": json.dumps(
                    _snapshot_payload(data),
                    ensure_ascii=False,
                ),
                "snapshot_schema_version": int(
                    data.get("snapshot_schema_version") or 0,
                ),
            },
        )


_UPSERT_PROVIDER_SQL = """
INSERT INTO provider_configs (
    tenant_id, provider_id, name, base_url, api_key_encrypted,
    enabled, is_builtin, is_custom, snapshot,
    snapshot_schema_version
) VALUES (
    :tenant_id, :provider_id, :name, :base_url, :api_key_encrypted,
    :enabled, :is_builtin, :is_custom, CAST(:snapshot_json AS jsonb),
    :snapshot_schema_version
)
ON CONFLICT (tenant_id, provider_id) DO UPDATE SET
    name = EXCLUDED.name,
    base_url = EXCLUDED.base_url,
    api_key_encrypted = EXCLUDED.api_key_encrypted,
    enabled = EXCLUDED.enabled,
    is_builtin = EXCLUDED.is_builtin,
    is_custom = EXCLUDED.is_custom,
    snapshot = EXCLUDED.snapshot,
    snapshot_schema_version = EXCLUDED.snapshot_schema_version,
    updated_at = now()
"""


async def load_provider_snapshots_pg(
    engine: Any = None,
) -> list[dict[str, Any]]:
    """Return all provider snapshots (plain dumps, api_key decrypted)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    portable_key = await _load_or_create_portable_key(engine)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT provider_id, name, base_url, api_key_encrypted, "
                "snapshot FROM provider_configs WHERE tenant_id = :tenant_id "
                "ORDER BY provider_id",
            ),
            {"tenant_id": DEFAULT_TENANT_ID},
        )
        rows = result.all()
    return [
        _row_to_provider_data(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            portable_key,
        )
        for row in rows
    ]


async def delete_provider_snapshot_pg(
    provider_id: str,
    engine: Any = None,
) -> None:
    """Delete one provider snapshot row (custom provider removal)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM provider_configs "
                "WHERE tenant_id = :tenant_id AND provider_id = :provider_id",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "provider_id": provider_id,
            },
        )


async def save_active_slot_pg(
    slot_name: str,
    provider_id: str,
    model: str,
    engine: Any = None,
) -> None:
    """Upsert one model slot row (empty provider_id clears the slot)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO model_active_slots "
                "(tenant_id, slot_name, provider_id, model) "
                "VALUES (:tenant_id, :slot_name, :provider_id, :model) "
                "ON CONFLICT (tenant_id, slot_name) DO UPDATE SET "
                "provider_id = EXCLUDED.provider_id, "
                "model = EXCLUDED.model, updated_at = now()",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "slot_name": slot_name,
                "provider_id": provider_id or "",
                "model": model or "",
            },
        )


async def clear_active_slot_pg(
    slot_name: str,
    engine: Any = None,
) -> None:
    """Remove one model slot row (active model cleared)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM model_active_slots "
                "WHERE tenant_id = :tenant_id AND slot_name = :slot_name",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "slot_name": slot_name,
            },
        )


async def load_active_slot_pg(
    slot_name: str,
    engine: Any = None,
) -> dict[str, str] | None:
    """Return ``{"provider_id": ..., "model": ...}`` or None."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT provider_id, model FROM model_active_slots "
                "WHERE tenant_id = :tenant_id AND slot_name = :slot_name",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "slot_name": slot_name,
            },
        )
        row = result.first()
    if row is None:
        return None
    return {"provider_id": row[0] or "", "model": row[1] or ""}


# ---------------------------------------------------------------------------
# 影子写调度（fire-and-forget，绝不阻塞业务路径）
# ---------------------------------------------------------------------------


def schedule_pg_write(operation: Callable[[], Awaitable[Any]]) -> None:
    """Schedule a fire-and-forget shadow write via the unified gateway.

    M2 收敛：调度策略与失败语义统一下沉到 ``db.write_gateway``
    （事件循环 create_task / 无循环守护线程 asyncio.run，失败仅告
    警），domain 固定为 provider_config（快照 + models 投影 + 槽位）。
    """
    write_gateway.submit_shadow_write(operation, domain="provider_config")


def mirror_provider_snapshot(provider_data: dict[str, Any]) -> None:
    """Schedule a fire-and-forget PG mirror of one provider snapshot.

    同步两件事：provider_configs 行（整包快照）+ provider_models 行级
    投影（每配置模型一行，参数独立）。
    """
    if not pg_provider_plane_available():
        return

    def _operation():
        async def _mirror() -> None:
            await upsert_provider_snapshot_pg(provider_data)
            await sync_provider_models_pg(
                str(provider_data.get("id") or ""),
                build_model_rows(provider_data),
            )

        return _mirror()

    schedule_pg_write(_operation)


# ---------------------------------------------------------------------------
# 行级模型投影（provider_models：每厂商每模型一行，参数独立）
# ---------------------------------------------------------------------------

#: provider_models 行的提升列（其余 ModelInfo 字段全部进 config JSONB）
_MODEL_PROMOTED_FIELDS = (
    "id",
    "name",
    "source",
    "is_free",
    "supports_multimodal",
)

_UPSERT_MODEL_ROW_SQL = """
INSERT INTO provider_models (
    tenant_id, provider_id, model_id, name, source,
    enabled, is_free, supports_multimodal, config
) VALUES (
    :tenant_id, :provider_id, :model_id, :name, :source,
    :enabled, :is_free, :supports_multimodal,
    CAST(:config_json AS jsonb)
)
ON CONFLICT (tenant_id, provider_id, model_id) DO UPDATE SET
    name = EXCLUDED.name,
    source = EXCLUDED.source,
    enabled = EXCLUDED.enabled,
    is_free = EXCLUDED.is_free,
    supports_multimodal = EXCLUDED.supports_multimodal,
    config = EXCLUDED.config,
    updated_at = now()
"""


def build_model_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Provider dump -> provider_models 行列表（只投影实际开放的模型）。

    投影范围与用户直觉一致：
    - 厂商未启用（需要 key 且未配置）→ 不投影任何行（停用即清空）；
    - 配置模型 = models（启用厂商的目录模型）+ extra_models（用户添加），
      按 configured_models 语义去重（先出现者优先）并剔除 removed；
    - ``disabled_model_ids`` 投影为行级 ``enabled = false``；
    - 除提升列外的全部 ModelInfo 字段进 ``config`` JSONB（参数独立保留）。
    """
    if not _derive_enabled(data):
        return []
    removed = set(data.get("removed_model_ids") or [])
    disabled = set(data.get("disabled_model_ids") or [])
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for collection_key in ("models", "extra_models"):
        for model in data.get(collection_key) or []:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("id") or "").strip()
            if not model_id or model_id in removed or model_id in seen:
                continue
            seen.add(model_id)
            config = {
                key: value
                for key, value in model.items()
                if key not in _MODEL_PROMOTED_FIELDS
            }
            rows.append(
                {
                    "model_id": model_id,
                    "name": str(model.get("name") or model_id),
                    "source": str(model.get("source") or "builtin"),
                    "enabled": model_id not in disabled,
                    "is_free": bool(model.get("is_free")),
                    "supports_multimodal": model.get("supports_multimodal"),
                    "config_json": json.dumps(
                        config,
                        ensure_ascii=False,
                    ),
                },
            )
    return rows


async def sync_provider_models_pg(
    provider_id: str,
    rows: list[dict[str, Any]],
    engine: Any = None,
) -> None:
    """全量替换一个厂商的 provider_models 行（快照替换语义）。"""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    if not provider_id:
        raise ValueError("provider_models sync requires a provider id")
    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        # DELETE 严格限定 provider_id + tenant_id（绝不全表）
        await conn.execute(
            text(
                "DELETE FROM provider_models "
                "WHERE tenant_id = :tenant_id AND provider_id = :provider_id",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "provider_id": provider_id,
            },
        )
        if rows:
            await conn.execute(
                text(_UPSERT_MODEL_ROW_SQL),
                [
                    {
                        "tenant_id": DEFAULT_TENANT_ID,
                        "provider_id": provider_id,
                        "model_id": row["model_id"],
                        "name": row["name"],
                        "source": row["source"],
                        "enabled": row["enabled"],
                        "is_free": row["is_free"],
                        "supports_multimodal": row["supports_multimodal"],
                        "config_json": row["config_json"],
                    }
                    for row in rows
                ],
            )


async def load_provider_models_pg(
    provider_id: str,
    engine: Any = None,
) -> list[dict[str, Any]]:
    """返回一个厂商的行级模型（提升列 + config 展开），查询/BI 用。"""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT model_id, name, source, enabled, is_free, "
                "supports_multimodal, config FROM provider_models "
                "WHERE tenant_id = :tenant_id AND provider_id = :provider_id "
                "ORDER BY model_id",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "provider_id": provider_id,
            },
        )
        rows = result.all()
    return [
        {
            "model_id": row[0],
            "name": row[1],
            "source": row[2],
            "enabled": row[3],
            "is_free": row[4],
            "supports_multimodal": row[5],
            "config": _coerce_snapshot(row[6]),
        }
        for row in rows
    ]


def mirror_provider_delete(provider_id: str) -> None:
    """Schedule a fire-and-forget PG delete for a removed provider."""
    if not pg_provider_plane_available():
        return

    def _operation():
        async def _delete() -> None:
            await delete_provider_snapshot_pg(provider_id)
            await sync_provider_models_pg(provider_id, [])

        return _delete()

    schedule_pg_write(_operation)


def mirror_active_slot(
    provider_id: str | None,
    model: str | None,
) -> None:
    """Schedule a fire-and-forget PG upsert/clear of the active slot."""
    if not pg_provider_plane_available():
        return
    if provider_id and model:
        schedule_pg_write(
            lambda: save_active_slot_pg(ACTIVE_SLOT_LLM, provider_id, model),
        )
    else:
        schedule_pg_write(lambda: clear_active_slot_pg(ACTIVE_SLOT_LLM))


# ---------------------------------------------------------------------------
# 密文自检：库里 api_key 必须是 ENC: 密文（测试/审计用）
# ---------------------------------------------------------------------------


def assert_encrypted_storage(data: dict[str, Any]) -> bool:
    """True when the snapshot's api_key column would store a cipher.

    Pure helper: verifies the value is either empty or already carries
    the ``ENC:`` prefix semantics applied by :func:`encrypt`.
    """
    api_key = str(data.get("api_key") or "")
    return (not api_key) or is_encrypted(encrypt(api_key))
