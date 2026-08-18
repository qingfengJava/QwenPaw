# QwenPaw 项目开发规则

> 来源：`.qoder/rules/project_rules.md` 与 `.qoder/rules/git-branch-strategy.md`（本文件为 AI 助手执行版，与原文冲突时以 `.qoder/rules/` 原文为准）。
> 标注"**必须**"、"**禁止**"的条目为**强制执行**，违反即不合格产出；标注"**优先**"、"**推荐**"的为最佳实践。

---

## 〇、需求理解铁律（最高优先级，先于一切执行）

> **北极星目标**：本项目正被改造为**企业级可落地的数字员工平台**（基于开源个人 AI 助手 QwenPaw）。所有需求理解、方案设计、Bug 修复都必须服务于这个目标，而不是维护"个人助手"的原样形态。
> **本节优先级高于本规范其余所有章节**：与其余章节冲突时，先满足本节。（原文：`.qoder/rules/project_rules.md` §〇）

### 0.1 核心原则：禁止字面执行（强制）

用户提出的需求可能是**一句概念**（"搞一个专家市场"）、**一个 bug**（"分享页打不开"）或**一个局部改动**（"把这个按钮挪个位置"）。AI 助手**禁止**只按字面最小改动执行，**必须**先以"企业级可落地的数字员工平台"的视角完成四维审查，再动手：

| 审查维度 | 必须回答的问题 |
| -------- | -------------- |
| **架构合理性** | 这个改动放进当前企业架构（双 API 平面 / 租户模型 / RBAC / 专家体系 / 多前端）是否自洽？是否违背已有分层与数据单一来源？是否为未来的多租户、编排、计量留了缝而不是堵死？ |
| **需求完整性** | 用户抛的是概念时，概念背后的完整业务闭环是什么（谁创建、谁使用、谁治理、权限如何分配、数据落在哪张表、列表/详情/新建/编辑/删除是否齐全）？是否存在只做了半截（能建不能删、能开不能关）的缺口？ |
| **正向流程完整性** | 主链路从头到尾是否走得通（前端入口 → API → 权限校验 → 业务规则 → 数据落库 → 状态回显 → 通知/统计联动）？每一环的数据结构是否严格一致？ |
| **逆向流程完整性** | 反向链路是否存在且完整：取消/撤销、删除（含级联清理与逻辑删除）、失败回滚与补偿、权限回收、配额回退、会话/文件删除后的关联数据处理、错误提示与兜底？**只做正向不做逆向 = 不合格产出**。 |

### 0.2 执行动作（强制）

1. **先审后做**：接到需求，先输出简短的需求理解与四维审查结论（发现补全了什么、发现了什么缺口），再进入实施；发现与北极星目标冲突的设计，必须指出并给出对齐建议。
2. **缺口必须显性化**：本次不做/留待后续的逆向流程或完整闭环缺口，必须在方案或交付说明中明确列出（"本次未覆盖：…"），禁止静默忽略。
3. **Bug 修复必须追根**：修 bug 时必须定位到根因层（架构/数据模型/契约不一致），禁止只在表象上打补丁；同类问题在其他模块是否存在要主动排查。
4. **企业落地标尺**：判断"合理性"的默认标尺是——多用户、权限隔离、可审计、可运维、可恢复、数据可治理。个人玩具式实现（单用户假设、无权限校验、删了就没了）一律视为不合理。

### 0.3 违反后果

- 违反本节（字面执行、只做正向、静默砍掉逆向流程、表象修 bug）产生的代码为**不合格产出**，必须按四维审查重做。
- 返修循环（同一模块反复修 bug）通常意味着首次交付违反了本节，应回顾补课而不是继续打补丁。

---

## 一、Git 分支策略规范（Fork 工作流）

> 适用范围：本 fork 仓库（qingfengJava/QwenPaw，fork 自 `agentscope-ai/QwenPaw`）的所有 Git 操作。
> 采用 **"上游镜像 + dev 主干 + feature 分支"** 的 GitFlow 变体模型。
> **本规范优先级高于其他规范中涉及分支主干定义的条款**（所有"main 分支"的语义在本仓库一律映射为 `dev`）。

### 1.1 核心原则（强制）

1. **`main` 分支只读**：仅用于同步上游 `upstream/main`，禁止任何业务开发与直接提交。
2. **`dev` 是开发主分支**：所有功能最终合并到此；`dev` 即"主干"。
3. **一切开发走 `feature/*` 分支**：从 `dev` 切出，通过 PR 合并回 `dev`，禁止直接 push 到 `dev`。
4. **AI 助手默认主干判断**：凡任务上下文提到"主干 / main 分支 / 主分支"，一律按 `dev` 处理。

### 1.2 分支模型

| 分支        | 角色                  | 来源               | 保护级别 | 允许操作                                |
| ----------- | --------------------- | ------------------ | -------- | --------------------------------------- |
| `main`      | 上游镜像分支          | `upstream/main` 同步 | 只读保护 | 仅允许同步上游，禁止任何业务提交        |
| `dev`       | 开发主分支 / 集成分支 | 基于 `main` 创建   | 保护分支 | 仅允许通过 PR 合并 `feature` / `hotfix` |
| `feature/*` | 功能开发分支          | 从 `dev` 切出      | 普通     | 开发、提交、PR 回 `dev`                 |
| `hotfix/*`  | 紧急修复分支          | 从 `dev` 切出      | 普通     | 修复、PR 回 `dev`                       |
| `release/*` | 发布分支（可选）      | 从 `dev` 切出      | 普通     | 版本定型，PR 回 `dev` 并 tag            |

强制规则：

- **禁止** 直接在 `main` 分支上开发或提交业务代码。
- **禁止** 直接 push 到 `dev`（必须走 Pull Request）。
- **禁止** `git push --force` 到 `main` / `dev` 任何受保护分支。
- **必须** 所有功能在 `feature/*` 分支开发，通过 PR 合并到 `dev`。
- **必须** `feature` 分支从 `dev`（而非 `main`）切出。
- **必须** 单人开发也走 PR：便于代码回溯、CI 校验、保留分支历史。

### 1.3 分支命名规范

| 类型     | 格式                            | 示例                                      |
| -------- | ------------------------------- | ----------------------------------------- |
| 功能分支 | `feature/{功能简述}_{YYYYMMDD}` | `feature/agent_stats_dashboard_20260812`  |
| 紧急修复 | `hotfix/{问题简述}_{YYYYMMDD}`  | `hotfix/memory_leak_20260812`             |
| 发布分支 | `release/{version}`             | `release/2.1.0`                           |

- 功能简述用全小写 + 下划线（snake_case），**禁止** 大写字母、连字符 `-`。
- 日期取创建分支当天（`YYYYMMDD`）。
- **禁止** `tmp`、`test`、`wip`、`dev2` 等无意义命名。
- 分支名去掉 `feature/` 前缀后的部分，**必须** 与 `db/feature/{分支名}/` SQL 目录名一一对应。

### 1.4 上游同步策略

Remote 配置（首次一次性执行）：

```bash
git remote add upstream https://github.com/agentscope-ai/QwenPaw.git
```

同步上游到 `main`（定期执行，推荐每周至少一次）：

```bash
git fetch upstream
git checkout main
git merge upstream/main --ff-only    # main 仅作镜像，保持与上游线性一致
git push origin main
```

- **必须** 使用 `--ff-only`；若失败（分叉），**禁止**改用普通 merge，**必须** `git reset --hard upstream/main` 后再 push（此为唯一允许 force 的场景，且仅作用于 `main`）。

同步 `main` 到 `dev`（每次上游更新后）：

```bash
git checkout dev
git merge main                       # 普通合并，保留合并提交标记"上游同步点"
git push origin dev
```

同步 `dev` 后，通知所有活跃 `feature` 分支 `rebase origin/dev`。

### 1.5 开发工作流

```bash
# 开始新功能
git checkout dev && git pull origin dev
git checkout -b feature/{功能简述}_{YYYYMMDD}
git push -u origin feature/{功能简述}_{YYYYMMDD}

# 开发过程中（定期 rebase，仅对未推送提交）
git fetch origin && git rebase origin/dev
git commit -m "feat(模块): 简述"

# 完成合并
git rebase origin/dev
make quick                            # 跑通测试
git push origin feature/{分支名}
# GitHub 创建 PR：feature/* → dev，合并方式 "Create a merge commit"（--no-ff），禁止 "Squash and merge"
# 合并后清理
git checkout dev && git pull origin dev
git branch -d feature/{分支名}
git push origin --delete feature/{分支名}
```

### 1.6 提交信息规范（Conventional Commits）

格式：`<type>(<scope>): <subject>`，body 说明为什么这样改（可选），footer 放 Breaking changes / Closes #issue（可选）。

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

示例：

```
feat(agent_stats): 新增 agent 运行统计面板

- 新增 /api/agent_stats 接口，按五步范式批量组装 VO
- 前端接入图表组件，支持时间范围筛选
```

**禁止** "update"、"fix"、"wip" 等无意义文案。

### 1.7 禁止行为清单

- ❌ 在 `main` 上直接开发或提交业务代码。
- ❌ 直接 push 到 `dev`（未经 PR）。
- ❌ `git push --force` 到 `main` / `dev`（唯一例外见 §1.4）。
- ❌ rebase 已推送到远程共享的分支。
- ❌ `feature` 分支从 `main` 切出（必须从 `dev`）。
- ❌ 分支命名用大写字母或连字符 `-`。
- ❌ 合并 `feature` 到 `dev` 用 "Squash and merge"。
- ❌ 在 `main` 分支上创建任何 `db/` 下的 SQL 变更文件。

---

## 二、SQL 变更管理规范

### 2.1 目录结构

核心设计原则：**每个分支（dev 和每个 feature 需求分支）都有自己独立的 `test.sql` + `prod.sql` 完整快照**，快照在目录顶层，`changelog/` 在其下存放增量变更。上线时直接执行对应分支的 `prod.sql`，无需逐条执行 changelog。

```
db/
├── dev/
│   ├── test.sql                               ← 主干全量快照（从零部署用）
│   ├── prod.sql                               ← 主干全量快照（上线时直接执行一次）
│   └── changelog/
│       └── {YYYYMMDD}/{NN_变更简述}.sql        ← 主干历史增量变更记录
└── feature/
    └── {分支名}/                              ← 分支名与 Git 分支对应（去掉 "feature/" 前缀）
        ├── test.sql                           ← 本需求分支完整快照（测试环境用）
        ├── prod.sql                           ← 本需求分支完整快照（上线时直接执行）
        └── changelog/{YYYYMMDD}/{NN_变更简述}.sql
```

> 路径映射：原规范 `db/main/...` 的语义在本 fork 一律映射为 `db/dev/...`；`db/feature/{分支名}/...` 不变。

### 2.2 创建 SQL 文件的分支判断规则（强制，禁止凭经验估猜路径）

```
第一步：执行 git branch --show-current 获取当前分支名

第二步：根据分支名选择路径
  ├── dev 分支：
  │   → changelog：db/dev/changelog/{今日日期}/{NN_变更简述}.sql
  │   → 快照：db/dev/test.sql 和 db/dev/prod.sql
  ├── feature 分支（如 feature/agent_stats_20260812）：
  │   → 取分支名去掉 "feature/" 前缀得到 {分支名}
  │   → changelog：db/feature/{分支名}/changelog/{今日日期}/{NN_变更简述}.sql
  │   → 快照：db/feature/{分支名}/test.sql 和 db/feature/{分支名}/prod.sql
  └── main 分支：
      → 禁止创建任何 SQL 变更文件，提示用户切到 dev 或 feature 分支

第三步：创建 changelog 文件（头部加注释）

第四步：同步更新本分支目录下的 test.sql 和 prod.sql 快照
```

禁止行为：

- 禁止在 feature 分支开发时将 SQL 变更写入 `db/dev/changelog/`。
- 禁止将快照文件 test.sql/prod.sql 放到 `db/` 根目录。
- 禁止 feature 分支的快照同步到 `db/dev/`（dev 的快照只在分支合并后才更新）。
- 禁止未确认分支直接创建文件。

### 2.3 changelog 记录规范

- 文件夹命名：`YYYYMMDD`，每个工作日一个文件夹；文件命名：`NN_变更简述.sql`，序号从 `01` 开始。
- 每个文件头部必须注释：

```sql
-- [变更说明] 修复积分菜单 url_path 权限路径错误
-- [变更时间] 2026-06-08
-- [变更人]   清风
-- [适用环境] 测试环境（在已有库基础上增量执行）
-- [同步至 db/dev/test.sql] 是
-- [同步至 db/dev/prod.sql] 是
```

- **快照同步（强制）**：每次往 `changelog/` 新增变更文件时，必须同步更新本分支下的 `test.sql` 和 `prod.sql`，保证快照始终是最新全量状态。

### 2.4 幂等性设计（强制）

所有 SQL 变更必须可重复执行不报错：

| 操作类型 | 幂等写法                                                     |
| -------- | ------------------------------------------------------------ |
| 建表     | `CREATE TABLE IF NOT EXISTS`                                 |
| 加字段   | 先判断字段是否存在，或捕获 `1060 Duplicate column` 错误      |
| 插入数据 | `INSERT IGNORE INTO` 或 `INSERT ... ON DUPLICATE KEY UPDATE` |
| 菜单插入 | 执行前先 `DELETE FROM t_menu WHERE menu_id = xxx`，再 INSERT |
| 更新数据 | `UPDATE ... WHERE` 条件本身具有幂等性                        |

### 2.5 使用流程与上线

```
有新 SQL 变更时：
  1. git branch --show-current 确认分支
  2. 按 §2.2 确定路径
  3. 建当天日期文件夹（已存在则直接用）
  4. 建序号文件 01_xxx.sql、02_xxx.sql…
  5. 写入变更 SQL（头部加注释）
  6. 同步更新本分支 test.sql
  7. 同步更新本分支 prod.sql
  8. 测试库执行当天最新 changelog 文件
```

- 上线：正式环境只执行对应分支的 `prod.sql` 全文（`db/dev/prod.sql` 或 `db/feature/{分支名}/prod.sql`），不需要执行 changelog。
- prod.sql **禁止**出现无条件的 `DROP TABLE`、`TRUNCATE`；确需删除必须加 `IF EXISTS` 并注释说明原因。
- PR 合并前检查：确认 `db/dev/test.sql` 和 `db/dev/prod.sql` 均已包含本次所有变更，禁止代码已合并但 SQL 遗漏。
- feature 合并到 `dev` 后：将 `db/feature/{分支名}/changelog/` 下的变更文件复制到 `db/dev/changelog/` 对应日期目录，并将快照并入 `db/dev/test.sql` 与 `db/dev/prod.sql`。

---

## 三、后端开发规范

### 3.1 代码风格

1. 避免不必要的对象复制或克隆。
2. 避免多层嵌套，优先使用**提前返回（Early Return）**。
3. 共享资源必须使用适当的并发控制机制（分布式锁、原子类等）。
4. **注释规范（强制）**：所有业务代码必须写注释，**禁止行尾注释**；类和方法用 Javadoc，作者统一 `qingfeng`；方法体内每行代码上方用单行注释说明业务逻辑，逻辑复杂处用多行注释。
5. **代码间距（强制）**：方法之间、不同逻辑块之间保留空行隔开。
6. **大括号（强制）**：所有控制语句（`if`/`else`/`for`/`while`/`do`）执行体**必须用 `{}`**，即使只有一行。

### 3.2 Java 编码规范（严格执行）

1. **流式编程优先**：集合操作优先 Stream + Lambda，禁止显式 `for` 循环处理集合。
2. **Builder 构建对象**：实体类统一 `@Builder`，非必要**禁止 new + setter**；写代码前先确认目标类是否有 `@Builder`，没有则补上。
3. **构造器注入**：Spring Bean 必须**构造器注入**，禁止字段 `@Autowired`。
4. **Hutool 优先**：判空、字符串、集合操作优先用 `hutool`，减少手写 `if (obj == null)`。
5. **Optional 替代 null 检查**：`Optional.ofNullable().orElseThrow()` 等链式调用。
6. **积极使用当前 JDK 版本新特性（强制）**：按项目 JDK 版本充分利用新 API，禁止旧式写法替代已有新 API：
   - 集合工厂：`List.of()`、`Set.of()`、`Map.of()`、`Map.entry()`
   - Optional 增强：`or()`、`ifPresentOrElse()`、`stream()`
   - Stream 增强：`Stream.ofNullable()`、`takeWhile()`、`dropWhile()`、`iterate()`
   - String 增强：`isBlank()`、`strip()`、`lines()`、`repeat()`
   - `var` 局部变量类型推断
   - `Files.readString()` / `Files.writeString()`
   - `java.net.http.HttpClient` 替代第三方库做简单 HTTP 请求
   - JDK 17/21 可用 Record、Sealed Class、Pattern Matching
7. **Lambda 内计数用 `AtomicInteger`**：禁止在 Lambda 内修改普通 `int` 变量。
8. **MyBatis-Plus Lambda 条件写法**：条件判断内联在链式调用中，如 `.eq(condition, Entity::getField, value)`。
9. **禁止内联包名**：所有类必须顶部 `import`，禁止 `new com.example.Foo()` 写法。

### 3.3 接口设计规范

1. 业务接口按 `module` 模块划分，每模块独立 `controller` 包，模块间功能独立、互不耦合。
2. **开发顺序**：先搭后端接口并定义好响应规范 → 再开发前端，前后端数据结构严格一致。
3. 所有查询接口**禁止连表查询**，必须拆分为**单表批量查询 + 内存组装**。

### 3.4 性能规范（强制，违反一处即严重性能缺陷）

- **禁止 N+1 查询**：禁止在 Stream 或循环内调用任何单条数据库查询（`selectById`、`selectOne`、含单个固定值的 `selectList` 等）。
- **列表接口五步范式（必须遵循）**：
  1. 主查询（分页/全量）获取主记录列表；
  2. `Stream + Collectors.toSet()` 提取所有关联外键 ID 并去重；
  3. 每类外键 ID 执行一次批量查询（`selectBatchIds` 或 `IN`），每种关联只查一次；
  4. `Collectors.toMap(Entity::getId, e -> e)` 构建内存索引 Map；
  5. 组装阶段所有关联数据从内存 Map 取值（`map.get` / `map.getOrDefault`），禁止触发任何额外查询。
- **禁止 N 次 COUNT**：统计关联数量时一次性查出全部关联记录，用 `Collectors.groupingBy + Collectors.counting()` 内存统计。
- **详情接口子列表批量化**：子列表 ID 一次性收集后批量查询，禁止逐条主记录循环触发子查询。
- **同语义数据只查一次**：同一请求内相同语义数据集合只查一次，结果赋变量复用；语义不同（如全局视角 vs 个人视角）必须分别查询。
- **OR 条件必须合并**：同一张表多个 OR 条件查询必须合并为一次带 `or()` 的查询。
- **仅查必要字段**：查询目的仅为收集 ID 时，必须 `.select(Entity::getId)`，禁止 `SELECT *` 后只取 ID。
- **慢 SQL 监控强制接入**：MyBatis Interceptor 慢 SQL 拦截器，阈值 500ms，超阈值输出 WARN 日志并携带 Mapper 方法全名。

### 3.5 参数校验规范（Bean Validation，强制执行）

- **声明式优先**：优先使用 Bean Validation 注解，禁止在 Service 层用 `if` 手动校验可声明化的格式/空值规则。
- **Controller 必须开启校验**：所有 `@RequestBody` / `@RequestParam` 参数必须加 `@Validated` 或 `@Valid`。
- **常用注解速查**：

  | 注解                      | 适用场景                                     |
  | ------------------------- | -------------------------------------------- |
  | `@NotNull`                | 对象/包装类型不为 null                       |
  | `@NotBlank`               | 字符串不为空串或纯空白（字符串字段优先用此） |
  | `@NotEmpty`               | 集合/数组/字符串不为空                       |
  | `@Size(min, max)`         | 字符串长度或集合大小范围                     |
  | `@Min` / `@Max`           | 数值最小/最大值                              |
  | `@Range(min, max)`        | 数值范围（Hibernate Validator 扩展）         |
  | `@Pattern(regexp)`        | 手机号、邮编等正则校验                       |
  | `@Email`                  | 邮箱格式                                     |
  | `@Future` / `@Past`       | 时间方向约束                                 |
  | `@Positive` / `@Negative` | 数值正负约束                                 |

- **嵌套对象级联校验**：DTO 嵌套对象字段必须加 `@Valid`。
- **分组校验**：新增与更新复用同一 DTO 时用 `@Validated(Create.class)` / `@Validated(Update.class)`。
- **自定义校验注解**：无法用标准注解表达的业务规则（枚举合法性、编码唯一性等）封装为自定义 `@Constraint` 注解，禁止 Service 层散落 if 判断。
- **统一异常处理**：`MethodArgumentNotValidException` 和 `ConstraintViolationException` 必须在 `GlobalExceptionHandler` 统一捕获，以标准 `ResponseDTO` 格式返回，禁止原始异常暴露给前端。
- **message 必须中文可读**（如"手机号不能为空"），禁止框架默认英文提示。
- **Service 层不重复校验**：格式/空值校验不在 Service 层重复；业务状态校验（记录存在、状态流转合法性）仍在 Service 层抛 `BizException`，两层职责分离。

### 3.6 分层架构规范（四层架构，强制执行）

`Controller → Service → Manager → Dao`，禁止跨层调用：

| 层次           | 包名          | 核心职责                                                     | 禁止事项                                                     |
| -------------- | ------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **Controller** | `controller/` | 接收 HTTP 请求、参数校验、权限注解、调用 Service、返回 `ResponseDTO` | 禁止写业务逻辑；禁止直接调用 Dao 或 Manager                  |
| **Service**    | `service/`    | 业务逻辑编排：事务控制、业务规则判断、跨 Manager 数据组装、状态流转 | 禁止直接操作 Dao（通过 Manager 间接访问）；禁止写与业务无关的通用查询逻辑 |
| **Manager**    | `manager/`    | 通用数据访问封装：**必须继承 `ServiceImpl<XxxDao, XxxEntity>`**，封装复用性高的单表/多表查询、批量操作，供多个 Service 复用 | 禁止写业务判断逻辑；禁止调用其他模块的 Service；禁止绕过 Manager 直接在 Service 中调 Dao |
| **Dao**        | `dao/`        | 数据库操作接口（MyBatis Plus `BaseMapper` 扩展），仅做数据存取 | 禁止写业务逻辑；复杂 SQL 使用 Mapper XML，禁止 Java 代码拼接 SQL |

- **禁止跨层调用**：Controller 不得直接调 Manager 或 Dao；Service 不得直接调 Dao。
- **Manager 必须继承 `ServiceImpl`**：天然具备 `saveBatch`、`listByIds` 等通用能力。
- **Service 之间可以互调**：注意事务边界和循环依赖。
- **Dao 仅由 Manager 持有**：其他层不得注入 Dao。
- **命名**：Manager 类 `{业务名}Manager`；Manager 方法以数据视角命名（`getByOrderId`、`batchGetByIds`、`listByUserId`），禁止业务语义命名（`checkUserCanRefund` 属业务逻辑，应在 Service）。

典型示例：

```java
// ✅ OrderManager.java —— 继承 ServiceImpl，构造器注入 Dao
@Service
public class OrderManager extends ServiceImpl<OrderDao, OrderEntity> {

    private final OrderDao orderDao;

    public OrderManager(OrderDao orderDao) {
        this.orderDao = orderDao;
    }

    /**
     * 按支付订单号查询订单
     *
     * @param payOrderId 支付订单号
     * @return 订单实体
     * @author qingfeng
     */
    public OrderEntity getByPayOrderId(String payOrderId) {
        // 按主键查询订单
        return orderDao.selectById(payOrderId);
    }
}

// ✅ OrderService.java —— 调 Manager，专注业务逻辑
public OrderVO queryDetail(String payOrderId) {
    // 通过 Manager 获取订单实体
    OrderEntity order = orderManager.getByPayOrderId(payOrderId);
    // 通过 Manager 批量查商品项
    List<OrderItemEntity> items = orderItemManager.listByPayOrderId(payOrderId);
    // 业务逻辑：组装 VO
    return buildOrderVO(order, items);
}

// ❌ 错误：Service 直接调 Dao
OrderEntity order = orderDao.selectById(payOrderId);
```

> 存量代码兼容说明：项目中存在部分早期代码 Service 直接调 Dao（历史遗留），**新增代码必须严格遵循四层规范**；重构时优先补充 Manager 层并迁移 Dao 调用。

### 3.7 接口返回类型：VO vs Entity 按需选择

**原则：按需选择，不强制用 VO，但需要关联名称时必须用 VO。**

| 场景                                    | 推荐返回类型                        | 说明                                                   |
| --------------------------------------- | ----------------------------------- | ------------------------------------------------------ |
| 简单单表 CRUD，无关联数据需要展示       | Entity 直接返回                     | 可接受                                                  |
| 需要展示关联名称（如 appName、apiName） | VO 继承 Entity，追加 `xxxName` 字段 | **必须用 VO**，禁止返回裸 Entity                       |
| 分页列表接口含外键 ID                   | VO，预先规划所有 `xxxName` 字段     | 设计 VO 时一次性把所有 Name 字段加齐，避免反复改造     |
| 详情接口含子列表                        | VO 包含子列表字段                   | 子列表同样适用五步范式                                 |

```java
// ✅ VO 继承 Entity，追加名称字段
@Data
@EqualsAndHashCode(callSuper = true)
public class XxxVO extends XxxEntity {
    /** 关联应用名称（批量查询组装）*/
    private String appName;
    /** 关联 API 名称（批量查询组装）*/
    private String apiName;
}
```

---

## 四、数据库设计规范

### 4.1 表结构基础规范

1. **三个基础字段必须齐全**：

   ```sql
   `id`          int UNSIGNED  NOT NULL AUTO_INCREMENT                           COMMENT '主键ID',
   `create_time` datetime      NOT NULL DEFAULT CURRENT_TIMESTAMP                COMMENT '创建时间',
   `update_time` datetime      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
   ```

   > 主键可用自增 `int UNSIGNED` 或雪花算法 `bigint`，**禁止字符串类型主键**。

2. **日期类型统一 `datetime`**：禁止 `timestamp`（2038 问题/时区）、`date`（丢时分秒）、`int` 时间戳。
3. **Java 层日期统一 `LocalDateTime`**：禁止 `java.util.Date`、`java.sql.Timestamp`。
4. **日期字段必须加格式化注解（强制）**：两个注解缺一不可：

   ```java
   @DateTimeFormat(pattern = "yyyy-MM-dd HH:mm:ss")
   @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss", timezone = "GMT+8")
   private LocalDateTime createTime;
   ```

### 4.2 命名规范

- **表名**：`模块前缀_业务名`，全小写 snake_case（如 `sys_user`、`biz_order`）。
- **字段名**：全小写 snake_case，禁止驼峰和大写字母。
- **布尔字段**：`is_` 前缀 + `tinyint(1)`，0 = 否，1 = 是（如 `is_enable`、`is_delete`）。

### 4.3 其他规范

- **字段注释必须填写**：所有字段加 `COMMENT`，枚举字段须在注释中列举所有枚举值及含义（`COMMENT '状态: 0-禁用, 1-启用'`）。
- **逻辑删除优先**：业务核心数据用逻辑删除（`is_delete` 字段），禁止直接物理删除。

---

## 五、前端开发规范

### 5.1 数据单一来源规范（强制，违反即不合格产出）

**核心原则：任何业务数据只能有一个权威来源，所有展示层必须从该来源读取，禁止一切形式的硬编码复制。**

1. **禁止前端硬编码业务数据**：所有来自后台配置的数值、文案、规则（积分数值、枚举描述、费率、限制次数等）**必须通过接口动态获取**。
   - 违规示范：`<em>+10 分</em>`、`每日上限 8 次`（写死后台可配置的值）
   - 正确做法：调用配置接口（如 `enabledRules`），用 `rule.awardPoints`、`rule.dailyLimit` 动态渲染
2. **单一数据源（Single Source of Truth）**：后端配置表（如 `t_points_rule`、`t_sys_dict`、`t_config`）是唯一权威来源；前端展示、后端业务逻辑、接口响应三者均从同一数据源读取；配置变更只需改数据库，所有展示**自动生效**，**禁止改了数据库还要同步改代码**。
3. **禁止前端复刻后端枚举/配置**：禁止在前端定义与后端枚举或配置表对应的静态 Map/常量对象；如需本地缓存，必须运行时从接口加载后缓存，禁止编译期写死。
4. **必须动态读取的场景（禁止硬编码）**：积分规则（数值/上限/名称/是否需审核）、枚举描述文本（订单状态、业务类型、操作类型等）、费率/折扣/价格区间、菜单权限路径、任何后台可动态配置的参数。

### 5.2 响应式绑定与筛选联动规范

**规则一：禁止 `v-model` 直接绑定 `computed` 返回的对象属性**（computed 每次返回新对象，Vue 无法追踪属性修改，操作无效）：

```vue
<!-- ❌ 错误 -->
<a-switch v-model:checked="computedList[i].someField" />

<!-- ✅ 正确：独立响应式 Map，:checked + @change 驱动 -->
<a-switch
  :checked="stateMap[record.id]?.someField ?? false"
  @change="(val) => handleChange(record.id, val)"
/>
```

**规则二：多级筛选必须实现联动清空（强制）**，如「应用 → API」：

1. 上级变更时**自动清空下级已选值**（`query.xxxId = null`）；
2. 上级变更时**重新加载下级选项数据**；
3. 上级未选时下级**禁用**并显示提示文字。

```vue
<a-select v-model:value="query.appId" @change="onAppChange" />
<a-select
  v-model:value="query.apiId"
  :placeholder="query.appId ? '请选择API' : '请先选择应用'"
  :disabled="!query.appId"
/>

// onAppChange 必须执行两步
const onAppChange = (appId) => {
  query.apiId = null          // 清空下级
  loadApiOptions(appId)       // 重新加载下级选项
}
```

---

## 六、UI/UX 设计规范

1. 所有界面设计必须遵守 `ui-ux-pro-max` 规范，现代化风格，禁止过时设计元素。
2. **后台管理页面**：优先网格布局、卡片式布局、筛选器、排序器等复杂交互组件，禁止仅做简单列表和表格。
3. **前台/用户端页面**：符合用户使用习惯，功能丰富、视觉高端，避免简陋。
4. 页面交互设计必须符合完整业务逻辑，避免逻辑错误或前后不一致。
5. 功能模块设计必须结合真实业务场景，实现完整业务闭环；一个完整项目数据库表**不得少于 15 张**（最低要求）。
6. 前端所有表格列必须**居中展示**。
7. 所有枚举值必须展示对应的**描述文本**，优先从数据字典获取，**禁止前端硬编码枚举文案**。
8. 列表中如有 ID 字段关联名称，必须展示关联名称；查询条件中涉及关联 ID 的，必须改为**下拉选择框**，禁止让用户直接输入 ID。

**📋 开发前强制自查清单（每次开发列表/筛选页面前必过）**：

| 检查项                       | 检查方式                                 | 未通过处理                                 |
| ---------------------------- | ---------------------------------------- | ------------------------------------------ |
| 列表是否有 `xxxId` 字段？    | 逐列扫描 VO 字段                         | 后端 VO 补 `xxxName`，五步范式批量关联查询 |
| 枚举字段是否直接显示原始值？ | 检查 `status`、`type`、`strategy` 等字段 | 加 `<a-tag>` 转中文标签                    |
| 查询条件是否有 ID 类筛选项？ | 扫描 `query` 对象字段                    | 改为 `a-select`，`onMounted` 加载选项数据  |
| 多级筛选是否实现联动清空？   | 如「应用→API」                           | 上级变化时清空下级并重新加载               |

---

## 七、测试规范

1. **数据结构一致性验证**：优先检查前后端数据字段、结构、类型是否严格一致，发现不一致必须修复后再提测。
2. **功能完整性验证**：测试每个模块功能是否完善可用，业务逻辑是否符合产品设计意图。
3. **接口规范验证**：验证接口是否正常响应、返回格式是否符合 `ResponseDTO` 标准包装。

---

## 八、项目目录结构规范

### 8.1 后端（Spring Boot）

```
{root-package}
├── module/{module}/              # 业务模块，按领域划分
│   ├── controller/
│   │   ├── web/                  # 后台管理接口（/web/** 路由前缀）
│   │   └── front/                # 前台用户接口（/front/** 路由前缀）
│   ├── service/                  # 核心业务逻辑层
│   ├── manager/                  # 通用数据访问层（必须继承 ServiceImpl）
│   ├── dao/                      # 数据库操作层（继承 BaseMapper）
│   └── job/                      # 定时任务（可选）
├── domain/{module}/              # 领域模型，与 module/ 一一对应
│   ├── entity/                   # 数据库实体类
│   ├── vo/                       # 视图对象（返回前端）
│   ├── form/                     # 表单对象（接收前端入参）
│   ├── dto/                      # 数据传输对象（服务间传输）
│   └── enums/                    # 模块相关枚举类
└── config/                       # 全局配置类
```

> 多 Maven 模块项目可将 `domain/` 放基础模块、`module/` 放业务模块，包内层次不变。

命名要求：

| 类型         | 规范                     | 示例                                      |
| ------------ | ------------------------ | ----------------------------------------- |
| Entity       | `{Model}Entity`          | `OrderEntity`                             |
| VO           | `{Model}VO`（列表详情共用）| `OrderVO`、`OrderRefundVO`              |
| Form         | `{Model}{Action}Form`    | `OrderQueryForm`、`OrderRefundCreateForm` |
| Enum         | `{Model}{Field}Enum`     | `OrderStateEnum`                          |
| Controller   | `{Model}Controller`      | `OrderController`                         |
| Service      | `{Model}Service`         | `OrderService`                            |
| Manager      | `{Model}Manager`         | `OrderManager`                            |
| Dao          | `{Model}Dao`             | `OrderDao`                                |

### 8.2 前端管理后台（Vue3 + Ant Design Vue）

```
src/
├── api/            # 接口封装层：business/（业务）、support/（支撑）、system/（系统），下按模块分目录
├── views/          # 页面视图，与 api/ 目录对应
├── components/     # 全局共用组件：framework/、business/、support/、system/
├── constants/      # 常量定义：business/、support/、system/、common-const.js、index.js
├── router/         # 路由：index.js、routers.js、support/、system/
├── store/          # 状态管理
├── layout/         # 布局组件
├── lib/            # axios 封装、通用工具
├── config/         # 全局配置（接口地址等）
├── style/ theme/ i18n/ directives/ utils/
├── App.vue / main.js
```

### 8.3 前端用户端（Vue3 前台）

同上，额外包含 `useHooks/`（自定义 Composition API Hooks）。

### 8.4 前端命名规范

| 目录/文件类型 | 命名规范                             | 示例                                 |
| ------------- | ------------------------------------ | ------------------------------------ |
| 模块目录      | 全小写 kebab-case                    | `order/`、`goods/`                   |
| 页面文件      | `{module}-{action}.vue`              | `order-list.vue`、`order-refund.vue` |
| API 文件      | `{module}-api.js`                    | `order-api.js`                       |
| 常量文件      | `{module}.js` 或 `{module}-const.js` | `order.js`、`common-const.js`        |
| 路由文件      | `{module}.js`                        | `order.js`                           |

### 8.5 层应对关系

```
前端 Vue → Controller → Service → Manager → Dao → Entity/VO/Form (domain)
```

- `api/` 层：每模块一个 `xxx-api.js`，与后端 Controller 一一对应。
- `views/` 层：页面必须放入对应业务模块目录，禁止直接放 views/ 根目录。
- `constants/` 层：前端枚举常量必须放对应目录，禁止内嵌页面文件硬编码。

---

## 九、AI 助手协作规范（强制执行）

### 9.1 Skill 优先使用原则（强制）

接到任何技术任务，必须优先调用环境中已安装的专业 Skill，不得在已有匹配 Skill 的情况下仅凭直觉产出代码或方案。

两个强制调用节点：

| 阶段                                 | 规则                                                         |
| ------------------------------------ | ------------------------------------------------------------ |
| **出方案 / 分析 / 对比 / 评估阶段**  | 接到"如何设计"、"选哪个"、"对比 X 与 Y"、"推荐方案"、"架构设计"类问题，必须先调用对应 Skill 拿到专业框架再输出方案 |
| **实施 / 编码 / 修改阶段**           | 开工前必须扫描可用 Skill 列表，匹配后立即调用，按 Skill 设计原则动手 |

技术栈对应 Skill 清单（按任务类型查表，找到匹配行必须调用，多类型可叠加）：

**调研 & 分析类**

| 任务类型                    | Skill                                              |
| --------------------------- | -------------------------------------------------- |
| 代码库结构摸底 / 依赖梳理   | `codebase-onboarding`、`repo-scan`、`code-tour`    |
| 陌生仓库上手 / 环境检查     | `workspace-surface-audit`、`automation-audit-ops`  |
| 技术调研 / 方案搜索         | `search-first`、`deep-research`、`research-ops`、`exa-search` |
| 文档查阅 / 第三方库接口参考 | `documentation-lookup`                             |
| 竞品分析 / 市场研究         | `market-research`、`competitive-platform-analysis`、`benchmark-methodology` |
| 需求拆解 / 验收标准定义     | `intent-driven-development`、`product-lens`、`product-capability` |
| 多方案对比 / 重大技术决策   | `council`、`brainstorming`                         |
| 复杂架构 / 多步骤实施规划   | `blueprint`、`writing-plans`                       |

**后端开发类**

| 任务类型                       | Skill                                                |
| ------------------------------ | ---------------------------------------------------- |
| Spring Boot / Java 后端        | `springboot-patterns`、`java-coding-standards`、`jpa-patterns` |
| Spring Security / 认证授权     | `springboot-security`                                |
| Quarkus                        | `quarkus-patterns`、`quarkus-security`               |
| Kotlin 后端 / 协程 / Ktor      | `kotlin-patterns`、`kotlin-coroutines-flows`、`kotlin-ktor-patterns` |
| Kotlin ORM（Exposed）          | `kotlin-exposed-patterns`                            |
| Python 通用后端                | `python-patterns`                                    |
| Django / DRF                   | `django-patterns`、`django-security`、`django-celery` |
| FastAPI / Pydantic v2          | `fastapi-patterns`                                   |
| Go 后端                        | `golang-patterns`                                    |
| Node.js / NestJS               | `nestjs-patterns`、`backend-patterns`                |
| PHP / Laravel                  | `laravel-patterns`、`laravel-security`               |
| Rust 后端                      | `rust-patterns`                                      |
| C# / .NET                      | `dotnet-patterns`                                    |
| Android / KMP 架构             | `android-clean-architecture`                         |

**数据库 & 缓存类**

| 任务类型                     | Skill                 |
| ---------------------------- | --------------------- |
| MySQL / MariaDB 设计与优化   | `mysql-patterns`      |
| PostgreSQL                   | `postgres-patterns`   |
| Redis 缓存 / 分布式锁 / 限流 | `redis-patterns`      |
| ClickHouse                   | `clickhouse-io`       |
| 数据库迁移 / 零停机变更      | `database-migrations` |
| Prisma ORM                   | `prisma-patterns`     |

**API & 集成类**

| 任务类型               | Skill                              |
| ---------------------- | ---------------------------------- |
| REST API 接口设计      | `api-design`                       |
| 新增第三方 API 集成    | `api-connector-builder`            |
| MCP Server 构建        | `mcp-server-patterns`、`mcp-builder` |
| 错误处理 / 重试 / 熔断 | `error-handling`                   |
| 内容哈希缓存设计       | `content-hash-cache-pattern`       |

**前端开发类**

| 任务类型                         | Skill                                                        |
| -------------------------------- | ------------------------------------------------------------ |
| Vue 3 / Composition API / Pinia  | `vue-patterns`                                               |
| Nuxt 4 / SSR                     | `nuxt4-patterns`                                             |
| React 18/19 / Next.js            | `react-patterns`、`frontend-patterns`                        |
| Vite 构建配置                    | `vite-patterns`                                              |
| UI 组件样式（shadcn / Tailwind） | `ui-styling`                                                 |
| UI 设计 / 组件构建 / 样式优化    | `ui-ux-pro-max`、`frontend-design`、`make-interfaces-feel-better` |
| 动效 / 过渡动画                  | `motion-foundations`、`motion-patterns`、`motion-advanced`、`motion-ui` |
| 无障碍设计（WCAG 2.2）           | `accessibility`、`frontend-a11y`                             |
| Vue 截图转组件                   | `ui-to-vue`                                                  |

**测试类**

| 任务类型                       | Skill                                                |
| ------------------------------ | ---------------------------------------------------- |
| 通用 TDD 工作流                | `tdd-workflow`、`test-driven-development`           |
| Spring Boot 单元/集成测试      | `springboot-tdd`、`springboot-verification`         |
| Python 测试（pytest）          | `python-testing`                                     |
| React 组件测试                 | `react-testing`                                      |
| E2E 浏览器自动化（Playwright） | `e2e-testing`                                        |
| Web 应用本地功能验证           | `webapp-testing`、`browser-qa`                       |
| AI 回归测试                    | `ai-regression-testing`                              |
| 完成前验证（禁止空口声称通过） | `verification-before-completion`、`verification-loop` |
| 部署后金丝雀监控               | `canary-watch`                                       |

**代码审查 & 安全类**

| 任务类型                       | Skill                                  |
| ------------------------------ | --------------------------------------- |
| 代码审查（逻辑 Bug / SOLID）   | `code-review-expert`、`gateguard`       |
| 安全审查（认证 / 注入 / 密钥） | `security-review`、`security-scan`      |
| 高风险改动双智能体对抗验证     | `santa-method`                          |
| 生产就绪审计                   | `production-audit`                      |
| 接收 / 请求代码审查            | `receiving-code-review`、`requesting-code-review` |

**调试 & 故障诊断类**

| 任务类型                       | Skill                                            |
| ------------------------------ | ------------------------------------------------- |
| 任何 Bug / 测试失败 / 异常行为 | `systematic-debugging`（遇 Bug 必须先调用）      |
| 按钮/交互类隐性状态 Bug 追踪   | `click-path-audit`                               |
| 完整 Bug 修复流程编排          | `orch-fix-defect`                                |
| 智能体流程失败诊断             | `agent-introspection-debugging`                  |

**工程工具 & DevOps 类**

| 任务类型                    | Skill                  |
| --------------------------- | ----------------------- |
| Git 分支策略 / 提交规范     | `git-workflow`          |
| GitHub Issue / PR / CI 管理 | `github-ops`            |
| Docker / Compose 容器化     | `docker-patterns`       |
| CI/CD 流水线 / 部署策略     | `deployment-patterns`   |
| Git Worktree 特性分支隔离   | `using-git-worktrees`   |

### 9.2 Skill 调用质量要求

1. **必须基于 Skill 输出的原则动手**，不能只调用不使用；Skill 中的 anti-pattern 必须避免。
2. 同一任务可多 Skill 叠加（如 `springboot-patterns` + `jpa-patterns` + `springboot-security`）。
3. 调用时传入具体任务描述，不能只传空参数。
4. 被用户提醒"没用 skill"等于本次产出失败，需重新带 Skill 产出。

### 9.3 会话起始检查项

- [ ] 本会话可用的 Skill 有哪些？
- [ ] 本任务匹配哪个 Skill？
- [ ] 项目记忆中是否已记录用户偏好与项目约定？
- [ ] 本规范中是否有与任务相关的强制条款？

### 9.4 例外情况（允许不调用 Skill）

- 纯读取文件、查看目录结构、查看 git 状态等信息型查询
- 单一字段改名、拼写错误修正、一行改动
- 用户明确说 "just do it" / "直接改" / "不用调 skill"

### 9.5 违反后果

违反本节规范产出的代码/方案为**不合格产出**，必须重新调 Skill 后重做。
