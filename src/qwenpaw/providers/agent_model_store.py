# -*- coding: utf-8 -*-
"""Agent default model slot plane (``agent_model_slots`` PG storage).

数字员工默认模型的 PG 落库平面（alembic ``0020_agent_model_slots``，
psql twin: changelog 20260909/07）。三态语义与 ``provider_store`` 完全
一致（共用 ``QWENPAW_STORAGE_BACKEND`` 开关）：

- ``json``（默认）：不触碰 PG，读写均走 agent.json；
- ``dual``：agent.json 权威 + 本表影子双写（fire-and-forget，失败仅告警），
  读取不查本表；
- ``pg``：本表权威读（无行/空槽回退 agent.json 存量兼容），写路径
  agent.json 降级备份 + 本表权威写。

SQL 风格对齐 ``provider_store``：async engine + 参数化 ``text()``，
任何 PG 异常只告警、绝不阻塞业务路径。

@author qingfeng
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config.config import ModelSlotConfig
from ..db.base import DEFAULT_TENANT_ID
from . import provider_store
from .provider_store import ACTIVE_SLOT_LLM, pg_provider_plane_available

logger = logging.getLogger(__name__)


# 员工级模型参数覆盖字段（ModelSlotConfig 可选覆盖字段全集，与
# agent_model_slots.config JSONB 列一一对应；None=跟随全局基线）
_OVERRIDE_FIELDS = (
    "max_input_length",
    "thinking_enabled",
    "thinking_budget",
    "reasoning_effort",
)


def _config_to_json(slot: ModelSlotConfig | None) -> str | None:
    """Serialize a slot's override fields to the ``config`` JSONB payload.

    全部覆盖字段均为空时返回 None（列存 NULL，语义与旧行完全兼容）。"""
    if slot is None:
        return None
    payload = {
        field: getattr(slot, field)
        for field in _OVERRIDE_FIELDS
        if getattr(slot, field) is not None
    }
    return json.dumps(payload, ensure_ascii=False) if payload else None


def _json_to_overrides(raw: Any) -> dict[str, Any]:
    """Parse the ``config`` JSONB column into validated override fields.

    任何脏数据（非 dict / 非法 JSON / 未知字段）只告警并丢弃，
    绝不让 PG 平面的读路径阻塞业务。"""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning(
                "agent_model_slots.config is not valid JSON; ignored",
            )
            return {}
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, Any] = {}
    try:
        probe = ModelSlotConfig(provider_id="", model="", **{
            field: raw[field] for field in _OVERRIDE_FIELDS if field in raw
        })
    except Exception:  # noqa: BLE001 - dirty data must never break reads
        logger.warning(
            "agent_model_slots.config has invalid override fields; ignored",
            exc_info=True,
        )
        return {}
    for field in _OVERRIDE_FIELDS:
        value = getattr(probe, field)
        if value is not None:
            overrides[field] = value
    return overrides


async def get_agent_model_slot_pg(
    agent_id: str,
    engine: Any = None,
) -> dict[str, Any] | None:
    """Return the agent's active model profile or None.

    返回激活档案 ``{"provider_id", "model", "overrides"}``：
    前两项为槽位模型，``overrides`` 为该模型的参数档案
    （空 dict=未覆盖，跟随全局基线）。"""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT provider_id, model, config FROM agent_model_slots "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND slot_name = :slot_name AND is_active",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "slot_name": ACTIVE_SLOT_LLM,
            },
        )
        row = result.first()
    if row is None:
        return None
    return {
        "provider_id": row[0] or "",
        "model": row[1] or "",
        "overrides": _json_to_overrides(row[2]),
    }


async def get_agent_model_profile_pg(
    agent_id: str,
    provider_id: str,
    model: str,
    engine: Any = None,
) -> dict[str, Any]:
    """Return one model profile's overrides (empty dict if absent).

    读取指定模型的参数档案（不管是否激活），供切换模型时把
    目标档案参数写入文件平面快照；档案不存在返回空 dict。"""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT config FROM agent_model_slots "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND slot_name = :slot_name "
                "AND provider_id = :provider_id AND model = :model",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "slot_name": ACTIVE_SLOT_LLM,
                "provider_id": provider_id or "",
                "model": model or "",
            },
        )
        row = result.first()
    return _json_to_overrides(row[0]) if row is not None else {}


async def upsert_agent_model_slot_pg(
    agent_id: str,
    provider_id: str,
    model: str,
    overrides: dict[str, Any] | None = None,
    engine: Any = None,
) -> None:
    """Activate one agent model profile (agent switches its slot).

    档案语义：一行 = 员工×模型的参数档案。本函数单事务两步：
    ① 同槽位所有档案行全部取消激活；② 目标模型档案行置为激活
    （不存在则新建，config 缺省 NULL=跟随全局基线）。
    *overrides* 为写入目标档案的参数（字段级 None=清除该项覆盖）；
    None 表示不改该档案既有 config（切回旧模型即恢复历史参数）。"""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    # 两种 SQL 形态：overrides=None 时完全不触碰 config 列
    # （新档案 INSERT 缺省 NULL，已有档案保留既有参数）；
    # 注意 INSERT VALUES 部分不可引用列名（PostgreSQL UndefinedColumnError）
    if overrides is None:
        upsert_sql = text(
            "INSERT INTO agent_model_slots "
            "(tenant_id, agent_id, slot_name, provider_id, model, is_active) "
            "VALUES (:tenant_id, :agent_id, :slot_name, "
            ":provider_id, :model, TRUE) "
            "ON CONFLICT (tenant_id, agent_id, slot_name, provider_id, model) "
            "DO UPDATE SET is_active = TRUE, updated_at = now()",
        )
    else:
        upsert_sql = text(
            "INSERT INTO agent_model_slots "
            "(tenant_id, agent_id, slot_name, provider_id, model, "
            "config, is_active) "
            "VALUES (:tenant_id, :agent_id, :slot_name, "
            ":provider_id, :model, :config, TRUE) "
            "ON CONFLICT (tenant_id, agent_id, slot_name, provider_id, model) "
            "DO UPDATE SET is_active = TRUE, "
            "config = EXCLUDED.config, updated_at = now()",
        )
    base_params = {
        "tenant_id": DEFAULT_TENANT_ID,
        "agent_id": agent_id,
        "slot_name": ACTIVE_SLOT_LLM,
        "provider_id": provider_id or "",
        "model": model or "",
    }
    async with engine.begin() as conn:
        # ① 取消同槽位全部激活档案（唯一激活索引保证至多一行）
        await conn.execute(
            text(
                "UPDATE agent_model_slots SET is_active = FALSE "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND slot_name = :slot_name AND is_active",
            ),
            base_params,
        )
        # ② 激活目标档案（不存在则建档）
        if overrides is None:
            await conn.execute(upsert_sql, base_params)
        else:
            await conn.execute(
                upsert_sql,
                {
                    **base_params,
                    "config": _config_to_json(
                        ModelSlotConfig(provider_id="", model="", **overrides),
                    ),
                },
            )


async def clear_agent_model_slot_pg(
    agent_id: str,
    engine: Any = None,
) -> None:
    """Deactivate the agent's active profile (falls back to global).

    仅删除激活档案行（员工回到跟随全局默认）；其余模型的参数
    档案保留，再次切换时历史参数记忆仍在。"""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM agent_model_slots "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND slot_name = :slot_name AND is_active",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "slot_name": ACTIVE_SLOT_LLM,
            },
        )


# ---------------------------------------------------------------------------
# 统一解析与三态写入口（业务路径唯一接触面）
# ---------------------------------------------------------------------------


async def resolve_agent_active_model(
    agent_id: str,
    agent_config: Any,
) -> ModelSlotConfig | None:
    """Resolve one agent's effective default model.

    优先级：pg 后端下 ``agent_model_slots`` 行（权威）→
    ``agent_config.active_model``（json/dual 权威 + pg 存量兼容）。
    PG 不可用/读取失败/槽位为空一律静默回退文件平面，绝不阻塞。
    """
    file_slot: ModelSlotConfig | None = getattr(
        agent_config,
        "active_model",
        None,
    )
    # 仅 pg 后端读本表；json/dual 的读取权威在 agent.json（与 provider 平面一致）
    if not pg_provider_plane_available():
        return file_slot
    if provider_store.provider_storage_backend() != provider_store._BACKEND_PG:  # noqa: SLF001
        return file_slot
    try:
        row = await get_agent_model_slot_pg(agent_id)
    except Exception:  # noqa: BLE001 - PG plane must never break business
        logger.warning(
            "agent_model_slots read failed for agent %s; "
            "falling back to file plane",
            agent_id,
            exc_info=True,
        )
        return file_slot
    if row and row.get("provider_id") and row.get("model"):
        return ModelSlotConfig(
            provider_id=row["provider_id"],
            model=row["model"],
            **row.get("overrides", {}),
        )
    return file_slot


def mirror_agent_model_slot(
    agent_id: str,
    provider_id: str,
    model: str,
    overrides: dict[str, Any] | None = None,
) -> None:
    """dual 后端：影子写一行（fire-and-forget，失败仅告警）。"""
    provider_store.schedule_pg_write(
        lambda: upsert_agent_model_slot_pg(
            agent_id,
            provider_id,
            model,
            overrides=overrides,
        ),
    )


async def persist_agent_model_slot(
    agent_id: str,
    provider_id: str,
    model: str,
    overrides: dict[str, Any] | None = None,
) -> None:
    """按三态语义把员工默认模型及参数覆盖落 PG。

    agent.json 的写入由调用方的既有 ``update_agent_config_async`` 承担
    （json/dual 权威写 + pg 降级备份），本函数只负责 PG 平面。
    overrides=None 语义为"不修改既有覆盖"（模型切换不碰参数）；
    字段级清除覆盖由调用方传显式空 dict/字段 None。"""
    backend = provider_store.provider_storage_backend()
    if backend == provider_store._BACKEND_PG:  # noqa: SLF001
        try:
            await upsert_agent_model_slot_pg(
                agent_id,
                provider_id,
                model,
                overrides=overrides,
            )
        except Exception:  # noqa: BLE001 - PG plane must never break business
            logger.warning(
                "agent_model_slots authoritative write failed for %s",
                agent_id,
                exc_info=True,
            )
        return
    if backend == provider_store._BACKEND_DUAL:  # noqa: SLF001
        mirror_agent_model_slot(
            agent_id,
            provider_id,
            model,
            overrides=overrides,
        )
