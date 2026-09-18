# cron 双台账收口专项设计（T13）

> 计划来源：《存储PG化与作用域治理》§3.2（T13「cron 双台账收口」）
> 状态：**已评审（2026-09-18，D1–D7 均采纳推荐项）；Phase 1（T13a）与 Phase 2 读切换（T13b）已实施**
> 分支：`feature/agent_run_logs_20260908`
> 作者：qingfeng（AI 协助）　日期：2026-09-18

---

## 0. 一句话结论

计划原文「读端点改查 cron 双表 → DROP `expert_scheduled_tasks`/`expert_task_runs`」在**当前数据模型下不能按字面直接执行**：expert 两表是携带 `cron_jobs`/`cron_job_history` 所缺字段的**领域读模型**，且 cron 双表在 `json` 存储后端下根本不落库。本设计给出**分阶段 expand→migrate→contract** 的收口方案，并列出 7 个必须拍板的决策点（§7）。

---

## 1. 现状精查（事实清单，均有代码证据）

### 1.1 同一权威、两套台账

| 项 | expert 台账 | cron 双表 |
|---|---|---|
| 表 | `expert_scheduled_tasks` / `expert_task_runs` | `cron_jobs` / `cron_job_history` |
| 定位 | UI 管理/统计**领域读模型**（`scheduling.py` 头注） | CronManager 的 **PG 权威投影**（`models_crons.py` 头注） |
| 权威 | 同一 CronManager（APScheduler）——expert 台账是它的第二投影 | 同左 |
| 归属键 | `expert_id`（裸 id，如 `abc123`） | `agent_id = expert_{expert_id}`（`expert_agent_id()`，models.py:72-74；`build_job_repository(agent_id=ws.agent_id)` workspace.py:534-536） |
| job id | UI 链路：`expert_task_{task_id}`（`EXPERT_TASK_JOB_PREFIX`）；chat/api 链路：裸 job_id | 同左 |
| 写入方 | `SchedulingStore`（原生 text() SQL，`require_enterprise_engine`，**无条件 PG**） | `PgJobRepository`（经 `build_job_repository` 按 `QWENPAW_STORAGE_BACKEND` 选择，**json 时走 `JsonJobRepository`，不落 PG**） |
| 读消费者 | admin 定时任务 API（6+ 端点）、worklog、详情页计数 | console CronJobs 页、执行历史弹层 |

### 1.2 字段级分歧（DROP 前的硬缺口）

`expert_scheduled_tasks` 相对 `cron_jobs`（spec JSONB + enabled + 归属三列）独有的列：

| expert 列 | cron_jobs 能否还原 | 依据 |
|---|---|---|
| `description` | ❌ CronJobSpec 无此字段 | `_build_spec` 只映射 name/prompt/schedule/dispatch/runtime |
| `name`（原始名） | ⚠️ 仅存 `"[数字员工] {name}"` 前缀版（scheduling.py:509） | 还原需剥前缀，语义脆弱 |
| `status`：`active/paused/completed/archived` | ⚠️ 仅 `enabled` bool；**completed/archived 无处安放** | `TASK_STATUS_*`（models.py:320+）；archived 行代表"job 已删但台账留痕" |
| `source`（ui/chat/api） | ⚠️ 仅 chat/api 在 `spec.meta.origin_source`；UI 链路**未写** | `_upsert_task_row`（scheduling.py:838）；`_build_spec` 的 meta 只有 `expert_task_id` |
| `origin`（dispatch/runtime 投影） | ✅ 可从 spec.dispatch/runtime 反推 | `_origin_from_spec`（scheduling.py:804） |
| `last_run_at` / `last_status` | ✅ 可由最新一条 history 反推 | cron_job_history ORDER BY seq DESC |
| `run_count` | ❌ 无处持久化；COUNT(history) **被 50 条修剪截断** | `append_history` limit=50 修剪（pg_repo.py:436-448） |
| `next_run_at` | ⚠️ 非持久字段，是 APScheduler 运行态（`get_state.next_run_at`） | `_refresh_projection`（scheduling.py:588） |
| `owner_id` | ✅ ≈ `spec.dispatch.target.user_id`（"cron" 占位需归一） | `_upsert_task_row`（scheduling.py:839-842） |

`expert_task_runs` 相对 `cron_job_history`（`run_at/status/error/trigger/seq`）独有的列：

| expert_task_runs 列 | cron_job_history 现状 | 依据 |
|---|---|---|
| `result_summary` | ❌ 表无此列，`CronExecutionRecord` 也无此字段 | worklog 时间线取它做标题（worklog.py:95-99,168-170） |
| `run_id` | ⚠️ **模型已有**（CronExecutionRecord.run_id/session_id，crons/models.py:276-279），manager 构造时**已赋值**（manager.py:882-883），但 **pg_repo 的 INSERT/SELECT 丢列**（pg_repo.py:417-424、362-364），表也无列；json repo 经 model_dump 倒是保留了 | 执行详情跳 agent_runs span 树的关联键 |
| `session_id` | 同 `run_id` | `cron:{job_id}` 会话回放 |
| `scheduled_for`（幂等锚） | ⚠️ 语义不同：history 以 `(tenant, agent, job_id, seq)` + 进程内锁防重 | scheduling.py:342/360 用 `(tenant, task_id, scheduled_for)` 幂等 |
| `expert_id` | ⚠️ 需从 `agent_id` 反剥 `expert_` 前缀 | `expert_agent_id` 逆映射 |
| 状态枚举 | 不同命名空间：ledger `running/succeeded/failed` vs history `success/error/running/skipped/cancelled`（映射逻辑见 `record_execution` scheduling.py:664-666） | |
| **在途可见性** | ❌ ledger `begin_run` 先写 running 行；cron history **只在完成时** append（manager.py:622、885 两处），在途不可见 | worklog 的"窗口内任务数"含在途，语义会漂移 |

### 1.3 读者与写者全量清单（改造成本盘点）

**读（必须改造或等价替代）**
- `routers/admin/expert_capability.py`：`list_scheduled_tasks`(:540)、`create`(:558)、`update`(:586)、`delete`(:616)、`pause/resume`(:636/:649)、`run_now`(:662)——全走 `get_scheduling_store()`
- 同文件 :197-201：详情统计 `SELECT count(*) FROM expert_scheduled_tasks ... status IN ('active','paused')`
- `experts/worklog.py`：:92-103 读 `expert_task_runs`（窗口内按 expert_id），:160-174 组装时间线
- 详情页四计数 `count_active_by_expert`（scheduling.py:301）

**写（观察者/服务双写）**
- `SchedulingStore.create_task / upsert_task_from_spec / update_task / delete_task(归档) / begin_run / finish_run`（scheduling.py:100-447）
- 注册观察者 `_make_registration_observer`（:861-889）：chat/api 创建/暂停/恢复/删除 → 台账 upsert/归档
- 执行观察者 `record_execution`（:632-699）：写 expert_task_runs + 回写 last_*/run_count/completed
- 启动回填 `_backfill_tasks_from_authority`（:903-924）
- `attach_expert_scheduling`（:927-940）：workspace 装配点接线（**注意：只有 admin 写操作才挂 SchedulingService factory；对话链路靠这个装配点**）

**权威侧（无需改，作为收口后的写路径）**
- `CronManager` → `_repo.upsert_job/append_history`；spec 落 `cron_jobs`，执行落 `cron_job_history`

### 1.4 存储后端缺口（关键前置）

`expert` 两表**无条件写 PG**（企业版引擎）；而 cron 双表仅在 `QWENPAW_STORAGE_BACKEND ∈ {dual,pg}` 时启用，`json`（默认）下走 `JsonJobRepository`，**`cron_jobs`/`cron_job_history` 完全空**。
→ 若按字面 DROP expert 表并把读端点切到 cron 双表：**json 后端部署下专家定时任务列表将全空**。收口的前提是 cron 平面必须 PG 权威（部署面收敛，见决策 D1）。

---

## 2. 目标（收口后的终态）

1. **单一权威存储**：专家定时任务的规格与执行留痕只落 `cron_jobs` / `cron_job_history`（含 §3 补列），不再有第二套表。
2. **API 不变**：`/admin/experts/{id}/scheduled-tasks*` 与 `work-record` 的响应结构与字段语义保持兼容（前端零改或仅微调）。
3. **写入路径唯一**：规格写 = CronManager 权威 + `spec.meta` 承载专家域注解；执行写 = `CronManager → append_history`（补 result_summary/run_id/session_id）。
4. **旧表安全退役**：`DROP TABLE IF EXISTS` 幂等 DDL + 变更注释，快照同步，可回滚（§6）。

---

## 3. 方案总览（expand → migrate → contract）

```
Phase 1 EXPAND（двух写共存，读仍走 expert 台账）
  ├─ DDL：cron_job_history 补列 result_summary/run_id/session_id/scheduled_for
  ├─ 模型：CronExecutionRecord 补 result_summary/scheduled_for
  ├─ 写路径：manager 填充 result_summary；pg_repo INSERT/SELECT 补列
  ├─ spec.meta 注解：SchedulingService._build_spec 写 meta.expert_task_name/description/origin_source="ui"
  └─ expert 台账照常写（安全垫）
Phase 2 MIGRATE（对账 + 读切换）
  ├─ 一次性幂等回填：expert_scheduled_tasks→cron_jobs.meta 注解；expert_task_runs→cron_job_history 补列
  ├─ 新增 CronLedgerReader（读 cron 双表，反推 ScheduledTaskRecord/TaskRunRecord 原形）
  ├─ SchedulingStore 读方法委托给 CronLedgerReader（API 形状零变）
  ├─ 对账脚本：逐任务/逐 run 双源比对，差异 = 0 才进入 Phase 3
  └─ 观察者的 expert_task_runs 写降级为"开关可回退"（保留一周观察窗）
Phase 3 CONTRACT
  ├─ 观察者/服务停写 expert 两表（删写路径）
  ├─ alembic 0040：DROP TABLE IF EXISTS expert_task_runs / expert_scheduled_tasks
  ├─ changelog 20260918/03 + test.sql/prod.sql 快照同步
  └─ 清理 scheduling.py 写 SQL；模块保留记录模型与观察者（执行检查闭环不动）
```

### 3.1 字段映射表（反推规则，CronLedgerReader 实现依据）

`cron_jobs → ScheduledTaskRecord`（查询条件 `tenant_id=:tid AND agent_id=expert_{expert_id}`，UI 链路 `job_id LIKE 'expert_task_%'`）：

| ScheduledTaskRecord | 来源 | 反推规则 |
|---|---|---|
| `id` | `job_id` | 去 `expert_task_` 前缀；无前缀则原样（chat/api 链路 id=job_id） |
| `expert_id` | 入参 | 由 API 路径的 expert_id 注入 |
| `name` | `spec.name` | 剥 `"[数字员工] "` 前缀；新写入同时落 `meta.expert_task_name`（权威），读取优先 meta |
| `description` | `spec.meta.expert_description` | 新写入必落；旧数据回填；缺省 "" |
| `task_prompt` | `spec.request.input` | 直接取 |
| `schedule_type` / `schedule_json` | `spec.schedule` | 复用 `_schedule_json_from_spec`（scheduling.py:779-801） |
| `timezone` | `spec.schedule.timezone` | 直接取 |
| `status` | `enabled` + 行存在性 + `schedule_type=once` 且已成功 | `enabled=true→active`；`false→paused`；once 成功（新增 `meta.expert_completed_at` 或依据最新 history success）→ `completed`；job 行已删 → 不再列出（archived 语义变更，见 D2） |
| `cron_job_id` | `job_id` | 直接取 |
| `next_run_at` | APScheduler `get_state` | 读时由调用方（admin router 已能解析 cron_manager）注入；reader 内部为 None |
| `last_run_at` / `last_status` | 最新 history 行 | `run_at`；状态映射 `success→succeeded, error→failed, 其他原样` |
| `run_count` | COUNT(history) | **语义降级**：最多到 50（修剪窗）；若需精确 → 决策 D3（建议：在 cron_jobs 加 `run_count` 冗余列，append_history 时 +1） |
| `source` | `spec.meta.origin_source` | 缺省 "ui"（UI 链路新写入补 "ui"；chat/api 已有） |
| `origin` | `spec.dispatch`/`runtime` | 复用 `_origin_from_spec` |
| `owner_id` | `spec.dispatch.target.user_id` | `"cron"`/空 → None |
| `created_at` / `updated_at` | cron_jobs 行时间列 | 直接取 |

`cron_job_history → TaskRunRecord`（查询条件 `agent_id=expert_{expert_id}` + `job_id`）：

| TaskRunRecord | 来源 | 反推规则 |
|---|---|---|
| `id` | `"{job_id}:{seq}"` 合成 | 或新增列（决定 D6）；仅要求 API 内唯一且稳定 |
| `task_id` | `job_id` 去前缀 | 同 task 映射 |
| `expert_id` | 入参 | 注入 |
| `scheduled_for` | **新增列** | Phase 1 补；`trigger=scheduled` 时 = run_at |
| `status` | history.status | `success→succeeded, error→failed, skipped/cancelled/running→原样` |
| `result_summary` | **新增列** | Phase 1 补 |
| `error` | history.error | 直接取 |
| `run_id` / `session_id` | **新增列** | Phase 1 补（manager 已赋值，只需落库/读回） |
| `started_at` | history.run_at | history 无 started/finished 之分——`started_at=finished_at=run_at`（语义降级，见 D5） |
| `finished_at` | 同 `run_at` | 同上 |

---

## 4. 改造清单（文件级）

### 4.1 存储层（Phase 1）

| 文件 | 改动 |
|---|---|
| `db/alembic/versions/0040_cron_history_expert_columns.py`（新） | `cron_job_history` 幂等加列：`result_summary TEXT NOT NULL DEFAULT ''`、`run_id VARCHAR(64) NOT NULL DEFAULT ''`、`session_id TEXT NOT NULL DEFAULT ''`、`scheduled_for TIMESTAMPTZ NULL`；部分唯一索引 `(tenant_id, agent_id, job_id, scheduled_for) WHERE scheduled_for IS NOT NULL`（对齐幂等锚，决定 D6） |
| `db/feature/agent_run_logs_20260908/changelog/20260918/03_cron_ledger_convergence.sql`（新） | psql twin（同 DDL，幂等）+ `[等价 alembic] 0040` 头注 |
| `db/.../test.sql`、`prod.sql` | 二进制追加同步（+ 后续 04_drop 也须同步） |
| `db/models_crons.py` | `CronJobHistoryRow` 补 4 列（含默认值） |
| `app/crons/models.py` | `CronExecutionRecord` 补 `result_summary: Optional[str] = None`、`scheduled_for: Optional[datetime] = None` |
| `app/crons/repo/pg_repo.py` | `append_history` INSERT/`get_history` SELECT 补 4 列；`scheduled_for` 幂等门（可选 ON CONFLICT DO NOTHING，决定 D6） |
| `app/crons/repo/json_repo.py` | 零改（model_dump 自动带新字段） |
| `app/crons/manager.py` | :616、:879 两处 `CronExecutionRecord(...)` 构造补 `result_summary=execution_result.get("final_text")[:500]`、`scheduled_for=...`（与 scheduling.py:667 的截断口径一致） |

### 4.2 权威侧注解（Phase 1）

| 文件 | 改动 |
|---|---|
| `app/experts/scheduling.py` `_build_spec` | `meta` 增加 `expert_task_name`（原始名）、`expert_description`、`origin_source="ui"`；`dispatch.meta` 同步 |
| 同文件 `record_execution` | Phase 2 起：`expert_task_runs` 写入由开关（`QWENPAW_CRON_LEDGER_DUAL_WRITE`，默认 on）控制；Phase 3 移除 |

### 4.3 读层（Phase 2）

| 文件 | 改动 |
|---|---|
| `app/experts/cron_ledger.py`（新） | `CronLedgerReader`：`list_tasks/get_task/list_runs/count_active`，按 §3.1 反推；查询条件 `agent_id=expert_agent_id(expert_id)`；`next_run_at` 由调用方注入 |
| `app/experts/scheduling.py` `SchedulingStore` | 读方法（get_task/list_tasks/list_runs/count_active_by_expert）委托 `CronLedgerReader`；`create_task` 改为「改经 SchedulingService 注册权威 + 读回」而非先插行（API 形状不变） |
| `routers/admin/expert_capability.py` | 零改（继续用 `get_scheduling_store()`；`_scheduling_service` 仍解析 cron_manager 供 next_run_at 注入）；:197-201 统计改走 reader.count_active |
| `experts/worklog.py` | 零改（仍调 store.list_runs/等价 reader；注意 D5 语义） |

### 4.4 收口（Phase 3）

| 动作 | 内容 |
|---|---|
| 停写 | 删 `SchedulingStore` 的 INSERT/UPDATE/归档 SQL；观察者的 executions 写路径移除（执行检查闭环 `_verify_execution_result` 保留） |
| DDL | `changelog/.../04_drop_expert_ledger.sql`：`DROP TABLE IF EXISTS expert_task_runs; DROP TABLE IF EXISTS expert_scheduled_tasks;` + 注释（[变更说明][变更时间][变更人][适用环境][快照同步] 六行头）；alembic `0041_drop_expert_ledger.py`（down 重建 DDL 见 §6） |
| 快照 | test.sql/prod.sql 同步移除两表 DDL（二进制追加方式） |

---

## 5. 迁移与回填（Phase 2 一次性，幂等）

1. **规格注解回填**（SQL，幂等）：
   ```sql
   UPDATE cron_jobs cj SET spec = jsonb_set(jsonb_set(jsonb_set(
            cj.spec, '{meta,expert_task_name}', to_jsonb(t.name)),
            '{meta,expert_description}', to_jsonb(COALESCE(t.description,''))),
            '{meta,origin_source}', to_jsonb(COALESCE(t.source,'ui'))), ...
    FROM expert_scheduled_tasks t
    WHERE cj.tenant_id=t.tenant_id AND cj.agent_id='expert_'||t.expert_id
      AND cj.job_id = 'expert_task_'||t.id
      AND NOT (cj.spec->'meta' ? 'expert_task_name');  -- 变更门，重放零写
   ```
   （chat/api 链路的 `t.id = cron_jobs.job_id` 同式处理；content_hash 重算。）
2. **执行记录补列回填**：`UPDATE cron_job_history h SET result_summary=t.result_summary, run_id=t.run_id, session_id=t.session_id, scheduled_for=CASE WHEN h.trigger='scheduled' THEN h.run_at END FROM expert_task_runs t WHERE h.tenant_id=t.tenant_id AND h.agent_id='expert_'||t.expert_id AND h.job_id=... AND h.run_at=t.finished_at`（匹配键：run_at≈finished_at + 状态映射；无法匹配的旧行保持默认空值——接受降级）。
3. **对账脚本** `scripts/reconcile_cron_ledger.py`（临时，跑完删）：逐 expert 比 list_tasks/list_runs 双源；输出差异 JSON；要求 **差异 = 0**（允许白名单：result_summary 空、在途 run）才进入 Phase 3。

---

## 6. 回滚方案

| 阶段 | 回滚动作 |
|---|---|
| Phase 1 | alembic downgrade 0040（DROP 新列/索引）；写路径补列对老代码零影响（列有默认值，老代码不 SELECT 新列） |
| Phase 2 | 读委托回退开关（`QWENPAW_CRON_LEDGER_READ=cron|expert`，默认 cron，异常切回 expert）；回填为纯 UPDATE，无数据破坏 |
| Phase 3 | 两表 DROP 前先 `pg_dump` 备份（运维步骤）；alembic `0041` 的 downgrade 内置**重建 DDL**（从 0029 迁移文件提取的 CREATE TABLE + 加列），且 `changelog/.../04_drop` 文件保留完整重建 SQL 于注释块外附 `_rebuild/` 子文件 |

关键防护：**DROP 与「停写」分两个变更日**（先停写观察 1 天业务无异常，再 DROP），符合 expand-contract 原则。

---

## 7. 决策点（需拍板，含推荐项）

| # | 问题 | 推荐 | 备选 |
|---|---|---|---|
| **D1** | json 存储后端下 cron 双表不落库，收口后专家定时任务列表会空 | 收口前置：专家域部署强制 `QWENPAW_STORAGE_BACKEND ∈ {dual,pg}`（文档化 + 启动 WARN）；不改默认值 | ①改默认值（影响面大）；②read 层双后端分支（违背单一权威） |
| **D2** | `archived` 行（job 已删的台账留痕）与 `completed` 终态在 cron 侧无安放处 | `completed`：新写入 `meta.expert_completed_at`（once 成功时由 manager/观察者补）；`archived`：**接受语义变更**——job 删除即从列表消失，历史靠 cron_job_history 已在删除时清理（对齐 console 现状） | 保留一张 tombstone 表（又一套台账，不推荐） |
| **D3** | `run_count` 精确值（history 50 条修剪截断） | `cron_jobs` 加 `run_count INT NOT NULL DEFAULT 0` 冗余列，`append_history` 同事务 +1（新增 1 列 + 1 语句） | 接受窗口内 COUNT 降级 |
| **D4** | 在途 run 可见性（ledger 先写 running；cron history 完成才 append） | 接受语义变更：运行列表只显示已完成 run（worklog 在途任务计入下个窗口）；**UI 已有 running 态渲染无需改**，只是出现时机延后 | 让 manager 在开始执行时也 append running 行（改 CronManager 生命周期，风险高） |
| **D5** | `started_at/finished_at` 双时间（cron history 只有 run_at） | 接受：两者同取 run_at | 补 started/finished 两列（收益低） |
| **D6** | 幂等锚：`(task_id, scheduled_for)` vs `(job_id, seq)` + 进程锁 | 沿用 seq 机制（append_history 已幂等：进程锁 + MAX+1）；**不新增** scheduled_for 唯一索引（多实例并发另有 cron 锁兜底） | 补 scheduled_for 唯一索引（跨实例防重，超范围） |
| **D7** | T13 是否分三个独立变更日交付 | 是：Phase1（DDL+写路径）→ 验证 → Phase2（回填+读切换）→ 对账=0 → Phase3（停写）→ 观察 → DROP | 一次性合并（风险不可控，不推荐） |

---

## 8. 验证计划（对齐项目测试分工：AI 负责接口/单测/集成，页面走查归用户）

**Phase 1**
- 单测：`tests/unit/app/crons/` 补 `CronExecutionRecord` 新字段序列化 + fake repo 落列断言
- 集成（5433）：`test_cron_history_columns.py`——append_history 写入 result_summary/run_id/session_id 后 SELECT 回读、幂等重放
- 回归：`pytest tests/unit/app/crons -q` + 基线比对 flake8

**Phase 2**
- 单测：`tests/unit/app/experts/test_cron_ledger_reader.py`——§3.1 每行映射的黄金用例（前缀剥离、状态映射、owner 归一、缺省回填）
- 集成：`test_cron_ledger_convergence.py`——种 3 类任务（UI/chat/api 各 1）+ 各 2 run → 回填 → **双源对账断言差异=0** → 幂等重跑差异=0
- worklog 对比：同一数据下 `build_work_record` 改造前后 total_tasks/时间线条数断言（允许 D4 白名单）

**Phase 3**
- DDL 幂等：0040→0041 up/down 循环各 2 次
- 全量回归：`pytest tests/unit/app tests/unit/drivers --ignore=tests/unit/app/kb -q`（kb 为并行会话 WIP）
- 验收证据：DROP 后 admin 6 端点 + work-record 冒烟（接口层）

---

## 9. 任务拆分建议（评审通过后的执行序）

| 步骤 | 内容 | 出口条件 |
|---|---|---|
| T13a | Phase 1：DDL（0040 + changelog 03 + 快照）、模型/写路径补列、meta 注解 | ✅ 2026-09-18 完成：单测 140+新增 7 绿、集成 2 passed（5433）、alembic 0040 up/down 循环与 psql twin 幂等验证通过 |
| T13b | Phase 2：回填 SQL + CronLedgerReader + 读委托 + 对账脚本 | ✅ 2026-09-18 完成：reader 单测 14 绿；集成收敛测（种 ui/chat/api/once 4 任务×6 run）回填→**对账差异=0**→幂等重跑零写；全量单测 1912 passed；对账 CLI 实跑 clean（见 §9.2） |
| T13c | Phase 2 观察窗结束 | 用户确认业务无异常 |
| T13d | Phase 3：停写 + DROP（0041 + changelog 04 + 快照） | DDL 幂等循环；全量回归绿 |
| T13e | 交接文档 + 记忆归档 | — |

### 9.1 T13a 实施备注（2026-09-18）

1. **D2 落地细化**：`completed` 终态**不新增** `meta.expert_completed_at` 写入，Phase 2 读层改从
   「`schedule.type=once` 且最新 history `success`」推导（§3.1 已列的备选口径）——与现行
   台账规则（scheduling.py `finish_run`：once+succeeded 即 completed）完全对齐，省去一条
   反向写权威 spec 的路径，降低 Phase 1 风险。
2. **D3 落地**：`cron_jobs.run_count` 与 `append_history` 同事务 `+1`（pg_repo 内第 3 条语句），
   不动 `updated_at`（执行不属于规格变更）。
3. **存量 Bug 修复（T13a 探查发现）**：`_build_spec` 构造 `DispatchTarget` 未传必填的
   `session_id`（上游 `9f49c911` 把该字段改为必填后 fork 侧未跟进），导致 UI 链路创建/编辑
   专家定时任务必抛 ValidationError。本次以 `session_id=""` 修复：executor 的
   `share_session=False` 分支据此派生专属会话 `cron:{job_id}`，与模块头注语义一致。
4. **expert 台账照常双写**（安全垫）：Phase 1 未动任何读路径与 expert 两表写入。

### 9.2 T13b 实施备注（2026-09-18）

1. **读层单一出口** `app/experts/cron_ledger.py`：纯映射函数
   （`task_from_cron_row`/`run_from_history_row`，无 IO 直接可测）+
   `CronLedgerReader`（批查 history 统计，无 N+1）+ 幂等回填
   `backfill_ledger_into_cron`（三段变更门：meta 键存在性 /
   history 四列空值 / run_count 只升不降）+ 双源对账
   `reconcile_expert`（库函数，CLI 在 `scripts/reconcile_cron_ledger.py`）。
2. **读门控接线**：`SchedulingStore` 的 get_task/list_tasks/
   count_active_by_expert/list_runs/runs_in_window 五方法头部
   `if cron_ledger_read_enabled(): return reader.…`（json 后端自动
   走台账，`QWENPAW_CRON_LEDGER_READ=expert` 可整体回退）；
   admin 详情批量计数改 `count_active_by_experts`（一条 GROUP BY）；
   worklog 的 task_runs 直 SQL 改走 `store.runs_in_window`（与读平面
   同源，杜绝双平面漂移）；装配点 `attach_expert_scheduling` 末尾
   挂幂等回填（best-effort 不阻启动）+ D1 json 后端告警。
3. **回填 SQL 两处修正（集成实跑才暴露，单测无法拦获）**：
   ① 两 timestamp 相减为 interval，PG **无 `abs(interval)`**，改
   `abs(EXTRACT(EPOCH FROM (a - b))) < 600`；② 就近匹配需**双向最优
   配对**（rn_h=1 且 rn_t=1），否则多条 history 会复制同一台账行
   （多对一）造成 run_id 串写；孤配行保持空值降级（§5.2 已接受）。
4. **D2 落地**：completed 从「once + 最新 history success」推导（批量
   `bool_or(status='success')` 一次取齐，不新增 meta 写）；archived
   行 job 已删即不列出（对账白名单剔除）；在途 running 不计入
   run 对账（D4 白名单）。
5. **存量台账测适配**：`test_enterprise_expert_capability.py` 的
   `enterprise_env` 钉 `QWENPAW_CRON_LEDGER_READ=expert`（该模块直写
   直读 legacy 台账不经权威注册，门控 ON 时会读到空 cron 面）；
   cron 读平面由 `test_cron_ledger_convergence.py` 端到端覆盖。
6. **已知环境约束（非本次引入）**：`test_cron_execution.py` /
   `test_cron_header.py` 依赖整机 app_server 子进程：本沙箱内子进程
   启动就绪超时（healthz 503）；且两用例假设 json 文件后端，而宿主
   环境只要 `QWENPAW_PG_DSN` 存在即默认 dual（PG 权威读面忽略 json
   种子）——跑它们须不带 PG DSN 的环境；T13b 未触碰执行面写路径
   （manager/pg_repo 属 T13a 已验范围）。
7. **无新 DDL**：T13b 纯读层/回填/工具，不动表结构；alembic 下一
   编号仍为 0041（T13d DROP）。

### 9.3 T13d 实施备注（2026-09-18，Phase 3 停写 + DROP）

1. **观察窗以事实替代（用户决策）**：T13c 取证发现开发库 legacy 两表
   （`expert_scheduled_tasks`/`expert_task_runs`）零数据、对账脚本
   `experts_checked=0` 空过——业务一直跑 json 文件平面台账，无存量双写
   流量可观测。经 AskUserQuestion 用户选「直接启动 T13d」，以集成测证据
   + 零数据事实替代 ≥1 天观察窗。
2. **json 后端 DROP 安全性论证（消除 D1 顾虑）**：核实
   `write_gateway._default_storage_backend()` = `BACKEND_DUAL if get_pg_dsn()
   else BACKEND_JSON`；而专家调度依赖 `require_enterprise_engine()`（需 PG
   DSN）——故「json 后端 + 可用专家调度」非真实状态：有 DSN 即默认 dual
   （cron 面权威），无 DSN 则 enterprise engine 不存在（503）。D1 降级只
   覆盖「显式设 json 又配 DSN」的矛盾配置，`warn_if_json_backend` 已兜住。
   **结论：DROP 对所有真实部署安全。**
3. **停写契约的真实深度**：不仅移除 observer/dual 写路径，还须把 admin
   管理写链路（create/update/pause/resume/delete）从「先写 legacy 行」改基到
   「CronManager 权威注册 + CronLedgerReader 读回」。`SchedulingStore` 收敛为
   只读 facade（5 方法全委托 reader）；`SchedulingService` 只挂执行观察者
   （删注册观察者）；`record_execution` 去 legacy 双写、保留执行检查闭环
   （`_verify_execution_result` + inbox 告警）。
4. **删除的 Phase 2 一次性脚手架**：`cron_ledger.py` 的门控
   （`cron_ledger_read_enabled`/`cron_ledger_dual_write_enabled`）、回填
   （`backfill_ledger_into_cron`）、对账（`reconcile_expert`）；注册观察者
   （`_make_registration_observer`/`_attach_registration_observer`/
   `_upsert_task_row`/`_backfill_tasks_from_authority`）；运维 CLI
   `scripts/reconcile_cron_ledger.py`；集成收敛测
   `tests/integration/test_cron_ledger_convergence.py`。
5. **DROP 迁移（alembic 0041_drop_expert_ledger）**：upgrade 先
   `DROP TABLE IF EXISTS expert_task_runs` 后 `expert_scheduled_tasks`；
   downgrade 内联重建（0012 建表 + 0029 加列 source/origin/run_id/
   session_id + CHECK/PK + 4 索引，全 IF NOT EXISTS）。changelog
   `20260918/04_drop_expert_ledger.sql` 为 psql twin；快照 test.sql/prod.sql
   二进制追加。**幂等实证**：scratch 库 fresh→head→down 0040→up head 2 循环
   + 幂等重放 MIGRATION-VERIFY-OK；应用到开发库 5433/qwenpaw 达 0041、两表
   count=0。DROP 前 pg_dump 备份 `.superpowers/sdd/
   backup_expert_ledger_20260918.sql`（13130 bytes，空数据）。
6. **收口残留活引用修复（归档期复查发现，关键）**：
   `app/routers/admin/pending.py` 的 `/pending-items` 聚合端点第 3 段
   （员工定时任务失败告警）**直查已 DROP 的 `expert_scheduled_tasks`**
   （`WHERE status='active' AND last_status='failed'`）——0041 应用后必抛
   `relation does not exist` 致端点 500。该端点**无任何测试覆盖**，故 T13d
   初轮 grep 复查把它与注释引用一并误判为误报而漏掉。修复：在
   `CronLedgerReader`（专家定时任务唯一读出口）新增跨员工面
   `list_active_failed_tasks(limit)`（一条批查：latest-per-job DISTINCT ON
   取最新 history + `enabled` + `status<>'success'` + `agent_id LIKE
   'expert_%'` 作用域，复用已测的 `task_from_cron_row` 映射），pending.py
   第 3 段改走 reader（移出 `engine.connect()` 块，因 reader 自管连接）。
   **教训**：收口类残留引用复查必须区分「注释/docstring 陈旧引用」与
   「活 SQL/代码引用」，且无测试覆盖的端点是高危盲区——须逐处读上下文
   判定，不能仅凭 grep 命中词归类误报。
7. **验证**：单测 `test_cron_ledger_reader.py`+`test_expert_scheduling_
   projection.py` 27 passed；集成 `test_enterprise_expert_capability.py`
   **19 passed**（5433 隔离库，含 admin scheduled-tasks CRUD + work-record
   冒烟 + 新增 `test_pending_inbox_reads_failed_tasks_from_cron_plane`
   端点级回归，即 §8 要求的接口层验收证据；隔离库已确证 0041、两表
   `to_regclass` 为 NULL）；全量回归 `tests/unit/app tests/unit/
   drivers --ignore=tests/unit/app/kb` = **1921 passed / 1 skipped / 1
   failed**（唯一 failed = 登记在案的 `test_list_pool_skills_returns_pool_
   specs` PG 状态依赖，非本次引入）；flake8 新改文件（scheduling/
   cron_ledger/0041）零违规，pending.py 仅存量 1 E501（items.sort lambda
   行，未触碰），expert_capability.py 仅存量 6 E501（基线一致）。

---

## 10. 附：证据索引（代码位点）

- 计划原文：`.qoder/plans/handoff_pg_scope_20260918.md` §2 T13
- 台账实现：`src/qwenpaw/app/experts/scheduling.py`（959 行全量已读）
- 记录模型：`src/qwenpaw/app/experts/models.py:479-547`（ScheduledTaskRecord/TaskRunRecord）
- 读消费者：`src/qwenpaw/app/routers/admin/expert_capability.py:540-665`、`src/qwenpaw/app/experts/worklog.py:92-174`
- cron 权威：`src/qwenpaw/db/models_crons.py`、`src/qwenpaw/app/crons/repo/pg_repo.py`、`src/qwenpaw/app/crons/manager.py:616/879`
- 归属映射：`src/qwenpaw/app/experts/models.py:72-74`、`src/qwenpaw/app/workspace/workspace.py:534-536`
- 装配点：`attach_expert_scheduling`（scheduling.py:927）、`SchedulingService` factory（expert_capability.py:102-128）