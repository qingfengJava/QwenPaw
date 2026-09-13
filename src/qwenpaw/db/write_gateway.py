# -*- coding: utf-8 -*-
"""Unified PG write gateway（全局数据架构的写路径收敛点，M2）。

所有资源域（provider 配置、agent 模型槽位、定时任务、收件箱、技能
目录等）的 PG 写入都经本网关，统一收敛三件事：

- **三态判定**：``QWENPAW_STORAGE_BACKEND``（json/dual/pg）解析与
  缓存 + DSN 可用性判定，此前在 provider/inbox/crons/skill 各域
  各自复制一份，现收敛为单一实现（历史实现保留为兼容门面）；
- **调度策略**：``submit_shadow_write`` 提供 fire-and-forget 影子写
  （事件循环内 create_task / 无循环时守护线程 ``asyncio.run``），
  绝不阻塞业务路径；
- **失败语义与日志**：任何 PG 写失败仅告警、绝不向调用方抛异常。
  日志文案统一为 ``"<domain> PG <mode> write failed"``，可全局
  grep 定位故障域。

设计原则（与 crons/inbox 平面同一范式）：

- 影子写（``shadow``）：dual 后端的旁路备份，失败丢弃不重试；
- 权威写（``authoritative``）：pg 后端的唯一写路径，失败仅告警、
  **禁止降级写文件**——投影已清空的域降级写文件只会制造无读方的
  孤儿数据（crons 平面自激振荡缺陷的姊妹教训）。

@author qingfeng
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Awaitable, Callable

from ..constant import EnvVarLoader

logger = logging.getLogger(__name__)

#: 与 app/chats/factory.py 一致的存储后端开关
STORAGE_BACKEND_ENV = "QWENPAW_STORAGE_BACKEND"

#: 三态后端取值
BACKEND_JSON = "json"
BACKEND_DUAL = "dual"
BACKEND_PG = "pg"

VALID_BACKENDS = frozenset(
    {BACKEND_JSON, BACKEND_DUAL, BACKEND_PG},
)

_backend_cache: str | None = None
_backend_lock = threading.Lock()


def _default_storage_backend() -> str:
    """动态默认（SQLite 退役范式）。

    配置了 ``QWENPAW_PG_DSN`` 时默认 ``dual``（文件 primary + PG
    影子），让各平面开始积累 PG 数据；未配置 DSN 的个人部署保持
    ``json`` 不变。显式 ``QWENPAW_STORAGE_BACKEND`` 恒优先。
    """
    try:
        from .engine import get_pg_dsn

        return BACKEND_DUAL if get_pg_dsn() else BACKEND_JSON
    except Exception:  # noqa: BLE001 - DSN 未配置/依赖缺失均视为 json
        return BACKEND_JSON


def resolve_storage_backend() -> str:
    """Return the resolved storage backend (json/dual/pg).

    双检锁缓存进程级判定结果（env 不可变假设）；测试切换环境后
    必须调用 :func:`reset_backend_cache`。
    """
    global _backend_cache  # pylint: disable=global-statement
    if _backend_cache is not None:
        return _backend_cache
    with _backend_lock:
        if _backend_cache is not None:
            return _backend_cache
        raw = EnvVarLoader.get_str(STORAGE_BACKEND_ENV, "").strip().lower()
        if raw in VALID_BACKENDS:
            _backend_cache = raw
        else:
            # 无效值静默回退动态默认（避免与 chats 工厂重复告警噪音）
            _backend_cache = _default_storage_backend()
        return _backend_cache


def reset_backend_cache() -> None:
    """Clear the cached backend (tests / env changes)."""
    global _backend_cache  # pylint: disable=global-statement
    with _backend_lock:
        _backend_cache = None


def pg_write_available() -> bool:
    """True when any plane should touch PG (dual/pg backend + DSN set)."""
    backend = resolve_storage_backend()
    if backend not in (BACKEND_DUAL, BACKEND_PG):
        return False
    return bool(EnvVarLoader.get_str("QWENPAW_PG_DSN", "").strip())


def submit_shadow_write(
    operation: Callable[[], Awaitable[Any]],
    *,
    domain: str = "pg",
) -> None:
    """Fire-and-forget a shadow PG write（绝不阻塞业务路径）。

    - 事件循环内：``create_task`` 异步执行；
    - 无事件循环（CLI / 启动同步路径）：独立守护线程中
      ``asyncio.run``；
    - 平面不可用（json 后端 / 无 DSN）直接短路，operation 永不执行；
    - 任何失败仅告警（``<domain> PG shadow write failed``）。
    """
    if not pg_write_available():
        return

    def _guarded() -> None:
        try:
            asyncio.run(operation())
        except Exception:  # noqa: BLE001 - shadow plane must never raise
            logger.warning(
                "%s PG shadow write failed",
                domain,
                exc_info=True,
            )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(target=_guarded, daemon=True).start()
        return

    async def _task() -> None:
        try:
            await operation()
        except Exception:  # noqa: BLE001 - shadow plane must never raise
            logger.warning(
                "%s PG shadow write failed",
                domain,
                exc_info=True,
            )

    asyncio.get_running_loop().create_task(_task())


async def authoritative_write(
    operation: Callable[[], Awaitable[Any]],
    *,
    domain: str,
) -> bool:
    """Await an authoritative PG write; warn (never raise) on failure.

    返回 ``True`` 表示写成功。失败仅告警（``<domain> PG authoritative
    write failed``）并返回 ``False``——禁止降级写文件：权威平面失效
    时文件投影早已清空（backfill 后契约），降级写只会制造无读方的
    孤儿数据。
    """
    try:
        await operation()
        return True
    except Exception:  # noqa: BLE001 - authoritative plane must never raise
        logger.warning(
            "%s PG authoritative write failed",
            domain,
            exc_info=True,
        )
        return False
