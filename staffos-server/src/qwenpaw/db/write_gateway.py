# -*- coding: utf-8 -*-
"""Unified PG write gateway（全局数据架构的写路径收敛点，M2）。

所有资源域（provider 配置、agent 模型槽位、定时任务、收件箱、技能
目录等）的 PG 写入都经本网关，统一收敛三件事：

- **三态判定**：``QWENPAW_STORAGE_BACKEND``（json/dual/pg）解析与
  缓存 + DSN 可用性判定，此前在 provider/inbox/crons/skill 各域
  各自复制一份，现收敛为单一实现（历史实现保留为兼容门面）；
- **调度策略**：``submit_shadow_write`` 提供 fire-and-forget 影子写
  （统一提交到进程级单例影子写守护 loop），绝不阻塞业务路径；
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

#: 进程级单例影子写守护 loop（所有影子写收敛于此；见 _get_shadow_loop）
_shadow_loop: asyncio.AbstractEventLoop | None = None
_shadow_loop_lock = threading.Lock()


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


def _get_shadow_loop() -> asyncio.AbstractEventLoop:
    """Return the process-wide shadow-write daemon loop（单例）。

    历史实现（无 loop 时每笔影子写起一线程跑 ``asyncio.run``）会为每次
    写创建一次性事件循环：operation 内部经共享工厂拿到的 asyncpg 池若
    绑定在其他 loop（或更糟——被一次性 loop 创建后随即关闭），协程会
    永久挂在 ``BEGIN`` 后，泄漏 ``idle in transaction`` 连接直至池耗尽。
    收敛为单例守护 loop 后，配合 per-loop engine 缓存（engine.py）每
    loop 一池，影子写稳定复用自己的连接。
    """
    global _shadow_loop  # pylint: disable=global-statement
    with _shadow_loop_lock:
        if _shadow_loop is None or _shadow_loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(
                target=loop.run_forever,
                name="qwenpaw-pg-shadow",
                daemon=True,
            ).start()
            _shadow_loop = loop
        return _shadow_loop


def submit_shadow_write(
    operation: Callable[[], Awaitable[Any]],
    *,
    domain: str = "pg",
) -> None:
    """Fire-and-forget a shadow PG write（绝不阻塞业务路径）。

    - 统一提交到进程级单例影子写守护 loop（``run_coroutine_threadsafe``）；
      历史的两个分支（事件循环内 ``create_task`` / 无循环时线程
      ``asyncio.run``）都会让 operation 脱离影子写自己的 loop 驱动，
      跨 loop 复用 asyncpg 池会挂死连接（见 :func:`_get_shadow_loop`）；
    - 平面不可用（json 后端 / 无 DSN）直接短路，operation 永不执行；
    - 任何失败仅告警（``<domain> PG shadow write failed``）。
    """
    if not pg_write_available():
        return

    loop = _get_shadow_loop()

    async def _task() -> None:
        try:
            await operation()
        except Exception:  # noqa: BLE001 - shadow plane must never raise
            logger.warning(
                "%s PG shadow write failed",
                domain,
                exc_info=True,
            )

    asyncio.run_coroutine_threadsafe(_task(), loop)


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
