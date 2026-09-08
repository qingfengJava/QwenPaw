# -*- coding: utf-8 -*-
"""Integration tests for the expert draft-preview runtime (20260908).

覆盖工作台「预览/发布双轨」的后端不变量：

- 草稿调试实例（``expert_{id}__draft``）与线上实例（``expert_{id}``）
  workspace 完全隔离（.drafts/ 子目录，互不可见）；
- preview start 幂等且每次重写草稿产物（agent.json / PROFILE.md）；
- 发布联动销毁调试实例（publish 后草稿 workspace 清理、running=False）；
- 版本快照链（list/get）与恢复（快照 spec 写回草稿、剥离运行时字段）。

Runs only when ``QWENPAW_TEST_PG_DSN`` is set. 沿用 captest 模式：
全部数据用 ``prevtest_`` 前缀显式 ID 创建，夹具按前缀定点清理。
"""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

# 定点清理（仅 prevtest_ 前缀；逐条静态语句，零插值）
_CLEANUP_STATEMENTS = (
    "DELETE FROM expert_skills WHERE expert_id LIKE 'prevtest_%'",
    "DELETE FROM published_experts WHERE expert_id LIKE 'prevtest_%'",
    "DELETE FROM expert_resource_bindings WHERE expert_id LIKE 'prevtest_%'",
    "DELETE FROM experts WHERE id LIKE 'prevtest_%'",
)


@pytest.fixture
async def enterprise_env(monkeypatch):
    """Bootstrap the enterprise schema, then clean this module's rows."""
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
        yield
    finally:
        async with engine.begin() as conn:
            for statement in _CLEANUP_STATEMENTS:
                await conn.execute(text(statement))
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


@pytest.fixture
def sandboxed_working_dir(tmp_path, monkeypatch):
    """workspace 物化 + 根配置重定向到临时目录。

    publish/preview 链在函数内延迟 import WORKING_DIR → patch
    ``qwenpaw.constant`` 模块属性即生效；config 读写经
    ``qwenpaw.config.utils``/``config.config`` 的模块级绑定，需一并
    patch（与 tests/unit/workspace 同模式）。
    """
    import qwenpaw.config.config as config_config_mod
    import qwenpaw.config.utils as config_utils_mod
    from qwenpaw import constant as constant_mod

    monkeypatch.setattr(constant_mod, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(config_utils_mod, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(config_config_mod, "WORKING_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 纯函数：agent id / workspace 目录推导
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_agent_id_and_workspace_isolation(sandboxed_working_dir):
    from qwenpaw.app.experts.models import (
        DRAFT_AGENT_SUFFIX,
        expert_agent_id,
        expert_draft_agent_id,
    )
    from qwenpaw.app.experts.preview import draft_workspace_dir
    from qwenpaw.app.experts.publish import _expert_workspace_dir

    assert DRAFT_AGENT_SUFFIX == "__draft"
    assert expert_draft_agent_id("abc") == f"{expert_agent_id('abc')}__draft"

    live_dir = _expert_workspace_dir("abc")
    draft_dir = draft_workspace_dir("abc")
    # 调试 workspace 与线上 workspace 严格分离，且互不为父子目录
    assert draft_dir != live_dir
    assert live_dir not in draft_dir.parents
    assert draft_dir not in live_dir.parents
    assert ".drafts" in draft_dir.parts


# ---------------------------------------------------------------------------
# 预览生命周期：start 幂等 → 发布联动销毁 → 版本/恢复
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_lifecycle_publish_joint_stop(
    enterprise_env,
    sandboxed_working_dir,
):
    from qwenpaw.app.experts.models import expert_draft_agent_id
    from qwenpaw.app.experts.preview import (
        draft_workspace_dir,
        preview_status,
        start_expert_preview,
    )
    from qwenpaw.app.experts.publish import publish_expert
    from qwenpaw.app.experts.store import get_expert_store

    store = get_expert_store()
    expert = await store.create_expert(
        name="预览测试员",
        expert_id="prevtest_preview",
        agent_spec={"language": "zh"},
    )
    assert expert.status == "draft"
    draft_agent = expert_draft_agent_id(expert.id)

    # ── 从未发布：running=False，草稿即「未发布变更」 ──
    status = await preview_status(expert.id)
    assert status["running"] is False
    assert status["has_unpublished_changes"] is True
    assert status["published_version"] is None

    # ── start：草稿实例物化，线上 workspace 不被触碰 ──
    result = await start_expert_preview(expert.id)
    assert result["running"] is True
    assert result["agent_id"] == draft_agent

    draft_dir = draft_workspace_dir(expert.id)
    live_dir = draft_dir.parent.parent / expert.id
    assert (draft_dir / "agent.json").is_file()
    assert json.loads((draft_dir / "agent.json").read_text("utf-8"))[
        "id"
    ] == draft_agent
    assert not live_dir.exists(), "预览启动不得创建线上 workspace"

    status = await preview_status(expert.id)
    assert status["running"] is True

    # ── start 幂等 + 草稿修改后重启即生效（agent.json 每次重写）──
    await store.update_expert(expert.id, description="调试改过的简介")
    await start_expert_preview(expert.id)
    assert (draft_dir / "agent.json").is_file()
    assert json.loads((draft_dir / "agent.json").read_text("utf-8"))[
        "description"
    ] == "调试改过的简介"

    # ── 发布：线上物化 + 快照落库 + 草稿实例联动销毁 ──
    published = await publish_expert(expert.id, published_by="tester")
    assert published.status == "published"
    assert published.version == 1
    assert live_dir.is_dir(), "发布必须物化线上 workspace"
    assert not draft_dir.exists(), "发布后调试实例必须被联动销毁"

    snapshots = await store.list_snapshots(expert.id)
    assert len(snapshots) == 1
    assert snapshots[0].version == 1

    status = await preview_status(expert.id)
    assert status["running"] is False
    # 草稿已发布：无未发布变更
    assert status["has_unpublished_changes"] is False
    assert status["published_version"] == 1

    # ── 再改草稿：未发布变更重新可见（发布边界隔离的判定基础）──
    await store.update_expert(expert.id, description="线上看不到的草稿简介")
    status = await preview_status(expert.id)
    assert status["has_unpublished_changes"] is True


@pytest.mark.asyncio
async def test_preview_stop_idempotent_and_cleanup(
    enterprise_env,
    sandboxed_working_dir,
):
    from qwenpaw.app.experts.preview import (
        draft_workspace_dir,
        start_expert_preview,
        stop_expert_preview,
    )
    from qwenpaw.app.experts.store import get_expert_store

    store = get_expert_store()
    expert = await store.create_expert(
        name="停启测试员",
        expert_id="prevtest_stop",
        agent_spec={"language": "zh"},
    )
    # 未启动时 stop：幂等静默
    result = await stop_expert_preview(expert.id)
    assert result["running"] is False

    await start_expert_preview(expert.id)
    assert draft_workspace_dir(expert.id).is_dir()

    result = await stop_expert_preview(expert.id)
    assert result["running"] is False
    assert not draft_workspace_dir(expert.id).exists(), (
        "stop 必须清理草稿 workspace（调试会话历史在后端会话存储中保留）"
    )


@pytest.mark.asyncio
async def test_version_restore_writes_draft_without_runtime_keys(
    enterprise_env,
    sandboxed_working_dir,
):
    from qwenpaw.app.experts.publish import publish_expert
    from qwenpaw.app.experts.store import get_expert_store
    from qwenpaw.app.routers.admin.experts import (
        _SPEC_RUNTIME_KEYS,
        restore_version,
    )

    store = get_expert_store()
    expert = await store.create_expert(
        name="回滚测试员",
        expert_id="prevtest_restore",
        agent_spec={"language": "zh", "tools": {"builtin_tools": {}}},
    )
    await publish_expert(expert.id, published_by="tester")
    # v2：改草稿后再发布，形成双快照
    await store.update_expert(expert.id, description="v2 简介")
    await publish_expert(expert.id, published_by="tester")

    versions = await store.list_snapshots(expert.id)
    assert [v.version for v in versions] == [2, 1]

    # 回滚到 v1：快照 spec 写回草稿（剥离运行时字段），线上不动
    restored = await restore_version(expert.id, 1)
    assert restored["restored_version"] == 1
    assert not (_SPEC_RUNTIME_KEYS & set(restored["agent_spec"].keys()))

    record = await store.get_expert(expert.id)
    assert record.description == "v2 简介", "恢复只覆盖 agent_spec，不动档案列"
    assert record.agent_spec.get("description") is None or (
        record.agent_spec.get("description") != "v2 简介"
    )
    # 快照链只增不可变
    assert len(await store.list_snapshots(expert.id)) == 2


@pytest.mark.asyncio
async def test_preview_missing_expert_raises(enterprise_env):
    from qwenpaw.app.experts.preview import preview_status

    with pytest.raises(ValueError, match="not found"):
        await preview_status("prevtest_missing")
