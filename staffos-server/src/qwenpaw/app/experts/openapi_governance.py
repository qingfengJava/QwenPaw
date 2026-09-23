# -*- coding: utf-8 -*-
"""Open API governance: idempotency replay / rate limit / audit (P4 收尾).

``/api/open`` 平面的横切协议层（设计文档 §九 遗留缺口②）：

- **幂等回放**：调用方携带 ``Idempotency-Key`` 时，同 key+幂等键+同
  请求指纹的重放直接回放缓存响应（TTL 24h 懒过期）；同键不同指纹
  抛 :class:`IdempotencyConflict`（调用方映射 409）。
- **限流**：per-key 进程内存滑动窗口（默认 30 req/min，
  ``QWENPAW_OPEN_RATE_LIMIT_RPM`` 可配）；限流态不落库，重启即重置
  （重置只会放宽，不会放大风险）。
- **审计**：全部 /api/open 请求（含 4xx/5xx）best-effort 落
  ``open_api_audit``；审计失败仅记日志，绝不阻塞业务主链路。

存储：与 experts 域同范式——PG（``require_enterprise_engine``）为
唯一权威；限流窗口天然进程内。
@author qingfeng
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ..enterprise import current_tenant_id, new_id, require_enterprise_engine

logger = logging.getLogger(__name__)

#: 幂等缓存 TTL（秒）：设计文档约定 24h
IDEMPOTENCY_TTL_S = 24 * 3600

#: 默认限流窗口（每密钥每分钟请求数；环境变量 QWENPAW_OPEN_RATE_LIMIT_RPM 覆盖）
DEFAULT_RATE_LIMIT_RPM = 30

#: 限流滑动窗口长度（秒）
RATE_WINDOW_S = 60.0

#: 审计路径提取 expert_id 的段数约定：/open/experts/{expert_id}[...]
_PATH_EXPERT_SEGMENTS = 2


class IdempotencyConflict(Exception):
    """同幂等键携带了不同请求指纹（调用方映射 409）。"""

    def __init__(self, idem_key: str) -> None:
        super().__init__(f"idempotency key reused with different payload: {idem_key}")
        self.idem_key = idem_key


def fingerprint_payload(payload: Any) -> str:
    """Canonical-JSON sha256 of one request body（键序无关）."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class OpenGovernance:
    """Idempotency replay + sliding-window rate limit + call audit."""

    def __init__(self) -> None:
        # 限流窗口：key_id -> 最近请求时间戳队列（进程内，重启即重置）
        self._rate_windows: Dict[str, deque] = defaultdict(deque)
        self._rate_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 幂等回放
    # ------------------------------------------------------------------

    async def check_idempotency(
        self,
        key_id: str,
        idem_key: str,
        fingerprint: str,
    ) -> Optional[Dict[str, Any]]:
        """Lookup one cached response.

        Returns ``{"status_code", "response"}`` on a replayable hit;
        ``None`` when the key is fresh（调用方继续执行并回写缓存）；
        raises :class:`IdempotencyConflict` on fingerprint mismatch.
        """
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT fingerprint, status_code, response_json "
                    "FROM open_api_idempotency WHERE tenant_id = :tid "
                    "AND key_id = :kid AND idem_key = :ik "
                    "AND expires_at > now()"
                ),
                {
                    "tid": current_tenant_id(),
                    "kid": key_id,
                    "ik": idem_key,
                },
            )
            row = result.first()
        if row is None:
            return None
        if str(row.fingerprint or "") != fingerprint:
            raise IdempotencyConflict(idem_key)
        return {
            "status_code": int(row.status_code or 200),
            "response": row.response_json or {},
        }

    async def store_idempotent_response(
        self,
        key_id: str,
        idem_key: str,
        fingerprint: str,
        status_code: int,
        response: Dict[str, Any],
    ) -> None:
        """Cache one executed response（同键重执行覆盖旧行，天然幂等）.

        best-effort：写失败仅告警——下次同键重放将重新执行而非回放，
        语义安全（调用方拿到的是新执行结果）。
        """
        try:
            engine = require_enterprise_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO open_api_idempotency (tenant_id, "
                        "key_id, idem_key, fingerprint, status_code, "
                        "response_json, expires_at) VALUES (:tid, :kid, "
                        ":ik, :fp, :sc, CAST(:resp AS JSONB), "
                        "now() + INTERVAL '1 second' * :ttl) "
                        "ON CONFLICT (tenant_id, key_id, idem_key) "
                        "DO UPDATE SET fingerprint = EXCLUDED.fingerprint, "
                        "status_code = EXCLUDED.status_code, "
                        "response_json = EXCLUDED.response_json, "
                        "created_at = now(), expires_at = EXCLUDED.expires_at"
                    ),
                    {
                        "tid": current_tenant_id(),
                        "kid": key_id,
                        "ik": idem_key,
                        "fp": fingerprint,
                        "sc": int(status_code),
                        "resp": json.dumps(
                            response,
                            ensure_ascii=False,
                            default=str,
                        ),
                        "ttl": IDEMPOTENCY_TTL_S,
                    },
                )
        except Exception:  # noqa: BLE001 - 缓存写失败不阻塞业务
            logger.warning(
                "open api idempotency cache write failed (key=%s)",
                idem_key,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # 限流（进程内存滑动窗口）
    # ------------------------------------------------------------------

    @staticmethod
    def _rate_limit_rpm() -> int:
        """Configured per-key RPM（环境变量容错解析）."""
        raw = os.environ.get("QWENPAW_OPEN_RATE_LIMIT_RPM", "")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_RATE_LIMIT_RPM
        return max(1, value)

    async def check_rate_limit(self, key_id: str) -> tuple[bool, int]:
        """Sliding-window admission for one key.

        Returns ``(allowed, retry_after_seconds)``；拒绝时 retry_after
        为窗口内最早一条请求出窗所需的秒数（至少 1）。
        """
        limit = self._rate_limit_rpm()
        now = time.monotonic()
        async with self._rate_lock:
            window = self._rate_windows[key_id]
            while window and now - window[0] >= RATE_WINDOW_S:
                window.popleft()
            if len(window) >= limit:
                retry_after = max(1, int(RATE_WINDOW_S - (now - window[0])) + 1)
                return False, retry_after
            window.append(now)
            return True, 0

    # ------------------------------------------------------------------
    # 审计流水
    # ------------------------------------------------------------------

    async def record_audit(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        latency_ms: int,
        key_id: str = "",
        expert_id: str = "",
        idem_key: str = "",
        client_ip: str = "",
    ) -> None:
        """Append one audit row（best-effort，绝不阻塞业务）."""
        try:
            engine = require_enterprise_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO open_api_audit (tenant_id, id, "
                        "key_id, expert_id, method, path, status_code, "
                        "latency_ms, idem_key, client_ip) VALUES "
                        "(:tid, :id, :kid, :eid, :m, :p, :sc, :ms, "
                        ":ik, :ip)"
                    ),
                    {
                        "tid": current_tenant_id(),
                        "id": new_id("oaadt"),
                        "kid": key_id,
                        "eid": expert_id,
                        "m": method[:8],
                        "p": path[:2048],
                        "sc": int(status_code),
                        "ms": int(latency_ms),
                        "ik": idem_key[:128],
                        "ip": client_ip[:64],
                    },
                )
        except Exception:  # noqa: BLE001 - 审计失败不阻塞业务
            logger.warning(
                "open api audit write failed (path=%s)",
                path,
                exc_info=True,
            )

    async def list_audit(
        self,
        *,
        key_id: str = "",
        expert_id: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Recent audit rows（倒序分页；过滤条件均可空）."""
        conditions = ["tenant_id = :tid"]
        params: Dict[str, Any] = {"tid": current_tenant_id()}
        if key_id:
            conditions.append("key_id = :kid")
            params["kid"] = key_id
        if expert_id:
            conditions.append("expert_id = :eid")
            params["eid"] = expert_id
        params["limit"] = max(1, min(int(limit), 500))
        engine = require_enterprise_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT id, key_id, expert_id, method, path, "
                    "status_code, latency_ms, idem_key, client_ip, "
                    "created_at FROM open_api_audit WHERE "
                    + " AND ".join(conditions)
                    + " ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
            return [
                {
                    "id": row.id,
                    "key_id": row.key_id,
                    "expert_id": row.expert_id,
                    "method": row.method,
                    "path": row.path,
                    "status_code": row.status_code,
                    "latency_ms": row.latency_ms,
                    "idem_key": row.idem_key,
                    "client_ip": row.client_ip,
                    "created_at": row.created_at,
                }
                for row in result
            ]


def extract_expert_id_from_path(path: str) -> str:
    """Pull ``{expert_id}`` out of ``/open/experts/{expert_id}/...``."""
    parts = [seg for seg in path.split("/") if seg]
    try:
        marker = parts.index("experts")
    except ValueError:
        return ""
    if len(parts) <= marker + _PATH_EXPERT_SEGMENTS - 1:
        return ""
    candidate = parts[marker + 1]
    return "" if candidate.startswith("{") else candidate


_governance: OpenGovernance | None = None


def get_open_governance() -> OpenGovernance:
    """Process-wide singleton（限流窗口必须全局共享）."""
    global _governance  # pylint: disable=global-statement
    if _governance is None:
        _governance = OpenGovernance()
    return _governance
