# -*- coding: utf-8 -*-
"""Ontology PG 存储平面（T4，0047）：七表 CRUD 与就绪探测。

与 ``kb/pg_store.py`` 同款约定：

- **仅 PG，无 json 面**——本体是 enterprise-engine 数据面，json 后端
  下整个平面不可用（``ont_pg_plane_available`` 静态三态判定），调用方
  fail-soft 降级；
- **专用引擎**（``dedicated=True``）——协程全部经服务层桥接循环执行，
  不与全局池共享（避免 asyncpg 跨 loop 连接腐蚀）；
- **正缓存永久 / 负缓存 TTL** 的表就绪探测（迁移补跑后同进程自愈）；
- 写入 ``ON CONFLICT (tenant_id, id) DO NOTHING`` + rowcount 语义，
  读链 ``_row_value`` 容缺转换。

@author qingfeng
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ...db.base import DEFAULT_TENANT_ID
from ...db import write_gateway
from .models import (
    KbObjectLink,
    OntologyAction,
    OntologyObject,
    OntologyRelation,
    OntologyRule,
    OntologyStateTransition,
    OntologyType,
)

logger = logging.getLogger(__name__)

#: 表就绪探测涉及的七张表（缺一不可走本体平面）
_ONT_TABLES = (
    "ontology_types",
    "ontology_objects",
    "ontology_relations",
    "ontology_state_transitions",
    "ontology_rules",
    "ontology_actions",
    "kb_object_links",
)

#: 负探测结果的重试间隔（秒）；正结果永久缓存
NOT_READY_RETRY_SECONDS = 60.0

#: 列投影（读写共用同一份字面量，列名漂移在读链早失败）
_TYPE_COLUMNS = (
    "SELECT id, name, layer, parent_id, description, "
    "attributes_schema, created_at"
)
_OBJECT_COLUMNS = (
    "SELECT id, type_id, name, aliases, attributes, state, state_detail, "
    "owner_id, org_id, department_id, status, source, evidence_refs, "
    "is_delete, created_at, updated_at"
)
_RELATION_COLUMNS = (
    "SELECT id, type, from_type, from_id, to_type, to_id, valid_from, "
    "valid_to, confidence, source, evidence_refs, created_at"
)
_TRANSITION_COLUMNS = (
    "SELECT id, object_id, from_state, to_state, trigger_type, "
    "preconditions, permission, postconditions, audit_required, created_at"
)
_RULE_COLUMNS = (
    "SELECT id, name, scope, object_type, priority, conditions, "
    "then_actions, else_actions, effective_from, version, evidence_refs, "
    "created_at"
)
_ACTION_COLUMNS = (
    "SELECT id, name, object_type, input_schema, preconditions, policy, "
    "approval, execution, postconditions, rollback, auditable, created_at"
)
_LINK_COLUMNS = (
    "SELECT id, kb_space_id, kb_document_id, object_type, object_id, "
    "relation, created_at"
)

#: 对象可更新字段白名单：列名 → SET 片段（键名枚举安全，值走绑定参数）。
#: ``updated_at`` 由每条 UPDATE 恒置 ``now()``，不在白名单。
_OBJECT_ASSIGNMENTS = {
    "name": "name = :name",
    "aliases": "aliases = CAST(:aliases AS JSONB)",
    "attributes": "attributes = CAST(:attributes AS JSONB)",
    "state": "state = :state",
    "state_detail": "state_detail = CAST(:state_detail AS JSONB)",
    "owner_id": "owner_id = :owner_id",
    "org_id": "org_id = :org_id",
    "department_id": "department_id = :department_id",
    "status": "status = :status",
    "source": "source = :source",
    "evidence_refs": "evidence_refs = CAST(:evidence_refs AS JSONB)",
}

_store: Optional["PgOntologyStore"] = None
_store_lock = threading.Lock()


def ont_pg_plane_available() -> bool:
    """True when the ontology plane may touch PG (dual/pg backend + DSN).

    静态三态判定复用写网关（不复制判定逻辑、不自行判 DSN）；表是否
    建好需 :meth:`PgOntologyStore.ensure_ready`（await 探测）。
    """
    return write_gateway.pg_write_available()


def _json_dumps(value: Any) -> str:
    """Serialize a JSONB payload (dict/list) to a compact JSON string."""
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _json_loads(raw: Any, default: Any) -> Any:
    """Decode a JSONB column that may arrive as ``str`` or already ``dict``."""
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("ontology pg jsonb decode failed, fallback default")
        return default


def _row_value(row: Any, key: str) -> Any:
    """Read one column from a mapping row, tolerating absent keys."""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _stamp_kwargs(row: Any, key: str) -> dict:
    """Build constructor kwargs for one NOT NULL timestamptz column."""
    value = _row_value(row, key)
    if not isinstance(value, datetime):
        raise KeyError(
            f"ontology pg row is missing datetime column {key!r}; "
            "check the SELECT column list against alembic 0047",
        )
    return {key: value}


def _opt_stamp(row: Any, key: str) -> Optional[datetime]:
    """Read one nullable timestamptz column（缺列/非时间落 None）。"""
    value = _row_value(row, key)
    return value if isinstance(value, datetime) else None


# ---------------------------------------------------------------------------
# row -> model 转换（模块级，测试可直接构造 mapping 行驱动）
# ---------------------------------------------------------------------------


def type_from_row(row: Any) -> OntologyType:
    """Build an :class:`OntologyType` from one ``ontology_types`` row."""
    return OntologyType(
        id=str(_row_value(row, "id") or ""),
        name=str(_row_value(row, "name") or ""),
        layer=str(_row_value(row, "layer") or "L1"),
        parent_id=str(_row_value(row, "parent_id") or ""),
        description=str(_row_value(row, "description") or ""),
        attributes_schema=_json_loads(
            _row_value(row, "attributes_schema"), {},
        ),
        **_stamp_kwargs(row, "created_at"),
    )


def object_from_row(row: Any) -> OntologyObject:
    """Build an :class:`OntologyObject` from one ``ontology_objects`` row."""
    return OntologyObject(
        id=str(_row_value(row, "id") or ""),
        type_id=str(_row_value(row, "type_id") or ""),
        name=str(_row_value(row, "name") or ""),
        aliases=_json_loads(_row_value(row, "aliases"), []),
        attributes=_json_loads(_row_value(row, "attributes"), {}),
        state=str(_row_value(row, "state") or ""),
        state_detail=_json_loads(_row_value(row, "state_detail"), {}),
        owner_id=str(_row_value(row, "owner_id") or ""),
        org_id=str(_row_value(row, "org_id") or ""),
        department_id=str(_row_value(row, "department_id") or ""),
        status=str(_row_value(row, "status") or "active"),
        source=str(_row_value(row, "source") or "manual"),
        evidence_refs=_json_loads(_row_value(row, "evidence_refs"), []),
        is_delete=bool(_row_value(row, "is_delete")),
        **_stamp_kwargs(row, "created_at"),
        **_stamp_kwargs(row, "updated_at"),
    )


def relation_from_row(row: Any) -> OntologyRelation:
    """Build one :class:`OntologyRelation` from a mapping row."""
    return OntologyRelation(
        id=str(_row_value(row, "id") or ""),
        type=str(_row_value(row, "type") or ""),
        from_type=str(_row_value(row, "from_type") or ""),
        from_id=str(_row_value(row, "from_id") or ""),
        to_type=str(_row_value(row, "to_type") or ""),
        to_id=str(_row_value(row, "to_id") or ""),
        valid_from=_opt_stamp(row, "valid_from"),
        valid_to=_opt_stamp(row, "valid_to"),
        confidence=float(_row_value(row, "confidence") or 1.0),
        source=str(_row_value(row, "source") or "manual"),
        evidence_refs=_json_loads(_row_value(row, "evidence_refs"), []),
        **_stamp_kwargs(row, "created_at"),
    )


def transition_from_row(row: Any) -> OntologyStateTransition:
    """Build one :class:`OntologyStateTransition` from a mapping row."""
    return OntologyStateTransition(
        id=str(_row_value(row, "id") or ""),
        object_id=str(_row_value(row, "object_id") or ""),
        from_state=str(_row_value(row, "from_state") or ""),
        to_state=str(_row_value(row, "to_state") or ""),
        trigger_type=str(_row_value(row, "trigger_type") or ""),
        preconditions=_json_loads(_row_value(row, "preconditions"), {}),
        permission=str(_row_value(row, "permission") or ""),
        postconditions=_json_loads(_row_value(row, "postconditions"), {}),
        audit_required=bool(_row_value(row, "audit_required")),
        **_stamp_kwargs(row, "created_at"),
    )


def rule_from_row(row: Any) -> OntologyRule:
    """Build an :class:`OntologyRule` from one ``ontology_rules`` row."""
    return OntologyRule(
        id=str(_row_value(row, "id") or ""),
        name=str(_row_value(row, "name") or ""),
        scope=str(_row_value(row, "scope") or ""),
        object_type=str(_row_value(row, "object_type") or ""),
        priority=int(_row_value(row, "priority") or 3),
        conditions=_json_loads(_row_value(row, "conditions"), {}),
        then_actions=_json_loads(_row_value(row, "then_actions"), {}),
        else_actions=_json_loads(_row_value(row, "else_actions"), {}),
        effective_from=_opt_stamp(row, "effective_from"),
        version=int(_row_value(row, "version") or 1),
        evidence_refs=_json_loads(_row_value(row, "evidence_refs"), []),
        **_stamp_kwargs(row, "created_at"),
    )


def action_from_row(row: Any) -> OntologyAction:
    """Build an :class:`OntologyAction` from one ``ontology_actions`` row."""
    return OntologyAction(
        id=str(_row_value(row, "id") or ""),
        name=str(_row_value(row, "name") or ""),
        object_type=str(_row_value(row, "object_type") or ""),
        input_schema=_json_loads(_row_value(row, "input_schema"), {}),
        preconditions=_json_loads(_row_value(row, "preconditions"), {}),
        policy=_json_loads(_row_value(row, "policy"), {}),
        approval=_json_loads(_row_value(row, "approval"), {}),
        execution=_json_loads(_row_value(row, "execution"), {}),
        postconditions=_json_loads(_row_value(row, "postconditions"), {}),
        rollback=_json_loads(_row_value(row, "rollback"), {}),
        auditable=bool(_row_value(row, "auditable")),
        **_stamp_kwargs(row, "created_at"),
    )


def link_from_row(row: Any) -> KbObjectLink:
    """Build a :class:`KbObjectLink` from one ``kb_object_links`` row."""
    return KbObjectLink(
        id=str(_row_value(row, "id") or ""),
        kb_space_id=str(_row_value(row, "kb_space_id") or ""),
        kb_document_id=str(_row_value(row, "kb_document_id") or ""),
        object_type=str(_row_value(row, "object_type") or ""),
        object_id=str(_row_value(row, "object_id") or ""),
        relation=str(_row_value(row, "relation") or "knowledge_mentions"),
        **_stamp_kwargs(row, "created_at"),
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class PgOntologyStore:
    """Async accessor for the ontology PG tables (alembic 0047).

    Engine 懒取专用池（同 KbPgStore 约定）；所有方法 fail-soft 由
    调用方决定——store 层只保证「平面不可用返回空值/False」。
    """

    def __init__(
        self,
        engine: Any = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        self._engine = engine
        self._tenant_id = tenant_id
        self._tables_ready: Optional[bool] = None
        self._tables_checked_at: float = 0.0

    # ------------------------------------------------------------------
    # engine / readiness
    # ------------------------------------------------------------------

    def _get_engine(self) -> Any:
        """Materialize a dedicated pooled engine from the PG DSN."""
        if self._engine is None:
            from ...db.engine import create_pg_engine

            self._engine = create_pg_engine(dedicated=True)
        return self._engine

    async def _probe_tables_async(self) -> bool:
        """Single round-trip ``to_regclass`` probe over seven tables."""
        from sqlalchemy import text

        columns = ", ".join(
            f"to_regclass('public.{name}')" for name in _ONT_TABLES
        )
        async with self._get_engine().connect() as conn:
            row = (await conn.execute(text(f"SELECT {columns}"))).fetchone()
        return bool(row) and all(value is not None for value in row)

    async def ensure_ready(self) -> bool:
        """True when PG is reachable and every ontology table exists.

        正结果永久缓存；负结果只缓存 :data:`NOT_READY_RETRY_SECONDS`；
        探测异常不写缓存（网络抖动不应把平面永久降级）。
        """
        if not ont_pg_plane_available():
            return False
        if self._tables_ready is True:
            return True
        cooled = (
            time.monotonic() - self._tables_checked_at
        ) < NOT_READY_RETRY_SECONDS
        if self._tables_ready is False and cooled:
            return False
        self._tables_checked_at = time.monotonic()
        try:
            self._tables_ready = await self._probe_tables_async()
        except Exception:  # pylint: disable=broad-except
            logger.warning("ontology tables probe failed", exc_info=True)
            return False
        if not self._tables_ready:
            logger.warning(
                "ontology tables missing; re-check after "
                "`alembic upgrade head`",
            )
        return self._tables_ready

    # ------------------------------------------------------------------
    # type ops（种子后只读为主，不提供写路径）
    # ------------------------------------------------------------------

    async def list_types(self, layer: str = "") -> List[OntologyType]:
        """List ontology types（layer 过滤；L0/L1 种子 + 自定义分层）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = f"{_TYPE_COLUMNS} FROM ontology_types WHERE tenant_id = :tid"
        params: Dict[str, Any] = {"tid": self._tenant_id}
        if layer:
            sql += " AND layer = :layer"
            params["layer"] = layer
        sql += " ORDER BY layer, id"
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(text(sql), params)
            ).mappings().all()
        return [type_from_row(row) for row in rows]

    async def get_type(self, type_id: str) -> Optional[OntologyType]:
        """Fetch one type by id（引用完整性校验的底层查询）。"""
        if not await self.ensure_ready():
            return None
        from sqlalchemy import text

        sql = (
            f"{_TYPE_COLUMNS} FROM ontology_types "
            "WHERE tenant_id = :tid AND id = :tid2"
        )
        async with self._get_engine().connect() as conn:
            row = (
                await conn.execute(
                    text(sql),
                    {"tid": self._tenant_id, "tid2": type_id},
                )
            ).mappings().first()
        return type_from_row(row) if row is not None else None

    # ------------------------------------------------------------------
    # object ops
    # ------------------------------------------------------------------

    async def create_object(self, obj: OntologyObject) -> bool:
        """Insert one object; False when the id already exists."""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO ontology_objects (tenant_id, id, type_id, "
                    "name, aliases, attributes, state, state_detail, "
                    "owner_id, org_id, department_id, status, source, "
                    "evidence_refs, is_delete) "
                    "VALUES (:tid, :id, :type_id, :name, "
                    "CAST(:aliases AS JSONB), CAST(:attributes AS JSONB), "
                    ":state, CAST(:state_detail AS JSONB), :owner_id, "
                    ":org_id, :department_id, :status, :source, "
                    "CAST(:evidence_refs AS JSONB), :is_delete) "
                    "ON CONFLICT (tenant_id, id) DO NOTHING",
                ),
                {
                    "tid": self._tenant_id,
                    "id": obj.id,
                    "type_id": obj.type_id,
                    "name": obj.name,
                    "aliases": _json_dumps(obj.aliases),
                    "attributes": _json_dumps(obj.attributes),
                    "state": obj.state,
                    "state_detail": _json_dumps(obj.state_detail),
                    "owner_id": obj.owner_id,
                    "org_id": obj.org_id,
                    "department_id": obj.department_id,
                    "status": obj.status,
                    "source": obj.source,
                    "evidence_refs": _json_dumps(obj.evidence_refs),
                    "is_delete": obj.is_delete,
                },
            )
        return result.rowcount > 0

    async def get_object(
        self,
        object_id: str,
        *,
        include_deleted: bool = False,
    ) -> Optional[OntologyObject]:
        """Fetch one live object（默认过滤逻辑删除行）。"""
        if not await self.ensure_ready():
            return None
        from sqlalchemy import text

        sql = (
            f"{_OBJECT_COLUMNS} FROM ontology_objects "
            "WHERE tenant_id = :tid AND id = :oid"
        )
        if not include_deleted:
            sql += " AND is_delete = FALSE"
        async with self._get_engine().connect() as conn:
            row = (
                await conn.execute(
                    text(sql),
                    {"tid": self._tenant_id, "oid": object_id},
                )
            ).mappings().first()
        return object_from_row(row) if row is not None else None

    async def list_objects(
        self,
        type_id: str = "",
        org_id: str = "",
        department_id: str = "",
        status: str = "",
        keyword: str = "",
        limit: int = 200,
    ) -> List[OntologyObject]:
        """List live objects（多条件 AND 过滤；keyword 匹配 name ILIKE）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = (
            f"{_OBJECT_COLUMNS} FROM ontology_objects "
            "WHERE tenant_id = :tid AND is_delete = FALSE"
        )
        params: Dict[str, Any] = {"tid": self._tenant_id}
        if type_id:
            sql += " AND type_id = :type_id"
            params["type_id"] = type_id
        if org_id:
            sql += " AND org_id = :org_id"
            params["org_id"] = org_id
        if department_id:
            sql += " AND department_id = :department_id"
            params["department_id"] = department_id
        if status:
            sql += " AND status = :status"
            params["status"] = status
        if keyword:
            # 名称与别名同时命中（aliases JSONB 序列化文本 ILIKE，
            # T5 grounding 依赖：Agent 侧传来的实体名常是别名形态）
            sql += " AND (name ILIKE :kw OR aliases::text ILIKE :kw)"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY updated_at DESC, id LIMIT :lim"
        params["lim"] = max(1, int(limit))
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(text(sql), params)
            ).mappings().all()
        return [object_from_row(row) for row in rows]

    async def update_object(
        self,
        object_id: str,
        fields: Dict[str, Any],
    ) -> bool:
        """Patch whitelisted fields + ``updated_at``; False when absent.

        空白名单直接返回 False（没有可写内容），不空转一次 UPDATE。
        """
        assignments = [
            fragment
            for key, fragment in _OBJECT_ASSIGNMENTS.items()
            if key in fields
        ]
        if not assignments:
            return False
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        params: Dict[str, Any] = {"tid": self._tenant_id, "oid": object_id}
        for key in _OBJECT_ASSIGNMENTS:
            if key not in fields:
                continue
            value = fields[key]
            if isinstance(value, (dict, list)):
                params[key] = _json_dumps(value)
            else:
                params[key] = value
        sql = (
            "UPDATE ontology_objects SET "
            + ", ".join(assignments)
            + ", updated_at = now() "
            "WHERE tenant_id = :tid AND id = :oid AND is_delete = FALSE"
        )
        async with self._get_engine().begin() as conn:
            result = await conn.execute(text(sql), params)
        return result.rowcount > 0

    async def soft_delete_object(self, object_id: str) -> bool:
        """Mark one object deleted（逻辑删除守项目规范；行保留可追溯）。"""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE ontology_objects SET is_delete = TRUE, "
                    "updated_at = now() "
                    "WHERE tenant_id = :tid AND id = :oid "
                    "AND is_delete = FALSE",
                ),
                {"tid": self._tenant_id, "oid": object_id},
            )
        return result.rowcount > 0

    # ------------------------------------------------------------------
    # relation ops
    # ------------------------------------------------------------------

    async def create_relation(self, rel: OntologyRelation) -> bool:
        """Insert one directed relation; False when the id already exists."""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO ontology_relations (tenant_id, id, type, "
                    "from_type, from_id, to_type, to_id, valid_from, "
                    "valid_to, confidence, source, evidence_refs) "
                    "VALUES (:tid, :id, :rtype, :from_type, :from_id, "
                    ":to_type, :to_id, :valid_from, :valid_to, "
                    ":confidence, :source, CAST(:evidence_refs AS JSONB)) "
                    "ON CONFLICT (tenant_id, id) DO NOTHING",
                ),
                {
                    "tid": self._tenant_id,
                    "id": rel.id,
                    "rtype": rel.type,
                    "from_type": rel.from_type,
                    "from_id": rel.from_id,
                    "to_type": rel.to_type,
                    "to_id": rel.to_id,
                    "valid_from": rel.valid_from,
                    "valid_to": rel.valid_to,
                    "confidence": rel.confidence,
                    "source": rel.source,
                    "evidence_refs": _json_dumps(rel.evidence_refs),
                },
            )
        return result.rowcount > 0

    async def list_relations(
        self,
        from_id: str = "",
        to_id: str = "",
        rel_type: str = "",
        limit: int = 200,
    ) -> List[OntologyRelation]:
        """List relations（端点/类型过滤；T5 CTE 遍历的平铺底座）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = (
            f"{_RELATION_COLUMNS} FROM ontology_relations "
            "WHERE tenant_id = :tid"
        )
        params: Dict[str, Any] = {"tid": self._tenant_id}
        if from_id:
            sql += " AND from_id = :from_id"
            params["from_id"] = from_id
        if to_id:
            sql += " AND to_id = :to_id"
            params["to_id"] = to_id
        if rel_type:
            sql += " AND type = :rtype"
            params["rtype"] = rel_type
        sql += " ORDER BY created_at DESC, id LIMIT :lim"
        params["lim"] = max(1, int(limit))
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(text(sql), params)
            ).mappings().all()
        return [relation_from_row(row) for row in rows]

    async def get_objects_batch(
        self,
        object_ids: List[str],
    ) -> List[OntologyObject]:
        """Fetch live objects by ids in one round-trip（禁 N+1）。"""
        if not object_ids or not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = (
            f"{_OBJECT_COLUMNS} FROM ontology_objects "
            "WHERE tenant_id = :tid AND is_delete = FALSE "
            "AND id = ANY(:ids) ORDER BY updated_at DESC, id"
        )
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(sql),
                    {"tid": self._tenant_id, "ids": list(object_ids)},
                )
            ).mappings().all()
        return [object_from_row(row) for row in rows]

    async def graph_from_objects(
        self,
        seed_ids: List[str],
        max_depth: int = 3,
        limit: int = 100,
    ) -> List[Tuple[str, str, str, int]]:
        """BFS relations from seed objects via ``WITH RECURSIVE``（≤depth）。

        T5 只读运行时的图遍历底座（spec §3：不引入图数据库，PG CTE
        ≤3 跳）。返回 ``(from_id, to_id, type, depth)`` 元组列表，
        depth 从 1 起（种子直接出边）。
        """
        if not seed_ids or not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = """
WITH RECURSIVE walk AS (
    SELECT from_id, to_id, type, 1 AS depth
    FROM ontology_relations
    WHERE tenant_id = :tid AND from_id = ANY(:seeds)
  UNION ALL
    SELECT r.from_id, r.to_id, r.type, w.depth + 1
    FROM ontology_relations r
    JOIN walk w ON r.from_id = w.to_id
    WHERE r.tenant_id = :tid AND w.depth < :max_depth
)
SELECT DISTINCT from_id, to_id, type, depth
FROM walk
ORDER BY depth, from_id, to_id
LIMIT :lim"""
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(sql),
                    {
                        "tid": self._tenant_id,
                        "seeds": list(seed_ids),
                        "max_depth": max(1, int(max_depth)),
                        "lim": max(1, int(limit)),
                    },
                )
            ).all()
        return [
            (str(row[0]), str(row[1]), str(row[2]), int(row[3]))
            for row in rows
        ]

    async def delete_relation(self, relation_id: str) -> bool:
        """Remove one relation（结构化事实物理删；行不存在返 False）。"""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM ontology_relations "
                    "WHERE tenant_id = :tid AND id = :rid",
                ),
                {"tid": self._tenant_id, "rid": relation_id},
            )
        return result.rowcount > 0

    # ------------------------------------------------------------------
    # transition / rule / action ops（本期仅建模留档）
    # ------------------------------------------------------------------

    async def create_transition(
        self,
        trn: OntologyStateTransition,
    ) -> bool:
        """Append one state-transition record（留档；对象 state 由服务层
        在同一业务动作里另行更新，本表不反写对象）。"""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO ontology_state_transitions (tenant_id, id, "
                    "object_id, from_state, to_state, trigger_type, "
                    "preconditions, permission, postconditions, "
                    "audit_required) "
                    "VALUES (:tid, :id, :object_id, :from_state, :to_state, "
                    ":trigger_type, CAST(:preconditions AS JSONB), "
                    ":permission, CAST(:postconditions AS JSONB), "
                    ":audit_required) "
                    "ON CONFLICT (tenant_id, id) DO NOTHING",
                ),
                {
                    "tid": self._tenant_id,
                    "id": trn.id,
                    "object_id": trn.object_id,
                    "from_state": trn.from_state,
                    "to_state": trn.to_state,
                    "trigger_type": trn.trigger_type,
                    "preconditions": _json_dumps(trn.preconditions),
                    "permission": trn.permission,
                    "postconditions": _json_dumps(trn.postconditions),
                    "audit_required": trn.audit_required,
                },
            )
        return result.rowcount > 0

    async def list_transitions(
        self,
        object_id: str,
        limit: int = 100,
    ) -> List[OntologyStateTransition]:
        """List transition records of one object（新→旧）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = (
            f"{_TRANSITION_COLUMNS} FROM ontology_state_transitions "
            "WHERE tenant_id = :tid AND object_id = :oid "
            "ORDER BY created_at DESC, id LIMIT :lim"
        )
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(sql),
                    {
                        "tid": self._tenant_id,
                        "oid": object_id,
                        "lim": max(1, int(limit)),
                    },
                )
            ).mappings().all()
        return [transition_from_row(row) for row in rows]

    async def create_rule(self, rule: OntologyRule) -> bool:
        """Insert one rule record（仅建模留档，无评估运行时）。"""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO ontology_rules (tenant_id, id, name, "
                    "scope, object_type, priority, conditions, "
                    "then_actions, else_actions, effective_from, version, "
                    "evidence_refs) "
                    "VALUES (:tid, :id, :name, :scope, :object_type, "
                    ":priority, CAST(:conditions AS JSONB), "
                    "CAST(:then_actions AS JSONB), "
                    "CAST(:else_actions AS JSONB), :effective_from, "
                    ":version, CAST(:evidence_refs AS JSONB)) "
                    "ON CONFLICT (tenant_id, id) DO NOTHING",
                ),
                {
                    "tid": self._tenant_id,
                    "id": rule.id,
                    "name": rule.name,
                    "scope": rule.scope,
                    "object_type": rule.object_type,
                    "priority": rule.priority,
                    "conditions": _json_dumps(rule.conditions),
                    "then_actions": _json_dumps(rule.then_actions),
                    "else_actions": _json_dumps(rule.else_actions),
                    "effective_from": rule.effective_from,
                    "version": rule.version,
                    "evidence_refs": _json_dumps(rule.evidence_refs),
                },
            )
        return result.rowcount > 0

    async def list_rules(
        self,
        object_type: str = "",
        limit: int = 200,
    ) -> List[OntologyRule]:
        """List rule records（object_type 过滤；priority 升序）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = f"{_RULE_COLUMNS} FROM ontology_rules WHERE tenant_id = :tid"
        params: Dict[str, Any] = {"tid": self._tenant_id}
        if object_type:
            sql += " AND object_type = :otype"
            params["otype"] = object_type
        sql += " ORDER BY priority, id LIMIT :lim"
        params["lim"] = max(1, int(limit))
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(text(sql), params)
            ).mappings().all()
        return [rule_from_row(row) for row in rows]

    async def create_action(self, action: OntologyAction) -> bool:
        """Insert one action record（仅建模留档，无执行/审批链）。"""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO ontology_actions (tenant_id, id, name, "
                    "object_type, input_schema, preconditions, policy, "
                    "approval, execution, postconditions, rollback, "
                    "auditable) "
                    "VALUES (:tid, :id, :name, :object_type, "
                    "CAST(:input_schema AS JSONB), "
                    "CAST(:preconditions AS JSONB), CAST(:policy AS JSONB), "
                    "CAST(:approval AS JSONB), CAST(:execution AS JSONB), "
                    "CAST(:postconditions AS JSONB), "
                    "CAST(:rollback AS JSONB), :auditable) "
                    "ON CONFLICT (tenant_id, id) DO NOTHING",
                ),
                {
                    "tid": self._tenant_id,
                    "id": action.id,
                    "name": action.name,
                    "object_type": action.object_type,
                    "input_schema": _json_dumps(action.input_schema),
                    "preconditions": _json_dumps(action.preconditions),
                    "policy": _json_dumps(action.policy),
                    "approval": _json_dumps(action.approval),
                    "execution": _json_dumps(action.execution),
                    "postconditions": _json_dumps(action.postconditions),
                    "rollback": _json_dumps(action.rollback),
                    "auditable": action.auditable,
                },
            )
        return result.rowcount > 0

    async def list_actions(
        self,
        object_type: str = "",
        limit: int = 200,
    ) -> List[OntologyAction]:
        """List action records（object_type 过滤）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = f"{_ACTION_COLUMNS} FROM ontology_actions WHERE tenant_id = :tid"
        params: Dict[str, Any] = {"tid": self._tenant_id}
        if object_type:
            sql += " AND object_type = :otype"
            params["otype"] = object_type
        sql += " ORDER BY id LIMIT :lim"
        params["lim"] = max(1, int(limit))
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(text(sql), params)
            ).mappings().all()
        return [action_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # kb_object_link ops（知识 ↔ 本体互引）
    # ------------------------------------------------------------------

    async def create_link(self, link: KbObjectLink) -> bool:
        """Insert one knowledge-object link; False on duplicate id."""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO kb_object_links (tenant_id, id, "
                    "kb_space_id, kb_document_id, object_type, object_id, "
                    "relation) "
                    "VALUES (:tid, :id, :space_id, :document_id, "
                    ":object_type, :object_id, :relation) "
                    "ON CONFLICT (tenant_id, id) DO NOTHING",
                ),
                {
                    "tid": self._tenant_id,
                    "id": link.id,
                    "space_id": link.kb_space_id,
                    "document_id": link.kb_document_id,
                    "object_type": link.object_type,
                    "object_id": link.object_id,
                    "relation": link.relation,
                },
            )
        return result.rowcount > 0

    async def delete_link(self, link_id: str) -> bool:
        """Remove one link; False when absent."""
        if not await self.ensure_ready():
            return False
        from sqlalchemy import text

        async with self._get_engine().begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM kb_object_links "
                    "WHERE tenant_id = :tid AND id = :lid",
                ),
                {"tid": self._tenant_id, "lid": link_id},
            )
        return result.rowcount > 0

    async def list_links_for_document(
        self,
        document_id: str,
    ) -> List[KbObjectLink]:
        """List links of one kb document（文档侧视角）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = (
            f"{_LINK_COLUMNS} FROM kb_object_links "
            "WHERE tenant_id = :tid AND kb_document_id = :did "
            "ORDER BY created_at, id"
        )
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(sql),
                    {"tid": self._tenant_id, "did": document_id},
                )
            ).mappings().all()
        return [link_from_row(row) for row in rows]

    async def list_links_for_object(
        self,
        object_id: str,
    ) -> List[KbObjectLink]:
        """List links pointing at one ontology object（对象侧视角）。"""
        if not await self.ensure_ready():
            return []
        from sqlalchemy import text

        sql = (
            f"{_LINK_COLUMNS} FROM kb_object_links "
            "WHERE tenant_id = :tid AND object_id = :oid "
            "ORDER BY created_at, id"
        )
        async with self._get_engine().connect() as conn:
            rows = (
                await conn.execute(
                    text(sql),
                    {"tid": self._tenant_id, "oid": object_id},
                )
            ).mappings().all()
        return [link_from_row(row) for row in rows]


async def get_ready_ontology_store() -> Optional[PgOntologyStore]:
    """工厂 + 就绪探测（进程内单例）；平面不可用返回 None。

    与 ``kb.pg_store.get_ready_kb_pg_store`` 同款语义：调用方拿到 None
    时 fail-soft 降级（本体是附加能力，不阻断知识主链路）。
    """
    global _store
    if not ont_pg_plane_available():
        return None
    with _store_lock:
        if _store is None:
            _store = PgOntologyStore()
    if not await _store.ensure_ready():
        return None
    return _store


def reset_ontology_store() -> None:
    """Drop the process-wide singleton（测试隔离用）。"""
    global _store
    with _store_lock:
        _store = None


__all__ = [
    "DEFAULT_TENANT_ID",
    "NOT_READY_RETRY_SECONDS",
    "PgOntologyStore",
    "ont_pg_plane_available",
    "get_ready_ontology_store",
    "reset_ontology_store",
    "type_from_row",
    "object_from_row",
    "relation_from_row",
    "transition_from_row",
    "rule_from_row",
    "action_from_row",
    "link_from_row",
]
