# Workforce 编排引擎缺陷修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 2026-08-18 workforce 架构审计发现的 2 个 P0 + 3 个 P1/P2 缺陷（崩溃恢复跳节点、熔断放行空转、双通道校验不一致、移交竞态、final 依赖漏 integration）。

**Architecture:** 全部为既有状态机/路由的边角修正，不新增模块。涉及 `src/qwenpaw/app/workforce/`（engine/verifier/planner/contracts/run_store）与 `src/qwenpaw/app/routers/xian/workforce.py`，测试集中在 `tests/integration/test_workforce_runs.py`。

**Tech Stack:** Python 3 / FastAPI / asyncio / SQLAlchemy asyncpg / pytest

**Spec:** `docs/design/2026-08-18-workforce-harness-architecture.md`（架构意图基线）；缺陷证据见本文「Findings」表（审计于 2026-08-18 晚，分支 feature/xianwork_enterprise_20260814，基线 ed13ceaf）。

## Global Constraints

- 禁止在 main 分支创建任何 SQL 变更文件；本批修复**零 DDL**，不涉及 db/ 目录。
- 所有 SQL 参数绑定，禁止拼接（列名仅可来自代码内白名单常量）。
- 新代码遵循仓库 CLAUDE.md（注释规范、大括号/空行等对 Python 按 pydantic/asyncio 既有风格）。
- 测试环境：`QWENPAW_TEST_PG_DSN=postgresql+asyncpg://qwenpaw:qwenpaw_test@127.0.0.1:5432/qwenpaw`（本机已迁移到 0011）。

## Findings（审计结论，修复对象）

| # | 级别 | 缺陷 | 证据 |
| --- | --- | --- | --- |
| F1 | P0 | 崩溃恢复跳过中间态节点：`mark_interrupted_runs` 只改 run 状态；engine 主循环只认 pending/done，卡在 delegated/verifying/repairing 的节点被永久跳过，run 可带缺失产出收敛 done | engine.py:192-199, run_store.py:464-487 |
| F2 | P0 | 熔断放行空转：verifier 预检 `repair_count >= max` 使第 max+1 次委派的结果不被验收直接熔断；人工 retry 不重置计数 → 每次放行重试白烧一轮委派 token | verifier.py:159-163, engine.py:450-459, xian/workforce.py:400-411 |
| F3 | P1 | xian `create_run` 缺团队 published 校验（admin 通道有，双通道不一致） | xian/workforce.py:157-161 vs admin/workforce.py:138-139 |
| F4 | P1 | handover 缺目标专家 published 校验（docstring 声称有）；RUNNING 态移交与引擎旧委派并发，旧结果会覆写移交 | xian/workforce.py:447-477, 492-493 |
| F5 | P2 | `_ensure_final_node` 只把 task 节点计入 final 依赖，漏 integration → final 可先于 integration 执行 | planner.py:148-149 |
| F6 | P2 | 意图分类未接线（无任何调用方）——需求完整性缺口，本计划**不修**，另行决策接线或文档降级为预留 | intent.py 全文无 consumer |
| F7 | P3 | 杂项：死代码 `is_result_actionable`、engine.py:411 重复写 VERIFYING、run_stats active 口径不含 interrupted、ResultContract 文档"重试"漂移、DagNode 无 quality_criteria 字段（验收标准恒为通用文案） | 各处 |

---

### Task 1: F2 — verifier 熔断边界对齐（`>=` → `>`）

**Files:**
- Modify: `src/qwenpaw/app/workforce/verifier.py:159`
- Test: `tests/integration/test_workforce_runs.py`

**Interfaces:**
- Consumes: `verify(verifier_expert_id, contract, result, policy, repair_count, previous_repair)` 签名不变。
- Produces: 语义变更——`repair_count` 为"已完成返工轮数"，等于 max 时**仍验收**本轮结果，只有 FAIL 后 engine 侧计数超 max 才熔断（engine.py:455 的 `>` 判断已正确）。

- [ ] **Step 1: 写失败测试（engine 级，验证 max 边界的结果必被验收）**

在 `tests/integration/test_workforce_runs.py` 追加（沿用文件内既有 `_seed_team` / `_patch_llm_seams` / `_one_node_plan` 风格；若无线性单节点 plan 工厂则仿照 `_two_node_plan` 构造 lead 单节点）：

```python
async def test_max_repair_boundary_result_is_verified(enterprise_env, run_store, monkeypatch):
    """max_repair_per_node=1 时：第 2 次委派（首轮 FAIL 后）的结果必须被验收，
    PASS 则节点 done——不得在验收前直接熔断丢弃结果。"""
    from qwenpaw.app.workforce import engine as engine_mod
    from qwenpaw.app.workforce.contracts import RunPolicy

    team, lead, member = await _seed_team()
    verdicts = iter(["FAIL", "PASS"])
    _patch_llm_seams(
        monkeypatch, _two_node_plan(lead.id, member.id), verdicts=verdicts
    )
    run = await run_store.create_run(
        team_id=team.id,
        goal="G",
        initiator_id="alice",
        policy=RunPolicy(max_repair_per_node=1).model_dump(),
    )
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    assert final["status"] == "done"
```

（若 `_patch_llm_seams` 不支持 verdicts 序列注入，按其现有打桩方式等价实现：第一次 verify 返回 FAIL+RepairContract，第二次返回 PASS。）

- [ ] **Step 2: 跑测试确认失败**

Run: `QWENPAW_TEST_PG_DSN=... .venv/Scripts/python.exe -m pytest tests/integration/test_workforce_runs.py::test_max_repair_boundary_result_is_verified -q`
Expected: FAIL（run 状态为 escalated，因为第 2 次结果未被验收）

- [ ] **Step 3: 最小修复**

`verifier.py:159` 一处改动：

```python
    # 熔断双保险：已超返工上限不再消耗 LLM（引擎层同样拦截）。
    # 边界对齐 engine：==max 时本轮结果仍须验收（FAIL 后由引擎计数超限熔断）
    if repair_count > policy.max_repair_per_node:
```

同时把 reason 文案改为 `f"返工次数超上限（{repair_count}/{policy.max_repair_per_node}），升级人工"`。

- [ ] **Step 4: 跑全量 workforce 测试**

Run: `QWENPAW_TEST_PG_DSN=... .venv/Scripts/python.exe -m pytest tests/integration/test_workforce_runs.py -q`
Expected: 全部 PASS（既有 escalated 用例语义不受影响——它们依赖 engine 层 `>` 熔断）

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/app/workforce/verifier.py tests/integration/test_workforce_runs.py
git commit -m "fix(workforce): verifier 熔断边界对齐引擎（>= 改 >），末轮返工结果必被验收"
```

---

### Task 2: F1 — 启动恢复重置中间态节点

**Files:**
- Modify: `src/qwenpaw/app/workforce/contracts.py`（新增节点活跃态常量）
- Modify: `src/qwenpaw/app/workforce/run_store.py:464-487`（`mark_interrupted_runs` 同事务重置节点）
- Test: `tests/integration/test_workforce_runs.py`

**Interfaces:**
- Produces: `NODE_ACTIVE_STATUSES: tuple[str, ...] = ("delegated", "running", "verifying", "repairing")`（contracts.py，供 run_store 与后续复用）。
- `mark_interrupted_runs()` 返回值语义不变（受影响 run 数）。

- [ ] **Step 1: 写失败测试**

```python
async def test_interrupted_resume_recovers_midflight_node(enterprise_env, run_store, monkeypatch):
    """崩溃时节点卡在 delegated（无 result）：续跑后必须被重新执行并 done，
    不得静默跳过导致 run 带缺失产出收敛。"""
    from qwenpaw.app.workforce import engine as engine_mod

    team, lead, member = await _seed_team()
    _patch_llm_seams(monkeypatch, _two_node_plan(lead.id, member.id))
    run = await run_store.create_run(team_id=team.id, goal="G", initiator_id="alice")
    await run_store.save_plan(run["id"], _two_node_plan(lead.id, member.id))
    # 模拟崩溃现场：task-1 委派中断（delegated、无结果），final 未开始
    await run_store.update_node(
        run["id"], "task-1", status="delegated",
        contract={"task_id": "task-1", "objective": "产出方案"},
    )
    await run_store.set_run_status(run["id"], "running")
    await run_store.mark_interrupted_runs()
    # 续跑
    await engine_mod.run_team_run(run["id"])
    final = await run_store.get_run(run["id"])
    nodes = {n["node_key"]: n for n in await run_store.list_nodes(run["id"])}
    assert final["status"] == "done"
    assert nodes["task-1"]["status"] == "done"
```

- [ ] **Step 2: 跑测试确认失败**

Expected: FAIL（task-1 停留 delegated，run 直接 done，final 汇总缺上游）

- [ ] **Step 3: 实现**

contracts.py 常量区追加：

```python
#: 节点活跃态集合（启动恢复时需重置回 pending 的中间状态）
NODE_ACTIVE_STATUSES = (
    NODE_STATUS_DELEGATED,
    NODE_STATUS_RUNNING,
    NODE_STATUS_VERIFYING,
    NODE_STATUS_REPAIRING,
)
```

run_store.mark_interrupted_runs 内，在现有 UPDATE 后、同一 `engine.begin()` 事务里追加（参数绑定，列名/状态值来自常量）：

```python
                    # 中间态节点回退 pending（单 worker 拓扑：启动时刻无并发
                    # 引擎任务，重置安全；contract/session 保留供委派复用）
                    await conn.execute(
                        text(
                            "UPDATE team_run_nodes n SET status = 'pending' "
                            "FROM team_runs r WHERE r.tenant_id = n.tenant_id "
                            "AND r.id = n.run_id AND r.tenant_id = :tid "
                            "AND r.status = ANY(:active) "
                            "AND n.status = ANY(:node_active)"
                        ),
                        {
                            "tid": current_tenant_id(),
                            "active": list(RUN_ACTIVE_STATUSES),
                            "node_active": list(NODE_ACTIVE_STATUSES),
                        },
                    )
```

注意：节点重置必须发生在 run 状态 UPDATE **之后**同事务执行（WHERE 条件依赖 r.status 仍为活跃态）。

- [ ] **Step 4: 跑全量测试**

Run: `QWENPAW_TEST_PG_DSN=... .venv/Scripts/python.exe -m pytest tests/integration/test_workforce_runs.py -q`
Expected: 全部 PASS（既有 `test_mark_interrupted_runs_scan` 不受影响）

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/app/workforce/contracts.py src/qwenpaw/app/workforce/run_store.py tests/integration/test_workforce_runs.py
git commit -m "fix(workforce): 启动恢复重置中间态节点，堵住续跑静默跳过与产出缺失"
```

---

### Task 3: F3 — xian create_run 补 published 校验

**Files:**
- Modify: `src/qwenpaw/app/routers/xian/workforce.py:157-161`
- Test: `tests/integration/test_workforce_runs.py`（访问控制区，参照既有 404 断言风格）

- [ ] **Step 1: 写失败测试**（建 draft 团队 → POST /api/xian/workforce/runs → 期望 400；用既有 FastAPI TestClient 挂路由的测试基建）

- [ ] **Step 2: 确认失败**（当前会 201 创建成功）

- [ ] **Step 3: 实现**（与 admin/workforce.py:138-139 同款）：

```python
    if team.status != "published":
        raise HTTPException(status_code=400, detail="Team is not published")
```

- [ ] **Step 4: 全量测试 PASS**

- [ ] **Step 5: Commit** `fix(xian): workforce 创建 run 补团队 published 校验（对齐 admin 通道）`

---

### Task 4: F4 — handover 补 published 校验 + 执行中节点防竞态

**Files:**
- Modify: `src/qwenpaw/app/routers/xian/workforce.py:447-456`

- [ ] **Step 1: 写失败测试**：a) 目标专家 draft → 400；b) run=running 且节点 delegated → 移交 → 409（节点执行中）。
- [ ] **Step 2: 确认失败**（当前分别 200/竞态放行）
- [ ] **Step 3: 实现**：

```python
    if expert.status != "published":
        raise HTTPException(status_code=400, detail="Target expert is not published")
```

节点状态检查（在 done 检查旁追加，`NODE_ACTIVE_STATUSES` 从 contracts 导入）：

```python
    if node["status"] in NODE_ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="节点执行中，请等待本轮完成或先取消任务")
```

- [ ] **Step 4: 全量测试 PASS**
- [ ] **Step 5: Commit** `fix(xian): workforce 移交补已发布校验并防执行中节点竞态`

---

### Task 5: F5 — final 依赖纳入 integration 节点

**Files:**
- Modify: `src/qwenpaw/app/workforce/planner.py:148-149`

- [ ] **Step 1: 写失败测试**：构造仅含 integration 节点（无 task）的 plan 走 `_ensure_final_node`，断言 final.deps 包含该 integration key。
- [ ] **Step 2: 确认失败**（当前 deps 为空）
- [ ] **Step 3: 实现**：

```python
    task_keys = [
        n.node_key
        for n in plan.nodes
        if n.node_type in (NODE_TYPE_TASK, NODE_TYPE_INTEGRATION)
    ]
```

- [ ] **Step 4: 全量测试 PASS**
- [ ] **Step 5: Commit** `fix(workforce): 自动补齐的 final 节点依赖纳入 integration 节点`

---

### Task 6（可选清理）: F7 杂项

删除 `bundle.py::is_result_actionable`（死代码）；删除 `engine.py:411` 重复 VERIFYING 写；`run_stats` 的 active FILTER 追加 `'interrupted'`（或单独返回 interrupted 计数）；修正 `set_run_status` 误导注释。一次性提交 `chore(workforce): 审计杂项清理`。

---

## 显性缺口（本计划不覆盖，禁止静默扩大）

- F6 意图分类接线（双态入口的"建议升级"半截）——需产品决策：接线聊天入口 vs 文档降级为预留。
- 续跑后时间预算重新起算（engine docstring 已自认迭代项）。
- DagNode 缺 quality_criteria/constraints 字段，节点级验收标准不可配置（架构文档示例与实现有落差）——涉及 console 编辑器联动，独立需求处理。
- verify/规划每轮新开 session 导致 chats 行增长（运维观测项）。
- 多实例水平扩展（RedisEventBus + SKIP LOCKED）——预留已到位。
