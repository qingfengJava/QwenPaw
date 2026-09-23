# -*- coding: utf-8 -*-
"""Multi-device sync/restore orchestrator (M3 全局数据架构收口).

PG 是唯一权威源、本地 workspace 文件是可丢弃的物化缓存。每台设备
启动时各域钩子已自动执行「PG → 本地」取回（agent_docs reconcile /
skill plane bootstrap / provider 权威读 / crons·inbox initialize）；
本模块把同一组取回动作收敛为**可手动触发、可观测**的统一编排：

- ``restore_domains``：逐域重放取回（全部幂等），单域异常隔离，
  供「B 设备启动取回失败补拉 / 强制刷新本地缓存」场景使用；
- ``sync_status``：各域 PG 侧计数 + 存储后端状态的只读快照，
  供控制台展示「这台设备从账号取回了什么」。

编排语义（与各域启动钩子严格一致）：

- 文件物化域（agent_docs / skills）：PG 权威覆盖文件（缓存重建）；
- providers：仅 ``pg`` 后端执行权威读（``dual`` 下文件仍是读权威，
  用 PG 覆盖文件会破坏单向语义，显式 ``skipped``）；
- 直读域（crons / inbox / memories / chats）：PG 直读、无本地文件
  物化，编排仅做连通性与计数校验。

任何域失败只影响自身条目，绝不向调用方抛异常（编排层兜底）。

@author qingfeng
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: 可编排的取回域（白名单，路由层入参校验用）
RESTORE_DOMAINS = (
    "agent_docs",
    "skills",
    "providers",
    "crons",
    "inbox",
    "memories",
    "chats",
)


def _pg_plane_available() -> bool:
    """True when dual/pg backend is active with a configured DSN."""
    from ..db import write_gateway

    return write_gateway.pg_write_available()


def _domain_error(exc: Exception) -> dict[str, Any]:
    """Build one isolated domain failure entry (never raises)."""
    return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# 域编排实现（每个函数返回该域的结果 dict；异常向上交由编排层隔离）
# ---------------------------------------------------------------------------


async def _restore_agent_docs() -> dict[str, Any]:
    """档案文档域：PG 权威覆盖工作区文件（复用启动 reconcile）。"""
    from .agent_docs.reconcile import reconcile_agent_docs

    stats = await reconcile_agent_docs()
    if not stats:
        # 空 dict = PG 未配置（reconcile 的诚实空态）
        return {"ok": False, "error": "PG not configured"}
    return {"ok": True, **stats}


async def _restore_skills() -> dict[str, Any]:
    """技能池域：manifest 回填 + 快照自愈 + 绑定/去重（幂等）。"""
    from ..db.backfill_skill_catalog import run_skill_plane_bootstrap

    result = await run_skill_plane_bootstrap()
    if not result:
        return {"ok": False, "error": "PG plane not available"}
    return {"ok": True, **result}


async def _restore_providers(
    provider_manager: Optional[Any],
) -> dict[str, Any]:
    """provider 域：pg 后端从 PG 权威读刷回内存与文件快照。

    dual/json 后端文件平面仍是读权威，跨设备取回语义不成立，
    显式 skipped（防误覆盖本机配置）。
    """
    from ..db import write_gateway

    if write_gateway.resolve_storage_backend() != write_gateway.BACKEND_PG:
        return {
            "ok": True,
            "skipped": "file plane is authoritative (non-pg backend)",
        }
    if provider_manager is None:
        return {"ok": False, "error": "provider manager unavailable"}
    restored = await provider_manager.load_providers_from_pg()
    return {"ok": True, "restored": restored}


#: 编排器允许计数的物理表白名单（域 → 表名；标识符拼接仅限此集合）
_STATUS_TABLES = {
    "agent_documents": "agent_documents",
    "agent_document_revisions": "agent_document_revisions",
    "skill_catalog": "skill_catalog",
    "skill_content_snapshots": "skill_content_snapshots",
    "cron_jobs": "cron_jobs",
    "inbox_events": "inbox_events",
    "expert_memories": "expert_memories",
    "chats": "chats",
    "provider_configs": "provider_configs",
}


async def _count_rows(table: str) -> int:
    """Count rows of one PG plane table (whitelisted identifier)."""
    from sqlalchemy import text

    from ..db.engine import create_pg_engine

    # 表名来自模块内白名单常量，非用户输入；ident 拼接仅限此处
    if table not in _STATUS_TABLES.values():
        raise ValueError(f"table not in status whitelist: {table}")
    engine = create_pg_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            # 白名单拦截后的 f-string 拼接仅限标识符，无注入面
            text(f"SELECT count(*) FROM {table}"),
        )
        return int(result.scalar() or 0)


async def _restore_readonly_domain(table: str, key: str) -> dict[str, Any]:
    """直读域编排：PG 连通性 + 计数校验（无本地物化动作）。"""
    count = await _count_rows(table)
    return {"ok": True, key: count}


# ---------------------------------------------------------------------------
# 统一编排入口
# ---------------------------------------------------------------------------


async def restore_domains(
    domains: Optional[list[str]] = None,
    *,
    provider_manager: Optional[Any] = None,
) -> dict[str, Any]:
    """逐域重放「PG → 本地」取回；单域异常隔离，聚合统计返回。

    Args:
        domains: 要取回的域列表；None/空 = 全域。
        provider_manager: providers 域权威读所需的 manager 实例
            （路由层从 ``app.state.provider_manager`` 取）。

    Returns:
        ``{"ok": bool, "results": {domain: {...}}}``；``ok`` 为全部
        域成功的合取。入参含未知域名时整体 400 由路由层负责。
    """
    selected = list(domains) if domains else list(RESTORE_DOMAINS)
    results: dict[str, Any] = {}
    for domain in selected:
        try:
            if domain == "agent_docs":
                results[domain] = await _restore_agent_docs()
            elif domain == "skills":
                results[domain] = await _restore_skills()
            elif domain == "providers":
                results[domain] = await _restore_providers(provider_manager)
            elif domain == "crons":
                results[domain] = await _restore_readonly_domain(
                    "cron_jobs",
                    "jobs",
                )
            elif domain == "inbox":
                results[domain] = await _restore_readonly_domain(
                    "inbox_events",
                    "events",
                )
            elif domain == "memories":
                results[domain] = await _restore_readonly_domain(
                    "expert_memories",
                    "memories",
                )
            elif domain == "chats":
                results[domain] = await _restore_readonly_domain(
                    "chats",
                    "chats",
                )
            else:  # pragma: no cover - 路由层白名单已拦截
                results[domain] = {"ok": False, "error": "unknown domain"}
        except Exception as exc:  # noqa: BLE001 - 单域异常隔离
            logger.warning(
                "sync restore failed for domain=%s",
                domain,
                exc_info=True,
            )
            results[domain] = _domain_error(exc)
    all_ok = all(
        bool(entry.get("ok")) for entry in results.values()
    ) if results else True
    if not all_ok:
        logger.warning("sync restore finished with failures: %s", results)
    else:
        logger.info("sync restore finished: %s", results)
    return {"ok": all_ok, "results": results}


async def sync_status(
    *,
    provider_manager: Optional[Any] = None,
) -> dict[str, Any]:
    """只读快照：存储后端状态 + 各域 PG 侧计数（可观测性）。

    单表计数异常隔离为 ``null`` 计数 + ``error`` 字段，绝不整体失败。
    """
    from ..db import write_gateway

    backend = write_gateway.resolve_storage_backend()
    pg_available = _pg_plane_available()
    counts: dict[str, Any] = {}
    if pg_available:
        for domain, table in _STATUS_TABLES.items():
            try:
                counts[domain] = await _count_rows(table)
            except Exception as exc:  # noqa: BLE001 - 单表隔离
                counts[domain] = None
                logger.debug(
                    "sync_status count failed for %s: %s",
                    table,
                    exc,
                )
    providers: dict[str, Any] = {}
    if pg_available and provider_manager is not None:
        try:
            providers["in_memory"] = len(
                getattr(provider_manager, "builtin_providers", {}) or {},
            ) + len(
                getattr(provider_manager, "custom_providers", {}) or {},
            )
        except Exception:  # noqa: BLE001 - 观测字段不参与成败
            providers["in_memory"] = None
    return {
        "backend": backend,
        "pg_available": pg_available,
        "pg_counts": counts,
        "providers": providers,
    }
