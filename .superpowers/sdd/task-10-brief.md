# Task 10（S0 切片）裁定基准 —— kb_search/kb_read 绑定收敛 + 孤绑定门控

> 分支 `feature/agent_run_logs_20260908`（KB 线我 + PG 线用户共工作树）· 基线 HEAD 5c774804（T9）
> 用户裁定：**先做 S0 绑定收敛切片**（安全硬化优先），S2 expand=section/graph、S3 rerank 留后续切片
> plan L808-820 · spec §6 检索管线 L166-180 + §8 决策点1 L240-244 · 继承 T9 延后 P3-1/P3-4余

---

## 一、切片范围（IN / OUT）

**IN（S0 绑定收敛，本次交付）**
1. `kb_search` scope 从「人侧 accessible_kbs」收敛为「Agent 绑定库集合 ∩ kb_id」。
2. `kb_read` scope 同步收敛（spec L241「kb_search/kb_read 工具链一期均按此语义」；T9 显式延后至 T10）。
3. P3-1 孤绑定门控：`_collect_kb_tools` 按**解析后 spaces**（绑定库 ∩ 现存库）门控，非 raw bound_ids。
4. 迁移既有人侧 ACL 测试 → 绑定模型；补 dual/孤绑定测试（P3-4余）。

**OUT（后续 T10 切片，本次不碰）**
- S2 `expand=section`（同 heading_path 父子合并）、`expand=graph`（kb_links 出入链摘要）。
- S3 `rerank`（qwen3-rerank 精排，凭证缺失降级）。
- 严格模式（Agent 检索 ∩ 对话人可见库）——spec L243 明示一期不开启，仅预留。

---

## 二、架构裁定（R1~R8）

- **R1 绑定即授权（scope 语义）**：agent 工具链检索可见域 = `set(await list_bound_space_ids(agent_id))`，**不叠加**对话人 `can_access`（spec §8 决策点1）。人侧 HTTP `/api/kb/search` 走 routers 既有 can_access，**不在本次改动面**。
- **R2 kb_id ∩ 绑定**：kb_id 指定 → 必须 ∈ bound_ids **且**库存在才检索；否则合并错误（不区分「不存在」/「未绑定」，不泄露存在性，沿用 T9 kb_read P3-2 保守裁定）。kb_id 空 → 检索全部绑定库、按 score 融合降序（tool.py L109-114 既有融合逻辑不变，仅换 scope 来源）。
- **R3 S0 先于 S1（强制断言，spec L306/L320）**：收敛必须在 `svc.search` 之前完成；测试用 spy 断言 `svc.search` 从未以未绑定 kb_id 被调用 → 证明「先过滤后检索，杜绝越权召回」。
- **R4 agent_id 注入 = 构造期传参 + 运行期重解析**：`make_kb_search_tool(service=None, agent_id="")` / `make_kb_read_tool(service=None, agent_id="")`；`_collect_kb_tools` 传 `make_kb_search_tool(svc, agent_id)`。工具**每次调用**重跑 `await list_bound_space_ids(agent_id)`（安全新鲜度：绑定撤销下次调用即生效，不用 build 期快照）。
- **R5 kb_read 收敛**：doc → `get_document_meta` → `meta.kb_id` → 断言 ∈ bound_ids；不在则合并拒绝（替换 T9 的人侧 `can_access`）。
- **R6 P3-1 孤绑定门控**：`_collect_kb_tools` 先算 `spaces = [kb for kb in svc.list_kbs() if kb.id in bound]`，再 `if not spaces: return [], ""`（绑定库全删→不注册不注入，目录空且工具缺席）；替代 T9 的 `if not bound_ids`（raw）早退。
- **R7 `_current_identity` 保留不删**：一期不再用于 scope，标注为未来严格模式（∩ 人可见库）预留；避免删掉 RBAC 解析逻辑（strict mode 需复用）。仅确保无 unused-import lint。
- **R8 冲突面最小化**：S0 scope 组合全部落 **tool.py**（`list_bound_space_ids` + 既有 `svc.list_kbs/get_kb/search` 已足），**不改 service.py**（PG 线高概率触碰）。builder.py 含用户 WIP → P3-1 改动走 git add -p hunk 分离（复用 T9 成功范式）。

---

## 三、共享文件冲突协议（沿用 T9 §五成功范式）

1. 提交前 `git status --short` 核实：tool.py/test_*.py 应为纯我方改动；builder.py 若仍 ` M`（用户 WIP）→ git add -p 逐 hunk 只暂存我方 P3-1 hunk。
2. `.qoder` 128 预暂存删除：`git reset HEAD -- .qoder` 隔离 → 裸 commit → `git add -A -- .qoder` 还原。
3. 审查轮 amend 用 `--only -- <我方文件>`；builder.py 若入首轮提交则 amend 不触碰（`git diff <base> HEAD -- builder.py` 核验）。
4. 核验提交版：`git show HEAD:<file>` 经 python subprocess 干净写出（utf-8 + newline \n）再 ast.parse+flake8，**禁 PowerShell Out-File/>**（管道损坏致 F821/E501 误报）。

---

## 四、验收标准（AC1~AC4）

- **AC1 越权查不到 + S0 先于 S1**：Agent 绑定库 A，查未绑定库 B（无论 kb_id 指定或融合）→ B 的文档绝不出现；spy 证明 `svc.search` 从未以 B.id 被调用。
- **AC2 多库融合按分排序**：Agent 绑定 A+B，不指定 kb_id → 命中跨 A/B 按 score 降序融合（沿用既有排序）。
- **AC3 孤绑定门控**：绑定库全被删 → `_collect_kb_tools` 返回 `([], "")`，不注册 kb_search/kb_read、不注入目录。
- **AC4 kb_read 收敛 + dual**：doc 所属库 ∈ 绑定才可读，否则合并拒绝；dual 后端 read_document 返回重建全文正常。

---

## 五、测试计划（Step1 红 → Step3 绿）

- **新建 `tests/unit/app/kb/test_kb_search_tool.py`**（plan L812 指定）：S0 绑定套件——AC1 越权+spy(S0先于S1) / AC2 多库融合 / kb_id∩绑定命中 / kb_id 未绑定合并拒绝 / 空绑定 / dual 后端检索。
- **迁移 `test_kb.py` L204-266**：`test_kb_search_tool_acl`（人侧 _current_identity）+ `test_kb_search_tool_no_bases` → 移入新文件重写为绑定模型（删除 test_kb.py 中该 2 例，避免人侧/绑定双模型混淆）。
- **更新 `test_kb_wiring.py`（T9）**：kb_read 用例从 human can_access → 绑定 scope（AC4）；AC2 wiring 构造传 agent_id。
- **builder P3-1 孤绑定门控测试**：test_kb_wiring.py AC2 区补「绑定库全删→([], "")」用例（AC3）。

> 环境钉桩沿用 T8/T9：autouse `_json_backend` fixture 清 `QWENPAW_STORAGE_BACKEND`/`QWENPAW_PG_DSN`；dual/pg 分支测试显式设后端。

---

## 六、提交纪律

点名提交（禁 add -A / commit -am，plan L22 + 用户长期约定）；Conventional Commits：`feat(kb): converge kb_search/kb_read to agent-binding ACL + orphan-binding gating（T10-S0）`。
