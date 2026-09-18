# Task 9 完成报告 —— Agent 接入：目录注入 + 工具注册门控 + kb_read

> 分支 `feature/agent_run_logs_20260908` · HEAD **5c774804**（父 = T8 47877b32）
> 复审门裁定：**达标（PASS，无 P0/P1）** · 8 文件 611+/14- · builder.py 与用户 PG 线 WIP 并发零冲突
> plan L761-804 · spec §7 · 裁定基准 task-9-brief.md（R1~R12）

---

## 一、T9 交付内容

**本质**：把「Agent 有绑定库」变成运行时可自主检索的装备——按 `agent_kb_bindings` 注入知识库目录到 system prompt，工具注册从「任意库存在即注册」收紧为「有绑定才注册」，并新增 `kb_read` 拉权威全文。

- **catalog.py**（新）：`render_kb_catalog(spaces)` → `<knowledge-bases>` 块（id/name/description + 「必须先调用 kb_search」引导语），空列表返 `""`。
- **builder._collect_kb_tools**（改 async）：查 `list_bound_space_ids(agent_id)`，非空才注册 `kb_search`+`kb_read` 并产出目录块，经 `ctx.extras["kb_catalog"]` 流转（仿 driver_prompt_hints 先例）。
- **prompt_contributors.KbCatalogContributor**（新）：从 `ctx.extras["kb_catalog"]` 取块注入 prompt，空串返 None（零注入）。
- **tool.make_kb_read_tool**（新）：`kb_read(doc_id)` 拉权威 MD 全文，ACL 与 kb_search 人侧一致。
- **service.read_document / get_document_meta / _pg_get_document**（新）：三态门面（pg=content_md 权威；json=切片按 seq 重建；pg 就绪即权威不复活，不可用 fail-soft 回退）。

---

## 二、关键架构裁定

- **R1 注入通道 = prompt_contributors（driver_prompt_hints 先例），非中间件 hook。** 已确认 skills 走 `Toolkit(skills_or_loaders)` 对象注入（AgentScope 自渲），KB 目录不搭 skills 车；本仓既有「工具采集顺带产出 prompt 块」范式 = driver_prompt_hints（`ctx.extras` → contributor 渲染），KB 目录同构，新增 `KbCatalogContributor`（priority 87，紧邻 driver 88）。契合 plan 首选「向 prompt 渲染追加 kb_catalog」而非 fallback hook。
- **R6 kb_read ACL 最小守卫**：复用人侧 `can_access`（get_document_meta 解析所属库 → get_kb → can_access），不比现 kb_search 弱；完整绑定 S0 收敛明确划归 T10。
- **R5 json 重建保真**：遗留 JSONL 无独立 MD 源，从切片重建是诚实 best-effort；chunk_text 的 ~100 字符 overlap 使多切片重建边界处少量重复（已 docstring 文档化，pg content_md 权威无此问题）。

---

## 三、审查闭环（SDD 独立门）

| 轮次 | 结论 | 要点 |
| --- | --- | --- |
| 复审（故障诊断工程师） | **达标 PASS** | 无 P0/P1；绑定门控/注入链闭合/kb_read 三态/async 改造 均正确；doc→kb 映射 space_id→kb_id 正确 |

### 已折叠（本轮 amend）
- **P2-1**：read_document docstring 明确 json 多切片重建 overlap 边界重复为已知限制 + 补多切片重建完整性测试。
- **P3-4**：补空 doc_id 守卫测试。

### 登记 T10（复审认可非阻断）
- **P3-1** 孤绑定门控（绑定库全删时工具仍注册但目录空）：T7 delete_space 已回收绑定（孤绑定罕见），T10 S0 收敛按解析后 spaces 门控自然覆盖。
- **P3-2** kb_read 错误消息合并 not-found/no-access：**刻意保留**——不向无权调用方泄露资源存在性（安全保守，receiving-code-review 据理 push back）。
- **P3-3** broad except 日志级别：沿用 _collect_kb_tools 既有模式，纯风格。
- **P3-4 余** dual 后端 read_document、孤绑定测试 → T10。

---

## 四、验证证据

| 项 | 结果 |
| --- | --- |
| kb 单测（catalog 5 + wiring 12 + facade pg 3 新增） | **241 passed** |
| runtime 单测（builder async 改造 + prompt_contributors 零回归） | **102 passed, 1 skipped** |
| flake8（8 文件 + 提交版 builder.py 干净检出） | **exit 0** |
| black -l 79 | **clean** |

---

## 五、⚠️ 并发冲突处理（本次成功规避，值得沉淀）

builder.py 含用户 PG 线**未提交 WIP**（54 行纯新增，L125-554），T9 必须改它。规避全程无损：

1. **区域不相交核实**：T9 的 5 处改动（HEAD L413/436/588/992/1016）与用户 WIP（L125-554）逐 hunk 核实不相交；SearchReplace 精确匹配我区域唯一文本，磁盘文件同时含两者但互不干扰。
2. **`git add -p` hunk 级精准暂存**：应答序列 `n×8,y,y,n,y,y,y`（14 hunk：用户 9 + 我 5），**仅暂存我的 5 hunk**，用户 WIP 全程留工作树未暂存（index-only 操作，工作树零改动 = 用户 WIP 零风险）。双向核验：staged=我的 5 hunk、unstaged=用户 9 hunk。
3. **`.qoder` 预暂存删除排除**：提交前发现索引含用户 128 个 `.qoder` staged 删除（T8 遗留），`git reset HEAD -- .qoder` unstage → 裸 `git commit` 提交纯 8 文件索引 → `git add -A -- .qoder` 还原用户暂存态。
4. **审查轮 amend 用 `--only`**：`git commit --amend --only -- service.py test_kb_wiring.py` 仅更新 2 文件，builder.py 不被触碰（`git diff aa093bba HEAD -- builder.py`=0 验证）、.qoder 不入提交。
5. **提交版自洽核验**：`git show HEAD:builder.py` 经 python 干净写出 → ast.parse OK + flake8 exit 0 + `active` 有定义（不依赖用户 WIP）→ clean clone 可用。

**关键教训**：共享文件提交，`git add -p` hunk 级分离是比 T8「事后 --only 补救」更优的**事前预防**；PowerShell `Out-File`/`>` 管道会损坏提取文件致 flake8 误报（F821/E501），核验提交版须用 python subprocess 干净读写。

---

## 六、变更文件（8）

- 新建：`src/qwenpaw/app/kb/catalog.py`、`tests/unit/app/kb/test_catalog.py`、`tests/unit/app/kb/test_kb_wiring.py`
- 改：`src/qwenpaw/app/kb/tool.py`（+make_kb_read_tool）、`src/qwenpaw/app/kb/service.py`（+read_document/get_document_meta/_pg_get_document）、`src/qwenpaw/runtime/prompt_contributors.py`（+KbCatalogContributor）、`src/qwenpaw/runtime/builder.py`（_collect_kb_tools async+门控+目录产出+接线）、`tests/unit/app/kb/test_service_facade.py`（+3 pg 分支测试）

---

## 七、下一任务

**T10 = kb_search 演进（kb_id/expand=section|graph/rerank/S0 绑定收敛）**（plan L808-820，可与 T9 并行，现 T9 已完成）。T9 延后项（P3-1 孤绑定门控、P3-4 dual/孤绑定测试）并入 T10 S0 收敛一并处理。
