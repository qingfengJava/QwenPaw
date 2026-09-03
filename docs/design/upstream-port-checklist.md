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
- [ ] [桶2] services/project_directory.py(+718)、config/context.py 新增、hooks/request_setup/contextvars_hook.py
- [ ] [桶3] app/chats/（api/manager/models/utils）
- [ ] [桶3] app/agent_context.py、runtime/builder.py、runtime/runtime.py
- [ ] [桶3] governance/（policy/resource_governor/tool_adapter）
- [ ] [桶3] agents/tools/（file_io/ast_tool/lsp_tool/shell/send_file/file_search/view_media/agent_management/fork_project）
- [ ] [桶3] app/workspace/（workspace.py/service_factories.py）、app/routers/console.py、app/routers/workspace.py
- [ ] 检查 src/qwenpaw/db 上游变更（alembic 协调）
- [ ] 验证：pytest integration workspace/chats/governance 子集

## M3 前端基建与聊天体验线
上游参考：e08f2e60(artifacts)、2bfe2b2b(复制不含推理)、75b9a810(自动折叠)、0dd1844f(未读指示)、e730e947(长会话性能)、25af0963(流卡死恢复)、51e58258(删desktop reminder)、9382a623(会话分组)
- [ ] [桶1] console/package.json 依赖升级（@agentscope-ai/chat 1.1.73-beta）+ lock 重装
- [ ] [桶1] api/error.ts、ChunkErrorBoundary、MediaDownload/、LazyAccordion、HostBubbles.module.less、SessionGroupDnd/、SessionGroupHeader/、SessionDateHeader/、SessionItem.test
- [ ] [桶1] hooks/（useChatGroups/useCollapsedChatGroups/useRevealActiveChatGroup/useSessionAttention）、ResponseArtifactList*、loadSessionProjectDirs.ts
- [ ] [桶3] api/modules/chat.ts(.test)、pages/Chat/index.tsx、HostBubbles.tsx、styles/layout.css
- [ ] [桶5] 删 utils/desktopModeHint* 并清理 Sidebar.tsx Tour 引用
- [ ] [桶3] 上游 Sidebar 测试按当前 IA 重写断言
- [ ] 验证：tsc 0 错误 + vitest + 浏览器冒烟

## M4 Marketplace 统一与 IA 挂接
上游参考：9bce6fb1(统一marketplace)、c1728668/35d66456(os market已安装标记)、461e65fa(装后免刷新)、5d4c9a34(dark mode+Extension改名)、d376ec5c(skill自动更新)、76ee1381(skill CLI重构)、f31c3594(skill文件缓存)
- [ ] [桶1] pages/AppCenter/ 重构族、pages/Market/、Settings/Market/、PluginManager 新组件族、Agent/Skills/（useSkillsPage/WebSearchConfigModal）、SkillPool
- [ ] [桶3] builtinMenu.ts（app-center→marketplace 改名+删 plugin-manager 菜单）、builtinRoutes.tsx
- [ ] [桶3] os/osApps.ts、os/osRouteMap.ts、os/SettingsApp.tsx、os/osAppRegistry.ts
- [ ] [桶3] layouts/Sidebar.tsx、SidebarSessionList.tsx、MainLayout/index.tsx、App.tsx
- [ ] 更新测试：adminMenu.test、osAppRegistry.test、osRouteMap.test、osPluginStore.test
- [ ] 验证：tsc + vitest + 浏览器实测

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
- [ ] 重写 3 个交集测试：tests/unit/app/chats/test_utils.py、governance/test_policy.py、tauri/test_entry.py
- [ ] 全面回归：pytest 全量 + tsc + vitest 全量 + build + e2e 子集 + 浏览器端到端冒烟
- [ ] 台账勾销完毕，PR：upstream_port → dev，随后 platform_ia_refactor → dev

## 基线记录
（待 M0 验证结果填入）
