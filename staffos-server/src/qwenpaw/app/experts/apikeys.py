# -*- coding: utf-8 -*-
"""Expert API keys: issue / list / revoke / verify (P4 凭证面).

员工级开放 API 密钥（设计文档 §四/§六 P4）：
- 签发：生成 ``sk_ek_<32 hex>`` 明文，**仅签发响应返回一次**；落库只存
  SHA-256 哈希 + 展示前缀（``sk_ek_`` + 前 8 hex）；
- 权限边界：key 绑定单一 expert_id，只能访问该员工的开放资源；
- 吊销：``revoked_at`` 软吊销留痕，验证时即时生效；
- 过期：可选 ``expires_at``。

``hash_key`` 使用 hashlib.sha256（无盐）——密钥本身是 128bit 随机数，
非用户口令，无彩虹表攻击面；哈希仅防库内泄露直接复用。
@author qingfeng
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine

#: 明文密钥前缀（辨识开放 API 密钥的固定标识）
KEY_PREFIX = "sk_ek_"

_COLS = (
    "id, expert_id, name, key_prefix, created_by, expires_at, "
    "revoked_at, created_at, updated_at"
)


def hash_key(plaintext: str) -> str:
    """SHA-256 hex of one plaintext key."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _row_to_key(row) -> Dict[str, Any]:
    """Map one expert_api_keys row (never exposes the hash)."""
    return {
        "id": row.id,
        "expert_id": row.expert_id,
        "name": row.name or "",
        "key_prefix": row.key_prefix or "",
        "created_by": row.created_by,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class ApiKeyStore:
    """CRUD + verification over ``expert_api_keys``."""

    async def issue_key(
        self,
        expert_id: str,
        name: str = "",
        created_by: str = "",
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Issue one key; returns the record WITH the plaintext (once)."""
        plaintext = KEY_PREFIX + secrets.token_hex(16)
        tid = current_tenant_id()
        engine = require_enterprise_engine()
        key_id = new_id("eak")
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO expert_api_keys (tenant_id, id, "
                    "expert_id, name, key_hash, key_prefix, created_by, "
                    "expires_at) VALUES (:tid, :id, :eid, :name, :hash, "
                    ":prefix, :by, :expires)"
                ),
                {
                    "tid": tid,
                    "id": key_id,
                    "eid": expert_id,
                    "name": name,
                    # 落库哈希；前缀截到 sk_ek_ + 8 hex（展示辨识）
                    "hash": hash_key(plaintext),
                    "prefix": plaintext[:14],
                    "by": created_by,
                    "expires": expires_at,
                },
            )
        record = await self.get_key(expert_id, key_id)
        record["plaintext"] = plaintext
        return record

    async def get_key(
        self,
        expert_id: str,
        key_id: str,
    ) -> Dict[str, Any]:
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _COLS + " FROM expert_api_keys WHERE "
                    "tenant_id = :tid AND expert_id = :eid AND id = :id"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "id": key_id,
                },
            )
            row = result.first()
            if row is None:
                raise ValueError("key not found")
            return _row_to_key(row)

    async def list_keys(self, expert_id: str) -> List[Dict[str, Any]]:
        """List one expert's keys (newest first; never the hash)."""
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT " + _COLS + " FROM expert_api_keys WHERE "
                    "tenant_id = :tid AND expert_id = :eid "
                    "ORDER BY created_at DESC"
                ),
                {"tid": current_tenant_id(), "eid": expert_id},
            )
            return [_row_to_key(r) for r in result]

    async def revoke_key(self, expert_id: str, key_id: str) -> bool:
        """Soft-revoke (revoked_at = now; idempotent)."""
        engine = require_enterprise_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE expert_api_keys SET revoked_at = now(), "
                    "updated_at = now() WHERE tenant_id = :tid "
                    "AND expert_id = :eid AND id = :id "
                    "AND revoked_at IS NULL"
                ),
                {
                    "tid": current_tenant_id(),
                    "eid": expert_id,
                    "id": key_id,
                },
            )
            return result.rowcount > 0

    async def verify(
        self,
        plaintext: str,
    ) -> Optional[Dict[str, Any]]:
        """Verify one plaintext key → {expert_id, key_id} or None.

        即时生效语义：哈希命中后仍校验 revoked_at / expires_at。
        """
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, expert_id, revoked_at, expires_at FROM "
                    "expert_api_keys WHERE tenant_id = :tid "
                    "AND key_hash = :hash"
                ),
                {"tid": current_tenant_id(), "hash": hash_key(plaintext)},
            )
            row = result.first()
        if row is None:
            return None
        now = (
            datetime.now(row.revoked_at.tzinfo)
            if row.revoked_at is not None
            else datetime.now()
        )
        if row.revoked_at is not None:
            return None
        if row.expires_at is not None and row.expires_at <= now:
            return None
        return {"key_id": row.id, "expert_id": row.expert_id}


_store: ApiKeyStore | None = None


def get_api_key_store() -> ApiKeyStore:
    """Process-wide singleton (stateless; engine shared per DSN)."""
    global _store  # pylint: disable=global-statement
    if _store is None:
        _store = ApiKeyStore()
    return _store
