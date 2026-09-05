# 上游 v2.2.x 功能移植台账（upstream-port-checklist）

> 基线：`feature/platform_ia_refactor_20260831`（93 提交自有改造）
> 工作分支：`feature/upstream_port_20260903`
> 上游参考：`main`（v2.1.0b4 → v2.2.1b1，dev..main = 225 提交）
> 处置桶别：桶1=直取(checkout main 新文件) / 桶2=复制+适配 / 桶3=手工融合(交集文件) / 桶4=综合取舍 / 桶5=删除跟随
> 状态：`[ ]` 待办 / `[x]` 完成 / `[~]` 放弃（附理由）

## M0 基线与安全网
- [x] console tsc --noEmit 0 错误
- [x] console vitest 全量跑完（首轮 1092s 完整通过）
- [x] console npm run build EXIT=0（M9 补验完成：verify-initial-bundle fork 化 env 覆盖，默认 10/3 MiB 不变）
- [x] 后端 pytest unit：providers+governance 663 通过；全量 6845 passed（混合态不作基线，M1 后重跑）
- [x] 切出工作分支 feature/upstream_port_20260903

## M1 后端基础与 Provider 统一体系
上游参考：434574cb(统一provider,174文件)、a04808fa(Volcengine/MiMo)、006b80a6(agent model routing)、3035bfcf(Ollama embedding)、98576088/d07265fd/96255b50(模型发现/输出限制)、13f13a7b2(agent stats口径)、555a458a(token趋势)
- [x] [桶1] src/qwenpaw/providers/ 新文件 ×20（provider_catalog/discovery/persistence/fallback_chat_model/model_error_policy/plugin_provider_registry/modelscope_provider/mimo_provider/stream_progress + data/*.json）
- [x] [桶1] agents/tools/websearch/ ×5（base/anysearch/tavily/factory/__init__）
- [x] [桶1] utils/ 新文件（oauth_callback/timeout/shell_normalization/file_snapshot_cache/image_resize/media_paths）
- [x] [桶1] app/exception_handlers.py、services/fs_name_rules.py、agents/skill_system/runtime_cache.py、backup/manager.py、drivers/handlers/mcp_streamable_http.py、plugins/module_isolation.py
- [x] [桶1] pawapp/（agent/dependency/service）
- [x] [桶1] agents/memory/（reme_embedding/reme_inbox/reme_reranker）
- [x] [桶3] pyproject.toml 依赖升级（agentscope 2.0.7.post1 + reme 0.4.1.11 + auto-fin/daily-paper + mcp + imap-tools；保留自有 argon2/xianwork/pg 组）并已 pip 安装
- [x] [桶3] providers/rate_limiter.py（上游 2 行 info→debug 已叠）
- [x] [桶3] providers/retry_chat_model.py（上游流式治理基底 + 自有 M3 用户槽/M4 门禁叠加，+144 行）
- [x] [桶3] app/routers/providers.py（上游版 + 自有 RBAC PERM_MODEL_MANAGE）
- [x] [桶3] app/routers/config.py（上游版 + 自有 RBAC PERM_ADMIN_PLATFORM）
- [x] [桶3] constant.py（上游版 + 自有 LLM_USER_* 配额常量）、exceptions.py（上游版 + 自有 AgentAccessDeniedException）
- [x] [桶3 追加] providers 目录其余 36 文件直取上游（provider.py/provider_manager.py 瘦身重构）
- [x] [桶3 追加] token_usage/buffer+manager+turn_usage 直取；model_wrapper.py 融合（上游 cache 指标 + 自有 PG sink/M4 配额 hook）
- [x] [桶3 追加] tests/unit/providers + tests/fixtures/providers 直取上游
- [~] [桶4] agent_stats 域：保留自有端点；上游 TC-AGT-06/趋势页随 M2/M9 吸收（顺延）
- [x] 验证：providers+token_usage+memory 814 passed；4 个 token_usage 旧测试失败为已知中间态（待 M2 agent_context 融合后升上游测试版消除）

## M2 多项目目录与运行时融合
上游参考：dd0c65ee(session多项目目录,47文件)、52c33cc2(AgentScope 2.0.7兼容)、c3d06ad9/5072269f(governance安全修复)

**侦察结论（2026-09-03）**：M2 范围内自有改动共 20 文件 +1974/-108 行。关键发现：当前分支在 chats 域有**自有双存储会话层**（6 个自有新文件共 +1105 行）：`chats/dual_session_store.py(+171)`、`chats/factory.py(+105)`、`chats/pg_session_store.py(+213)`、`chats/repo/dual_repo.py(+191)`、`chats/repo/pg_repo.py(+349)`、`chats/session_store.py(+76)`。上游 dd0c65ee 对 chats/api(+294)/manager(+58) 的多项目目录改造与此存储层交织，融合时须保持自有 PG/dual 后端注册链不破坏。

逐文件自有改动量：agent_context.py(+126)、chats/api(+123)、chats/manager(+162)、chats/models(+17)、chats/utils(+54)、routers/console(+196)、workspace×2(+84)、governance policy/tool_adapter(+78)、runtime×2(+131)、modes(+71 估算)、tools 9 文件(小改)。上游无改动的纯自有文件直接保留。

**M2 完成后的消除项**：token_usage 旧测试 4 个失败 → 已消除（升上游测试版后 47 passed）。

- [x] [桶2] config/context.py 上游新增部分、hooks/request_setup/contextvars_hook.py(+415)
- [x] [桶3] app/agent_context.py（上游+98 多项目目录 + 自有+126 用户身份/配额上下文；`git diff --stat main` = +126 验证法）
- [x] [桶3] app/chats/（api/manager/models/utils 融合；自有 6 个存储新文件保留；manager 锁体系 _tx_safe/_write_lock/_owner_lock 随 transactional 后端降级为 _NoopAsyncLock，锁序 owner→write）
- [x] [桶3] runtime/builder.py(+117上游/+119自有)、runtime/runtime.py
- [x] [桶3] governance/policy.py(+165上游/+40自有，ToolCallSpec user_id/roles/teams+subject 规则)、resource_governor.py、tool_adapter.py、detectors.py、tool_registry.py
- [x] [桶3] agents/tools/ 9 文件（多项目目录路径解析接入）+ tools/utils.py 直取（单行截断 artifact continuation_mode）
- [x] [桶3] app/workspace/×2、routers/console.py(+148上游/+196自有)、routers/workspace.py
- [x] [桶3] modes/coding/mixin.py、mission/handler.py、security/tool_guard guardians
- [x] [桶3] app/task_tracker.py（main 基底 on_finished 回调 + 叠自有 get_status_many）、agents/middlewares.py（main 版 + auto_memory_search 叠自有 user_id）
- [x] [决策] routers/workspace.py 不整取 main：上游版混入 M2 范围外 embedding 热更新（依赖 reme 新语义，整取致 30 测试失败）→ HEAD 基底 + dd0c65ee 增量（_resolve_extra_project_root 等 +101/-43 与上游 diff 精确一致）
- [x] [决策] console.py chat_task 后台路径不传身份（request 可能为 None，与 HEAD 语义一致）
- [x] [补齐] M1 漏直取连锁：agents/model_factory.py、utils/message_request_normalizer.py、utils/file_handling.py、utils/image_freezing.py（沿 integration/unit 失败链定位）
- [x] 检查 src/qwenpaw/db 上游变更：M2 范围零变更，无需 alembic 协调
- [x] 验证：QWENPAW_STORAGE_BACKEND=json 下 pytest integration workspace/chats/governance 子集 53 passed + token_usage 升级转绿 47 passed
- [~] [桶4] 上游 groups 分组在 PG 后端持久化暂走默认值（PgChatRepository.load() 未迁移 groups 语义），记录为已知限制，待 M9 一并处理

## M3 前端基建与聊天体验线
上游参考：e08f2e60(artifacts)、2bfe2b2b(复制不含推理)、75b9a810(自动折叠)、0dd1844f(未读指示)、e730e947(长会话性能)、25af0963(流卡死恢复)、51e58258(删desktop reminder)、9382a623(会话分组)
**侦察补充（2026-09-05）**：实际范围超出原 8 提交，纳入 dd0c65ee/d744922f(console 多项目目录前端+目录浏览)、2982502b(媒体下载)、b4807613(mobile composer)、173c8449/f0d28623(chat 组件库 1.1.73-beta.1787638407498)；Hub(f07a6a01) 污染隔离：api/error.ts、ChunkErrorBoundary、scripts/Hub 耦合部分归 M6。

- [x] [桶1] package.json 依赖升级（main 基底 + 自有 diff devDep 保留）+ scripts 2 个纯 Node 构建辅助脚本提前直取 + npm install 重生成 lock
- [x] [桶1] 86 文件直取（39 新：SessionGroupDnd/Header/DateHeader、useChatGroups 等 4 hooks、ResponseArtifactList、LazyAccordion、MediaDownload、loadSessionProjectDirs、ApprovalToggle、chatGroups/messageDisplay/longChatPerformance/sessionAttentionStore 等；47 改：ChatSessionDrawer 族、SessionItem、files-workspace 族、sessionListStore、messageScroll、SessionProjectDirectory 族、useIsMobile、ChatHeaderTitle、ChatActionGroup、HarnessApprovalToggle 等）
- [x] [桶1 追加] tsc 断链驱动直取 10 个上游依赖：chatInputDraft/backgroundQueueRegistry/fallbackNotice/turnUsageStore/sessionTime/profileFileSelection/memoryTree/turnUsage/ApprovalCard×2/console.ts（均自有无改动验证）
- [x] [桶3] api/modules/chat.ts(.test)（main 基底含 include_app_owned + 自有 agentId/X-Agent-Id）
- [x] [桶3] pages/Chat/index.tsx（main 基底+自有 AI 调优预填 21 行）、HostBubbles.tsx(+MessageFeedbackBar)、styles/layout.css、LoopModeSelector.tsx(antd classNames API)
- [x] [桶3] locales ×7 深合并（脚本：main 基底 key 序保持 + 自有 key 追加；zh 3 处品牌冲突保留自有：渠道接入/应用中心/模型配置）
- [x] [桶3] layouts/index.module.less（main 基底 + 自有主题色 #18181a×26 + header 64px + logoWrapper 移动端 + sider 分隔线）
- [x] [桶5] 删 utils/desktopModeHint×2 + Sidebar.tsx（保留自有 IA 基底）清理 Tour/desktopModeHint 引用 43 行
- [x] [决策] Sidebar.tsx/SidebarSessionList 不取上游：自有菜单驱动 IA 与上游会话列表架构分叉，SidebarSessionList 维持删除状态；上游会话分组由直取的 ChatSessionDrawer 消费
- [x] [决策] sessionApi/index.ts 含 Hub 改动仅 type-import 无害直取
- [x] [测试] Sidebar.test.tsx 按当前 IA 重写断言（core.app-center+primary.platform；M4 改名时同步回 core.marketplace）；iconArrangement.test.ts 断言对齐自有 osApps（core.agents/Digital Employees）
- [x] [治本] .gitattributes 补 console/src/**/*.txt eol=lf：replay fixture 被 Windows smudge 成 CRLF 致 `?raw` 解析失败（SSE `\n\n` 分割失效），工作区文件已同步修复
- [x] 验证：tsc -b --noEmit 0 错误 + vitest 全量（首轮 1974 passed/4 failed → 修复后第二轮 1981 passed/2 failed；剩余 2 个为 AgentLoopCard.render 渲染测试在全量并发下超 15s 默认超时，属 Windows 本机资源竞争，单独跑稳定通过，上游文件保持逐字节一致不改动）

## M4 Marketplace 统一与 IA 挂接
上游参考：9bce6fb1(统一marketplace)、c1728668/35d66456(os market已安装标记)、461e65fa(装后免刷新)、5d4c9a34(dark mode+Extension改名)、d376ec5c(skill自动更新)、76ee1381(skill CLI重构)、f31c3594(skill文件缓存)
**侦察修正（2026-09-05）**：AgentSelector 组件及样式在自有分支已删除，上游 +10/-10 不跟随；osApps/SettingsApp 等中途被改回净零的提交以 MB..main 终态判定；台账点名的 adminMenu.test/osPluginStore.test 为预估失配，实际为 plugins/registry/__tests__/*（已随 direct 同步）；locales ×7 无需处理（M3 深合并基底为 main 终态已含 M4 key）。

- [x] [桶1] 77+2 文件直取：pages/Market 新页面族、AppCenter 重构族、PluginManager 新组件族、Settings/Market、SkillPool、Agent/Skills、os/AppStore、useOsAppMarket、osCleanup、pawapp-sdk 全目录升级（+1912 行，scope/ui/dependencies/scoping.test 新文件）、registry __tests__×3、utils（marketAppState/skillChangeEvents/skill）、useEdgeReveal（shouldRevealDock）
- [x] [桶3] builtinMenu.ts：core.app-center→core.marketplace（label nav.marketplace/Extension）+ 删 core.plugin-manager 菜单项与 SparkPluginLine
- [x] [桶3] builtinRoutes.tsx：/apps→/market 路由（Market 页）+ 删 /plugin-manager 路由，保留 /apps/:appId deep-link
- [x] [桶3] os/osApps.ts（自有数据基底 + 叠 MARKETPLACE_APP，保留自有 RETIRED_OS_APP_IDS）、os/SettingsApp.tsx（删 plugin-manager 项）、os/osRouteMap.ts（删映射）
- [x] [桶3] os/DesktopOS.tsx：main 基底（dock reveal/免刷新卸载）+ 叠自有 RETIRED one-shot 清理与 initialPath 传参，回退不存在的 agentVisibility 引用
- [x] [桶3] layouts/Sidebar.tsx：自有 IA 基底 + SIMPLE_MODE_WHITELIST 同步 core.marketplace（上游仅 1 行）；SidebarSessionList 维持删除（M3 决策延续）
- [x] 测试更新：Sidebar.test 断言回 core.marketplace（M3 待办闭环）、osRouteMap.test fixture、osAppRegistry.test 叠 MARKETPLACE_APP 断言；AppCenter accent 叠自有主题色 #18181a
- [x] 验证：tsc -b --noEmit 0 错误 + vitest M4 域回归 108 文件 843 tests 全绿（os/layouts/plugins/api/Market/AppCenter/PluginManager/SkillPool/Skills/utils）
- [~] [桶4] 浏览器实测顺延 M9 全面回归（与 M3 同口径）；AgentSelector 样式上游小改不跟随（组件已删）

## M5 模型路由前端（依赖 M1）
上游参考：434574cb(console部分,M1遗漏)、006b80a6(agent model routing settings)、81be8cc4(model selector样式)
**侦察修正（2026-09-05）**：实际范围远超原 2 提交——M1 仅直取了 434574cb 后端部分，其 console 前端（ModelSelector 新组件族 8 文件、Settings/Models 重构、api modules/types agent(s)/provider）全部遗漏，本轮一并补齐；后端 config.py 的 FallbackPolicyConfig 与 routers/agents.py 的 CreateAgentRequest 三字段同为 M1 漏网；Settings/Agents/index.tsx 已被自有平台 IA 删除（AgentsGalleryPage 替代），其 model routing 增量改移植到 AgentsGalleryPage；locales ×6 经 3-way 复核 M3 深合并基底已含全部 M5 key，免处理；上游对旧 provider key 的批量删除顺延 M9（避免破坏 M1 遗漏未升级组件引用）。

- [x] [桶1] 45 文件直取：ModelSelector 全目录 12（AgentModelSettings/CandidateModelSection/modelSelectorApi/modelSelectorModels/useModelSelectorData 及测试）、Settings/Models（ModelCapabilityTags/ModelConfigEditor 新 modal、RemoteModelManageModal、ModelsSection、useProviders、index.module.less）、api modules/types（agents/provider/agent 及测试）、AgentModal + mailDomains 族×3、Chat 测试×5（ChatPage/HarnessModelSelector.test/fallbackNotice.test/turnUsage.test/turnUsageStore.test）、providerPlatformLocales.test
- [x] [桶1 追加] tsc 断链驱动直取 13：ReMe 三件套（ReMeLightMemoryCard/ReMeStatusModal + test）、EmbeddingModelCard、useEmbeddingVerification、embeddingUtils、memoryMaintenanceContext、useReMeRuntimeStatus、embeddingVerificationStore（新）、api agent.ts/types/agent.ts/agent.test.ts
- [x] [桶3] src/qwenpaw/config/config.py（FallbackPolicyConfig 类 + AgentProfileConfig 三字段）、app/routers/agents.py（CreateAgentRequest 三字段 + create_agent 传参，M1 漏网 8 行）
- [x] [桶3] pages/Agents/AgentsGalleryPage.tsx 叠上游 model routing 6 处（ModelSettingsDraft/state/handleCreate 重置/createAgent 传参/AgentModal 3 props）
- [x] [桶3] HarnessModelSelector.tsx（updateBackendSettings 显式 null，保留自有 antd classNames 新 API）、Settings/Models/index.tsx（manageModels URL 参数分支，保留 destroyOnHidden）、Settings/Agents/index.module.less（插 .agentRoutingFormItem）、Agent/Config/index.tsx（main 版 + 恢复自有 destroyOnHidden 1 行）
- [x] [桶1] tests/integration/test_multi_agent_lifecycle.py（含新 test_create_agent_persists_model_routing）
- [~] [桶4] 浏览器模型切换实测顺延 M9 全面回归（与 M3/M4 同口径）
- [x] 验证：tsc -b --noEmit 0 错误 + vitest M5 域 28 文件 278 tests（277 passed，AgentLoopCard.render 1 个为已知 Windows 并发超时，单独跑 4/4 通过）；后端 pytest：lifecycle 23 passed（含新 routing 测试）+ agents_router/config/agent_management 140 passed

## M6 Hub 自托管多用户（依赖 M3）
上游参考：f07a6a01(self-hosted Hub)、4e2e9ae2/a756623c(agentscope升级)
**侦察修正（2026-09-05）**：hub/ 实际 24 文件（台账 ×22 失配）；agentscope 升级的 pyproject/venv（2.0.7.post1）与 builder.py max_image_num 适配已在 M1/M2 提前就位，本批仅 __version__.py 版本号；4e2e 的 local_workspace/capping_formatter/pruning 测试 SAME-ALREADY 免处理；上游 app/auth.py 为单用户设计与自有 M1 多用户体系全面冲突 → 仅叠 RuntimeBoundaryMiddleware（自有 users.json/argon2id 全保留）；Sidebar/builtinRoutes/main.tsx 上游混入另一条 IA 演化路线不跟随，只摘 Hub 专属增量；less 的 accountIdentity/runtimeRecovery 已提前在位免处理；locales ×7 hub key 族 M3 基底已含免处理；website ×8/.github ×2 顺延 M9、deploy/Dockerfile 顺延 M8；tests/unit/cli/test_hub_cmd.py 台账预估失配不存在；pyproject hub extra（docker）M1 已带入但 venv 未装，本批 pip install docker 7.2.0。

- [x] [桶1] 75 文件直取：src/qwenpaw/hub/ ×24、cli/hub_cmd.py、console auth/gate.ts、api/modules/hub.ts、pages/Hub/ ×4、pages/Login/ 重设计、api/error.ts、ChunkErrorBoundary + test、PluginContext idle 初始化、scripts/precompress-assets + verify-initial-bundle、oauth 回调链路、tests/unit/hub ×15 + runtime_boundary/oauth/client_ip
- [x] [桶3] App.tsx（上游 BackendModeRouter/RuntimeAvailabilityGuard 骨架 + 自有 StaffDeck tokens/authStore identity 叠层）、api/auth.ts（叠 mode 等三字段 + responseErrorMessage，保留自有 verify/VerifyResponse）、Sidebar（自有基底叠 Hub 六处）、MainLayout（hubMode + canRestartRuntime，保留 workbench fallback）、index.html（boot 启动屏，保留品牌 title）、vite.config（charts/editor vendor）、main.tsx（hostSdk/registerBuiltinCards 移交 PluginContext idle）、app/auth.py + _app.py（RuntimeBoundaryMiddleware）
- [x] [桶4] Hub=部署接入层 与 RBAC=应用权限层并存落地：标准模式走自有 authApi.verify → authStore identity（M1/M4 RBAC 过滤）；hub 模式（res.mode=="hub"）gate 放行 + hubApi.me/changePassword/restartOwnRuntime 接管账户与 runtime 管理；Login 直取上游版（bootstrap/免责声明 Modal），identity 由 App.tsx AuthGuard 统一衔接 authStore
- [x] 检查 src/qwenpaw/db 上游变更：f07a/4e2e/a756 均未触及 db/（Hub 自带 sqlite database.py，无 Alembic 变更）
- [~] [桶4] 浏览器登录→桌面全流程实测顺延 M9 全面回归（与 M3-M5 同口径）
- [x] 验证：tsc -b --noEmit 0 错误；vitest M6 域 10 文件 139 tests 全绿（hub/gate/ChunkErrorBoundary/Hub 页 ×13/Login/hubLocales/TabbedEditor/layouts/sessionApi/MCP）；pytest：tests/unit/hub 133 passed/4 skipped（process_isolation 2 个 linux 挂载断言失败为 M7 已知中间态：packages/qwenpawmail-mcp 未检出致 editable 挂载集缺路径）+ auth/oauth 33 + users/sandbox 257 + lifecycle 23；Hub e2e 环境门控 skip 预期

## 基线记录（M6 实测）
- console tsc -b --noEmit：0 错误（仅 1 处 clearAuthToken 未使用，职责已移入 gate.ts）
- console vitest M6 域：10 文件 139 tests 全绿（8 核心域 70 + layouts 54 + sessionApi/MCP 15）
- 后端 pytest（QWENPAW_STORAGE_BACKEND=json）：tests/unit/hub + runtime_boundary 133 passed/4 skipped/2 failed（process_isolation linux 挂载断言，M7 已知中间态）；auth+oauth 33 passed；users+auth_users+sandbox 257 passed；lifecycle 23 passed（RuntimeBoundaryMiddleware 叠加零破坏）；tests/e2e/test_hub_local_runtime skip（环境门控）
- 架构决策：Hub 与自有 RBAC 并存——app/auth.py 保留 M1 多用户体系（users.json/argon2id/UserStore/XianWork share 前缀），仅叠 RuntimeBoundaryMiddleware（QWENPAW_RUNTIME_INTERNAL_TOKEN 环境变量 + x-qwenpaw-runtime-token 头，websocket 4401/HTTP 401）；前端 resolveAuthGate 负责 token 放行，authStore identity 由 AuthGuard verify 后写入，两套体系在标准/hub 双模式下均可用
- 依赖：venv 补装 docker 7.2.0（pyproject hub extra M1 已带入未安装）
- 提交：c4fc387c(M6桶1,75文件,+18711/-145) → e7ed0351(M6桶3,9文件,+528/-118) → 本提交(M6台账)

## M7 mailbox 邮件族（可并行）
上游参考：f3046db6(邮件助手)、e3b61d71(inbox降噪)、67d5eff7(文档)、4f659968(CLI configurators)、fbca3562(desktop打包mail MCP)
- [x] [桶1] app/mail/ ×4、routers/mail_access_control.py、agents/tools/mail_f1_tool.py、skills/mailbox-en|zh/、md_files 新增、packages/qwenpawmail-mcp/
- [x] [桶1] console api/modules/mailAccessControl.ts
- [x] [桶3] pages/Inbox/ 融合
- [x] 验证：pytest tests/unit/app/mail + Inbox 冒烟（实测：全域 292 passed + mail/inbox/workspace 328 passed，详见下方落地记录）

## 落地记录（M7 实测）
- 验证：tsc --noEmit 0 错误；vitest Inbox 域 20 tests 全程（useInboxData 18 + inboxEvents 2）；pytest 全域（config/mail_validation/mail_access_control/reme_inbox/app_inbox/cli_channels/tauri/setup_utils/agents_router）292 passed 全绿；mail+inbox+workspace 328 passed；process_isolation 11 passed/3 skipped/1 failed——唯一失败 test_linux_command_mounts_python_base_prefix 为 Windows symlink 特权缺失（WinError 1314），环境性非缺陷；tests/unit/agents/memory 全量存在慢测试超时，与 M7 改动无关（目标文件 13 passed）
- 桶3 融合：config.py（mail 类族+凭据三层存储+migrate/hydrate+thinking_level+pending_reindex_embedding_config 字段+load_agent_config 深拷贝语义+mutate_agent_config）；agents.py（mail 驱动卡/回滚/验证函数族 + CreateAgentRequest.mail + create/copy/update mail 集成）；service_factories.py（qwenpawmail card 升级 + create_mail_monitor_service 3参 publish 协议）；workspace.py（mail_monitor 注册）；reme_light_memory_manager.py（inbox 推送委托化）；AgentsGalleryPage.tsx（mail 三块映射）
- 意外追平（M7 直取 main 终态测试拉出）：434574cb（#6302 unify agent controls）在 agents.py 的原语重构——mutate_config/mutate_agent_config 导入、reorder/set_pinned/delete/toggle 原语化、get_agent/update_backend_settings/copy_agent off-event-loop、_persist_created_agent/_resolve_custom_workspace_dir/_prepare_copied_workspace 新增、AgentModelSettingsPatch + PATCH /model-settings 端点、AutoMemoryRuntimeStatus/RecentMemoryRuntimeStatus 对齐 main 精简、memory reindex scope 参数 + undo 端点 + embedding_reindex_required/undo_available 字段、runtime_status 组装；reme_light_memory_manager.py 的 rebuild_index(scope)/undo_embedding_reindex 薄委托（ReMeEmbedding service 接线）+ inbox 推送委托 reme_inbox.emit_job_result（auto_fin/auto_dream 终态语义）
- 顺延确认：deploy/Dockerfile 意外暂存已撤回（M8 桶3，含自有 xianwork 阶段不可抹）；Auto Fin 主体（manager auto_fin 方法/ReMe 0.4.1.11）顺延后续里程碑；tests/unit/agents/memory 全量慢测试待 M9 全面回归时处理

## M8 通道修复 + creator/DataPaw + 桌面打包（可并行）
上游参考：2f621f44/c19801d1(matrix)、5cf8d14f(qq)、c4326313/58ebb9a0(dingtalk)、59f2849c(onebot)、6d8217d3(console channel)、673091e6(yuanbao)、29473338(xiaoyi)、63799c1f/77c2e5f8(creator)、6b3dc19d(DataPaw)+6dd0dd23(改名qwenpaw-data)、f1879477/d3efdf2e/72c2b2b3/2ce39f81/61ffff54/9a88d2ec/b2f84a95(桌面修复)
**侦察修正（2026-09-05）**：实际 20 提交（台账漏列 6dd0dd23 datapaw→qwenpaw-data 改名+PyPI runtime）；549 变更文件三桶筛查：TAKE 452（含 own无改动 ×大量——M2 融合基底即 main 终态故 6b3dc19d 后端增量多已就位）/MERGE 25/SAME 32/GONE 57（creator 旧测试跟随删）/EVAP 7（datapaw 旧路径改名蒸发免处理）；base.py 的 HEAD..main 307 行差异来自 434574cb 遗漏+37e7f647(#6767 不在任何批次)+0dd1844f(M3 后端遗漏)，M8 一并追平；AgentSelector 复活不跟随（M4 决策延续），但其新增依赖 agentVisibility.ts 直取供 MissionControl/SpacesPanel/DesktopOS 使用；locales ×7 免处理（M3 深合并基底已含）；creator 两提交零越界触碰。

- [x] [桶3] app/channels/base.py（fallback notice 方法族+流内调用×3+send_event 后×1、on_finished=mark_chat_finished、sanitize_log_value×4、OnReplySent→Awaitable+await×2；自有 owner身份/背压/RBAC 异常块全保留）+ console/channel.py（await on_reply_sent）+ channels/manager.py（OnLastDispatch Awaitable）+ dingtalk/channel.py（main 基底+自有 _routing_user_id 叠层；连锁直取 7f825219 的 content_utils/constants 台账漏列）+ dingtalk/console 通道 config.py 字段（OneBot media_dir/media_download_max_mb、Console keep_console_enabled、Matrix/DingTalk share_session_in_group）
- [x] [桶1] app/channels/onebot/media.py + matrix/qq/xiaoyi/yuanbao channel + qq/cards/tool_guard（own无改动）
- [x] [桶1] plugins/apps/qwenpaw-creator/（目录覆盖，513 文件）+ qwenpaw-data/（58 文件终态直取，等价 6b3dc19d+6dd0dd23）+ plugins/bundle/computer-use/（7f825219 之外无变更，核对后免处理）+ 桶5 删 creator 旧测试 59 个
- [x] [桶3] console/src-tauri 直取 webview_recovery.rs/Cargo（WebView2 恢复 f1879477）+ tauri/entry.py+d3efdf2e PyInstaller hook + scripts/verify/desktop_verify.py；桶3 DesktopOS.tsx 叠 isAgentAvailableInChat 过滤；stop-backend-sidecar.ps1 核对：上游未删，保留
- [x] [桶3] 桌面修复族：2ce39f81 杀软（sandbox/windows_unelevated_sandbox+Security 页面族直取+routers/config.py deny-paths 端点已在）、61ffff54 CRLF（write_bytes 已在）、9a88d2ec envs 原子写、b2f84a95 截图目录、test_entry.py +41（freeze_support abort 测试）；agents.py 补 AgentSummary.managed_by_app/available_in_chat（6b3dc19d）
- [x] 验证：tsc -b --noEmit 0 错误；pytest channels+pack+pawapp+tauri/config_router/chats 1939 passed（config_router 2 个 M1 遗留中间态正式转绿）+ DingTalkConfig 补字段后 dingtalk 14 passed；integration channels_config+dingtalk_mock_im 11 passed/1 failed（P2 long_reply 为 mock-IM 链路时序，实现 3500 分支已就位，顺延 M9）；pawapp symlink 1 failed 为 WinError 1314 环境性；creator tests 子集验证见下

## 落地记录（M8 实测）
- 侦察陷阱三则：①提交集含 datapaw 路径但 main 终态已改名 qwenpaw-data，需 EVAP 桶识别蒸发文件+终态路径替换；②git checkout main -- 目录不删除 HEAD 独有文件，GONE 需显式 git rm（漏网 2 个 creator 旧测试靠 plugins 域与 main 残差扫描捕荻）；③PowerShell `>` 重定向 UTF-16 污染文件再次触发（m8_recon 输出），侦察脚本一律内部 open/write。
- M2 融合基底即 main 终态的结论多次验证：6b3dc19d 对 retry_chat_model/builder/runtime/model_wrapper/chats api+utils 的后端增量在 HEAD 已就位，HEAD..main 残差全为自有方向，MERGE≠需融合；甄别方法=逐 hunk plus>minus 统计+读上下文定性。
- integration app 子进程不继承 pytest pythonpath，中文路径下 qwenpawmail_mcp 不可导入 → conftest.py env 段显式注入 PYTHONPATH（packages/qwenpawmail-mcp/src）。
- 桌面修复族的 7 提交共 33 路径中 6 处已在 HEAD（M1/M2/M7 直取 main 终态时顺带入），真正新融合 12 文件。
- 顺延：Auto Fin 主体继续顺延；tests/integration 缺失 132 文件归 M9 测试扩容（本批仅补 mock_dingtalk_im.py/_coverage_app_main.py 供 M8 通道测试闭合）；deploy/Dockerfile 待桶3 最后一项（M8 收尾或 M9 前置）。

## M9 website/docs/CI + 测试扩容 + 全面回归
- [x] [桶1] website/docs 归位：website 73 路径直取（plugins.en/zh.md 保留自有——上游删 primary.platform location 值属自有平台 IA 功能）；docs/ 侦察为空（7 个自有设计文档 main 无，免处理）
- [x] .github/ 逐文件甄别：16+1 全 upstream-only 直取（blob 谱系分类），自有 3 workflows 未受影响
- [x] tests/ 上游新测试按域归位（integration ×132 / unit ×130 直取）；own-touched 7 个保留（conftest PYTHONPATH 注入、test_console_channel、test_utils/test_policy/test_agent_model 融合版、test_runtime、test_entry）；GONE test_coding_project.py 显式删；决策删自有-only test_config_path_isolation.py（M2 动态读取已回退，前提消失）
- [x] 交集测试融合：chats/test_api.py main 终态直调适配（list_chats request 可选参数、tracker get_status_many hasattr 回退、get_chat owned 直调回退 mgr 查询）；tauri/test_entry.py 已在 M8 融合
- [x] 实现面终态收拢：src 64 upstream-only 直取 + config.py/utils.py 反转融合 + media_token_estimate 补齐 + backup/skill_system 域连锁 + Auto Fin 主体（auto_fin/cron/热更新委托化）+ provider 启动 offload to_thread + embedding 热更新事务对齐（force_reload/restores_indexed_space/run_async_to_completion）+ agents.py managed_by_app 组装 + multi_agent_manager main 基底叠自有 LRU/TTL + scroll manager _raise_if_summary_interrupted 补齐 + agent_stats service 直取 + models.py 融合（LlmToolDaily + 自有 brief）
- [x] 全面回归：pytest unit 分域批跑 ~7500 passed（失败全定性：symlink WinError 1314 ×7 / checkpoints 时序 ×3 实现测试均 main 零 diff / 其余修复转绿）；tsc 0 错误；vitest 全量 2243 passed/4 并发超时（单跑全绿）；npm build EXIT=0；e2e ui_smoke 4 passed；浏览器端到端冒烟 PASS（SPA 渲染 0 console error）
- [x] 台账勾销完毕，PR：upstream_port → dev，随后 platform_ia_refactor → dev（push 由用户手动执行）

## 落地记录（M9 实测）
- 残差甄别方法升级：桶1 直取后全仓库三档扫描（src / scripts+e2e+plugins / console），共捕犾 upstream-only 落后 197 文件（src 64 + 全仓 44 + console 89）——桶1 目录级直取无法覆盖跨目录引用链，tsc 断链与 pytest import 错误是两大驱动信号。
- 反转融合二例：config.py（87 行 own-only 残差全为手工适配版与 main 原版实现差异，非真自有功能）与 utils.py（M2 动态读取决策回退为 main 静态绑定）直接 checkout main 终态；判定标准=自有向残差是否承载可辨识的自有功能语义。
- FastAPI 签名陷阱：`request: Request | None = None` 触发 FastAPIError（Union 被误判为查询参数），纯 `Request = None` 才走 DI 注入分支且允许直调缺省——自有认证参数与上游测试直调共存的标准解法。
- pytest-timeout 在 Windows 的 asyncio 挂起测试上 dump 栈后整个 run 中断且丢弃统计输出：全量单进程跑不可行，分域 subprocess 批跑（timeout=150/1500s 双层）是本仓库唯一可靠的全量回归形态。
- multi_agent_manager 挂起根因：HEAD 保留自有 LRU/TTL 但缺 main 的 reload guard（note_agent_config_changed 代际检查），测试 build_gate 永挂 → 以 main 为基底重叠自有回收器；scroll manager 同型：缺 _raise_if_summary_interrupted 致取消传播测试失败。
- 环境性失败终态定性：symlink WinError 1314 ×7（cli/security/pawapp/plugins/hub）+ checkpoints 取消传播时序 ×3（实现与测试均与 main 零 diff，Windows 调度敏感）+ vitest 并发超时 ×4（单跑全绿），均不改动上游文件。
- 陷阱：pip install -e 在中文路径仓库生成 UTF-8 .pth，site.py 以 GBK 读取致整个 venv Python 启动崩溃——删除该 .pth 恢复，qwenpawmail_mcp 改用 PYTHONPATH 注入（与 tests/conftest 同法）。
- e2e 冒烟链路：QWENPAW_WORKING_DIR 隔离目录 + `python -m qwenpaw app --port 7077`（PYTHONPATH 注入 qwenpawmail-mcp/src）+ Playwright ui_smoke 4 passed + 浏览器加载冒烟（v2.2.1b1 + 自有 IA 菜单完整渲染）。
- 顺延确认：M5 locales 旧 provider key 清理已闭合（246 stale 全自有 key 无残留）；M2 known limitation（PG 后端 chats groups 默认值）维持已知限制。

## 基线记录（M0/M1 实测）
- console tsc --noEmit：0 错误
- console vitest：完整跑完（Duration 1092s，npm run test 为 watch 模式须用 `npm run test:run`）
- pytest tests/unit/providers+governance（基线）：663 passed
- M1 验收（QWENPAW_STORAGE_BACKEND=json）：providers 全绿；agents+app 2181 passed / 12 failed → 其中 scroll 簇 5 个为本机 .env PG 后端泄漏（设 json 后 45/45 通过，非回归）；config_router 2 个为上游 console-channel-keep-enabled 行为待 M8；token_usage 4 个旧测试待 M2 升级
- agentscope 已升 2.0.7.post1（含 model-ollama extra）、reme-ai 0.4.1.11、reme-auto-fin/daily-paper 0.1.2、mcp、imap-tools 1.15.0 已安装
- 提交：a90b452c(M1桶1) → 96d2011b(M1桶3) → 1a666812(M1收尾)

## 基线记录（M2 实测，QWENPAW_STORAGE_BACKEND=json）
- import 冒烟：32/32 模块通过（.venv python，agentscope 2.0.7.post1）
- token_usage：47 passed（M1 中间态消除）
- governance + tool_guard：755 passed
- chats/routers 域：461 passed（config_router 2 个为已知 M8 中间态）
- agents/runtime：1407 passed 全绿
- integration workspace/chats/governance 子集：53 passed
- workspace：52 passed（test_agent_model patch 目标改 qwenpaw.constant.WORKING_DIR 配合 M1 动态读取语义）
- unit 全量：7310 passed / 21 failed，定性：config_router 2（M8 中间态）+ checkpoint 2（三版本零改动的继承性环境时序，M9 处理）+ cli_task 2 / skill_scanner 5（WinError 1314 symlink 特权 + GBK 编码，Windows 环境限制非移植回归）
- 已知限制：PG 后端 chats groups 分组持久化走默认值
- 提交：bcec12a3(M2桶1,55文件) → ee18363b(M2桶3,21文件) → 100cfda4(M2台账)

## 基线记录（M3 实测）
- console tsc -b --noEmit：0 错误（含 96 文件移植后的断链驱动修复）
- console vitest 全量：第二轮 1981 passed / 2 failed（245 文件，Duration 915s）；2 个失败为 AgentLoopCard.render 渲染测试全量并发下超 15s 默认超时，单独跑稳定通过，属 Windows 本机资源竞争非移植回归，上游文件保持逐字节一致不改动
- 首轮 4 个失败全部定位：iconArrangement×2（断言对齐自有 osApps：core.agents/Digital Employees）、replaySdkIntegration（fixture 被 git smudge 成 CRLF 致 `?raw` 解析失败，.gitattributes 补 console/src/**/*.txt eol=lf 治本）、AgentLoopCard（超时，同上）
- 依赖：@agentscope-ai/chat 1.1.73-beta.1787638407498、antd 5.29.3、vite 6.4.1 已装，npm install 增量 +25/-1/1
- 待办顺延：api/error.ts 与 ChunkErrorBoundary 归 M6（Hub）；Sidebar.test 断言中 core.app-center 待 M4 改名时同步回 core.marketplace；浏览器冒烟随 M9 全面回归执行
- 提交：6fc32950(M3桶1,109文件) → b4269271(M3桶3,21文件) → 52abcdb7(M3台账)

## 基线记录（M4 实测）
- console tsc -b --noEmit：0 错误（pawapp-sdk 全目录升级后断链修复）
- console vitest M4 域回归：108 文件 843 tests 全绿（os/layouts/plugins/api/Market/AppCenter/PluginManager/SkillPool/Skills/utils）
- M4 净变化精简：86 个变更文件中 9 个中途改回净零（AgentSelector.less/osApps.ts 中间态等），真融合仅 11 文件 +70/-58
- pawapp-sdk 升级：api/host/types/index/task 大改 + scope/ui/dependencies/scoping.test 新文件（+1912/-81），自有无改动全目录直取
- plugin-manager 入口全链路移除（菜单/路由/os 设置项/route-map），页面文件保留（跟随上游统一 marketplace）
- 提交：ceb06449(M4桶1,79文件) → 0f8a1f83(M4桶3,11文件) → 本提交(M4台账)

## 基线记录（M5 实测）
- console tsc -b --noEmit：0 错误（断链驱动补齐 M1 遗漏的 ReMe/Embedding 族与 mailDomains 族）
- console vitest M5 域：28 文件 278 tests，277 passed；唯一失败 AgentLoopCard.render 超时为 M3 已定性 Windows 并发资源竞争（单独跑 4/4 通过）
- 后端 pytest（QWENPAW_STORAGE_BACKEND=json）：test_multi_agent_lifecycle 23 passed（含 test_create_agent_persists_model_routing 端到端持久化验证）；test_agents_router + unit/config + test_agent_management 140 passed
- 关键发现：M1 的 434574cb 只直取了后端，console 前端（ModelSelector 12 文件目录/Settings/Models 重构/api types）整体遗漏由 M5 补齐；后端 config.py FallbackPolicyConfig 与 routers/agents.py 三字段同为漏网，本轮补齐；自有无改动验证后直取是安全边界
- locales ×6：3-way 复核（MB/HEAD/main）确认 M3 深合并基底已含 M5 全部新增 key；上游删除的旧 provider key 顺延 M9 清理
- 提交：cb587425(M5桶1,49文件,+9426/-1835) → 492835fb(M5桶3,7文件,+77/-5) → 本提交(M5台账)
