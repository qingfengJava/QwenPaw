# XianWork 侧边栏 UI 修复 + 媒体文件登记体系 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复侧边栏四个 UI 问题（按钮位置 / 置顶图标 / 批量标题 / 助理导航加粗），并把 `media_files` 表升级为「会话文件登记表」：上传文件带会话关联与存储类型，Agent 产出文件落库快照支持误删恢复。

**Architecture:** 前端只改 xianwork 四个文件 + 一处 CSS；后端在既有「本地 media/ 工作副本 + PG media_files 持久副本」双写链路上扩展元数据列（chat_id / session_id / owner_id / source / storage_type / storage_uri / sha256），通过 ToolHookRegistry 的 before/after 钩子登记 Agent 写出的文件，新增 `/api/xian/files` 列表与恢复端点。

**Tech Stack:** React 19 + zustand + vitest（xianwork）；FastAPI + SQLAlchemy(async, PG) + Alembic（qwenpaw 后端）；SQL 变更走 `db/feature/xianwork_enterprise_20260814/`。

**Spec:** 本计划自带需求（用户 2026-08-16 提出的 5 点），媒体存储设计文档见 `docs/design/2026-08-16-media-file-storage.md`（Task 9 产出）。

## Global Constraints

- 分支 `feature/xianwork_enterprise_20260814`，SQL 只写入 `db/feature/xianwork_enterprise_20260814/`（changelog + 快照双更），全部幂等（IF NOT EXISTS / IF NOT col）。
- 后端业务代码强制中文注释、方法体逐行注释、Javadoc 作者 qingfeng、构造器注入、`{}` 大括号（本计划新增 Python 代码同样逐行注释；作者标注 qingfeng）。
- 所有 SQL 一律参数绑定（text() + :param），禁止拼接。
- FontAwesome 免费版：`fa-thumbtack` 无 regular 字形 → 置顶统一改用 `fa-flag`（regular/solid 双态，workbuddy 同款）。
- 提交遵循 Conventional Commits（`feat(xian): …` / `fix(xian): …`）。

---

### Task 1: 侧边栏标题行按钮改为纯图标按钮（需求1）

**Files:**
- Modify: `xianwork/src/components/sidebar/SidebarChatTree.tsx:320-382`
- Modify: `xianwork/src/styles/global.css`（新增 `.sidebar-icon-btn`，删除 `.sidebar-select-btn` / `.sidebar-add-workspace` 旧样式）

**Interfaces:** 无跨文件接口；`SidebarSection.extra` 继续接收 ReactNode。

- [x] **Step 1: 修改 SidebarChatTree**
  - 任务区 `extra`：`<button className="sidebar-icon-btn" title="批量选择任务" aria-label="批量选择任务"><i className="fa-regular fa-square-check" /></button>`（去掉「选择」文字）。
  - 空间区 `extra`：`<button className="sidebar-icon-btn" title="新建空间" aria-label="新建空间"><i className="fa-solid fa-plus" /></button>`（去掉「新建空间」文字）。
- [x] **Step 2: CSS** — 新增 `.sidebar-icon-btn`（无边框幽灵图标按钮 22×22，muted 色，hover 变 accent）；删除 `.sidebar-select-btn`、`.sidebar-add-workspace` 三段旧规则。
- [x] **Step 3: 空区提示文案** — `还没有空间，点击右上「新建空间」注册一个磁盘目录` → `还没有空间，点击空间标题右侧 + 注册一个磁盘目录`。
- [x] **Step 4: 验证** — `npm run build` 通过（xianwork 目录）。

### Task 2: 置顶图标换旗帜（需求2）

**Files:**
- Modify: `xianwork/src/components/sidebar/ChatListItem.tsx:141-146,193-206`
- Modify: `xianwork/src/styles/global.css`（`.chat-pinned-icon` 微调）

- [x] **Step 1:** 行首已置顶指示：`fa-solid fa-thumbtack` → `fa-solid fa-flag`。
- [x] **Step 2:** hover 操作按钮：`fa-${pinned?"solid":"regular"} fa-thumbtack` → `fa-${pinned?"solid":"regular"} fa-flag`（两种字形免费版均存在）。
- [x] **Step 3:** 跑 `npx vitest run src/components/sidebar/ChatListItem.test.tsx` 全绿。

### Task 3: 批量模式显示会话标题（需求3）

**Files:**
- Modify: `xianwork/src/components/sidebar/ChatListItem.tsx:109-156`
- Test: `xianwork/src/components/sidebar/ChatListItem.test.tsx`

- [x] **Step 1:** 重构 `nav-item-left`：复选框独立渲染（`batchMode && !renaming`），标题/置顶指示分支不再被 batchMode 互斥。
- [x] **Step 2:** 测试断言批量模式下 `screen.getByText("任务一")` 存在且复选框 checked。
- [x] **Step 3:** vitest 全绿。

### Task 4: 会话内不激活「助理」导航（需求4）

**Files:**
- Modify: `xianwork/src/layouts/MainLayout.tsx:51-56,107`

- [x] **Step 1:** `navActive(item, path, search)` 增加第三参；`/chat` 项在 `search` 含 `chat=` 时返回 false（打开具体会话 ≠ 助理导航激活）。
- [x] **Step 2:** 调用处传 `location.search`；`npm run build` 通过。

### Task 5: media_files 表扩展（需求5 数据层）

**Files:**
- Create: `db/feature/xianwork_enterprise_20260814/changelog/20260816/03_media_registry.sql`
- Modify: `db/feature/xianwork_enterprise_20260814/test.sql` / `prod.sql`（追加第 10 节）
- Create: `src/qwenpaw/db/alembic/versions/0007_media_registry.py`
- Modify: `src/qwenpaw/db/models_media.py`

**Interfaces（后续任务依赖的列名/枚举值）:**
- 列：`chat_id VARCHAR(128) NULL`、`session_id VARCHAR(255) NULL`、`owner_id VARCHAR(128) NULL`、`source VARCHAR(32) NOT NULL DEFAULT 'upload'`（`upload`|`agent_output`）、`storage_type VARCHAR(16) NOT NULL DEFAULT 'db'`（`db`|`local`|`minio`|`oss`）、`storage_uri TEXT NULL`、`sha256 VARCHAR(64) NULL`。
- 索引：`ix_media_files_chat (tenant_id, chat_id)`、`ix_media_files_session (tenant_id, session_id)`。

- [x] **Step 1:** changelog SQL（ALTER TABLE … ADD COLUMN IF NOT EXISTS ×7 + 2 索引 + COMMENT + alembic 标记推进 0007）。
- [x] **Step 2:** 快照 test.sql / prod.sql 追加同内容（幂等）。
- [x] **Step 3:** alembic 0007（inspector 判列存在再 add_column，幂等）。
- [x] **Step 4:** `models_media.py` 补 mapped_column + Index。

### Task 6: 上传链路登记完整元数据（需求5）

**Files:**
- Modify: `src/qwenpaw/app/media_store.py`（`save_media_blob` 扩展可选参数；新增 `list_media_records` / `load_media_record`）
- Modify: `src/qwenpaw/app/routers/console.py:486-582`（`/console/upload`）

- [x] **Step 1:** `save_media_blob` 增加 kwargs：`chat_id/session_id/owner_id/source/storage_type/storage_uri/sha256`（默认值保持旧行为），upsert set_ 同步新列。
- [x] **Step 2:** 上传端点计算 sha256，传 chat_id、`chat.session_id`、`request.state.user`、`source="upload"`、`storage_type="db"`、`storage_uri=str(path)`。
- [x] **Step 3:** 新增 `list_media_records(tenant_id, chat_id, session_id)` / `load_media_record(tenant_id, stored_name)`（参数绑定）。

### Task 7: Agent 产出文件登记 hook（需求5）

**Files:**
- Create: `src/qwenpaw/tool_calls/media_hooks.py`
- Modify: `src/qwenpaw/agents/react_agent.py`（`_register_tool_call_hooks` 末尾挂载）

**Interfaces:**
- `register_media_output_hooks(registry: ToolHookRegistry) -> None`：对 `write_file` / `edit_file` / `append_file` 注册 before（stash file_path 进 ctx.extra）/ after（成功则登记）。
- 登记行：`source='agent_output'`、`storage_type='db'`、`session_id=ctx.session_id`、`stored_name = sha256前16位_安全文件名`（内容寻址去重）。
- 快照上限 `MAX_AGENT_OUTPUT_SNAPSHOT_BYTES = 20MB`，超限跳过；全程 best-effort 不抛错。

- [x] **Step 1:** 实现 media_hooks（文件读取/哈希走 `asyncio.to_thread`）。
- [x] **Step 2:** react_agent 挂载（保留原 timeout 注册——registry.register 字段合并语义）。
- [x] **Step 3:** `python -c "import qwenpaw.tool_calls.media_hooks"` 冒烟。

### Task 8: xian files API（列表 + 恢复）（需求5）

**Files:**
- Create: `src/qwenpaw/app/routers/xian/files.py`
- Modify: `src/qwenpaw/app/routers/xian/__init__.py`

- [x] **Step 1:** `GET /api/xian/files?chat_id=` — 校验会话归属（复用 workspaces.py 的 `_owned_chat_filter` 语义），按 `chat_id OR session_id` 参数化查询，返回 `exists_local` / `url`（`/api/console/media/{stored_name}`）。
- [x] **Step 2:** `POST /api/xian/files/{stored_name}/restore` — 行归属校验 → PG 副本写回 `storage_uri`（绝对路径校验 + mkdir parents）→ 返回恢复路径。
- [x] **Step 3:** 注册路由；导入冒烟。

### Task 9: 媒体存储设计文档（需求5）

**Files:**
- Create: `docs/design/2026-08-16-media-file-storage.md`

- [x] 内容：现状确认（本地+PG 双写）、目标表结构、本地存储模式、云存储模式（MinIO/OSS 落地步骤与开关设计）、Agent 产出文件恢复流程、保留策略。

### Task 10: 测试、构建与提交

- [x] **Step 1:** `npx vitest run`（xianwork 全部测试）。
- [x] **Step 2:** `npm run build`。
- [x] **Step 3:** 后端：`python -m compileall` 新增/修改文件 + 现有相关 pytest 子集。
- [x] **Step 4:** 分两个 commit：`fix(xian): …`（UI 四项）、`feat(xian): …`（媒体登记体系 + SQL + 文档）。
