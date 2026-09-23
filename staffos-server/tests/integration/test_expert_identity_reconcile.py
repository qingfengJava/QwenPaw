# -*- coding: utf-8 -*-
"""Integration test for expert identity reconciliation against real PG.

覆盖 T14 端到端：真实 ``experts`` 表列出 published 专家 → 工作区
``agent.json`` 身份列漂移检测 → ``mutate_agent_config`` 真实修复
（文件 + agent_documents 影子行）→ 幂等重跑零写。

Runs only when ``QWENPAW_TEST_PG_DSN`` is set. 测试数据全部使用
``captest_`` 前缀显式 ID，夹具按前缀定点清理，绝不触碰存量数据。
"""

from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

_EXPERT_ID = "captest_identity"
_AGENT_ID = "expert_captest_identity"

# 定点清理（仅本文件前缀；逐条静态语句，零插值）
_CLEANUP_STATEMENTS = (
    "DELETE FROM agent_document_revisions "
    "WHERE agent_id LIKE 'expert_captest_%'",
    "DELETE FROM agent_documents WHERE agent_id LIKE 'expert_captest_%'",
    "DELETE FROM experts WHERE id LIKE 'captest_%'",
)


@pytest.fixture
async def identity_env(monkeypatch):
    """Bootstrap enterprise schema, then clean this module's rows."""
    if not DSN:
        pytest.skip("QWENPAW_TEST_PG_DSN not set")
    monkeypatch.setenv("QWENPAW_PG_DSN", DSN)

    from qwenpaw.app import enterprise as ent_mod
    from qwenpaw.db import engine as engine_mod

    engine_mod._engines.clear()
    ent_mod._schema_ready = False
    ok = await ent_mod.bootstrap_enterprise()
    assert ok, "enterprise bootstrap failed against the test database"
    engine = engine_mod.create_pg_engine(DSN)
    async with engine.begin() as conn:
        for statement in _CLEANUP_STATEMENTS:
            await conn.execute(text(statement))
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            for statement in _CLEANUP_STATEMENTS:
                await conn.execute(text(statement))
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


async def _wait_shadow_writes() -> None:
    """Wait for fire-and-forget doc shadow writes to drain."""
    from qwenpaw.app.agent_docs import store as docs_store_mod

    for _ in range(100):
        if not docs_store_mod._shadow_tasks:
            return
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_expert_identity_repaired_end_to_end(
    identity_env,
    tmp_path,
    monkeypatch,
) -> None:
    """真实 PG：漂移 → 修复（文件 + 影子行）→ 重跑幂等。"""
    from qwenpaw.app.agent_docs import reconcile as recon
    from qwenpaw.app.experts.models import EXPERT_STATUS_PUBLISHED
    from qwenpaw.app.experts.store import get_expert_store

    store = get_expert_store()
    await store.create_expert(
        name="身份对账员",
        expert_id=_EXPERT_ID,
        description="权威简介",
    )
    await store.set_expert_status(_EXPERT_ID, EXPERT_STATUS_PUBLISHED)

    workspace = tmp_path / _EXPERT_ID
    workspace.mkdir(parents=True)
    config_path = workspace / "agent.json"
    config_path.write_text(
        json.dumps(
            {
                "id": "expert_wrong",
                "name": "旧名",
                "description": "旧简介",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        recon,
        "_expert_workspace_dir",
        lambda expert_id: tmp_path / expert_id,
    )
    # 真实 mutate/save 链（原子写 + 影子行），root 配置注入 tmp 工作区
    fake_config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                _AGENT_ID: SimpleNamespace(workspace_dir=str(workspace)),
            },
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.load_config",
        lambda: fake_config,
    )

    stats = await recon.reconcile_expert_identities()

    assert stats["repaired"] == 1
    assert stats["failed"] == 0
    repaired = json.loads(config_path.read_text(encoding="utf-8"))
    assert repaired["id"] == _AGENT_ID
    assert repaired["name"] == "身份对账员"
    assert repaired["description"] == "权威简介"

    # 影子行随修复落库（与文件同一收口）
    await _wait_shadow_writes()
    async with identity_env.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT content FROM agent_documents "
                "WHERE agent_id = :aid AND doc_type = 'agent_json'"
            ),
            {"aid": _AGENT_ID},
        )
        row = result.first()
    assert row is not None, "shadow row missing after repair"
    shadow_payload = json.loads(row[0])
    assert shadow_payload["name"] == "身份对账员"

    # 幂等重跑：clean，零再写
    again = await recon.reconcile_expert_identities()
    assert again["repaired"] == 0
    assert again["failed"] == 0
    unchanged = json.loads(config_path.read_text(encoding="utf-8"))
    assert unchanged == repaired
