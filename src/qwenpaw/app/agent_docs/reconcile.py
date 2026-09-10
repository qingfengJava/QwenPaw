# -*- coding: utf-8 -*-
"""Startup reconciliation between PG identity documents and workspace files.

Phase B 权威裁决：PG ``agent_documents`` 是档案文档的持久权威，
工作区文件是可重建的物化缓存。本模块在应用启动时（lifespan 后台
任务，不阻塞启动）对每个已注册 agent 工作区逐一处理四个白名单文件：

- PG 有行 & 文件缺失或内容不一致 → **以 PG 覆盖文件**（缓存重建，
  权威裁决），并 WARN 列出被覆盖文件供人工核查；
- PG 无行 & 文件存在 → 读文件回填种子（首次升级存量环境）；
- 一致或双无 → 跳过；单 agent 异常隔离继续。

多实例语义天然成立：每个实例启动对账一次，运行期间写路径双写
保证缓存新鲜。无 PG 部署（无 DSN）本模块为 no-op。

@author qingfeng
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .store import (
    DOC_TYPE_BY_FILENAME,
    AgentDocsStore,
    content_hash,
    get_agent_docs_store,
)

logger = logging.getLogger(__name__)


async def _reconcile_one_document(
    store: AgentDocsStore,
    agent_id: str,
    filename: str,
    doc_type: str,
    workspace_dir: Path,
) -> str:
    """对齐一个档案文档，返回动作标签（promote/restore/overwrite/skip）。"""
    file_path = workspace_dir / filename

    def _read_file() -> str | None:
        try:
            return file_path.read_text(encoding="utf-8")
        except OSError:
            return None

    file_content = await asyncio.to_thread(_read_file)
    row = await store.get_document(agent_id, doc_type)

    if row is not None:
        row_content = str(row.get("content") or "")
        if file_content is not None and content_hash(file_content) == row.get(
            "content_hash",
        ):
            return "skip"
        # PG 权威裁决：覆盖物化缓存（文件缺失 = 缓存丢失，静默重建；
        # 内容漂移 = 需人工关注，显式告警）
        drifted = file_content is not None
        await asyncio.to_thread(
            lambda: file_path.parent.mkdir(parents=True, exist_ok=True),
        )
        await asyncio.to_thread(
            lambda: file_path.write_text(row_content, encoding="utf-8"),
        )
        if drifted:
            logger.warning(
                "Agent docs reconcile overwrote drifted file with PG "
                "authority: agent=%s file=%s",
                agent_id,
                filename,
            )
        return "overwrite" if drifted else "restore"

    if file_content is None:
        return "skip"
    # PG 无行：文件回填种子（幂等 upsert，内容不变不递增版本）
    await store.upsert_document(
        agent_id,
        doc_type,
        file_content,
        updated_by="startup_reconcile",
    )
    return "promote"


async def reconcile_agent_docs() -> dict:
    """启动对账入口（lifespan 后台任务；无 PG 时静默返回）。

    Returns:
        统计字典 {"agents": n, "overwrite": n, "restore": n,
        "promote": n, "skip": n}；无 PG 返回空 dict。
    """
    store = get_agent_docs_store()
    if store is None:
        return {}

    from ...config.utils import load_config

    try:
        profiles = dict(load_config().agents.profiles)
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Agent docs reconcile skipped (config load failed)",
            exc_info=True,
        )
        return {}

    stats = {"agents": 0, "overwrite": 0, "restore": 0, "promote": 0, "skip": 0}
    for agent_id, ref in profiles.items():
        workspace_dir = getattr(ref, "workspace_dir", None)
        if not workspace_dir:
            continue
        stats["agents"] += 1
        for filename, doc_type in DOC_TYPE_BY_FILENAME.items():
            try:
                action = await _reconcile_one_document(
                    store,
                    agent_id,
                    filename,
                    doc_type,
                    Path(workspace_dir),
                )
            except Exception:  # pylint: disable=broad-except
                # 单文档异常隔离，不阻断其余文档对账
                logger.warning(
                    "Agent docs reconcile failed: agent=%s file=%s",
                    agent_id,
                    filename,
                    exc_info=True,
                )
                continue
            stats[action] = stats.get(action, 0) + 1

    if any(stats[key] for key in ("overwrite", "restore", "promote")):
        logger.info("Agent docs reconcile finished: %s", stats)
    return stats
