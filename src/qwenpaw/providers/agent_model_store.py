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

import logging
from typing import Any

from ..config.config import ModelSlotConfig
from ..db.base import DEFAULT_TENANT_ID
from . import provider_store
from .provider_store import ACTIVE_SLOT_LLM, pg_provider_plane_available

logger = logging.getLogger(__name__)


async def get_agent_model_slot_pg(
    agent_id: str,
    engine: Any = None,
) -> dict[str, str] | None:
    """Return ``{"provider_id": ..., "model": ...}`` for one agent or None."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT provider_id, model FROM agent_model_slots "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND slot_name = :slot_name",
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
    return {"provider_id": row[0] or "", "model": row[1] or ""}


async def upsert_agent_model_slot_pg(
    agent_id: str,
    provider_id: str,
    model: str,
    engine: Any = None,
) -> None:
    """Upsert one agent default model row (agent switches its slot)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agent_model_slots "
                "(tenant_id, agent_id, slot_name, provider_id, model) "
                "VALUES (:tenant_id, :agent_id, :slot_name, "
                ":provider_id, :model) "
                "ON CONFLICT (tenant_id, agent_id, slot_name) DO UPDATE SET "
                "provider_id = EXCLUDED.provider_id, "
                "model = EXCLUDED.model, updated_at = now()",
            ),
            {
                "tenant_id": DEFAULT_TENANT_ID,
                "agent_id": agent_id,
                "slot_name": ACTIVE_SLOT_LLM,
                "provider_id": provider_id or "",
                "model": model or "",
            },
        )


async def clear_agent_model_slot_pg(
    agent_id: str,
    engine: Any = None,
) -> None:
    """Remove one agent slot row (falls back to agent.json / global)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    engine = engine or create_pg_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM agent_model_slots "
                "WHERE tenant_id = :tenant_id AND agent_id = :agent_id "
                "AND slot_name = :slot_name",
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
        )
    return file_slot


def mirror_agent_model_slot(
    agent_id: str,
    provider_id: str,
    model: str,
) -> None:
    """dual 后端：影子写一行（fire-and-forget，失败仅告警）。"""
    provider_store.schedule_pg_write(
        lambda: upsert_agent_model_slot_pg(agent_id, provider_id, model),
    )


async def persist_agent_model_slot(
    agent_id: str,
    provider_id: str,
    model: str,
) -> None:
    """按三态语义把员工默认模型落 PG（json 零动作 / dual 影子 / pg 权威）。

    agent.json 的写入由调用方的既有 ``update_agent_config_async`` 承担
    （json/dual 权威写 + pg 降级备份），本函数只负责 PG 平面。
    """
    backend = provider_store.provider_storage_backend()
    if backend == provider_store._BACKEND_PG:  # noqa: SLF001
        try:
            await upsert_agent_model_slot_pg(agent_id, provider_id, model)
        except Exception:  # noqa: BLE001 - PG plane must never break business
            logger.warning(
                "agent_model_slots authoritative write failed for %s",
                agent_id,
                exc_info=True,
            )
        return
    if backend == provider_store._BACKEND_DUAL:  # noqa: SLF001
        mirror_agent_model_slot(agent_id, provider_id, model)
