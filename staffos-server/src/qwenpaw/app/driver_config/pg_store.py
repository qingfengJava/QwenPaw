# -*- coding: utf-8 -*-
"""PG accessor for driver cards + credentials (``driver_cards`` /
``driver_credentials`` tables).

T12 driver PG 权威：数字员工外部能力（MCP/ACP）驱动卡与其凭据的权威存储。
与档案（``agent_documents``）同构——PG 为持久权威，workspace 下的
``drivers/{protocol}/{name}.yaml`` 与 ``credentials.yaml`` 降级为**投影**
（写入时物化，运行热路径 ``DriverManager.build_drivers`` 仍从文件构建），
本 store 只在应用层（Console/API 经 :class:`DriverConfigService`）读写时参与。

设计要点：

- 引擎来自共享池 ``QWENPAW_PG_DSN``（同其它 PG store 工厂），无 PG 时工厂
  返回 ``None``，调用方保持纯文件平面行为（json 后端零动作）；
- 凭据以 :mod:`security.secret_store`（Fernet）加密成 ``cipher`` 落库，
  明文绝不入库；``env:`` 前缀引用指向进程环境、不可持久化，直接跳过；
- 所有语句参数化、幂等（``ON CONFLICT ... DO UPDATE``），内容未变的幂等
  重放不刷新 ``updated_at``（用 hash 谓词拦截），避免版本/时间抖动。

模块顶层禁止 import sqlalchemy（异步栈约定）：所有依赖在方法内惰性导入。

@author qingfeng
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_store: Optional["DriverPgStore"] = None
_store_lock = threading.Lock()


def _canonical(value: Any) -> str:
    """把可 JSON 序列化的结构归一化为稳定字符串，用于幂等 hash 比对。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _as_mapping(value: Any) -> dict:
    """把 JSONB 列值归一化为 dict（asyncpg 多数返回 dict，防御 str/None）。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            loaded = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _as_bool(value: Any) -> bool:
    """把 text() 可能返回的 str/int/bool 归一化为 bool（防全 str 化污染）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)


class DriverPgStore:
    """Async accessor for the ``driver_cards`` / ``driver_credentials`` tables.

    Shares the pooled engine from ``QWENPAW_PG_DSN``; every statement is
    parameterized and idempotent.
    """

    def __init__(self, engine: Any = None, tenant_id: str = "default") -> None:
        if engine is None:
            from ...db.engine import create_pg_engine

            engine = create_pg_engine()
        self._engine = engine
        self._tenant_id = tenant_id

    # -- cards -------------------------------------------------------------

    async def upsert_card(
        self,
        agent_id: str,
        *,
        name: str,
        protocol: str,
        enabled: bool,
        spec: dict,
        policy: dict,
    ) -> bool:
        """Upsert one driver card; return True only when content changed.

        ``spec`` 承载 endpoint/config/credentials，``policy`` 承载
        DriverPolicy；内容（enabled+spec+policy）未变时为幂等重放，
        不刷新 ``updated_at``、返回 False。
        """
        from datetime import datetime, timezone

        from sqlalchemy import text

        now = datetime.now(timezone.utc)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO driver_cards (tenant_id, agent_id, "
                    "protocol, name, enabled, spec, policy, created_at, "
                    "updated_at) "
                    "VALUES (:tid, :aid, :proto, :name, :enabled, "
                    "CAST(:spec AS JSONB), CAST(:policy AS JSONB), "
                    ":now, :now) "
                    "ON CONFLICT (tenant_id, agent_id, protocol, name) "
                    "DO UPDATE SET enabled = EXCLUDED.enabled, "
                    "spec = EXCLUDED.spec, policy = EXCLUDED.policy, "
                    "updated_at = EXCLUDED.updated_at "
                    "WHERE (CAST(driver_cards.spec AS TEXT) <> "
                    "CAST(EXCLUDED.spec AS TEXT)) "
                    "OR (CAST(driver_cards.policy AS TEXT) <> "
                    "CAST(EXCLUDED.policy AS TEXT)) "
                    "OR (driver_cards.enabled IS DISTINCT FROM "
                    "EXCLUDED.enabled) "
                    "RETURNING 1"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "proto": protocol,
                    "name": name,
                    "enabled": bool(enabled),
                    "spec": _canonical(spec),
                    "policy": _canonical(policy),
                    "now": now,
                },
            )
            row = result.first()
            if row is None:
                # WHERE 拦截 → 内容未变，幂等重放
                logger.debug(
                    "driver card unchanged (idempotent replay): %s/%s",
                    agent_id,
                    name,
                )
                return False
            return True

    async def get_card(
        self,
        agent_id: str,
        name: str,
        *,
        protocol: str,
    ) -> Optional[dict]:
        """Read one card as a normalized dict, or ``None`` when absent."""
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT name, protocol, enabled, spec, policy "
                    "FROM driver_cards WHERE tenant_id = :tid "
                    "AND agent_id = :aid AND protocol = :proto "
                    "AND name = :name"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "proto": protocol,
                    "name": name,
                },
            )
            row = result.mappings().first()
        if row is None:
            return None
        return self._row_to_card(row)

    async def list_cards(
        self,
        agent_id: str,
        *,
        protocol: str | None = None,
    ) -> list[dict]:
        """List cards of one agent, optionally filtered by protocol."""
        from sqlalchemy import text

        sql = (
            "SELECT name, protocol, enabled, spec, policy FROM driver_cards "
            "WHERE tenant_id = :tid AND agent_id = :aid"
        )
        params: dict[str, Any] = {
            "tid": self._tenant_id,
            "aid": agent_id,
        }
        if protocol is not None:
            sql += " AND protocol = :proto"
            params["proto"] = protocol
        sql += " ORDER BY protocol, name"
        async with self._engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            rows = result.mappings().all()
        return [self._row_to_card(row) for row in rows]

    async def delete_card(
        self,
        agent_id: str,
        name: str,
        *,
        protocol: str | None = None,
    ) -> bool:
        """Delete one card (all protocols when ``protocol`` is ``None``)."""
        from sqlalchemy import text

        sql = (
            "DELETE FROM driver_cards WHERE tenant_id = :tid "
            "AND agent_id = :aid AND name = :name"
        )
        params: dict[str, Any] = {
            "tid": self._tenant_id,
            "aid": agent_id,
            "name": name,
        }
        if protocol is not None:
            sql += " AND protocol = :proto"
            params["proto"] = protocol
        async with self._engine.begin() as conn:
            result = await conn.execute(text(sql), params)
        return bool(result.rowcount)

    @staticmethod
    def _row_to_card(row: Any) -> dict:
        """把 DB 行还原为重建 DriverCard 所需的归一化 dict。"""
        return {
            "name": str(row["name"]),
            "protocol": str(row["protocol"]),
            "enabled": _as_bool(row["enabled"]),
            "spec": _as_mapping(row["spec"]),
            "policy": _as_mapping(row["policy"]),
        }

    # -- credentials -------------------------------------------------------

    async def put_credential(
        self,
        agent_id: str,
        record: dict,
    ) -> bool:
        """Encrypt and upsert one credential record; skip ``env:`` refs.

        ``record`` 为 CredentialRecord 归一化 dict（ref/kind/public/
        secrets/meta）。整包 JSON 经 secret_store 加密进 ``cipher``。
        """
        from datetime import datetime, timezone

        from sqlalchemy import text

        ref = str(record.get("ref") or "")
        if not ref or ref.startswith("env:"):
            return False
        from ...security.secret_store import encrypt

        cipher = encrypt(_canonical(record))
        now = datetime.now(timezone.utc)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO driver_credentials (tenant_id, agent_id, "
                    "ref, cipher, created_at, updated_at) "
                    "VALUES (:tid, :aid, :ref, :cipher, :now, :now) "
                    "ON CONFLICT (tenant_id, agent_id, ref) DO UPDATE SET "
                    "cipher = EXCLUDED.cipher, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "ref": ref,
                    "cipher": cipher,
                    "now": now,
                },
            )
        return True

    async def get_credential(
        self,
        agent_id: str,
        ref: str,
    ) -> Optional[dict]:
        """Read and decrypt one credential record, or ``None`` when absent."""
        from sqlalchemy import text

        if not ref or ref.startswith("env:"):
            return None
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT cipher FROM driver_credentials WHERE "
                    "tenant_id = :tid AND agent_id = :aid AND ref = :ref"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "ref": ref,
                },
            )
            row = result.mappings().first()
        if row is None:
            return None
        from ...security.secret_store import decrypt

        payload = decrypt(str(row["cipher"]))
        if not payload:
            return None
        try:
            loaded = json.loads(payload)
        except (ValueError, TypeError):
            logger.warning(
                "driver credential cipher is not valid JSON: %s/%s",
                agent_id,
                ref,
            )
            return None
        return loaded if isinstance(loaded, dict) else None

    async def delete_credential(self, agent_id: str, ref: str) -> bool:
        """Delete one credential row if present; skip ``env:`` refs."""
        from sqlalchemy import text

        if not ref or ref.startswith("env:"):
            return False
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM driver_credentials WHERE tenant_id = :tid "
                    "AND agent_id = :aid AND ref = :ref"
                ),
                {
                    "tid": self._tenant_id,
                    "aid": agent_id,
                    "ref": ref,
                },
            )
        return bool(result.rowcount)

    async def has_any_cards(self, agent_id: str) -> bool:
        """True when the agent already has PG cards (backfill gating)."""
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT 1 FROM driver_cards WHERE tenant_id = :tid "
                    "AND agent_id = :aid LIMIT 1"
                ),
                {"tid": self._tenant_id, "aid": agent_id},
            )
            return result.first() is not None


def driver_pg_plane_available() -> bool:
    """True when a PG DSN is configured (engine creation deferred)."""
    from ...constant import EnvVarLoader
    from ...db.engine import PG_DSN_ENV

    return bool(EnvVarLoader.get_str(PG_DSN_ENV, "").strip())


def get_driver_pg_store() -> Optional[DriverPgStore]:
    """Return the shared store; ``None`` when PostgreSQL is not configured."""
    global _store  # pylint: disable=global-statement
    if _store is not None:
        return _store
    if not driver_pg_plane_available():
        return None
    with _store_lock:
        if _store is None:
            _store = DriverPgStore()
        return _store


def reset_store_for_tests() -> None:
    """Drop the cached singleton（测试切换环境变量后必须调用）。"""
    global _store  # pylint: disable=global-statement
    with _store_lock:
        _store = None
