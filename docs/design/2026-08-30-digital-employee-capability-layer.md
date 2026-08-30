# 数字员工能力层设计 —— StaffDeck 能力移植与 console UI 重构

> 日期：2026-08-30　分支：`feature/xianwork_enterprise_20260814`　作者：清风
> 状态：已评审（本文件为实施依据）
> 参照物：`StaffDeck/`（OpenBMB，仅作设计参考，**不进仓库**，已加入 `.gitignore`）

---

## 一、背景与目标

StaffDeck（OpenBMB 开源企业数字员工平台）的**数字员工能力层**设计成熟：每个数字员工
拥有岗位档案、能力挂载（资料/技能/SOP/知识/工具）、分桶记忆、定时任务、工作记录、
反馈演进闭环与人工接管。但其执行内核是"意图路由 + SOP 状态机逐步执行"，固化在
预设流程里，缺少本项目的核心优势：

> **Hierarchical ReAct + Plan-and-Execute + Supervisor + Verification + Recovery**
> （`src/qwenpaw/app/workforce/`，两级 Harness，见 `docs/design/2026-08-18-workforce-harness-architecture.md`）

**目标**：把 StaffDeck 的能力层"长"到本项目的 experts + workforce 架构上——
数字员工的**档案、资产、记忆、排期、台账、反馈**照 StaffDeck 的产品形态做齐；
**执行**全部走我们自己的引擎（SOP 只作为流程资产注入规划，绝不替代引擎）；
同时用 StaffDeck 的设计语言重构 console 的数字员工界面。

## 二、StaffDeck 能力层拆解（学习结论）

| # | 能力域 | StaffDeck 做法 | 采纳策略 |
|---|--------|----------------|----------|
| 1 | 员工档案 | 岗位/部门/工作风格/擅长领域/创建者/入职时间 + 资料·技能·SOP·定时任务四计数 + 插画头像 + 在线状态 | ✅ 全量采纳：`experts` 扩档案列；计数走聚合一站式返回 |
| 2 | 能力挂载 | `agent_resource_bindings` 枢纽表：员工 × {skill, general_skill, knowledge_base, tool}，区分"广场绑定（引用）"与"私有副本（拷贝/分支）" | ✅ 采纳：新表 `expert_resource_bindings`（sop/knowledge_base/tool）；技能沿用既有 `expert_skills`（发布链权威，不迁移） |
| 3 | SOP 资产 | SkillCard 图（nodes/edges/槽位/条件/子流程）+ 版本链 + 员工私有分支（synced/diverged）+ 晋升/回滚 | ✅ 形态采纳（图定义+版本+绑定）；❌ 执行不采纳：SOP 作为**流程资产注入 workforce 规划与验收**（见决策 D3） |
| 4 | 分桶记忆 | `memories`：kind ∈ profile/preference/fact，后台 LLM 萃取 upsert/delete，按 (user, expert) 归属，注入上下文 + 槽位水合 | ✅ 采纳：`expert_memories`（DB 制，可 UI 管理）；注入走发布物化 + 上下文构建（见决策 D4） |
| 5 | 定时任务 | once/daily/weekly/monthly + 时区 + 并发/错峰策略；执行=建独立会话走同一引擎，结果写工作记录 | ✅ 采纳：`expert_scheduled_tasks` 投影表 + 执行权威复用 `crons.CronManager`（APScheduler），执行=对该专家发起一次真实任务，留痕 `expert_task_runs` |
| 6 | 工作记录 | 回复统计（today/by_day）+ 事件时间线（能力分配/任务运行）+ Day/Week/Month 日历 + 好评率/差评率 | ✅ 采纳：`GET .../work-record` 聚合 API（统计来源：team_runs/team_run_nodes/expert_task_runs/message_feedback/feed_events），console 日历时间线 |
| 7 | 反馈→演进 | 消息级 👍/👎 → 技能级反馈 → LLM 13 桶归因 → evolution_proposals（评估→审批→发布/回滚） | ✅ 分期：本期建 `message_feedback` + `evolution_proposals`（采集+提案生命周期）；LLM 自动归因后台 Job 列入二期 |
| 8 | 人工接管 | handoff 队列 + 回复后恢复 SOP | ✅ 已有等价物：workforce `escalated` + `resolve_escalation`/`answer_clarification`/`handover`；本期补"待办收件箱"查询面，不新建平行机制 |
| 9 | 渠道多员工调度 | 渠道挂载多员工 + 意图自动分发 + 斜杠指令 | ⏸ 暂缓：本项目 18 渠道 registry + team router 模式已覆盖主场景；多员工意图分发列入路线图 |
| 10 | 员工级开放 API | 员工级 API Key + Runs + SSE + Webhook + 幂等 | ⏸ 暂缓：`/api/open` 平面列入路线图（复用 auth.py JWT + rbac grants） |

**不抄的部分**：意图路由器/TurnPlan/TaskFrame 执行内核、SOP 状态机运行时
（step_agent/graph_rules/skill_runtime）、mutation-observer 式 i18n、自绘 SOP 画布
（8.5k 行单文件）。这些与我们的引擎定位冲突或维护成本过高。

## 三、总体架构

```
                    console / xianwork（StaffDeck 设计语言）
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        │ /api/admin/experts/**    │ /api/xian/experts/**      │ /api/cron（既有）
        │ 档案·资源·SOP·记忆·排期  │ 市场·详情·召唤·自建       │
        ▼                          ▼                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 数字员工能力层（本设计新增，全部挂在 experts 域，不建平行体系）      │
│  experts/capability.py   资源挂载（sop/kb/tool 绑定）               │
│  experts/sops.py         SOP 资产 + 版本链                          │
│  experts/memories.py     分桶记忆（DB）+ 发布物化注入               │
│  experts/scheduling.py   员工定时任务（投影 + CronManager 权威）    │
│  experts/worklog.py      工作记录聚合（只读，五步范式）             │
│  experts/feedback.py     消息反馈 + 演进提案生命周期                │
└─────────────────────────────────────────────────────────────────────┘
        │ 复用（不改造语义）                                     │ 例外：执行时被"引用"
        ▼                                                        ▼
 expert_skills → publish.py 物化                    workforce 引擎（Plan/Verify/Recover）
 crons.CronManager（APScheduler 权威）              team_runs / team_run_nodes / feed_events
```

原则：
1. **单一来源**：技能绑定权威= `expert_skills`；调度权威= CronManager；运行留痕权威=
   `team_runs`/`history_entries`。新表一律是"投影/资产/台账"，不做第二权威。
2. **不建平行体系**：StaffDeck 的 Employee=本项目的 Expert；一切能力挂在 experts 域。
3. **正向/逆向成对**：每个资源都有 create→…→delete/archive 完整路径（详见 §五、§六）。

## 四、关键决策记录

**D1 档案放列、不放 JSONB 黑洞**
StaffDeck 把岗位/部门塞 `metadata_json`（自由键），检索与统计困难。本项目把 UI 与
统计真实需要的字段建成显式列：`department` / `work_styles` / `work_modes` /
`hire_date`；`title`（职称）与 `tags`（擅长标签）既有列沿用。在线状态**不落列**，
派生计算（已发布且未被归档=在线；未来叠加渠道连接态）。

**D2 技能绑定不迁移，新增统一资源绑定表**
`expert_skills` 是发布物化链（`publish._sync_workspace_skills`）的权威且已稳定。
新建 `expert_resource_bindings` 只管 StaffDeck 有而我们没有的三类：`sop` /
`knowledge_base` / `tool`。两张表职责在注释中互相指认，避免后来人误并。

**D3 SOP = 流程资产，执行注入 workforce（本设计的灵魂）**
SOP 定义（nodes/edges/槽位/验收要点）落 `sops`+`sop_versions`；绑定到专家后：
- **规划期**：workforce `_planning_phase` 已从 kb/组织记忆取上下文 → 追加"专家绑定
  SOP 的节点链摘要"进 ContextBundle，中央大脑把 SOP 当参考蓝图而非硬状态机；
- **执行期**：TaskContract 附 `sop_ref`（节点验收要点），子员工在 Hierarchical
  ReAct 中自由选择工具路径达成节点目标；
- **验收期**：Verifier 的 rubric 可引用 SOP 节点 expected_outcome。
这样既保住"经验固化"（StaffDeck 的价值），又保住引擎的灵活与恢复能力（我们的价值）。

**D4 记忆走 DB + 发布物化双通道**
- 存取：`expert_memories`（kind=profile/preference/fact + dedup_key 幂等 upsert），
  console 可视化管理（增删改查），这是 StaffDeck 的产品形态；
- 注入：发布链与记忆变更时，把该专家记忆按 kind 汇总物化到专家 workspace 的
  `memory/expert_memory.md`（agent_md_manager 既有摘要机制自然加载），零运行时侵入。

**D5 定时任务：投影 + 权威分离（复制 automations 的成熟模式）**
`routers/xian/automations.py` 已验证"DB 投影 + CronManager 权威"模式。照抄该模式：
`expert_scheduled_tasks` 为运营台账（UI 管理/统计），真实调度注册为 CronManager job
（job_id 前缀 `expert_task_`），执行回调=对该专家发起一次真实任务（走 workforce run
通道），结果写 `expert_task_runs` + feed_events，成为工作记录的天然素材。

**D6 工作记录是聚合视图，不建流水新表**
数据已存在：`team_runs`/`team_run_nodes`（团队任务）、`expert_task_runs`（定时任务）、
`message_feedback`（反馈）、`feed_events`（动态）。`worklog.py` 只做一次批量聚合
（按天 group by，禁止 N+1），产出 StaffDeck WorkRecordTab 需要的全部形状。

**D7 反馈闭环分期**
本期：采集（👍/👎 + comment）→ 汇总（按专家/按天/净评分）→ 演进提案手工人审状态机
（draft→ready_for_review→approved/rejected→published/rolled_back）。
二期：LLM 归因后台 Job（差评 → 归因桶 → 自动起草 evolution_proposal）。

**D8 console UI 重构 = 设计语言移植，不是换框架**
console 保持 React 18 + antd 5 + less 现栈。新增 `src/styles/staffdeck-tokens.css`
（冷灰蓝 tokens：墨色 #18181a / 辅助 #757f9c / 发丝线 #e3e7f1 / 中性面 #f6f6f6 /
主按钮黑 / 状态四色板；圆角分级 20/14/10/8；阴影克制）+ `src/components/staffdeck/`
通用组件（StatCard、StatusPill、UnderlineTabs、EmployeeCard、ActivityTimeline）。
重构 `/admin/experts` 列表页（统计卡行 + 状态 tabs + 卡片网格），新增
`/admin/experts/:expertId` 详情页（Hero 档案卡 + 工作记录/定时任务/记忆/能力资产/对话日志 Tabs）。

## 五、数据模型设计（DDL 概览）

全部幂等（IF NOT EXISTS / ADD COLUMN IF NOT EXISTS），changelog：
`db/feature/xianwork_enterprise_20260814/changelog/20260830/01_digital_employee_capability.sql`
+ alembic `0012_digital_employee_capability`，快照同步 test.sql / prod.sql。

```sql
-- 1. experts 扩档案列（D1）
ALTER TABLE experts ADD COLUMN IF NOT EXISTS department   TEXT NOT NULL DEFAULT '';
ALTER TABLE experts ADD COLUMN IF NOT EXISTS work_styles  JSONB NOT NULL DEFAULT '[]';  -- ["耐心细致",...]
ALTER TABLE experts ADD COLUMN IF NOT EXISTS work_modes   JSONB NOT NULL DEFAULT '[]';  -- ["7x24值守",...]
ALTER TABLE experts ADD COLUMN IF NOT EXISTS hire_date    TIMESTAMPTZ;                 -- 入职时间（NULL=未填）

-- 2. 能力挂载（D2；resource_type: sop/knowledge_base/tool）
CREATE TABLE IF NOT EXISTS expert_resource_bindings (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    expert_id VARCHAR(64) NOT NULL,
    resource_type TEXT NOT NULL,          -- sop | knowledge_base | tool
    resource_id   TEXT NOT NULL,          -- sops.id / kb 文档 id / 工具名
    enabled   BOOLEAN NOT NULL DEFAULT TRUE,
    seq       INTEGER NOT NULL DEFAULT 0,
    metadata  JSONB NOT NULL DEFAULT '{}',-- 挂载时快照（名称等，防悬挂显示）
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_resource_bindings PRIMARY KEY (tenant_id, expert_id, resource_type, resource_id)
);

-- 3. SOP 资产 + 版本链（D3）
CREATE TABLE IF NOT EXISTS sops (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id        VARCHAR(64) NOT NULL,
    name      TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    business_domain TEXT NOT NULL DEFAULT '',
    goal      TEXT NOT NULL DEFAULT '',       -- 流程总目标
    nodes     JSONB NOT NULL DEFAULT '[]',    -- [{id,title,instruction,expected_outcome,tools[]}]
    edges     JSONB NOT NULL DEFAULT '[]',    -- [{from,to,condition}]
    slots     JSONB NOT NULL DEFAULT '[]',    -- [{key,label,required,ask_prompt}]
    status    TEXT NOT NULL DEFAULT 'draft',  -- draft|published|archived
    version   INTEGER NOT NULL DEFAULT 1,
    owner_id  TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_sops PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS sop_versions (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    sop_id    VARCHAR(64) NOT NULL,
    version   INTEGER NOT NULL,
    snapshot  JSONB NOT NULL,                 -- 发布时全量快照
    change_note TEXT NOT NULL DEFAULT '',
    published_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_sop_versions PRIMARY KEY (tenant_id, sop_id, version)
);

-- 4. 员工分桶记忆（D4；kind: profile/preference/fact）
CREATE TABLE IF NOT EXISTS expert_memories (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id        VARCHAR(64) NOT NULL,
    expert_id VARCHAR(64) NOT NULL,
    user_id   TEXT NOT NULL DEFAULT '',       -- ''=组织级公共记忆
    kind      TEXT NOT NULL,                  -- profile|preference|fact
    content   TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,     -- 0~1
    dedup_key TEXT NOT NULL DEFAULT '',       -- 语义去重键（kind 内唯一）
    metadata  JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_memories PRIMARY KEY (tenant_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_memories_dedup
    ON expert_memories (tenant_id, expert_id, user_id, kind, dedup_key);

-- 5. 员工定时任务 + 执行留痕（D5）
CREATE TABLE IF NOT EXISTS expert_scheduled_tasks (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id        VARCHAR(64) NOT NULL,
    expert_id VARCHAR(64) NOT NULL,
    name      TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_prompt TEXT NOT NULL,                -- 执行时投给专家的指令
    schedule_type TEXT NOT NULL DEFAULT 'cron',-- cron|once
    schedule_json JSONB NOT NULL DEFAULT '{}',-- {cron:"0 9 * * 1-5"} | {run_at:...}
    timezone  TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    status    TEXT NOT NULL DEFAULT 'active', -- active|paused|completed|archived
    cron_job_id TEXT NOT NULL DEFAULT '',     -- CronManager 权威 job id
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_status TEXT NOT NULL DEFAULT '',     -- succeeded|failed|running|''
    run_count  BIGINT NOT NULL DEFAULT 0,
    owner_id  TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_expert_scheduled_tasks PRIMARY KEY (tenant_id, id)
);
CREATE TABLE IF NOT EXISTS expert_task_runs (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id        VARCHAR(64) NOT NULL,
    task_id   VARCHAR(64) NOT NULL,
    expert_id VARCHAR(64) NOT NULL,
    scheduled_for TIMESTAMPTZ,                -- 计划触发点（幂等锚）
    status    TEXT NOT NULL DEFAULT 'running',-- running|succeeded|failed
    result_summary TEXT NOT NULL DEFAULT '',
    error     TEXT NOT NULL DEFAULT '',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    CONSTRAINT pk_expert_task_runs PRIMARY KEY (tenant_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_expert_task_runs_idem
    ON expert_task_runs (tenant_id, task_id, scheduled_for)
    WHERE scheduled_for IS NOT NULL;

-- 6. 消息反馈（D7）
CREATE TABLE IF NOT EXISTS message_feedback (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id        VARCHAR(64) NOT NULL,
    message_id  TEXT NOT NULL,                -- history_entries 消息 id
    session_id  TEXT NOT NULL DEFAULT '',
    expert_id   TEXT NOT NULL DEFAULT '',     -- 归属专家（可空=非专家会话）
    user_id     TEXT NOT NULL DEFAULT '',
    rating    TEXT NOT NULL,                  -- up|down
    comment   TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_message_feedback PRIMARY KEY (tenant_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_message_feedback_once
    ON message_feedback (tenant_id, message_id, user_id);

-- 7. 演进提案（D7；状态机 draft→ready_for_review→approved|rejected→published|rolled_back）
CREATE TABLE IF NOT EXISTS evolution_proposals (
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    id        VARCHAR(64) NOT NULL,
    expert_id VARCHAR(64) NOT NULL,
    title     TEXT NOT NULL,
    trigger_type TEXT NOT NULL DEFAULT 'feedback', -- feedback|manual|audit
    risk_level TEXT NOT NULL DEFAULT 'low',     -- low|medium|high
    hypothesis TEXT NOT NULL DEFAULT '',        -- 改进假设
    evidence  JSONB NOT NULL DEFAULT '[]',      -- 证据（反馈 id/摘录）
    candidate JSONB NOT NULL DEFAULT '{}',      -- 变更体（sop/system_prompt/skills diff）
    status    TEXT NOT NULL DEFAULT 'draft',
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_evolution_proposals PRIMARY KEY (tenant_id, id)
);
```

索引按查询面补齐：`expert_resource_bindings(expert_id)`、`sops(owner_id)`、
`expert_memories(expert_id, user_id)`、`expert_scheduled_tasks(status, next_run_at)`、
`expert_task_runs(task_id, started_at)`、`message_feedback(expert_id, created_at)`、
`evolution_proposals(expert_id, status)`。

## 六、API 设计

管理面（`/api/admin/experts`，RequireAdmin）与用户面（`/api/xian/experts`，
ACL 沿用 `_enforce_expert_acl` + owner 规则）对称暴露；用户面只读+自建资源可写。

| 方法 | 路径（挂 experts 前缀下） | 说明 | 逆向路径 |
|------|---------------------------|------|----------|
| GET | `/{expert_id}/work-record?days=30&tz=` | 工作记录聚合（D6）：reply_stats.by_day、feedback 统计、timeline[]（team_run/task_run/resource 绑定事件） | 只读 |
| GET/PUT | `/{expert_id}/resources` | 资源绑定整表替换（sop/kb/tool），PUT 幂等 | PUT 空数组=清空 |
| GET/POST | `/sops`、GET/PATCH/DELETE `/sops/{id}`、POST `/sops/{id}/publish`、POST `/sops/{id}/rollback`、GET `/sops/{id}/versions` | SOP 资产 CRUD+版本链 | publish 写快照；rollback 恢复历史快照为新版本；DELETE 仅 draft（published 走 archive） |
| GET/POST | `/{expert_id}/memories`、PATCH/DELETE `/{expert_id}/memories/{mid}` | 分桶记忆；POST 按 dedup_key 幂等 upsert；写后触发物化刷新（D4） | DELETE 物理=记忆修正语义；物化文件同步重建 |
| GET/POST | `/{expert_id}/scheduled-tasks`、PATCH/DELETE `/{id}`、POST `/{id}/pause`、`/resume`、`/run-now` | 定时任务（D5）：创建=投影行+CronManager 注册；PATCH=两侧同步；DELETE=注销 job+归档行 | pause/resume/run-now/delete 双侧一致；失败回滚（先建投影成功再注册 job，注册失败删行） |
| GET | `/{expert_id}/feedback-summary?days=30` | 👍/👎 计数、好评率、按天分布、最近差评列表 | 只读 |
| POST | `/{expert_id}/feedback` | 采集（message_id+rating+comment，(message,user) 唯一，重复=覆盖语义） | — |
| GET | `/evolution-proposals?expert_id=`、POST `/evolution-proposals`、POST `/{id}/review`（approve/reject）、POST `/{id}/publish`、`/{id}/rollback` | 演进提案生命周期（admin 审批） | rejected/rolled_back 终态留痕，不物理删 |

员工详情页头部四计数（资料=资源绑定数+技能数、技能、SOP、定时任务）并入
`GET /{expert_id}` 详情响应（一次批量聚合，禁止 N+1）。

## 七、console UI 设计语言（StaffDeck 移植版）

**Tokens**（`src/styles/staffdeck-tokens.css`，CSS 变量 + 工具类）：

| Token | 值 | 用途 |
|---|---|---|
| `--sd-ink` | #18181a | 标题/主按钮底 |
| `--sd-text-2` | #757f9c | 次级文字 |
| `--sd-line` | #e3e7f1 | 发丝边框（0.5px） |
| `--sd-surface` | #f6f6f6 | 中性面板/卡片 header 带 |
| `--sd-bg` | #fcfcfc | 页面底 |
| `--sd-link` | #1a71ff | 链接/蓝状态 |
| `--sd-green/red/amber/gray` | #2cb360/#d20b0b/#d97706/#858b9c + 对应浅底 | 状态四色板（StatusPill 表驱动） |
| 圆角 | 页面卡 20 / 区块 14 / 控件 10 / 胶囊 999 | 分级 |
| 阴影 | 默认无；浮起 `0 16px 30px rgba(0,0,0,.10)` | 克制 |

**组件**（`src/components/staffdeck/`）：`StatCard`（34px 大数字+灰标签+tone）、
`StatusPill`（tone 表驱动圆角胶囊）、`UnderlineTabs`（下划线选项卡）、
`EmployeeCard`（灰 header 带+姓名/职称/状态胶囊+描述两行+底部三格计数）、
`ActivityTimeline`（Day/Week/Month 切换 + 按天分道时间线）。

**页面**：
- `/admin/experts` 重构：顶部搜索 + 统计卡行（员工总数/已发布/草稿/+ 新建）+
  状态 UnderlineTabs + EmployeeCard 网格；保留原有新建/发布/归档/删除弹窗逻辑。
- `/admin/experts/:expertId` 新增：Hero 档案卡（头像位+姓名职称+在线胶囊+创建者+
  入职时间+工作风格标签+四计数条+「召唤」快捷）+ UnderlineTabs：
  工作记录（StatCard 四联 + ActivityTimeline + 成长记录=演进提案流）、定时任务、
  记忆（分组卡片+增删改）、能力资产（SOP/技能/知识/工具绑定管理）、对话日志
  （近期 run/会话 + 反馈标注）。

## 八、实施路线

| 阶段 | 内容 | 状态 |
|---|---|---|
| **P0（本次）** | 设计文档 + 全量 DDL + alembic + 六个能力模块 + admin/xian 路由 + 定时任务执行接线 + 记忆物化注入 + console tokens/组件/列表重构/详情页 + 测试 | ✅ 已交付 |
| **P0.5（同日补全）** | ① 对话气泡 👍/👎 埋点（MessageFeedbackBar，expert 会话专属）；② P1 引擎接线：成员能力快照进 ContextBundle（member_caps 版本化）→ TaskContract.sop_refs + 绑定工具并入 available_tools + SOP 验收要点并入 quality_criteria（Verifier rubric 自动覆盖）+ 绑定 KB 优先检索，委派 prompt 渲染"参考流程（非硬状态机）"段且不泄露全团队快照；③ SOP 只读流程图预览（SopFlowPreview 抽屉）；④ LLM 差评自省归因自动起草演进提案（每日限量 3 条护栏） | ✅ 已交付 |
| **P1 收尾 + P2 完整 + P3/P4/P5 内核（同日第三批）** | 直聊绑定生效：绑定 SOP/知识/工具随发布物化进专家 PROFILE.md（系统提示词），绑定变更即时重建；13 桶归因（ATTRIBUTION_BUCKETS）+ SOP 结构变更候选（target=sop 经 publish_new_version 进版本链）+ 发布差评基线与自动回滚监控（满 24h + ≥5 新评分 + 好评率跌幅 ≥20pp 三重门槛）；P3 待办收件箱（/admin/pending-items 聚合熔断升级/待澄清/待审提案/失败任务 + console 页 `/admin/pending`）；P4 `/api/open`（员工级 API Key：0013 迁移 + 签发/吊销/验证 + open 档案/任务端点 + 密钥管理 UI）；P5 意图分发内核（intent_dispatch：LLM 分类 + 置信阈值 + 粘性保护 + 全链路降级）+ 分发端点 | ✅ 已交付 |
| P5 收尾 | 渠道适配器逐一接线 dispatch_expert_intent（内核/API 已就绪，涉及渠道 registry 改动面，独立批次） | 待开工 |
| 持续项 | xianwork SPA 同步 StaffDeck 化；open API 幂等/审计/限流横切；归因桶汇总分析页 | 待开工 |

## 九、遗留缺口（第三批后重估，显性化）

1. **渠道适配器接线**：意图分发内核与端点已就绪，18 渠道的适配器尚未
   逐一调用（涉及渠道 registry 改动面，独立批次交付）。
2. **open API 横切协议**：Idempotency-Key 幂等、审计流水、限流未接
   （当前面以"能被外部系统安全调用"为线）。
3. **归因桶消费面**：bucket 已写入提案 candidate，按桶统计的差评热力
   分析页未建（数据已备，随运营后台批次）。
4. **SOP 自绘画布编辑器**：仍不做（维护成本考量）——只读流程图预览 +
   结构化表单编辑已覆盖管理诉求。
5. **experts 逻辑删除**：沿用现状（draft 物理删、published 归档=审计
   优先语义，与本设计一致，不另行改动）。
