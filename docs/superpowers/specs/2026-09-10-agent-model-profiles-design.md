# 员工×模型参数档案与激活状态设计（agent_model_slots 档案化）

- 日期：2026-09-10
- 分支：feature/agent_run_logs_20260908（SQL 按分支映射落 db/feature/agent_run_logs_20260908/）
- 状态：设计已经用户确认（方案：员工×模型一行档案 + is_active 激活位）

## 1. 背景与问题

当前 `agent_model_slots`（alembic 0020/0021）为"每员工一行"：
PK `(tenant_id, agent_id, slot_name)`，`config` JSONB 存该员工的参数覆盖集。
参数**跟人**不**跟模型**，导致：

1. 员工给模型 A 配好参数（如 GLM-5.3-Flash 的 400K + 思考中），
   切到模型 B 再切回 A 时，参数已被 B 的配置覆盖或错位沿用，需重新设置；
2. 切换模型时旧参数被无差别带到新模型上（如把 400K 覆盖套到 1M 模型），
   语义错配。

## 2. 目标

- 参数档案按 **员工 × 模型** 独立存储：每个模型在员工名下各有一份参数档案；
- 切换模型 = 启用目标模型的档案（历史参数自动恢复）；
- 从未配置过的模型启用后 **跟随全局基线**（用户已确认该语义）；
- 对外 API（GET/PUT /api/models/active）结构不变，前端零结构改动。

## 3. 表结构改造（修订 alembic 0021）

> 0021 为本分支当日新增且未合并主干，直接修订内容，
> 不新增 0022（避免无意义中间态迁移）。本地库需
> `alembic downgrade 0020_agent_model_slots` 后重新 upgrade。

```sql
-- 主键加入模型维度：一行 = 员工用过的某模型的参数档案
ALTER TABLE agent_model_slots DROP CONSTRAINT IF EXISTS pk_agent_model_slots;

-- 激活状态位：当前生效的档案
ALTER TABLE agent_model_slots
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE;

-- 存量行全部置为激活（每员工一行时代的数据平移）
UPDATE agent_model_slots SET is_active = TRUE WHERE NOT is_active;

ALTER TABLE agent_model_slots
    ADD CONSTRAINT pk_agent_model_slots
    PRIMARY KEY (tenant_id, agent_id, slot_name, provider_id, model);

-- 同一员工同一槽位至多一行激活
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_model_slots_active
    ON agent_model_slots (tenant_id, agent_id, slot_name) WHERE is_active;
```

- `config` JSONB 语义不变：该档案模型的参数覆盖，NULL/字段缺省=跟随全局。
- 修订后的 0021 upgrade = 原 `ADD COLUMN IF NOT EXISTS config` 职责
  （全新库首次建列）+ 上述档案化序列（两段均幂等，兼容
  “已应用旧 0021 的本地库”与“全新库”两条升级路径）。
- 列注释同步更新（含 is_active 与 config 的档案语义）。
- downgrade：删索引 → 删新 PK（多档案行时仅保留 is_active 行）→
  还原旧三列 PK → 删 is_active 列。

同步物：`db/feature/agent_run_logs_20260908/changelog/20260910/01_agent_model_slot_overrides.sql`
修订（当日文件未上线，修订而非新增 02，头部注释补充档案化说明），
`test.sql` / `prod.sql` 快照同步更新。

## 4. 存储层（agent_model_store.py）

| 函数 | 改造 |
|---|---|
| `get_agent_model_slot_pg(agent_id)` | SQL 增加 `AND is_active`，语义="读激活档案"（对 resolve 链路透明） |
| `upsert_agent_model_slot_pg(agent_id, provider_id, model, overrides=None)` | 语义升级为"**激活目标模型档案**"，单事务两步：① 同槽位所有行 `is_active=FALSE`；② INSERT 目标档案行 ON CONFLICT `(tenant,agent,slot,provider,model)` DO UPDATE 置 `is_active=TRUE`。overrides=None=保留该档案既有 config（切回即恢复历史参数）；overrides=dict=写入该档案 config |
| `clear_agent_model_slot_pg(agent_id)` | 改为仅删除 `is_active=TRUE` 行（员工回到跟随全局，**其余模型档案保留**，参数记忆不丢） |
| `resolve_agent_active_model` / `persist_agent_model_slot` / `mirror_agent_model_slot` | 签名与三态语义不变 |

保留约束（不可回退的设计原则）：

- PG 平面任何异常只告警、绝不阻塞业务（静默回退文件平面）；
- SQL 一律参数化 `text()`，禁止列名作值表达式；
- 激活切换两步必须在同一事务（`engine.begin()`）。

## 5. 接口层（app/routers/providers.py，PUT /active scope=agent）

现有 RBAC（agent:manage）与审计（audit_events, agent_model_config.update）不变。
改造点——**文件平面快照必须写目标模型的档案参数**（否则 PG 读失败回退
agent.json 时带的是旧模型参数）：

1. pg 后端下，切模型前先查目标档案的既有 overrides
   （新增 `get_agent_model_profile_pg(agent_id, provider_id, model)`，未配置返回空）；
2. `agent.json active_model` 写入
   `ModelSlotConfig(provider, model, **目标档案 overrides)`
   （json/dual 后端维持现状：沿用旧值，无档案概念）；
3. `persist_agent_model_slot` 调用签名不变；
4. 审计触发条件维持现状：仅当本次携带参数变更（overrides 提供时）落审计，
   extra：before=旧激活档案 overrides，after=本次参数变更集；
   纯模型切换不落审计（模型变化已由档案行与 agent.json 可追溯）。

GET /active：`agent_overrides` = 激活档案的 config（行为不变，数据源自动切换）。

## 6. 前端

本次零改动（ModelConfigEditor 员工域读写的本来就是激活行档案）。
后续可选增强（不在本设计范围）：模型列表给"已配置过的模型"加档案标记。

## 7. 测试计划

- **单测**：store 档案语义（激活切换、档案保留、clear 仅删激活行）；
  路由层文件平面快照写入目标档案参数；
- **集成**（test_provider_model_management.py，一次性员工隔离）：
  配 GLM 参数 → 切 qwen3.8（跟随全局）→ 切回 GLM → 断言参数自动恢复；
- **真实 PG 端到端**：直查 agent_model_slots 断言多档案行 + 唯一激活；
- **重启后端**验证 alembic 0021 修订平滑升级（存量行 is_active=TRUE）；
- 回归：unit/providers、unit/app、vitest ModelSelector、tsc、eslint。

## 8. 明确不做（YAGNI）

- 档案数量上限/清理策略（员工配置过的模型有限，堆积无害）；
- fallback 模型套用档案参数（维持现状：仅 thinking_level）；
- 档案列表 UI。
