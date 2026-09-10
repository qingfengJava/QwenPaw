# 模型能力平面与数字员工使用链路设计

> 日期：2026-09-10　作者：qingfeng　状态：已评审，P0/P1 已实施
> 目标：把已有的模型能力元数据与专业配置能力，从「Settings 全局管理平面」贯通到「数字员工详情页/聊天页的使用平面」，让用户在选模型的现场就能看到能力（上下文窗口、深度思考、视觉）并完成专业配置。

---

## 一、CAPABILITY（能力重述）

**谁能做什么**：管理员/员工使用者在数字员工详情页（或聊天页）选择模型时，能够 ① 直观看到每个模型的关键执行能力（上下文窗口大小、是否支持深度思考、视觉、免费）；② 在使用现场对当前模型做专业参数配置（思考模式开关与档位、上下文窗口档位）；③ 这些配置有明确的生效层级（模型全局能力 vs 员工使用偏好），且界面始终标注参数值的来源（探测 / 自定义 / 默认），避免误配直接影响智能体执行效果。

** outcomes 变化**：从「配置要去 Settings 翻找、选择器只显示模型名」变成「能力所见即所得、配置就地完成、层级语义清晰」。

## 二、CONSTRAINTS（固定约束与不变量）

1. **配置双平面语义（核心不变量）**：
   - **模型能力配置（per-model，全局）**：上下文窗口、思考参数形态（budget/effort）、思考档位与范围、最大输出。影响所有使用该模型的员工。权威存储：`provider_models.config` JSONB（PG）/ providers.json（文件平面），写入走既有 `PUT /api/models/{provider}/models/{model}/config`。
   - **员工使用偏好（per-agent）**：thinking_level（inherit/off/low/medium/high）、fallback 模型、subagent 模型。权威存储：agent.json + agent_model_slots。写入走既有 `updateModelSettings`。
   - 两层**不允许配置同一参数的两个副本**：员工级只配"用多强的思考"，模型级只配"思考参数长什么样、取值范围是什么"。运行时由 `_apply_agent_thinking_level`（provider.py L822-824）统一合并，此机制不变。
2. **能力值可信度分级（展示强制）**：任何能力数值展示必须标注来源——
   `auto_detected`（供应商 API 探测）> `configured`（用户显式覆盖，带"已自定义"标记）> 内置默认（上下文 128K，`context_windows.py DEFAULT_CONTEXT_WINDOW`）。
   禁止把默认值伪装成探测值展示。
3. **参数形态适配不许前端硬编码厂商清单**：思考配置 UI 形态完全由后端下发的 `thinking_param_style`（'budget'→Slider / 'effort'→Select / null→不支持）、`reasoning_effort_options`、`thinking_budget_range` 驱动，模型级可覆盖厂商级（既有回退链：`m.x ?? provider.x`）。新增厂商零前端改动。
4. **思考支持判定唯一来源**：`supports_agent_thinking`（后端派生：DashScope 系为 true，其余查模型元数据）。前端禁止自造 heuristic。
5. **PG 平面绝不阻塞业务**：所有能力读写沿用 provider_store / agent_model_store 的三态语义与静默降级原则，本设计不新增存储平面。

## 三、IMPLEMENTATION CONTRACT（实施契约）

### 3.1 Actors & Surfaces

| Actor | Surface | 动作 |
|---|---|---|
| 管理员 | Settings → 模型管理（已有 ModelConfigEditor） | 配置模型能力（上下文/思考形态/档位/最大输出）——**能力权威配置点** |
| 使用者 | 数字员工详情页 / 聊天页 ModelSelector | 看能力标签 → 选模型 → 就地做员工级偏好配置、跳转模型级能力配置 |

### 3.2 展示层设计（P0，纯前端）

选择器模型项（`.modelItem`）信息架构，对标竞品但按可信度分级增强：

```
┌──────────────────────────────────────────────┐
│ GLM-5.3-Flash  128K        [深度思考] [视觉] ✓ │
│ qwen3.8-max    1M·已自定义  [深度思考]        │
│ qwen3.8-flash  128K·默认    [视觉] [免费]     │
└──────────────────────────────────────────────┘
```

- **上下文 badge**：取值优先级 `max_input_length_auto_detected ?? max_input_length`，格式化（`128K`/`1M`）；来源标注（默认/探测/已自定义）经 badge 的 title 属性与触发按钮能力卡展示，保持列表行视觉干净（实施时的微调：后缀不入 badge 正文，避免每行噪音）。数据在 `GET /api/models` 响应中已全量存在，零后端改动。
- **深度思考 tag**：`model.supports_agent_thinking === true` 时渲染（与现有视觉/免费 tag 同排同款样式）。
- **触发按钮能力卡（Tooltip 升级）**：hover 触发按钮时展示当前模型能力摘要——上下文（含来源）、最大输出、多模态（图/视频）、思考（形态+当前档位）、免费/计费。

### 3.3 使用现场配置链路（P1）

数字员工详情页选中项 hover 出现「配置」入口，分两个明确的层级：

```
模型项 hover → [⚙ 配置]
   ├─ 员工使用偏好（本员工生效）：thinking_level 五档（复用 AgentModelSettings 逻辑）
   └─ 模型能力配置（全局生效，跳转/弹层复用 ModelConfigEditor）：
        上下文窗口：档位单选（默认[探测值] / 200K / 400K / 1M / 自定义≥1000）
        思考模式：  按 thinking_param_style 渲染 Slider(budget) 或 Select(effort)
        最大输出：  数字输入
```

- 弹层**直接复用 `ModelConfigEditor` 组件**（从 Settings 页抽出为共享组件，放到 `components/` 供两处引用），保证管理平面与使用平面的配置表单永不漂移。
- 档位单选的数据源：`thinking_budget_range` 同款思路，为上下文生成建议档位 `[探测值, 200K, 400K, 1M]` ∪ 当前值，保留自定义输入兜底（≥1000 校验已有）。
- 保存后广播既有 `model-switched` / 刷新 `effective_max_input_length`，上下文用量条即时跟随。

### 3.4 数据模型与接口

**零新表、零新接口**。全部复用：

| 既有资产 | 用途 |
|---|---|
| `ModelInfo.max_input_length / _auto_detected / _configured` | 上下文展示与配置 |
| `ModelInfo.thinking_enabled(三态) / thinking_budget / reasoning_effort / thinking_param_style / reasoning_effort_options / thinking_budget_range / supports_agent_thinking` | 思考能力展示与配置 |
| `PUT /models/{p}/models/{m}/config`（max_input_length + generate_kwargs） | 模型能力写入 |
| `agentsApi.updateModelSettings`（thinking_level） | 员工偏好写入 |
| `ActiveModelsInfo.effective_max_input_length` | 用量条联动 |
| PG `provider_models.config` JSONB + `config_overrides` | 持久化与"用户改过"溯源 |

**唯一可选的后端增量（P2）**：`ModelInfo.version: str | None`（对齐竞品"版本: 260420"），模型发现/ catalog 时带出；无值不渲染。

### 3.5 状态与生命周期

- 能力探测：沿用现有 availability/multimodal probe 机制，本设计不新增探测任务。
- 配置生效：模型级配置保存即全局生效（下次请求携带）；员工级 thinking_level 保存后走既有 `schedule_agent_reload` 热加载。
- 冲突裁决：运行时 generate_kwargs 合并顺序 = provider 级 < model 级 < agent thinking level 映射（既有 `_apply_agent_thinking_level`），不变更。

## 四、NON-GOALS（本设计不做）

1. 不做"智能选择"（竞品的平台自动选模型）——可作为后续独立需求。
2. 不做模型版本号管理与多版本并存切换。
3. 不新增任何数据库表/迁移；不改 provider 快照结构（version 字段除外，走既有 manifest 版本机制重投影）。
4. 不做员工级"覆盖模型上下文窗口"——上下文是模型物理能力，员工级只读展示，防止误配压缩阈值。

## 五、OPEN QUESTIONS（已决策，2026-09-10 评审通过）

1. 使用现场的「模型能力配置」入口：**详情页内嵌弹层复用 ModelConfigEditor**，Settings 保留为管理权威页。✅ 已实施
2. 上下文档位清单：**探测值 + 通用档（128K/200K/400K/1M）+ 自定义输入兑底**，不做厂商硬编码。✅ 已实施
3. 免费模型计费提示：**不做**，现有「免费」标签语义已足够，避免展示噪音。

## 六、HANDOFF（执行路径）

- **P0（展示层）**：纯前端，`ModelSelector` item/tag/tooltip + i18n 7 语言；可直接进入实施，验收 = 选择器展示与来源标注正确。
- **P1（配置整合）**：ModelConfigEditor 抽共享 + 档位化上下文选择 + 详情页配置入口；需先过一次交互评审（§五.1）。
- **P2（version 字段）**：后端 ModelInfo 加字段 + discovery 带出 + manifest 提号重投影。
- 测试策略：P0 vitest 快照 + 展示断言；P1 复用 ModelConfigEditor 既有测试 + 新增档位选择测试；后端零改动（P2 除外）故无 pytest 增量（P2 补序列化断言）。
