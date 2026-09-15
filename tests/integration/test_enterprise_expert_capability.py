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

    # 私有能力化语义：已发布也可直接改内容（不改 status/不升 version）
    edited_pub = await store.update_sop(sop.id, name="改名")
    assert edited_pub is not None
    assert edited_pub.name == "改名"
    assert edited_pub.version == 2

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

    # 归档后仍可物理删（store 层不设状态门槛，绑定守卫在 router 层）
    archived = await store.archive_sop(sop.id)
    assert archived is not None and archived.status == "archived"
    assert await store.delete_sop(sop.id)
    assert await store.get_sop(sop.id) is None
    draft = await store.create_sop(
        name="草稿SOP",
        sop_id="captest_sop_draft",
    )
    assert await store.delete_sop(draft.id)


@pytest.mark.asyncio
async def test_sop_environment_isolation_and_promote(enterprise_env):
    """SOP 环境化：草稿行编辑不污染线上行，promote 才升线上并写快照。"""
    from qwenpaw.app.experts.models import (
        SOP_ENVIRONMENT_DRAFT,
        SOP_ENVIRONMENT_PRODUCTION,
    )
    from qwenpaw.app.experts.sops import get_sop_store

    store = get_sop_store()
    # 工作台/AI 新建落草稿环境行
    draft = await store.create_sop(
        name="退款流程",
        sop_id="captest_sop_env",
        goal="30 分钟完成退款",
        nodes=[{"id": "n1", "title": "受理", "expected_outcome": "工单已建"}],
        owner_id="captest_expert_env",
        environment=SOP_ENVIRONMENT_DRAFT,
    )
    assert draft.environment == SOP_ENVIRONMENT_DRAFT
    assert draft.status == "draft"

    # 草稿行存在时，线上行尚未创建
    assert await store.get_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_PRODUCTION,
    ) is None

    # 编辑只作用于草稿行，不影响（尚不存在的）线上行
    await store.update_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_DRAFT,
        nodes=[
            {"id": "n1", "title": "受理", "expected_outcome": "工单已建"},
            {"id": "n2", "title": "审核", "expected_outcome": "风险已判"},
        ],
    )
    draft_after = await store.get_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_DRAFT,
    )
    assert len(draft_after.nodes) == 2

    # promote：草稿 → 线上 v1 + 快照
    promoted = await store.promote_sop(draft.id, published_by="qingfeng")
    assert promoted.environment == SOP_ENVIRONMENT_PRODUCTION
    assert promoted.status == "published"
    assert promoted.version == 1
    assert len(promoted.nodes) == 2
    versions = await store.list_versions(draft.id)
    assert len(versions) == 1 and versions[0].version == 1

    # 草稿行 promote 后保留（作为后续可编辑工作副本）
    assert await store.get_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_DRAFT,
    ) is not None

    # 再改草稿 + 再 promote → 线上 v2，草稿与线上分叉即“有未发布变更”
    await store.update_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_DRAFT,
        goal="20 分钟完成退款",
    )
    promoted2 = await store.promote_sop(draft.id)
    assert promoted2.version == 2
    assert promoted2.goal == "20 分钟完成退款"
    # 线上行仍是 v2 新目标，草稿行 goal 也同步（promote 复制非移动）
    prod_now = await store.get_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_PRODUCTION,
    )
    assert prod_now.goal == "20 分钟完成退款"
    assert len(await store.list_versions(draft.id)) == 2

    # 合并列表视图：同 id 草稿优先（代表可编辑工作态）
    merged = await store.list_sops(
        owner_id="captest_expert_env",
        environment=SOP_ENVIRONMENT_DRAFT,
    )
    assert any(r.id == draft.id for r in merged)

    # 物理删：双环境行 + 版本链一并清除
    assert await store.delete_sop(draft.id)
    assert await store.get_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_DRAFT,
    ) is None
    assert await store.get_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_PRODUCTION,
    ) is None


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


@pytest.mark.asyncio
async def test_sop_private_semantics(enterprise_env):
    """SOP 私有能力化：published 可编辑、full 投影、duplicate、无绑定可删。"""
    from qwenpaw.app.experts.sops import get_sop_store

    store = get_sop_store()
    created = await store.create_sop(
        name="源流程",
        sop_id="captest_sop_priv",
        goal="原目标",
        nodes=[{"id": "n1", "title": "步骤一", "expected_outcome": "ok"}],
        slots=[{"key": "k1", "label": "槽位"}],
        owner_id="captest_expert_a",
    )
    assert created.status == "draft"
    assert created.owner_id == "captest_expert_a"

    # 发布后允许直接编辑内容：status 保持 published、version 不变
    published = await store.publish_sop("captest_sop_priv")
    assert published is not None and published.version == 2
    edited = await store.update_sop("captest_sop_priv", goal="新目标")
    assert edited is not None
    assert edited.goal == "新目标"
    assert edited.status == "published"
    assert edited.version == 2

    # full 投影带 nodes；light 投影 nodes 为空
    full_rows = await store.list_sops(owner_id="captest_expert_a", full=True)
    assert any(r.id == "captest_sop_priv" and r.nodes for r in full_rows)
    light_rows = await store.list_sops(owner_id="captest_expert_a")
    assert all(not r.nodes for r in light_rows)

    # duplicate：新行 draft、owner 归目标员工、内容一致、不复制绑定
    copy = await store.duplicate_sop(
        "captest_sop_priv",
        target_expert_id="captest_expert_b",
        new_sop_id="captest_sop_copy",
    )
    assert copy is not None
    assert copy.status == "draft"
    assert copy.version == 1
    assert copy.owner_id == "captest_expert_b"
    assert copy.name == "源流程"
    assert copy.goal == "新目标"
    assert [n["id"] for n in copy.nodes] == ["n1"]

    # delete：无绑定时 published 也可物理删（版本快照同删）
    assert await store.delete_sop("captest_sop_copy") is True
    assert await store.get_sop("captest_sop_copy") is None


@pytest.mark.asyncio
async def test_ensure_binding_idempotent(enterprise_env):
    """ensure_binding 重复调用只落一行（发布自动绑定的幂等底座）。"""
    from qwenpaw.app.experts.capability import get_capability_store

    cap = get_capability_store()
    await cap.ensure_binding(
        "captest_expert_e", "sop", "captest_sop_e", {"name": "x"},
    )
    await cap.ensure_binding(
        "captest_expert_e", "sop", "captest_sop_e", {"name": "x"},
    )
    bindings = await cap.list_bindings("captest_expert_e", "sop")
    assert len([b for b in bindings if b.resource_id == "captest_sop_e"]) == 1


@pytest.mark.asyncio
async def test_sop_publish_auto_bind_and_private_guards(enterprise_env):
    """发布组合自动绑定 + 一对一私有守卫 + 复制式复用 + 删除守卫。

    直接调用路由函数（绕过鉴权依赖），覆盖 endpoint 层组合逻辑。
    """
    import types

    from fastapi import HTTPException

    from qwenpaw.app.experts.capability import get_capability_store
    from qwenpaw.app.experts.models import (
        ResourceBinding,
        SopDuplicateBody,
        SopPublishBody,
    )
    from qwenpaw.app.experts.sops import get_sop_store
    from qwenpaw.app.experts.store import get_expert_store
    from qwenpaw.app.routers.admin.expert_capability import (
        ResourceBindingsPutBody,
        delete_sop,
        duplicate_sop,
        publish_sop,
        replace_resources,
    )

    request = types.SimpleNamespace(
        state=types.SimpleNamespace(user="tester"),
        app=types.SimpleNamespace(state=types.SimpleNamespace()),
    )
    expert_a = await get_expert_store().create_expert(
        name="甲", expert_id="captest_expert_ra",
    )
    expert_b = await get_expert_store().create_expert(
        name="乙", expert_id="captest_expert_rb",
    )
    store = get_sop_store()
    sop = await store.create_sop(
        name="流程甲",
        sop_id="captest_sop_router",
        owner_id=expert_a.id,
    )

    # 发布：自动绑定归属员工（重复发布幂等不重复建行）
    await publish_sop(sop.id, request, SopPublishBody(expert_id=expert_a.id))
    await publish_sop(sop.id, request, SopPublishBody(expert_id=expert_a.id))
    bindings_a = await get_capability_store().list_bindings(expert_a.id, "sop")
    assert [b.resource_id for b in bindings_a] == [sop.id]

    # 发布到非归属员工 → 400（私有守卫）
    with pytest.raises(HTTPException):
        await publish_sop(sop.id, request, SopPublishBody(expert_id=expert_b.id))

    # 员工乙直接绑定甲的 SOP → 400；先复制为副本再绑定 → 放行
    with pytest.raises(HTTPException):
        await replace_resources(
            expert_b.id,
            ResourceBindingsPutBody(bindings=[
                ResourceBinding(resource_type="sop", resource_id=sop.id),
            ]),
            request,
        )
    copy = await duplicate_sop(
        sop.id,
        SopDuplicateBody(target_expert_id=expert_b.id),
    )
    assert copy.owner_id == expert_b.id
    assert copy.status == "draft"
    saved = await replace_resources(
        expert_b.id,
        ResourceBindingsPutBody(bindings=[
            ResourceBinding(resource_type="sop", resource_id=copy.id),
        ]),
        request,
    )
    assert any(b["resource_id"] == copy.id for b in saved["bindings"])

    # 仍有绑定的 SOP 不可删；解除（停用）后可删
    with pytest.raises(HTTPException):
        await delete_sop(sop.id)
    await replace_resources(
        expert_a.id,
        ResourceBindingsPutBody(bindings=[]),
        request,
    )
    await delete_sop(sop.id)
    assert await store.get_sop(sop.id) is None

    # 自清理：duplicate 副本是随机 id（不在 captest_ 前缀内），当场删净
    await replace_resources(
        expert_b.id,
        ResourceBindingsPutBody(bindings=[]),
        request,
    )
    await delete_sop(copy.id)
    assert await store.get_sop(copy.id) is None
