# -*- coding: utf-8 -*-
"""Integration tests for the digital-employee capability layer (20260830).

Cover the six capability stores against a real PostgreSQL: profile
columns, resource bindings, SOP version chain, bucketed memories,
scheduled-task projection + run records, message feedback and the
evolution-proposal lifecycle — plus the work-record aggregation shape.
Runs only when ``QWENPAW_TEST_PG_DSN`` is set.

⚠️ 本机测试库与真实库同库（见项目记忆 dev-machine-pg-env）：本文件
**不做全表清空**——全部测试数据用 ``captest_`` 前缀的显式 ID 创建，
夹具按前缀定点清理，绝不触碰存量业务数据。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()

# 定点清理（仅 captest_ 前缀；逐条静态语句，零插值）
_CLEANUP_STATEMENTS = (
    "DELETE FROM expert_task_runs WHERE expert_id LIKE 'captest_%'",
    "DELETE FROM expert_scheduled_tasks WHERE expert_id LIKE 'captest_%'",
    "DELETE FROM expert_memories WHERE expert_id LIKE 'captest_%'",
    "DELETE FROM evolution_proposals WHERE expert_id LIKE 'captest_%'",
    "DELETE FROM message_feedback WHERE expert_id LIKE 'captest_%'",
    "DELETE FROM expert_resource_bindings WHERE expert_id LIKE 'captest_%'",
    "DELETE FROM expert_skills WHERE expert_id LIKE 'captest_%'",
    "DELETE FROM published_experts WHERE expert_id LIKE 'captest_%'",
    "DELETE FROM team_run_nodes WHERE assignee_expert_id LIKE 'captest_%'",
    "DELETE FROM sop_versions WHERE sop_id LIKE 'captest_%'",
    "DELETE FROM sops WHERE id LIKE 'captest_%'",
    "DELETE FROM experts WHERE id LIKE 'captest_%'",
)


@pytest.fixture
async def enterprise_env(monkeypatch):
    """Bootstrap the enterprise schema (applies alembic 0012), then clean
    only this module's ``captest_``-prefixed rows."""
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
        # 定点清理本模块数据 + dispose 连接（避免绑死旧事件循环）
        async with engine.begin() as conn:
            for statement in _CLEANUP_STATEMENTS:
                await conn.execute(text(statement))
        await engine_mod.dispose_engines()
        ent_mod._schema_ready = False


# ---------------------------------------------------------------------------
# experts 档案列（D1）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expert_profile_columns_roundtrip(enterprise_env):
    from qwenpaw.app.experts.store import get_expert_store

    store = get_expert_store()
    record = await store.create_expert(
        name="档案测试员",
        expert_id="captest_profile",
        department="客户成功部",
        work_styles=["耐心细致", "结果导向"],
        work_modes=["7x24 值守"],
    )
    assert record.department == "客户成功部"
    assert record.work_styles == ["耐心细致", "结果导向"]
    assert record.work_modes == ["7x24 值守"]
    assert record.hire_date is not None

    updated = await store.update_expert(
        record.id,
        department="交付部",
        work_styles=["严谨"],
        hire_date_clear=True,
    )
    assert updated is not None
    assert updated.department == "交付部"
    assert updated.work_styles == ["严谨"]
    assert updated.hire_date is None

    # 不传 = 不修改（None 语义）
    untouched = await store.update_expert(record.id, badge="特邀")
    assert untouched is not None
    assert untouched.department == "交付部"
    assert untouched.work_styles == ["严谨"]


# ---------------------------------------------------------------------------
# 能力挂载（D2）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_bindings_replace_and_clear(enterprise_env):
    from qwenpaw.app.experts.capability import get_capability_store
    from qwenpaw.app.experts.models import ResourceBinding
    from qwenpaw.app.experts.store import get_expert_store

    expert = await get_expert_store().create_expert(
        name="挂载测试员",
        expert_id="captest_binding",
    )
    cap = get_capability_store()
    saved = await cap.replace_bindings(
        expert.id,
        [
            ResourceBinding(
                resource_type="sop",
                resource_id="captest_sop_ref",
                metadata={"name": "合同审查 SOP"},
            ),
            ResourceBinding(resource_type="tool", resource_id="http_get"),
            # 同 type+id 重复 → 去重
            ResourceBinding(resource_type="sop", resource_id="captest_sop_ref"),
            # 非法类型 → 丢弃
            ResourceBinding(resource_type="skill", resource_id="x"),
        ],
    )
    assert len(saved) == 2
    types = {(b.resource_type, b.resource_id) for b in saved}
    assert ("sop", "captest_sop_ref") in types
    assert ("tool", "http_get") in types

    # PUT 空数组 = 清空（逆向路径）
    cleared = await cap.replace_bindings(expert.id, [])
    assert cleared == []
    assert await cap.list_bindings(expert.id) == []


# ---------------------------------------------------------------------------
# SOP 资产 + 版本链（D3）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sop_lifecycle_with_versions(enterprise_env):
    from qwenpaw.app.experts.sops import get_sop_store

    store = get_sop_store()
    sop = await store.create_sop(
        name="合同审查",
        sop_id="captest_sop_main",
        goal="输出合规审查意见",
        nodes=[
            {"id": "n1", "title": "收集合同", "expected_outcome": "文本齐备"},
        ],
    )
    assert sop.status == "draft"
    assert sop.version == 1

    # 草稿可编辑
    updated = await store.update_sop(
        sop.id,
        description="覆盖合同审查、条款风险识别",
        slots=[{"key": "contract_text", "required": True}],
    )
    assert updated is not None
    assert updated.description.startswith("覆盖")

    # 发布：version+1 + 快照
    published = await store.publish_sop(sop.id, published_by="qingfeng")
    assert published.status == "published"
    assert published.version == 2
    versions = await store.list_versions(sop.id)
    assert len(versions) == 1
    assert versions[0].version == 2
    assert versions[0].snapshot["nodes"][0]["id"] == "n1"

    # 已发布不可直接改字段（必须走版本链）
    with pytest.raises(ValueError):
        await store.update_sop(sop.id, name="改名")

    # 再发布一次验证快照链
    again = await store.publish_sop(sop.id, change_note="二次发布")
    assert again.version == 3
    assert len(await store.list_versions(sop.id)) == 2

    # 回滚到 v2 = 以 v4 新版本恢复 v2 内容（不改历史）
    # v2 快照发布于 slots/description 编辑之后，回滚应带全部当时字段
    rolled = await store.rollback_sop(sop.id, to_version=2, published_by="t")
    assert rolled.version == 4
    assert rolled.nodes[0]["id"] == "n1"
    assert rolled.slots == [{"key": "contract_text", "required": True}]
    assert rolled.description.startswith("覆盖")
    all_versions = await store.list_versions(sop.id)
    assert [v.version for v in all_versions] == [4, 3, 2]

    # 归档 + draft-only 删除保护
    archived = await store.archive_sop(sop.id)
    assert archived is not None and archived.status == "archived"
    assert not await store.delete_sop(sop.id)
    draft = await store.create_sop(
        name="草稿SOP",
        sop_id="captest_sop_draft",
    )
    assert await store.delete_sop(draft.id)


# ---------------------------------------------------------------------------
# 分桶记忆（D4）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_upsert_dedup_and_clear(enterprise_env):
    from qwenpaw.app.experts.memories import get_memory_store
    from qwenpaw.app.experts.store import get_expert_store

    expert = await get_expert_store().create_expert(
        name="记忆测试员",
        expert_id="captest_memory",
    )
    store = get_memory_store()
    first = await store.upsert_memory(
        expert.id,
        user_id="u1",
        kind="preference",
        content="偏好周报用表格",
        dedup_key="weekly_report",
        importance=0.8,
    )
    # 同 dedup_key 再写 = 覆盖（不新增行）
    second = await store.upsert_memory(
        expert.id,
        user_id="u1",
        kind="preference",
        content="偏好周报用表格，附趋势列",
        dedup_key="weekly_report",
        importance=0.9,
    )
    assert second.id == first.id
    # REAL 列浮点精度：用近似比较
    assert second.importance == pytest.approx(0.9)
    records = await store.list_memories(expert.id, user_id="u1")
    assert len(records) == 1

    # 非法 kind 回落 fact
    fallback = await store.upsert_memory(
        expert.id,
        kind="unknown_kind",
        content="x",
    )
    assert fallback.kind == "fact"

    # 清空（逆向）
    assert await store.clear_memories(expert.id) == 2
    assert await store.list_memories(expert.id) == []


# ---------------------------------------------------------------------------
# 定时任务投影 + 执行留痕（D5，store 层；权威接线由观察者单测覆盖）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_task_store_and_runs(enterprise_env):
    from qwenpaw.app.experts.scheduling import get_scheduling_store
    from qwenpaw.app.experts.store import get_expert_store

    expert = await get_expert_store().create_expert(
        name="排期测试员",
        expert_id="captest_sched",
    )
    store = get_scheduling_store()
    task = await store.create_task(
        expert_id=expert.id,
        name="每日巡检",
        task_prompt="巡检线上服务并输出日报",
        schedule_type="cron",
        schedule_json={"cron": "0 9 * * 1-5"},
    )
    assert task.status == "active"
    assert await store.count_active_by_expert(expert.id) == 1

    # 执行留痕：同 scheduled_for 幂等（begin_run 返回同一行）
    run = await store.begin_run(task, task.created_at)
    duplicate = await store.begin_run(task, task.created_at)
    assert run.id == duplicate.id
    await store.finish_run(run, status="succeeded", result_summary="一切正常")
    runs = await store.list_runs(task.id)
    assert len(runs) == 1
    assert runs[0].status == "succeeded"

    refreshed = await store.get_task(task.id)
    assert refreshed is not None
    assert refreshed.last_status == "succeeded"
    assert refreshed.run_count == 1

    # 归档（删除语义）后默认列表不可见
    assert await store.delete_task(task.id)
    assert await store.list_tasks(expert.id) == []
    assert await store.list_tasks(expert.id, include_archived=True)


# ---------------------------------------------------------------------------
# 反馈 + 演进提案（D7）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feedback_rate_and_summary(enterprise_env):
    from qwenpaw.app.experts.feedback import get_feedback_store
    from qwenpaw.app.experts.store import get_expert_store

    expert = await get_expert_store().create_expert(
        name="反馈测试员",
        expert_id="captest_feedback",
    )
    store = get_feedback_store()
    await store.rate("captest_m1", "u1", "up", expert_id=expert.id)
    # 改口（覆盖评分），不传 expert_id 也不应抹掉归属
    await store.rate("captest_m1", "u1", "down", comment="改口")
    await store.rate("captest_m2", "u1", "up", expert_id=expert.id)
    with pytest.raises(ValueError):
        await store.rate("captest_m3", "u1", "meh")

    summary = await store.summary(expert.id, days=30)
    assert summary["feedback_up"] == 1
    assert summary["feedback_down"] == 1
    assert summary["positive_rate"] == 0.5
    recent = await store.recent_for_expert(expert.id)
    assert {r["message_id"] for r in recent} == {
        "captest_m1",
        "captest_m2",
    }


@pytest.mark.asyncio
async def test_evolution_proposal_lifecycle(enterprise_env):
    from qwenpaw.app.experts.feedback import get_evolution_store
    from qwenpaw.app.experts.store import get_expert_store

    expert = await get_expert_store().create_expert(
        name="演进测试员",
        expert_id="captest_evolution",
        system_prompt="原始人设",
    )
    store = get_evolution_store()
    proposal = await store.create_proposal(
        expert_id=expert.id,
        title="收紧差评场景的回复口径",
        hypothesis="明确兜底话术可降低差评率",
        candidate={
            "target": "system_prompt",
            "new_value": "改进后人设",
            "previous_value": "原始人设",
        },
    )
    assert proposal.status == "draft"

    # 状态机守卫：draft 不能直接 review
    with pytest.raises(ValueError):
        await store.review(proposal.id, "approve", reviewer="admin")
    await store.submit_for_review(proposal.id)
    approved = await store.review(proposal.id, "approve", reviewer="admin")
    assert approved is not None and approved.status == "approved"
    assert approved.reviewed_by == "admin"

    await store.mark_published(proposal.id)
    with pytest.raises(ValueError):
        await store.mark_published(proposal.id)  # 不能重复发布
    await store.mark_rolled_back(proposal.id)
    final = await store.get_proposal(proposal.id)
    assert final is not None and final.status == "rolled_back"


# ---------------------------------------------------------------------------
# 工作记录聚合（D6）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_work_record_aggregation(enterprise_env):
    from qwenpaw.app.experts.feedback import get_feedback_store
    from qwenpaw.app.experts.scheduling import get_scheduling_store
    from qwenpaw.app.experts.store import get_expert_store
    from qwenpaw.app.experts.worklog import get_worklog_service

    expert = await get_expert_store().create_expert(
        name="台账测试员",
        expert_id="captest_worklog",
    )
    await get_scheduling_store().create_task(
        expert_id=expert.id,
        name="每日巡检",
        task_prompt="巡检",
    )
    task = (await get_scheduling_store().list_tasks(expert.id))[0]
    run = await get_scheduling_store().begin_run(task, task.created_at)
    await get_scheduling_store().finish_run(
        run,
        status="succeeded",
        result_summary="巡检完成",
    )
    await get_feedback_store().rate(
        "captest_m1",
        "u1",
        "up",
        expert_id=expert.id,
    )
    await get_feedback_store().rate(
        "captest_m2",
        "u1",
        "down",
        expert_id=expert.id,
    )

    record = await get_worklog_service().build_work_record(expert.id, days=7)
    assert record.total_tasks == 1
    assert record.succeeded_tasks == 1
    assert record.feedback_up == 1
    assert record.feedback_down == 1
    assert record.positive_rate == 0.5
    assert len(record.by_day) == 7
    kinds = {e["kind"] for e in record.timeline}
    assert "scheduled" in kinds


@pytest.mark.asyncio
async def test_api_key_issue_verify_revoke(enterprise_env):
    """P4 凭证面：签发（明文仅一次）→ 验证 → 吊销 → 验证失效。"""
    from qwenpaw.app.experts.apikeys import get_api_key_store
    from qwenpaw.app.experts.store import get_expert_store

    expert = await get_expert_store().create_expert(
        name="密钥测试员",
        expert_id="captest_apikey",
    )
    store = get_api_key_store()
    issued = await store.issue_key(
        expert.id,
        name="OA 集成",
        created_by="qingfeng",
    )
    plaintext = issued["plaintext"]
    assert plaintext.startswith("sk_ek_")
    # 落库不含明文/哈希外泄
    assert "plaintext" not in await store.get_key(expert.id, issued["id"])
    # 验证通过且绑定专家边界
    verified = await store.verify(plaintext)
    assert verified is not None
    assert verified["expert_id"] == expert.id
    # 错误密钥不通过
    assert await store.verify("sk_ek_" + "0" * 32) is None
    # 吊销后即时失效
    assert await store.revoke_key(expert.id, issued["id"])
    assert await store.verify(plaintext) is None
    # 幂等重复吊销返回 False
    assert not await store.revoke_key(expert.id, issued["id"])
