# SmartWork Console 平台信息架构（Platform IA）

> 平台 IA 重构的设计与实现记录。分 6 个阶段落地，每阶段独立提交并有验证门。

## 一、背景

重构前，Console 侧边栏把「平台功能」和「智能体专属功能」混在一起，靠顶部全局
`AgentSelector` 切换数据域——管理平台视角下不合理。目标形态（对标 StaffDeck）：

- **侧边栏 = 平台级公用管理菜单**（工作台 / 数字员工 / 渠道接入 / 收件箱 / 应用中心 /
  模型配置 / 技能池 + 设置 / 高级 / 管理员组）
- **数字员工详情页 = 员工专属功能容器**（`/agents/:aid/*` 内部 Tab）
- **对话入口收进员工详情**（全局无独立 /chat 入口，旧深链重定向）
- 数据域从「隐式全局 store」转为「显式路由参数 `:aid`」；后端零改动

## 二、目标 IA

### 侧边栏（primary.platform bucket，全部不依赖 :aid）

| 菜单 | 路由 | 说明 |
|------|------|------|
| 工作台 | `/workbench` | 新增：员工卡片网格 + 收件箱摘要 + 快捷入口；`/` 默认落地 |
| 数字员工 | `/agents` | 列表主页（AgentsGalleryPage） |
| 渠道接入 | `/channels` | 平台化：逐员工并行拉取、按员工分组聚合展示（只读） |
| 收件箱 / 应用中心 / 模型配置 / 技能池 | 原样 | 平台域 |
| 设置 / 高级 / 管理员组 | 原样 | — |

### 员工详情页 `/agents/:aid/*`

Tab 即路由，分三组：

- **基本**：概览（index）/ 对话（chat，eager）/ 会话 / 定时任务
- **能力**：文件 / 技能 / 工具 / MCP / ACP
- **运维**：检查点 / 渠道绑定 / 运行配置 / 运行统计 / 心跳

Tab 显隐由员工 `backend_capabilities` 驱动（`capabilities.ts#filterTabsForAgentCapabilities`）：
`workspace_ui === false` 时隐藏工作区类 Tab（files/acp/checkpoints/config/stats，
skills/tools/mcp 按细粒度能力）。

## 三、核心机制

### 1. 「借壳」数据域同步

`AgentDetailLayout` 挂载时执行 **URL :aid → selectedAgent 单向同步**（相同 aid 短路，
避免 `menuRegistry.refresh()` 风暴）。URL 是唯一事实来源；此后所有现有页面 hooks
零改动自动获得正确数据域（底层通道：`buildAuthHeaders` 从 storage 读 selectedAgent →
`X-Agent-Id` header）。

### 2. hooks 渐进参数化（阶段5起）

显式 `agentId` 参数优先于借壳兜底：

```ts
useChannels(agentId?)   // api.listChannels(agentId) → X-Agent-Id header
useSessions(agentId?)   // chatApi.listChats(undefined, agentId)
useCronJobs(agentId?)   // api.listCronJobs(agentId)
```

详情页内组件从 `useParams().aid` 读取并传入；`request()` 层保证调用方显式
`X-Agent-Id` 优先、Authorization 自动补齐。已参数化：channels / sessions /
cron-jobs；其余页面沿用借壳通道（过渡态，不阻塞）。

### 3. 旧路径重定向矩阵

`builtinRoutes.tsx#createAgentScopedRedirect`：`/chat/* /files /sessions /cron-jobs
/skills /tools /mcp /acp /checkpoints /agent-config /agent-stats /heartbeat` →
`/agents/{selectedAgent|default}/<sub>`（保留子路径与 query）。`/channels` 例外：
直达平台渠道页（目标态）。route id 全部保留（component 换 Redirect），
插件 wrap/replace 契约不破坏。

### 4. 兼容性约定

- `MenuLocation` 的 `primary.agentScoped` 类型保留（第三方插件注册兼容），
  渲染时归并进平台菜单尾部「插件」分组
- 壳路由 `/agents/:aid/*` 内部自渲染子 `<Routes>`，registry 扁平契约零破坏
- `lazyImportWithRetry`：glob 查不到时降级为「模块未找到」占位（不再 throw 炸全站，
  典型场景：dev server 运行中新建文件导致 glob 陈旧；生产构建不受影响）

## 四、阶段记录

| 阶段 | 内容 | 提交 |
|------|------|------|
| 0 | 基线冻结（tsc 0 错误 + 107 单测 + 路由清单） | — |
| 1 | 平台级侧边栏重组 | 6cb94fbf |
| 2 | 数字员工列表主页 `/agents` | bbda8c8d |
| 3 | 详情壳 + 借壳迁移 + 重定向矩阵 | c3e4b801 |
| 4 | 概览 Tab + 能力过滤 + 工作台页 | 6a68a3c0 |
| 5 | 渠道平台化 + hooks 参数化 + e2e 基建 | a83c5325 |
| 6 | 死代码清理 + i18n 校对 + 文档 + 回归 | — |

## 五、遗留与 P2

- 概览指标卡（今日会话/好评率）：`chats` 表无 agent 维度、feedback 仅有写入接口，
  现阶段不做假数据；若聚合需求增多，考虑 `GET /agents/{agentId}/summary`
- e2e 套件存在与本次重构无关的历史失配（英文断言 vs 中文渲染、UI 演进后的
  选择器漂移），见 `e2e/E2E_COVERAGE_REPORT.md`，待单独任务治理
- 剩余 hooks（heartbeat 等）按需继续参数化
