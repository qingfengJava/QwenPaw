# QwenPaw 企业级数字员工平台演进方案

## 一、核心诊断结论（三大根因，已逐一验证）

**根因 1：身份信任链断裂——"隔离"在架构上不成立**
- [runtime.py:462-463](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/runtime/runtime.py#L462-L463)：`user_id` 缺省时回退为 `session_id`，身份由客户端请求体自报，服务端无鉴权绑定
- [chats/api.py](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/app/chats/api.py)：`list_chats` 的 `user_id` 是客户端 Query 参数，任何调用方可列举任意用户会话
- [auth.py:10-12](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/app/auth.py#L10-L12)：认证硬编码单用户（"only one account can be registered"），密码为加盐 SHA-256（非 argon2/bcrypt）

**根因 2：记忆系统以 Workspace 为隔离边界，没有"人"的维度**
- [workspace.py:382-389](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/app/workspace/workspace.py#L382-L389)：记忆管理器按 Agent（工作区）维度单例创建
- [reme_light_memory_manager.py:68-82](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/agents/memory/reme_light_memory_manager.py#L68-L82)：ReMe vault = workspace 根目录，session 键 = `sha256(session_id)`，A 用户的提问会检索出 B 用户写入的长期记忆
- [middlewares.py:102-107](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/agents/middlewares.py#L102-L107)：`auto_memory_search` 检索链路不传递 user_id
- scroll `history.db` 行键只有 `session_id + agent_id`；[adbpg_memory_manager.py:46](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/agents/memory/adbpg_memory_manager.py#L46) 硬编码 `_effective_user_id = "shared"`

**根因 3：单进程拓扑假设渗透全栈，文件存储无并发保障**
- [io_utils.py:21-24](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/utils/io_utils.py#L21-L24)：明示"one application worker and one event loop"，路径锁为进程内 `asyncio.Lock`
- [json_repo.py:20-28](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/app/chats/repo/json_repo.py#L20-L28)：`chats.json` 单文件全量读-改-写（O(N) 写入放大），自述"no cross-process lock"；同款 JSON 单文件模式遍布 crons/inbox/checkpoints/token_usage 6+ 处
- [harnesses/runtime.py:44-110](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/harnesses/runtime.py#L44-L110)：同一 provider 全用户共用一个适配器实例；Codex 后端每 workspace 一个 app-server 子进程，`_write_lock` 串行化所有调用——多用户并发互为瓶颈
- [manager.py:37-50](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/app/chats/manager.py#L37-L50)：`ChatManager` 持有全局 `asyncio.Lock`，多用户写串行化

**有利条件（演进接缝已预留，改造成本低于预期）**：
- `BaseChatRepository` ABC 抽象已存在（[repo/base.py:13-187](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/app/chats/repo/base.py#L13-L187)），repo 实例化点全库仅 2 处（[service_factories.py:110](file:///d:/IDEA版java相关知识学习/37-openAi开发/AI案例/QwenPaw/src/qwenpaw/app/workspace/service_factories.py#L110)、`agent_stats/service.py:283`）
- `agent_context.py:37-40` 已预留 `_current_user_id` ContextVar；JWT payload 已带 `sub` + `jti`；会话文件名已内嵌 user_id 维度
- `Runtime` 是 per-request 无状态 8 阶段流水线；`Workspace` = 一个 Agent 的完整独立运行时，天然就是"数字员工"载体
- `governance/`（策略引擎/资源配额/审计）与 `security/secret_store.py`（字段级加密）可直接复用；测试体系经 `temp_workspace` fixture 与存储解耦

---

## 二、数据库选型决策（需求 1）

| 维度 | **PostgreSQL 16+（推荐）** | MySQL 8 | SQLite |
|---|---|---|---|
| JSON 文档（会话/记忆/审计负载天然是 JSON） | **JSONB 可索引、可部分更新、GIN 索引** | JSON 类型功能较弱 | JSON1 只读可用，无路径索引 |
| 向量检索（知识库/记忆） | **pgvector 原生扩展（HNSW），与业务数据同事务同权限域** | 需外挂 Milvus/Qdrant，多一个运维组件 | sqlite-vec 生态不成熟 |
| 数据隔离兜底（需求 2 关键） | **行级安全（RLS）：DB 层强制 owner 过滤，应用层漏判也不越权** | 无等价物 | 无权限概念 |
| 多用户并发写 | MVCC + 行级锁，强 | MVCC + 行级锁，强 | 单写锁，多用户场景致命 |
| 私有化运维 | 单容器即可，docker-compose 与 MySQL 相当 | 国内 DBA 生态最熟 | 零运维但天花板最低 |

**决策：PostgreSQL 16+ + pgvector**。决定性理由：RLS 为"会话与记忆严格隔离"提供数据库级兜底；pgvector 免除独立向量库。通过 SQLAlchemy 2.0 async 保持可移植，若企业强制 MySQL 可降级（需应用层强制过滤 + 独立向量库补偿）。SQLite 保留为开发者单机模式实现，不进企业部署拓扑。

**回答你之前的问题**：PostgreSQL 是数据库本体（与 MySQL 同级）；JSONB 是它独有的字段类型，能存 JSON 文档并建索引——QwenPaw 的会话状态、事件、审计负载本来全是 JSON，用 PostgreSQL 可以"文档入列、关键字段建索引、还能 JOIN 权限表"，MySQL 的 JSON 能力做不到这一点。

---

## 三、目标架构蓝图

```
┌─────────────────────────────────────────────────────────┐
│  员工客户端 (apps/employee: React+Tauri)  管理端 (apps/admin: React Web) │
├─────────────────────────────────────────────────────────┤
│  FastAPI 层：/api/* (员工) + /api/admin/* (管理, require_perm)        │
│  AuthMiddleware(JWT) → 可信 user_id → ContextVar 全链路        │
├─────────────────────────────────────────────────────────┤
│  运行时：MultiAgentManager (数字员工池) → Workspace(=数字员工)      │
│  Runtime 8阶段流水线 + Harness 适配器池 (provider_id, user_id)   │
│  每用户并发闸 + 背压队列 + per-user LLM 配额                    │
├─────────────────────────────────────────────────────────┤
│  数据层 (SQLAlchemy async + Alembic)：                        │
│  PostgreSQL 16 + pgvector                                │
│  ├─ 业务表: users/teams/identity_bindings/chats/sessions/jobs   │
│  ├─ 记忆: memory_items (user_id, scope, agent_id, embedding)  │
│  ├─ 知识库: knowledge_bases/kb_documents/kb_chunks/kb_grants    │
│  └─ 管控: roles/permissions/user_roles/agent_grants/quotas/audit│
│  RLS: 全部用户数据表 ENABLE ROW LEVEL SECURITY                 │
└─────────────────────────────────────────────────────────┘
```

**两条正交主线**：保留 Workspace=Agent（数字员工）这一正确抽象不动，把"人"的维度注入身份、会话、记忆、权限四条链路。

---

## 四、分阶段实施计划

> 每个阶段对应一个 `feature/*` 分支（命名遵循 `.qoder/rules/git-branch-strategy.md`），准出统一要求 `make test`（unit+integration+contract）全绿 + 该阶段新增验证用例通过。

### 阶段 M0 — 存储抽象收口与特性开关（纯重构，零行为变更）
**目标**：把所有文件存储收拢到接口后，埋好切换开关。
1. 抽 `BaseSessionStore`（收口 `SafeJSONSession` 四方法）、`BaseHistoryStore`（收口 scroll history 的 SQLite FTS 实现）；现有文件实现原样保留
2. 新增特性开关 `QWENPAW_STORAGE_BACKEND=json|dual|pg`（默认 `json`）；`service_factories.py:110` 与 `agent_stats/service.py:283` 两处注入点改为工厂函数
3. 为 repo 契约补 contract 测试（`tests/contract/test_chat_repository_contract.py`），参数化覆盖三种 backend
**回滚**：删开关即回现状。**影响面**：零行为变更。

### 阶段 M1 — 多用户账号与会话/记忆严格隔离（需求 2 核心，存储仍是文件）
**目标**：先把"人"立起来，隔离语义在文件时代落地，使 DB 迁移时数据天然带 owner 键。
1. **用户体系**：`auth.json` → `users.json` 多用户模型（复用 `secret_store.py` 字段加密）；密码哈希升级 argon2/bcrypt；存量单用户自动升级为首名 admin；新建 `identity_bindings` 映射（钉钉/Discord/Telegram sender_id → 系统 user_id，未绑定者走现有 `access_control` pending 审批流）
2. **可信身份强制**：`AuthMiddleware` 验签后把 user_id 写入 `request.state.user` + `_current_user_id` ContextVar；**runtime.py:462-463 改为 user_id 只从认证上下文取，请求体自报一律忽略**——先以"警告模式"上线（记录日志不拦截），灰度两周后强制；`chats/api.py` 等全部端点强制叠加当前用户过滤
3. **会话隔离**：`ChatSpec` 增加 `owner_id`（默认 `system` 向后兼容）；会话 JSON 文件名的 user_id 实参从通道身份切换为系统 owner；存量数据一次性回填脚本（dry-run 输出映射清单）
4. **记忆隔离（单点函数改造）**：`_to_reme_session_id` 改为 `hash(owner_id + ":" + session_id)`；ReMe vault 从 workspace 根改为 `workspace_root/users/{owner_id}/`；`middlewares.py` 的 `auto_memory_search` 必传可信 user_id；`builder.py:817-822` 改为按 `(workspace, user_id)` 获取记忆视图（薄代理共享底层连接）；旧 vault 保留只读兜底检索，新记忆写新 vault
5. scroll history 表增 `owner_id` 列（幂等 ALTER，复刻 `audit.py:172` 的 `_migrate_legacy_schema` 模式），FTS 查询强制带 owner 条件
6. `ChatManager` 全局锁降级为 per-owner 锁字典（过渡措施，M2 删）
**准出**：新增隔离 contract 测试——用户 A 的任何 API/记忆/历史检索均不可见用户 B 数据；**回滚**：默认 `system` 用户路径。

### 阶段 M2 — PostgreSQL 双写迁移（需求 1 落地）
**目标**：绞杀者模式切换主存储，全程可秒级回滚。
1. `pyproject.toml` 新增 `sqlalchemy[asyncio]>=2.0`、`asyncpg`、`alembic`；新建 `src/qwenpaw/db/`（engine/base/rls/alembic 迁移）；所有表预留 `tenant_id`（本阶段恒 `"default"`）+ `created_at/updated_at`，避免二次 ALTER
2. 实现 `PgChatRepository`/`PgSessionStore`（会话状态存 JSONB 列，主键 `(tenant_id, channel, owner_id, session_id)`）/`PgHistoryStore`（tsvector 替代 SQLite FTS）；用户数据表启用 RLS POLICY（先 PERMISSIVE 灰度，策略单测覆盖）；连接池 `pool_size=20, max_overflow=40, pool_pre_ping=True`
3. `DualWriteRepository` 装饰器：主写 JSON + 影子写 PG（异步，失败仅告警），内置抽样比对输出不一致指标
4. 离线迁移脚本 `scripts/migrate_storage_to_pg.py`：chats/sessions/scroll/users/audit 全量入库，幂等可重跑，行数校验 + 内容 hash 抽样比对；原文件保留 30 天
5. 开关切 `pg`：读走 PG；观察期后 JSON 写下线归档；`ChatManager` 删锁（DB 事务接管并发）；`audit.py` 同步 sqlite 迁异步（兑现 L104 TODO）；docker-compose 增加 `postgres:16` 服务
**准出**：双写不一致率为 0 且稳定 1 周 + 回滚演练一次（拨回 `json` 功能无损）；**回滚**：开关拨回 `json`（主写从未离开 JSON）。

### 阶段 M3 — Harness 企业级并发升级（需求 3，可与 M2 并行）
**诊断结论：现有 Harness 不能直接支撑企业级多人使用**，但 Runtime 编排层设计良好（per-request 无状态），瓶颈在共享服务层，升级路径对编排层零侵入：
1. **适配器池化**：`harnesses/runtime.py:44-110` 的 `_adapters` 键从 `provider_id` 改为 `(provider_id, user_id)`，配置变更只重建对应键
2. **Codex 子进程池化**：`harnesses/codex/app_server.py` 每用户 1 个子进程、全局上限 N 个，超出进 asyncio 队列背压；空闲 TTL 回收（防内存/句柄耗尽）
3. **每用户并发闸**：新增 `ConcurrencyGate`——user_id 维度信号量（默认每用户 3 并发 turn）+ 全局队列深度上限（超限 429 + Retry-After）
4. **per-user LLM 配额**：复用 `providers/rate_limiter.py` 骨架增加用户维度；`governance/resource_governor.py` 策略上下文注入 user/team
5. **性能优化**：`AgentBuilder.build` 按 `(agent_id, config_mtime, user_role)` 缓存装配结果（消除每请求全量构建）；大 JSON 序列化/记忆检索迁移到专属 `ThreadPoolExecutor`，与文件 I/O 线程池隔离
6. **多副本清障**（仅清障不上线）：进程内可迁移状态（task_tracker 登记、启动去重 Event）逐步外置到 DB，为远期多 worker 扫清障碍
**回滚**：池化键退回 provider 维度 + 并发闸配置关闭。

### 阶段 M4 — RBAC、知识库与 Agent/模型管控（需求 4）
**权限模型（简洁版）**：`permission = resource:action`（如 `agent:use`、`kb:write`、`model:invoke`、`admin:users`）；角色=权限集合（内置 `platform_admin`/`team_lead`/`employee`）；`agent_grants`、`model_grants` 授权表。
1. 新建 `src/qwenpaw/app/rbac/`：roles/permissions/user_roles/teams 表 + FastAPI 依赖 `require_perm()`（插在 AuthMiddleware 之后）；特性开关 `QWENPAW_RBAC_ENFORCE` 灰度逐路由收紧，未标注路由默认放行
2. 治理主体化：`governance/policy.py` 策略引擎增加 `subject(user/team)` 维度（无 subject 的旧策略视为全局，向后兼容）；`audit.py` 事件补 `actor_id`；`runtime/tool_guard.py` 支持"某角色禁用某工具"
3. **Agent（数字员工）管控**：`config.agents.profiles` 迁为 DB 表 + `team_id` 归属 + 模型白名单；文件配置保留为 bootstrap/回退源，DB 为权威；`MultiAgentManager` 启动前查库校验归属
4. **配额与成本**：`quotas(subject_type[user|team|agent], model, window, limit)` 表 + 进程内计数器（拓扑为单 worker，无需 Redis）；token 费用日累计阈值自动熔断（复用 `token_usage/buffer.py` 批量 flush 模式）
5. **企业知识库三级体系**：个人库（M1 已建，user 私有）+ 团队共享库 + 企业公共库；新表 `knowledge_bases/kb_documents/kb_chunks(embedding vector, tsv tsvector)/kb_grants`；摄入走异步任务（PG `SKIP LOCKED` 队列表）；检索实现为 Agent 工具，向量 ANN + `kb_grants` ACL 强制过滤 + tsvector 混合（复用现有 RRF 融合思路）；**记忆与知识库分表不混**——知识库=企业/团队共享语料（授权访问），长期记忆=个人偏好事实（user 私有）
6. 新建 `src/qwenpaw/app/routers/admin/`：用户/团队/角色/授权/配额/模型路由/审计查询 API，与员工 API 物理分目录
**回滚**：`QWENPAW_RBAC_ENFORCE=off`。

### 阶段 M5 — 前端拆分（需求 5，两步走）
**第一步（本阶段，低风险）**：单 SPA 角色分流。
1. `console/src/App.tsx` 的 `AuthGuard` 扩展为 `RoleGuard`（verify 接口返回角色）；新增 `/admin/*` 路由分支（用户/团队/Agent/模型/配额/审计/知识库管理页）
2. `api/modules` 按 `employee/`、`admin/`、`shared/` 三分；`MainLayout/Sidebar` 菜单按角色过滤（展示层过滤，权限强制仍在后端）；员工端保留 Tauri 壳
3. e2e 补角色分流用例 + 双用户隔离用例 + 迁移一致性用例
**第二步（远期，规模需要时）**：物理拆分为 `apps/employee`（保留 Tauri）+ `apps/admin`（纯 Web）monorepo，共享 `packages/api-client` 与 `packages/design`（抽自现有 71 个 API 模块与组件库）；Vite 双构建产物由 FastAPI 分别挂载 `/` 与 `/admin/`。
**回滚**：菜单过滤关闭，全量菜单恢复。

### 阶段 M6（可选扩展，规模触发时再启动）— 水平扩展与观测
仅当单进程垂直扩展确认不足（实测 >200 并发会话饱和）时启动：
- 状态外置 Redis（分布式限流/配额/路径锁，进程内实现保留为降级）；uvicorn 多 worker + Nginx sticky by session_id（SSE 会话亲和）+ Redis pub/sub 断连补发
- OpenTelemetry trace 贯穿 Runtime 8 阶段；Prometheus 指标（在途 turn 数、per-model LLM in-flight、PG 池水位、SSE 连接数）；PG 日备 + WAL 归档替代文件备份

---

## 五、阶段依赖关系

```
M0(抽象+开关) → M1(多用户+隔离打标) → M2(PG双写迁移) → M4(RBAC/知识库/管控) → M5(前端拆分)
                                    ↘ M3(Harness池化，依赖M1的可信user_id，可与M2并行) ↗
M6 为可选扩展，仅依赖 M2 完成
```
- **M1 硬依赖 M0**：隔离打标必须落在收口后的接口上，否则 DB 实现改两遍
- **M2 硬依赖 M1**：PG 表结构的 `owner_id`/RLS 依赖 M1 的数据打标（反向不成立——M1 刻意不依赖 DB，保证独立交付）
- **每阶段回滚独立**，见各阶段回滚预案

---

## 六、风险与缓解（Top 8）

| 风险 | 等级 | 缓解 |
|---|---|---|
| 双写迁移期数据不一致 | 高 | 影子写异步化+失败告警；定时全量对账；读切换前不一致率必须为 0 稳定 1 周；主写从未离开 JSON，回滚零丢失 |
| ReMe 文件存储与 PG 检索内核耦合（reme-ai 的 BM25/file_store 深埋内部） | 高 | M1 先做 1 周 spike 验证 ReMe store 可插拔点；不可行则按 `BaseMemoryManager` 接口自研轻量检索（PG tsvector + pgvector + RRF），接口不变对上层透明 |
| 身份语义变更破坏存量通道（禁止自报 user_id 后旧脚本/匿名会话断裂） | 高 | 警告模式灰度两周再强制；未绑定身份走 pending 审批兜底 |
| RLS 误配导致合法访问被拒 | 高 | 先 PERMISSIVE 灰度 + 应用层过滤为主 RLS 为兜底双保险；集成测试断言"跨用户读取恒为空"；运维角色 BYPASSRLS |
| 记忆 vault 切换导致旧记忆"失忆" | 中 | 旧 vault 保留只读兜底；幂等合并迁移脚本；回滚=vault 根指回 workspace 根 |
| 每用户 Codex 子进程资源膨胀 | 中 | 全局池上限 + 空闲 TTL + 排队背压；超限明确报错而非挂起 |
| 存量数据 owner 回填误判 | 中 | 确定性规则（单用户存量归首 admin）；通道数据按白名单映射人工确认；dry-run 先行 |
| `users.json`→DB 迁移失败锁死登录 | 中 | 复用现有 `_auth_load_error` fail-closed 机制；迁移前自动 `.bak` 备份 |

---

## 七、Rejected Alternatives（已否决方案及理由）

1. **全面迁移 Java/Spring Boot**：Agent 生态（agentscope/ReMe）需重建，工作量数月级，违背"分阶段渐进"决策——用户已明确选择保持 Python
2. **微服务拆分**：单企业私有化 200 并发规模，单进程 asyncio + PG 垂直扩展足够；微服务的分布式复杂度会吞噬交付节奏
3. **MySQL 主库**：无 RLS（隔离只能靠应用层自觉）、向量检索需外挂 Milvus——增加一个运维组件且隔离无 DB 层兜底
4. **多租户 SaaS 架构**：用户已明确单企业私有化；但所有表预留 `tenant_id` 字段，未来升级多租户无需二次 ALTER
5. **M6 的 Redis/多 worker 提前到主线**：对单企业私有化属过度设计，每多一个中间件都是私有化部署的运维成本；降级为规模触发的可选阶段
6. **新建独立管理端仓库做前端拆分**：需重复维护 i18n（5 语言）、71 个 API 模块、26 个 stores、设计系统，回归面翻倍；选择"单 SPA 角色分流 → 远期 monorepo 物理拆分"两步走
7. **DB 先行再补隔离（A/B 方案顺序）**：数据需二次回填 owner 键，且隔离是最关键需求应尽早交付；采纳 C 的"文件时代先打标"顺序
8. **HarnessRuntime 无需改造的结论（C 方案局部观点）**：部分否决——编排层确实无状态可复用，但共享适配器与 Codex 子进程串行化是多用户实测瓶颈，采纳 A 的 (provider, user) 池化方案

---

## 八、关键假设

1. 企业规模按 500~5000 员工、峰值 ~200 并发会话设计；超出此规模触发 M6
2. 保持 Python 技术栈、单企业私有化部署、分阶段渐进演进（用户已确认）
3. 项目规范中 Java/MySQL 特定条款按"精神映射到 Python 技术栈"执行：声明式校验→Pydantic、分层职责→现有 app/services/agents 结构、禁止 N+1/数据单一来源原样遵守
4. 存量单用户数据归首名 admin 是可接受的默认迁移语义
5. ReMe 可插拔性 spike 在 M1 第一周完成，若阻塞则启用自研轻量检索备选路径（不改变 M1 交付目标）
