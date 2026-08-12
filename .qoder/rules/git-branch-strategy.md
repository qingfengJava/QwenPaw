---
trigger: always_on
---



# Git 分支策略规范（Fork 工作流）

> **适用范围**：本规范适用于当前 fork 仓库（qingfengJava/QwenPaw）的所有 Git 操作与分支判断。
> 本仓库 fork 自上游 `agentscope-ai/QwenPaw`，采用 **"上游镜像 + dev 主干 + feature 分支"** 的 GitFlow 变体模型。
> **本规范优先级高于** 全局 `project-rule.md` 中涉及分支主干定义的相关条款（主要是 §4 SQL 变更管理中所有"main 分支"的语义，在本仓库一律映射为 `dev`）。

---

## 〇、核心原则（强制，违反即不合格产出）

1. **`main` 分支只读**：仅用于同步上游 `upstream/main`，禁止任何业务开发与直接提交。
2. **`dev` 是开发主分支**：所有功能最终合并到此；`dev` 即"主干"。
3. **一切开发走 `feature/*` 分支**：从 `dev` 切出，通过 PR 合并回 `dev`，禁止直接 push 到 `dev`。
4. **AI 助手默认主干判断**：凡任务上下文提到"主干 / main 分支 / 主分支"，在本仓库一律按 `dev` 处理。

---

## 一、分支模型

### 1.1 分支定义

| 分支        | 角色                  | 来源               | 保护级别 | 允许操作                                |
| ----------- | --------------------- | ------------------ | -------- | --------------------------------------- |
| `main`      | 上游镜像分支          | `upstream/main` 同步 | 只读保护 | 仅允许同步上游，禁止任何业务提交        |
| `dev`       | 开发主分支 / 集成分支 | 基于 `main` 创建   | 保护分支 | 仅允许通过 PR 合并 `feature` / `hotfix` |
| `feature/*` | 功能开发分支          | 从 `dev` 切出      | 普通     | 开发、提交、PR 回 `dev`                 |
| `hotfix/*`  | 紧急修复分支          | 从 `dev` 切出      | 普通     | 修复、PR 回 `dev`                       |
| `release/*` | 发布分支（可选）      | 从 `dev` 切出      | 普通     | 版本定型，PR 回 `dev` 并 tag            |

### 1.2 强制规则

- **禁止** 直接在 `main` 分支上开发或提交业务代码。
- **禁止** 直接 push 到 `dev`（必须走 Pull Request）。
- **禁止** `git push --force` 到 `main` / `dev` 任何受保护分支。
- **必须** 所有功能在 `feature/*` 分支开发，通过 PR 合并到 `dev`。
- **必须** `feature` 分支从 `dev`（而非 `main`）切出，确保包含最新集成状态与上游同步内容。
- **必须** 单人开发也走 PR：便于代码回溯、CI 校验、保留分支历史。

---

## 二、分支命名规范

### 2.1 命名格式

| 类型     | 格式                            | 示例                                    |
| -------- | ------------------------------- | --------------------------------------- |
| 功能分支 | `feature/{功能简述}_{YYYYMMDD}` | `feature/agent_stats_dashboard_20260812` |
| 紧急修复 | `hotfix/{问题简述}_{YYYYMMDD}`  | `hotfix/memory_leak_20260812`            |
| 发布分支 | `release/{version}`             | `release/2.1.0`                          |

### 2.2 命名规则

- 功能简述用全小写 + 下划线（snake_case），**禁止** 大写字母、连字符 `-`。
- 日期取创建分支当天（`YYYYMMDD`），便于按时间排序与回溯。
- 简述应能体现代码意图（模块名 / 功能名），**禁止** `tmp`、`test`、`wip`、`dev2` 等无意义命名。
- 分支名去掉 `feature/` 前缀后的部分，**必须** 与 `db/feature/{分支名}/` SQL 目录名一一对应（见原规范 §4.4 及本规范 §六的映射）。

---

## 三、上游同步策略

### 3.1 Remote 配置（首次一次性执行）

```bash
git remote add upstream https://github.com/agentscope-ai/QwenPaw.git
```

### 3.2 同步上游到 `main`（定期执行）

```bash
git fetch upstream
git checkout main
git merge upstream/main --ff-only    # main 仅作镜像，保持与上游线性一致
git push origin main
```

- **必须** 使用 `--ff-only`：`main` 是上游镜像，不引入额外的合并提交。
- 若 `--ff-only` 失败（说明本地 `main` 与上游发生了分叉），**禁止** 改用普通 merge，**必须** `git reset --hard upstream/main` 重置后再 `git push origin main`（此为唯一允许 force 的场景，且仅作用于 `main`）。

### 3.3 同步 `main` 到 `dev`（每次上游更新后）

```bash
git checkout dev
git merge main                       # 普通合并，保留合并提交以标记"上游同步点"
# 解决冲突（如有），提交冲突解决说明
git push origin dev
```

### 3.4 同步频率

- **推荐** 每周至少同步一次上游。
- 上游有重要 release / 安全修复时立即同步。
- 同步 `dev` 后，通知所有活跃 `feature` 分支 `rebase origin/dev` 以纳入上游变更。

---

## 四、开发工作流

### 4.1 开始新功能

```bash
# 1. 确保 dev 是最新
git checkout dev
git pull origin dev

# 2. 从 dev 切出 feature 分支（命名见 §2.1）
git checkout -b feature/{功能简述}_{YYYYMMDD}

# 3. 推送到远程建立追踪
git push -u origin feature/{功能简述}_{YYYYMMDD}
```

### 4.2 开发过程中

```bash
# 定期 rebase dev，保持与主干同步（仅对未推送的提交 rebase）
git fetch origin
git rebase origin/dev

# 提交（遵循 Conventional Commits，见 §5）
git add <files>
git commit -m "feat(模块): 简述"
```

### 4.3 完成功能合并

```bash
# 1. 最后一次 rebase dev 并跑通测试（见原规范 §5 测试规范）
git rebase origin/dev
make quick   # 或等效的快速测试命令

# 2. 推送最终版本
git push origin feature/{分支名}

# 3. 在 GitHub 创建 PR：feature/* → dev
#    - PR 标题遵循 Conventional Commits
#    - 合并方式选择 "Create a merge commit"（--no-ff），保留分支历史
#    - 禁止使用 "Squash and merge"（会丢失分支语义）

# 4. 合并后清理本地与远程分支
git checkout dev
git pull origin dev
git branch -d feature/{分支名}
git push origin --delete feature/{分支名}
```

---

## 五、提交信息规范（Conventional Commits）

### 5.1 格式

```
<type>(<scope>): <subject>

[可选 body：说明为什么这样改，而非改了什么]

[可选 footer：Breaking changes / Closes #issue]
```

### 5.2 Type 速查

| type       | 用途                  |
| ---------- | --------------------- |
| `feat`     | 新功能                |
| `fix`      | Bug 修复              |
| `docs`     | 文档                  |
| `refactor` | 重构（不改行为）      |
| `test`     | 测试                  |
| `chore`    | 构建 / 依赖 / 杂项    |
| `perf`     | 性能优化              |
| `ci`       | CI/CD                 |
| `revert`   | 回滚                  |

### 5.3 示例

```
feat(agent_stats): 新增 agent 运行统计面板

- 新增 /api/agent_stats 接口，按五步范式批量组装 VO
- 前端接入图表组件，支持时间范围筛选
```

---

## 六、与原项目 SQL 规范的映射关系（重要）

> 原项目规范 `project-rule.md` §4「SQL 变更管理」以 `main` 分支为主干。在本 fork 仓库中，开发主干已改为 `dev`，需做如下映射。**AI 助手创建 / 判断 SQL 文件路径时必须按此映射执行。**

### 6.1 SQL 文件路径映射

| 原规范路径                          | 本 fork 实际路径                   | 说明                 |
| ----------------------------------- | ---------------------------------- | -------------------- |
| `db/main/changelog/{日期}/{NN}.sql` | `db/dev/changelog/{日期}/{NN}.sql` | 主干增量变更记录     |
| `db/main/test.sql`                  | `db/dev/test.sql`                  | 主干测试快照         |
| `db/main/prod.sql`                  | `db/dev/prod.sql`                  | 主干生产快照         |
| `db/feature/{分支名}/...`           | `db/feature/{分支名}/...`          | 不变                 |

### 6.2 AI 助手创建 SQL 文件的分支判断规则（修订版）

```
第一步：执行 git branch --show-current 获取当前分支名

第二步：根据分支名选择路径
  ├── 若当前在 dev 分支（主干开发）
  │   → changelog 路径：db/dev/changelog/{今日日期}/{NN_变更简述}.sql
  │   → 快照文件：db/dev/test.sql 和 db/dev/prod.sql
  │
  └── 若当前在 feature 分支（如 feature/agent_stats_20260812）
      → 取分支名去掉 "feature/" 前缀，得到 {分支名}（此处为 agent_stats_20260812）
      → changelog 路径：db/feature/{分支名}/changelog/{今日日期}/{NN_变更简述}.sql
      → 快照文件：db/feature/{分支名}/test.sql 和 db/feature/{分支名}/prod.sql
  │
  └── 若当前在 main 分支
      → 禁止在 main 上创建任何 SQL 变更文件
      → 提示用户：main 仅用于上游同步，开发请切到 dev 或 feature 分支

第三步：创建 changelog 文件（头部加注释，见原规范 §4.3）

第四步：同步更新本分支目录下的 test.sql 和 prod.sql 快照
```

### 6.3 上线规范映射

- 原规范「正式环境只执行 `db/main/prod.sql`」→ 本 fork 改为执行 `db/dev/prod.sql`。
- `feature` 分支上线流程不变：直接执行 `db/feature/{分支名}/prod.sql`。
- 合并流程不变：`feature` 分支合并到 `dev` 后，将 `db/feature/{分支名}/changelog/` 下的变更文件复制到 `db/dev/changelog/` 对应日期目录，并合并快照到 `db/dev/test.sql` 与 `db/dev/prod.sql`。

---

## 七、初始化清单（首次执行）

> 本 fork 仓库当前仅有 `main` 分支且未配置 upstream remote。按以下步骤完成初始化：

```bash
# 1. 配置上游 remote
git remote add upstream https://github.com/agentscope-ai/QwenPaw.git

# 2. 创建 dev 分支（基于当前 main）
git checkout main
git pull origin main
git checkout -b dev
git push -u origin dev

# 3. 在 GitHub 仓库设置中（手动操作）：
#    - Settings → Branches → Default branch：将默认分支改为 dev
#    - 为 main 添加保护规则：禁止直接 push（仅允许同步上游）
#    - 为 dev 添加保护规则：require PR / require status checks
```

---

## 八、禁止行为清单

- ❌ 在 `main` 上直接开发或提交业务代码。
- ❌ 直接 push 到 `dev`（未经 PR）。
- ❌ `git push --force` 到 `main` / `dev`（唯一例外见 §3.2）。
- ❌ rebase 已推送到远程共享的分支。
- ❌ `feature` 分支从 `main` 切出（必须从 `dev`）。
- ❌ 分支命名用大写字母或连字符 `-`。
- ❌ 提交信息用 "update"、"fix"、"wip" 等无意义文案。
- ❌ 合并 `feature` 到 `dev` 用 "Squash and merge"（会丢失分支语义，用 "Create a merge commit"）。
- ❌ 在 `main` 分支上创建任何 `db/` 下的 SQL 变更文件。
