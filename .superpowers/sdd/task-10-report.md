# Task 10（S0 切片）完成报告 —— kb_search/kb_read 绑定收敛 + 孤绑定门控

> 分支 `feature/agent_run_logs_20260908` · HEAD **48b5bb50**（父 = T9 5c774804）
> 复审门裁定：**达标（PASS，无 P0/P1/P2）** · 6 文件 423+/130- · builder.py 与用户 PG 线 WIP 并发零冲突
> plan L808-820 · spec §6 L166-180 + §8 决策点1 L240-244 · 裁定基准 task-10-brief.md（R1~R8）
> 用户裁定：**先做 S0 绑定收敛切片**（安全硬化优先），S2 expand / S3 rerank 留后续切片

---

## 一、T10-S0 交付内容

**本质**：把 agent 检索工具链的「可检索范围」判定，从**对话人身份可见库**收敛为**agent 绑定库集合**（绑定即授权），先过滤后检索，杜绝越权召回。

- **tool.py `make_kb_search_tool(service, agent_id)`**：候选库 = `list_bound_space_ids(agent_id) ∩ kb_id`；每次调用重解析绑定（撤销即时生效）；未绑定/不存在合并 not-found。
- **tool.py `make_kb_read_tool(service, agent_id)`**：doc 所属库必须 ∈ 绑定集才可读；未绑定视同不可见，合并 not-found（不泄露存在性）。
- **builder.py `_collect_kb_tools`**：补 P3-1 孤绑定门控——按解析后 `spaces`（绑定库 ∩ 现存库）门控而非 raw `bound_ids`，绑定库全删则不注册工具、不注入目录；工具构造期注入 `agent_id`。
- **人侧 HTTP `/api/kb/search` 不变**：仍走既有 `can_access` ACL，本次仅收敛 agent 工具链。

**OUT（后续切片）**：S2 `expand=section|graph`、S3 `rerank`、严格模式（∩ 对话人可见库，spec L243 预留）。

---

## 二、关键架构裁定（R1~R8 摘要）

- **R1 绑定即授权**：agent 工具链可见域 = 绑定集，**不叠加**对话人 can_access（spec §8 决策点1）；`_current_identity` 保留供未来严格模式复用（R7），一期不用于 scope。
- **R2/R5 合并 not-found**：kb_id/doc 未绑定与不存在合并同一提示，不泄露库存在性与绑定态（延续 T9 kb_read P3-2 保守裁定）。
- **R3 S0 先于 S1**：收敛在 `svc.search` 之前，spy 断言引擎从未以未绑定 kb_id 被调用（spec L306/L320 强制断言）。
- **R4 绑定新鲜度**：工具每次调用重解析 `list_bound_space_ids`，绑定撤销下次调用即生效（非构造期快照）。
- **R6 P3-1 孤绑定门控**：`_collect_kb_tools` 按解析后 spaces 门控，覆盖 T9 延后项。
- **R8 冲突面最小化**：S0 scope 组合全落 tool.py（`list_bound_space_ids` + 既有 `svc.list_kbs/get_kb/search`），**不改 service.py**（PG 线高概率触碰）；仅 builder.py 需 hunk 分离。

---

## 三、审查闭环（SDD 独立门）

| 轮次 | 结论 | 要点 |
| --- | --- | --- |
| 复审（故障诊断工程师） | **达标 PASS** | R1~R8 全部正确实现；收敛先于检索/合并错误不泄露/绑定撤销即时生效 经代码审查+实验验证；AC1~AC4 均有测试且全绿；无 P0/P1/P2 |

### 已折叠（本轮 amend，receiving-code-review 逐条评估）
- **P3-1**：AC2 测试原用相同文本致 score 相等、排序不可观测 → 改灌相关度不同文本（A 短高频 / B 长单次），正则提取 score 序列断言严格降序。
- **P3-2**：补「绑定集含已删库 X + 显式 `kb_search(kb_id=X)`」用例 → `get_kb` 返 None 合并 not-found，且 spy 证明不触发引擎（builder 全孤绑定门控不覆盖此部分孤绑定路径）。
- **P3-3**：补 R4 绑定撤销即时生效回归守护（同一工具实例两次调用间 `current.clear()` → 第二次即 "no bound"）。

### 书面记录偏差（据理 push back，非硬修）
- **P3-4** dual kb_search 工具测：复审自陈「工具层对后端透明、dual 路由已由 test_service_facade.py 覆盖」= 低价值。已在 test_kb_search_tool.py 模块 docstring 记录偏差理由（工具层仅调 `svc.search`/`svc.list_kbs`，dual/pg 路由由 facade 测覆盖，含本切片新增 dual read_document 重建测），不重复测后端路由。

---

## 四、验证证据

| 项 | 结果 |
| --- | --- |
| kb 单测（test_kb_search_tool 8 + wiring 13 + facade dual 1 新增/迁移） | **249 passed** |
| runtime 单测（builder P3-1 门控 + 零回归） | **102 passed, 1 skipped** |
| TDD 红（改造前） | **11 failed 8 passed**（精准红：kb_search 6 + kb_read 4 + 孤绑定门控 1，无误伤） |
| flake8（6 文件 + 提交版 builder.py 干净检出） | **exit 0** |
| black -l 79 | **clean** |

---

## 五、⚠️ 并发冲突处理（本次成功规避，复用 T9 范式）

工作树极活跃（用户 PG/cron/skill 多线，~90 改文件 + 大量未跟踪）。T10-S0 6 文件中仅 **builder.py** 与用户 WIP 共存：

1. **纯我方文件核实**：tool.py/test_kb*.py/test_service_facade.py 逐文件核 hunk 头，全部落我编辑区（无用户 WIP 混入）→ `git add` 整体暂存。
2. **builder.py `git add -p` hunk 级分离**：11 hunk（用户 9 @L125-558 + 我 2 @L1036/L1059），应答序列 `n×9,y,y`，**仅暂存我的 2 hunk**；双向核验 staged=我的 2、unstaged=用户 9。
3. **`.qoder` 128 预暂存删除**：`git reset HEAD -- .qoder` 隔离 → 裸 `git commit` 纯 6 文件 → `git add -A -- .qoder` 还原用户暂存态。
4. **审查轮 amend `--only`**：`git commit --amend --only -F <msg> -- test_kb_search_tool.py` 仅更新 1 文件，builder.py 零触碰（`git diff 0d57251d HEAD -- builder.py`=0）、.qoder 不入提交。
5. **提交版自洽核验**：`git show HEAD:builder.py` 经 python subprocess 干净写出 → ast.parse OK + flake8 exit 0 + `if not spaces:`（P3-1 门控）在位（不依赖用户 WIP）→ clean clone 可用。

**本次踩坑（已记入记忆）**：`git commit --amend --only -- <path> -F <msg>` 参数顺序错误——`--` 之后的 `-F <msg>` 被当成 pathspec 致 amend 失败（exit 1）。正确顺序：`-F <msg>` 必须在 `--` **之前**（`git commit --amend --only -F <msg> -- <path>`）。失败未损任何状态，纠正后即成功。

---

## 六、变更文件（6）

- 新建：`tests/unit/app/kb/test_kb_search_tool.py`（8 例绑定收敛套件）
- 改：`src/qwenpaw/app/kb/tool.py`（kb_search/kb_read +agent_id +绑定收敛）、`src/qwenpaw/runtime/builder.py`（_collect_kb_tools P3-1 门控 + agent_id 注入）、`tests/unit/app/kb/test_kb.py`（移除 2 例人侧 ACL kb_search 测试）、`tests/unit/app/kb/test_kb_wiring.py`（kb_read 迁绑定 scope + AC3 孤绑定门控）、`tests/unit/app/kb/test_service_facade.py`（+dual read_document 重建）

---

## 七、下一任务

**T10 后续切片**：S2 `expand=section`（同 heading_path 父子合并）/ `expand=graph`（kb_links 出入链摘要，引导 kb_read）/ S3 `rerank`（qwen3-rerank，凭证缺失降级 RRF）。或 **T11 人侧 API 扩展**（文档 CRUD / 上传 / chunk 预览 / search-test，plan L824-835）。T10-S0 已闭环，无遗留阻断项。
