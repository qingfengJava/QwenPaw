# 上游 v2.2.x 功能移植台账（upstream-port-checklist）

> 基线：`feature/platform_ia_refactor_20260831`（93 提交自有改造）
> 工作分支：`feature/upstream_port_20260903`
> 上游参考：`main`（v2.1.0b4 → v2.2.1b1，dev..main = 225 提交）
> 处置桶别：桶1=直取(checkout main 新文件) / 桶2=复制+适配 / 桶3=手工融合(交集文件) / 桶4=综合取舍 / 桶5=删除跟随
> 状态：`[ ]` 待办 / `[x]` 完成 / `[~]` 放弃（附理由）

## M0 基线与安全网
- [x] console tsc --noEmit 0 错误
- [x] console vitest 全量跑完（首轮 1092s 完整通过）
- [ ] console npm run build EXIT=0（M9 前补验）
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
上游参考：006b80a6(agent model routing settings)、81be8cc4(model selector样式)
- [ ] [桶1] pages/Chat/ModelSelector/ 新组件族、Settings/Models/ 新 modals
- [ ] [桶3] components/AgentSelector/、LoopModeSelector.tsx、HarnessModelSelector.tsx、Settings/Agents/
- [ ] 验证：tsc + vitest + 模型切换冒烟

## M6 Hub 自托管多用户（依赖 M3）
上游参考：f07a6a01(self-hosted Hub)、4e2e9ae2/a756623c(agentscope升级)
- [ ] [桶1] src/qwenpaw/hub/ ×22、cli/hub_cmd.py
- [ ] [桶1] console auth/gate.ts、api/modules/hub.ts、pages/Hub/、pages/Login/、scripts/precompress-assets.mjs、verify-initial-bundle.mjs
- [ ] [桶3] App.tsx、api/modules/auth.ts、stores/authStore.ts、console/index.html、layouts/index.module.less、MainLayout
- [ ] [桶4] Hub=部署接入层 与 RBAC=应用权限层并存；Login 衔接 authStore
- [ ] 检查 src/qwenpaw/db 上游变更
- [ ] 验证：pytest tests/unit/hub + 登录→桌面全流程

## M7 mailbox 邮件族（可并行）
上游参考：f3046db6(邮件助手)、e3b61d71(inbox降噪)、67d5eff7(文档)、4f659968(CLI configurators)、fbca3562(desktop打包mail MCP)
- [ ] [桶1] app/mail/ ×4、routers/mail_access_control.py、agents/tools/mail_f1_tool.py、skills/mailbox-en|zh/、md_files 新增、packages/qwenpawmail-mcp/
- [ ] [桶1] console api/modules/mailAccessControl.ts
- [ ] [桶3] pages/Inbox/ 融合
- [ ] 验证：pytest tests/unit/app/mail + Inbox 冒烟

## M8 通道修复 + creator/DataPaw + 桌面打包（可并行）
上游参考：2f621f44/c19801d1(matrix)、5cf8d14f(qq)、c4326313/58ebb9a0(dingtalk)、59f2849c(onebot)、6d8217d3(console channel)、673091e6(yuanbao)、29473338(xiaoyi)、63799c1f/77c2e5f8(creator)、6b3dc19d(DataPaw)、f1879477/d3efdf2e/72c2b2b3/2ce39f81/61ffff54/9a88d2ec/b2f84a95(桌面修复)
- [ ] [桶3] app/channels/base.py、console/channel.py、dingtalk/channel.py
- [ ] [桶1] app/channels/onebot/media.py
- [ ] [桶1] plugins/apps/qwenpaw-creator/、qwenpaw-data/、plugins/bundle/computer-use/
- [ ] [桶3] deploy/Dockerfile、console/src-tauri 打包（确认后跟随删 stop-backend-sidecar.ps1）
- [ ] [桶3] 桌面修复族（WebView2/PyInstaller/杀软/CRLF/envs原子写/截图目录）
- [ ] 验证：pytest channels/contract + plugins 子集 + 打包干跑

## M9 website/docs/CI + 测试扩容 + 全面回归
- [ ] [桶1] git checkout main -- website docs
- [ ] .github/ 逐文件甄别采用
- [ ] tests/ 上游新测试按域归位（integration ×132 / unit ×130）
- [ ] 重写交集测试：tauri/test_entry.py（chats/test_utils.py 与 governance/test_policy.py 已在 M2 提前完成：main 基底+自有叠加）
- [ ] 全面回归：pytest 全量 + tsc + vitest 全量 + build + e2e 子集 + 浏览器端到端冒烟
- [ ] 台账勾销完毕，PR：upstream_port → dev，随后 platform_ia_refactor → dev

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
