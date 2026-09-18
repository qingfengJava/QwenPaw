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
    "DELETE FROM agent_document_revisions WHERE agent_id LIKE 'captest_%'",
    "DELETE FROM agent_documents WHERE agent_id LIKE 'captest_%'",
    "DELETE FROM cron_job_history WHERE agent_id LIKE 'expert_captest_%'",
    "DELETE FROM cron_jobs WHERE agent_id LIKE 'expert_captest_%'",
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
    from qwenpaw.app.experts.models import (
        SOP_ENVIRONMENT_DRAFT,
        SOP_ENVIRONMENT_PRODUCTION,
    )
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

    # 统一发布闸门语义：回滚到 v2 = 把 v2 快照内容恢复到草稿行，
    # 线上行不动（仍 v3）、不写新快照；需员工发布才 promote 生效
    rolled = await store.rollback_sop(sop.id, to_version=2, published_by="t")
    assert rolled.environment == SOP_ENVIRONMENT_DRAFT
    assert rolled.status == "draft"
    assert rolled.nodes[0]["id"] == "n1"
    assert rolled.slots == [{"key": "contract_text", "required": True}]
    assert rolled.description.startswith("覆盖")
    # 线上行保持 v3 未被回滚改写
    prod_now = await store.get_sop(
        sop.id,
        environment=SOP_ENVIRONMENT_PRODUCTION,
    )
    assert prod_now.version == 3
    # 回滚不产生新版本快照，版本链仍 [3, 2]
    all_versions = await store.list_versions(sop.id)
    assert [v.version for v in all_versions] == [3, 2]

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

    # promote 幂等：草稿无改动时重复 promote 不 bump 版本、不新增快照
    again_same = await store.promote_sop(draft.id)
    assert again_same.version == 1
    assert len(await store.list_versions(draft.id)) == 1
    # 无差异 → 归属员工无未发布变更
    assert not await store.has_unpublished_changes("captest_expert_env")

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

    # promote 后草稿与线上一致 → 无未发布变更
    assert not await store.has_unpublished_changes("captest_expert_env")
    # 再改草稿 → 出现未发布变更（员工发布徽标依据）
    await store.update_sop(
        draft.id,
        environment=SOP_ENVIRONMENT_DRAFT,
        goal="10 分钟完成退款",
    )
    assert await store.has_unpublished_changes("captest_expert_env")

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
# 定时任务读平面（收口后 store 委托 CronLedgerReader 读 cron 双表）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_task_reads_from_cron_plane(enterprise_env, tmp_path):
    """收口后无 legacy 台账：执行留痕落 cron_job_history，store 读回。"""
    from datetime import datetime, timedelta, timezone

    from qwenpaw.app.crons.models import CronExecutionRecord
    from qwenpaw.app.crons.repo.pg_repo import PgJobRepository
    from qwenpaw.app.experts.scheduling import get_scheduling_store
    from qwenpaw.app.experts.store import get_expert_store

    expert = await get_expert_store().create_expert(
        name="排期测试员",
        expert_id="captest_sched",
    )
    # 执行留痕直接落 cron 权威面（agent_id=expert_<id>，UI 前缀 job）
    repo = PgJobRepository(
        agent_id=f"expert_{expert.id}",
        jobs_path=tmp_path / "j.json",
    )
    await repo.append_history(
        "expert_task_w1",
        CronExecutionRecord(
            run_at=datetime.now(timezone.utc),
            status="success",
            trigger="scheduled",
            result_summary="巡检完成",
            run_id="run-w1",
            session_id="cron:expert_task_w1",
        ),
    )

    store = get_scheduling_store()
    # list_runs 经 reader 反推：job_id 去前缀→task_id，success→succeeded
    runs = await store.list_runs("w1")
    assert len(runs) == 1
    assert runs[0].status == "succeeded"
    assert runs[0].result_summary == "巡检完成"
    assert runs[0].run_id == "run-w1"
    # runs_in_window（worklog 同源）按 agent 维度窗口读
    window = await store.runs_in_window(
        expert.id,
        datetime.now(timezone.utc) - timedelta(days=1),
    )
    assert len(window) == 1


@pytest.mark.asyncio
async def test_pending_inbox_reads_failed_tasks_from_cron_plane(
    enterprise_env, tmp_path,
):
    """T13d 收口回归：/pending-items 第3段不再直查已 DROP 的
    ``expert_scheduled_tasks``，改经 ``CronLedgerReader.
    list_active_failed_tasks`` 从 cron 双表反推「启用中且最近一次
    执行失败」的专家定时任务。

    播种三任务：①active+最新失败 → 命中；②active+最新成功 →
    不命中；③paused(enabled=False)+最新失败 → 不命中。覆盖 SQL 的
    enabled 过滤、latest-per-job DISTINCT ON、status<>success 过滤与
    expert_ 前缀作用域；末段直调 pending_items() 端点证明不再 500。
    """
    from datetime import datetime, timezone

    from qwenpaw.app.crons.models import (
        CronExecutionRecord,
        CronJobRequest,
        CronJobSpec,
        DispatchSpec,
        DispatchTarget,
        JobRuntimeSpec,
        ScheduleSpec,
    )
    from qwenpaw.app.crons.repo.pg_repo import PgJobRepository
    from qwenpaw.app.experts.cron_ledger import get_cron_ledger_reader
    from qwenpaw.app.experts.store import get_expert_store

    expert = await get_expert_store().create_expert(
        name="收件箱测试员",
        expert_id="captest_pending",
    )
    repo = PgJobRepository(
        agent_id=f"expert_{expert.id}",
        jobs_path=tmp_path / "j.json",
    )

    def _spec(job_id: str, name: str, *, enabled: bool) -> CronJobSpec:
        # 与 UI 链路同形：meta 携带 expert_task_name（读层 name 单一来源）
        return CronJobSpec(
            id=job_id,
            name=name,
            schedule=ScheduleSpec(
                type="cron", cron="0 9 * * *", timezone="Asia/Shanghai",
            ),
            task_type="agent",
            request=CronJobRequest(input="巡检"),
            dispatch=DispatchSpec(
                target=DispatchTarget(user_id="cron", session_id=""),
            ),
            runtime=JobRuntimeSpec(),
            enabled=enabled,
            meta={"expert_task_name": name, "origin_source": "ui"},
        )

    # ① active + 最新失败 → 命中
    await repo.upsert_job(_spec("expert_task_p1", "失败巡检", enabled=True))
    await repo.append_history(
        "expert_task_p1",
        CronExecutionRecord(
            run_at=datetime.now(timezone.utc),
            status="error",
            trigger="scheduled",
            error="boom",
        ),
    )
    # ② active + 最新成功 → 不命中（status<>success 过滤）
    await repo.upsert_job(_spec("expert_task_p2", "正常巡检", enabled=True))
    await repo.append_history(
        "expert_task_p2",
        CronExecutionRecord(
            run_at=datetime.now(timezone.utc),
            status="success",
            trigger="scheduled",
        ),
    )
    # ③ paused + 最新失败 → 不命中（enabled 过滤）
    await repo.upsert_job(_spec("expert_task_p3", "停用巡检", enabled=False))
    await repo.append_history(
        "expert_task_p3",
        CronExecutionRecord(
            run_at=datetime.now(timezone.utc),
            status="error",
            trigger="scheduled",
        ),
    )

    tasks = await get_cron_ledger_reader().list_active_failed_tasks()
    ids = {t.id for t in tasks}
    assert "p1" in ids
    assert "p2" not in ids
    assert "p3" not in ids
    p1 = next(t for t in tasks if t.id == "p1")
    assert p1.expert_id == expert.id
    assert p1.name == "失败巡检"
    assert p1.last_status == "failed"
    assert p1.status == "active"

    # 端点级回归：直调 pending_items（绕鉴权依赖），证明收口后
    # 不再因直查已 DROP 表而 500，且失败任务入收件箱
    from qwenpaw.app.routers.admin.pending import pending_items

    payload = await pending_items()
    task_items = [i for i in payload["items"] if i["kind"] == "task_failed"]
    assert any(i["id"] == "p1" for i in task_items)
    assert payload["counts"].get("task_failed", 0) >= 1


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
async def test_work_record_aggregation(enterprise_env, tmp_path):
    from datetime import datetime, timezone

    from qwenpaw.app.crons.models import CronExecutionRecord
    from qwenpaw.app.crons.repo.pg_repo import PgJobRepository
    from qwenpaw.app.experts.feedback import get_feedback_store
    from qwenpaw.app.experts.store import get_expert_store
    from qwenpaw.app.experts.worklog import get_worklog_service

    expert = await get_expert_store().create_expert(
        name="台账测试员",
        expert_id="captest_worklog",
    )
    # 收口后执行留痕落 cron_job_history（agent_id=expert_<id>）；worklog
    # 经 SchedulingStore→CronLedgerReader 读回同一 cron 平面
    repo = PgJobRepository(
        agent_id=f"expert_{expert.id}",
        jobs_path=tmp_path / "j.json",
    )
    await repo.append_history(
        "expert_task_w1",
        CronExecutionRecord(
            run_at=datetime.now(timezone.utc),
            status="success",
            trigger="scheduled",
            result_summary="巡检完成",
            run_id="run-w1",
            session_id="cron:expert_task_w1",
        ),
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
async def test_sop_expert_topic_broadcast(enterprise_env):
    """员工级 SOP 活动流：写操作向 sop-expert topic 发轻量索引事件。

    面板跟随底座：AI 新建 SOP 时前端尚不知 sop_id，created 事件供
    面板自动开画布；事件不含图数据（全量快照走 sop 级通道）。
    """
    import asyncio

    from qwenpaw.app.enterprise import current_tenant_id
    from qwenpaw.app.events.bus import get_event_bus, sop_expert_topic
    from qwenpaw.app.experts.sops import get_sop_store

    store = get_sop_store()
    subscription = get_event_bus().subscribe(
        sop_expert_topic(current_tenant_id(), "captest_expert_ev"), "",
    )
    try:
        created = await store.create_sop(
            name="事件流程",
            sop_id="captest_sop_ev",
            owner_id="captest_expert_ev",
            nodes=[{"id": "n1", "title": "步骤一"}],
        )
        assert created.owner_id == "captest_expert_ev"
        # created：轻量索引事件（开画布信号），无图数据
        ev1 = await asyncio.wait_for(subscription.__anext__(), timeout=2.0)
        assert ev1.data["action"] == "created"
        assert ev1.data["sop_id"] == "captest_sop_ev"
        assert ev1.data["owner_id"] == "captest_expert_ev"
        assert "nodes" not in ev1.data

        await store.update_sop("captest_sop_ev", goal="新目标")
        ev2 = await asyncio.wait_for(subscription.__anext__(), timeout=2.0)
        assert ev2.data["action"] == "updated"
        assert ev2.data["sop_id"] == "captest_sop_ev"

        # 无主 SOP（owner_id 为空）不产生员工级事件
        await store.create_sop(
            name="无主流", sop_id="captest_sop_ev_free", owner_id=None,
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(subscription.__anext__(), timeout=0.3)
    finally:
        subscription.close()


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


@pytest.mark.asyncio
async def test_sop_owner_attribution_and_list_visibility(enterprise_env):
    """T10：SOP 归属快照贯穿行生命周期 + 列表可见性分层（draft 仅 owner）。

    1) create 显式归属落库；promote 复制到线上行；存量 production-only
       行 ensure_draft_row fork 保留归属；owner 无治理/无部门时快照为空
       （best-effort 不阻断）；
    2) 无 owner 过滤的跨员工视图仅 production 行（纯草稿 SOP 不外泄）；
       传 owner_id 时双环境合并、同 id 草稿优先。
    """
    from qwenpaw.app.experts.models import (
        SOP_ENVIRONMENT_DRAFT,
        SOP_ENVIRONMENT_PRODUCTION,
    )
    from qwenpaw.app.experts.sops import get_sop_store
    from qwenpaw.app.routers.admin import expert_capability as cap_mod

    store = get_sop_store()
    draft = await store.create_sop(
        name="归属流程",
        sop_id="captest_sop_attr",
        owner_id="captest_expert_attr",
        environment=SOP_ENVIRONMENT_DRAFT,
        department_id="dept_captest/sub",
    )
    assert draft.department_id == "dept_captest/sub"
    assert draft.project_id is None

    # promote：归属快照随草稿内容复制到线上行
    promoted = await store.promote_sop(draft.id, published_by="tester")
    assert promoted.department_id == "dept_captest/sub"

    # fork：存量 production-only 行首次进画布 → 草稿副本保留归属
    prod_only = await store.create_sop(
        name="存量流程",
        sop_id="captest_sop_attr_fork",
        owner_id="captest_expert_attr",
        environment=SOP_ENVIRONMENT_PRODUCTION,
        department_id="dept_captest",
    )
    forked = await store.ensure_draft_row(prod_only.id)
    assert forked is not None
    assert forked.environment == SOP_ENVIRONMENT_DRAFT
    assert forked.department_id == "dept_captest"

    # best-effort 兜底：owner 无治理行/无部门 → 快照为空，不阻断写入
    bare = await store.create_sop(
        name="无归属流程",
        sop_id="captest_sop_attr_bare",
        owner_id="captest_expert_nobody",
        environment=SOP_ENVIRONMENT_DRAFT,
    )
    assert bare.department_id is None

    # 纯草稿 SOP（从未发布）：跨员工视图中不可见
    draft_only = await store.create_sop(
        name="纯草稿",
        sop_id="captest_sop_attr_draft_only",
        owner_id="captest_expert_attr",
        environment=SOP_ENVIRONMENT_DRAFT,
    )
    assert draft_only.id == "captest_sop_attr_draft_only"

    # 跨员工视图（无 owner 过滤）：仅 production 行，草稿绝不外泄
    unscoped = await cap_mod.list_sops(full=True)
    unscoped_by_id = {r.id: r for r in unscoped}
    assert all(r.environment == SOP_ENVIRONMENT_PRODUCTION for r in unscoped)
    assert unscoped_by_id["captest_sop_attr"].environment == (
        SOP_ENVIRONMENT_PRODUCTION
    )
    assert "captest_sop_attr_draft_only" not in unscoped_by_id

    # 员工工作集（owner 过滤）：双环境合并，同 id 草稿优先
    scoped = {
        r.id: r
        for r in await cap_mod.list_sops(
            owner_id="captest_expert_attr",
            full=True,
        )
    }
    assert scoped["captest_sop_attr"].environment == SOP_ENVIRONMENT_DRAFT
    assert scoped["captest_sop_attr_fork"].environment == (
        SOP_ENVIRONMENT_DRAFT
    )
    assert scoped["captest_sop_attr_draft_only"].environment == (
        SOP_ENVIRONMENT_DRAFT
    )


# ---------------------------------------------------------------------------
# T11 个人档案草稿（agent_documents owner 平面）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_doc_draft_plane_roundtrip(enterprise_env):
    """个人草稿与共享行隔离：多用户共存、共享读不泄露、待应用判定正确。"""
    from qwenpaw.app.agent_docs.store import (
        AgentDocsStore,
        annotate_draft_status,
    )

    store = AgentDocsStore()
    agent_id = "captest_doc_plane"

    # 共享行（admin/manager 写）
    assert await store.upsert_document(agent_id, "profile", "# shared") is True
    # alice 写四文档落本人 draft 行（不触共享行）
    assert (
        await store.upsert_document(
            agent_id,
            "profile",
            "# alice draft",
            owner_user_id="alice",
        )
        is True
    )
    # bob 同文档草稿：coalesce 表达式唯一索引允许共存（旧四元约束会冲突）
    assert (
        await store.upsert_document(
            agent_id,
            "profile",
            "# bob draft",
            owner_user_id="bob",
        )
        is True
    )

    # 共享读：owner 过滤，绝不读到他人草稿
    shared = await store.get_document(agent_id, "profile")
    assert shared is not None
    assert shared["content"] == "# shared"
    # 草稿读：每人只见自己的
    alice = await store.get_document(
        agent_id,
        "profile",
        owner_user_id="alice",
    )
    assert alice is not None and alice["content"] == "# alice draft"
    bob = await store.get_document(agent_id, "profile", owner_user_id="bob")
    assert bob is not None and bob["content"] == "# bob draft"
    assert (
        await store.get_document(
            agent_id,
            "profile",
            owner_user_id="carol",
        )
        is None
    )

    # 待应用判定：与共享行分叉 → unapplied
    drafts = await store.list_personal_drafts(agent_id)
    assert {row["owner_user_id"] for row in drafts} == {"alice", "bob"}
    single = await store.list_personal_drafts(
        agent_id,
        owner_user_id="alice",
    )
    assert len(single) == 1 and single[0]["owner_user_id"] == "alice"
    shared_docs = await store.list_documents(agent_id)
    annotated = annotate_draft_status(drafts, shared_docs)
    assert all(row["unapplied"] is True for row in annotated)

    # 个人草稿不写发布链 revision（快照链仅属于共享闸门）：
    # 任何环境都不得出现本 agent 的 draft 修订
    from qwenpaw.db import engine as engine_mod

    engine = engine_mod.create_pg_engine(DSN)
    async with engine.connect() as conn:
        draft_revisions = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM agent_document_revisions "
                    "WHERE agent_id = 'captest_doc_plane' "
                    "AND environment = 'draft'",
                ),
            )
        ).scalar()
    assert draft_revisions == 0


@pytest.mark.asyncio
async def test_personal_doc_draft_apply_promotes_and_clears_badge(
    enterprise_env,
):
    """apply = promote 共享行 + revision；应用后徽标消除、草稿行保留。"""
    from qwenpaw.app.agent_docs.store import (
        AgentDocsStore,
        annotate_draft_status,
    )

    store = AgentDocsStore()
    agent_id = "captest_doc_apply"

    # 共享基线 + alice 草稿
    await store.upsert_document(agent_id, "soul", "# v1 shared")
    await store.upsert_document(
        agent_id,
        "soul",
        "# alice proposal",
        owner_user_id="alice",
    )

    # apply = 草稿内容 promote 到共享行（version++ + revision 快照）
    version = await store.promote(
        agent_id,
        "soul",
        "# alice proposal",
        updated_by="apply:alice:admin",
    )
    assert version == 2
    revision = await store.get_revision(agent_id, "soul", 2)
    assert revision is not None
    assert revision["content"] == "# alice proposal"

    # 共享行已更新；徽标消除（内容与共享一致，非「草稿行存在」信号）
    shared = await store.get_document(agent_id, "soul")
    assert shared is not None and shared["content"] == "# alice proposal"
    drafts = await store.list_personal_drafts(agent_id)
    annotated = annotate_draft_status(drafts, [shared])
    assert annotated[0]["owner_user_id"] == "alice"
    assert annotated[0]["unapplied"] is False


@pytest.mark.asyncio
async def test_agent_documents_owner_column_and_unique_index(enterprise_env):
    """alembic 0038 落地：owner 列 + coalesce 表达式唯一索引存在且生效。"""
    from qwenpaw.db import engine as engine_mod

    engine = engine_mod.create_pg_engine(DSN)
    async with engine.connect() as conn:
        column_names = {
            row[0]
            for row in (
                await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'agent_documents'",
                    ),
                )
            ).fetchall()
        }
        assert "owner_user_id" in column_names
        indexdef = (
            await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'uq_agent_documents_doc_owner'",
                ),
            )
        ).scalar()
        assert indexdef is not None
        # 表达式唯一索引：owner NULL 归一为空串（多用户草稿互不冲突）
        assert "coalesce" in indexdef.lower()
        assert "unique" in indexdef.lower()
