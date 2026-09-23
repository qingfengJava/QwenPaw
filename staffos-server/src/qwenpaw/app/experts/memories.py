# -*- coding: utf-8 -*-
"""Expert bucketed memories: store, dedup upsert, workspace materialize.

数字员工分桶长期记忆（StaffDeck memories 的对应物，决策 D4）：
- 存取：``expert_memories`` 表，kind ∈ profile/preference/fact，
  ``dedup_key`` 非空时按 (expert, user, kind, dedup_key) 幂等 upsert；
- 注入：按专家把记忆物化为 workspace ``memory/expert_memory.md``
  （agent_md_manager 的 memory 目录机制自然加载，零运行时侵入），
  重要度降序 + 时间降序，条数与字数设上限防 prompt 膨胀。
@author qingfeng
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine
from .models import MEMORY_KINDS, MemoryRecord

logger = logging.getLogger(__name__)

_COLS = (
    "id, expert_id, user_id, kind, content, importance, dedup_key, "
    "metadata, created_at, updated_at"
)

#: 物化文件最多写入的记忆条数（prompt 预算护栏）
MATERIALIZE_MAX_ITEMS = 50

#: 物化文件的分节标题（kind → 中文标题，单一来源）
_KIND_TITLES: Dict[str, str] = {
    "profile": "用户画像",
    "preference": "偏好",
    "fact": "事实",
}


def _row_to_memory(row) -> MemoryRecord:
    """Map one expert_memories row."""
    return MemoryRecord(
        id=row.id,
        expert_id=row.expert_id,
        user_id=row.user_id or "",
        kind=row.kind,
        content=row.content,
        importance=float(row.importance or 0.0),
        dedup_key=row.dedup_key or "",
        metadata=row.metadata or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class MemoryStore:
    """CRUD over ``expert_memories``, tenant-scoped."""

    async def list_memories(
        self,
        expert_id: str,
        user_id: str = "",
        kind: str = "",
    ) -> List[MemoryRecord]:
        """List one expert's memories (scope filters optional)."""
        engine = require_enterprise_engine()
        clauses = ["tenant_id = :tid", "expert_id = :eid"]
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "eid": expert_id,
        }
        if user_id:
            clauses.append("user_id = :uid")
            params["uid"] = user_id
        if kind:
            clauses.append("kind = :kind")
            params["kind"] = kind
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT "
                    + _COLS
                    + " FROM expert_memories WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY importance DESC, updated_at DESC"
                ),
                params,
            )
            return [_row_to_memory(r) for r in result]

    async def upsert_memory(
        self,
        expert_id: str,
        user_id: str = "",
        kind: str = "fact",
        content: str = "",
        importance: float = 0.5,
        dedup_key: str = "",
        metadata: Optional[dict] = None,
        memory_id: Optional[str] = None,
    ) -> MemoryRecord:
        """Insert, or overwrite when dedup_key hits (idempotent anchor).

        - kind 合法性防御：非法值回落 fact（不因脏数据失败）；
        - dedup_key 冲突 = 覆盖内容/重要度（语义修正），不动 created_at。
        """
        if kind not in MEMORY_KINDS:
            kind = "fact"
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            if dedup_key:
                existing = await conn.execute(
                    text(
                        "SELECT id FROM expert_memories WHERE "
                        "tenant_id = :tid AND expert_id = :eid AND "
                        "user_id = :uid AND kind = :kind AND "
                        "dedup_key = :dkey"
                    ),
                    {
                        "tid": tid,
                        "eid": expert_id,
                        "uid": user_id,
                        "kind": kind,
                        "dkey": dedup_key,
                    },
                )
                row = existing.first()
                if row is not None:
                    await conn.execute(
                        text(
                            "UPDATE expert_memories SET content = :content, "
                            "importance = :importance, "
                            "metadata = CAST(:meta AS JSONB), "
                            "updated_at = now() WHERE tenant_id = :tid "
                            "AND id = :id"
                        ),
                        {
                            "tid": tid,
                            "id": row.id,
                            "content": content,
                            "importance": importance,
                            "meta": json.dumps(metadata or {}),
                        },
                    )
                    memory_id = row.id
            if memory_id is None:
                memory_id = memory_id or new_id("mem")
                await conn.execute(
                    text(
                        "INSERT INTO expert_memories (tenant_id, id, "
                        "expert_id, user_id, kind, content, importance, "
                        "dedup_key, metadata) VALUES (:tid, :id, :eid, "
                        ":uid, :kind, :content, :importance, :dkey, "
                        "CAST(:meta AS JSONB))"
                    ),
                    {
                        "tid": tid,
                        "id": memory_id,
                        "eid": expert_id,
                        "uid": user_id,
                        "kind": kind,
                        "content": content,
                        "importance": importance,
                        "dkey": dedup_key,
                        "meta": json.dumps(metadata or {}),
                    },
                )
        record = await self.get_memory(expert_id, memory_id)
        assert record is not None
        return record

    async def get_memory(
        self,
        expert_id: str,
        memory_id: str,
    ) -> Optional[MemoryRecord]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _COLS + " FROM expert_memories WHERE "
                    "tenant_id = :tid AND expert_id = :eid AND id = :id"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "id": memory_id,
                },
            )
            row = result.first()
            return _row_to_memory(row) if row else None

    async def delete_memory(self, expert_id: str, memory_id: str) -> bool:
        """物理删除=记忆修正语义（员工认知可被人工纠偏）。"""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM expert_memories WHERE tenant_id = :tid "
                    "AND expert_id = :eid AND id = :id"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "id": memory_id,
                },
            )
            return result.rowcount > 0

    async def clear_memories(
        self,
        expert_id: str,
        user_id: str = "",
    ) -> int:
        """清空（可按 user 维度）——StaffDeck 记忆 Tab 的"清空"动作。"""
        engine = require_enterprise_engine()
        clauses = ["tenant_id = :tid", "expert_id = :eid"]
        params: Dict[str, object] = {
            "tid": current_tenant_id(),
            "eid": expert_id,
        }
        if user_id:
            clauses.append("user_id = :uid")
            params["uid"] = user_id
        async with engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM expert_memories WHERE " + " AND ".join(clauses)),
                params,
            )
            return result.rowcount or 0


async def materialize_expert_memory(expert_id: str) -> Optional[Path]:
    """Materialize one expert's memories into its workspace memory file.

    发布链与记忆 CRUD 后调用（best-effort：专家未发布/无 workspace 时
    静默跳过，绝不阻塞主流程）。文件头写说明，正文按分桶分节，供
    agent_md_manager 的 memory 目录机制在会话中自然加载。
    """
    store = get_memory_store()
    records = await store.list_memories(expert_id)
    if not records:
        return None

    from ...constant import WORKING_DIR

    from .publish import _expert_workspace_dir

    workspace = _expert_workspace_dir(expert_id)
    if not workspace.is_dir():
        # 未发布（无 workspace）——无需物化
        return None
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    target = memory_dir / "expert_memory.md"

    # 重要度降序 + 更新时间降序，截断到预算内
    ordered = sorted(
        records,
        key=lambda r: (-r.importance, r.updated_at or r.created_at),
    )[:MATERIALIZE_MAX_ITEMS]

    lines: List[str] = [
        "# 数字员工记忆（自动物化，请勿手工编辑）",
        "",
        "> 来源：expert_memories 表；记忆管理页增删改后自动重建。",
        "",
    ]
    for kind in MEMORY_KINDS:
        bucket = [r for r in ordered if r.kind == kind]
        if not bucket:
            continue
        lines.append(f"## {_KIND_TITLES.get(kind, kind)}")
        lines.append("")
        for record in bucket:
            # 组织级记忆标注范围，便于人工审阅
            scope = "" if not record.user_id else "（针对特定用户）"
            lines.append(f"- {record.content}{scope}")
        lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = MemoryStore()
    return _store
