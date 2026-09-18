# Task 9 裁定基准 —— Agent 接入：目录注入 + 工具注册改造 + kb_read

> 分支 `feature/agent_run_logs_20260908` · 父 HEAD **47877b32**（T8）
> plan：`docs/superpowers/plans/2026-09-17-knowledge-base-architecture.md` L761-804
> spec：`docs/superpowers/specs/2026-09-17-knowledge-base-architecture-design.md` §7（Agent 接入层）
> 依赖：T7 `list_bound_space_ids`（已交付 5df13c4c）、T2 spaces（name/description）、T8 门面三态

---

## 一、任务边界（严格对齐 plan，防越界到 T10）

**T9 做**：① `catalog.py` 目录渲染；② `_collect_kb_tools` 注册语义从「任意库存在即注册」→「Agent 有绑定才注册 `kb_search`+`kb_read` 并注入目录」；③ 新增 `kb_read(doc_id)` 工具；④ 目录块注入 system prompt。

**T9 不做（明确划给 T10）**：kb_search 内部 S0 绑定 ACL 收敛（`agent_kb_bindings ∩ kb_id`）、`expand=section/graph`、rerank、多库融合排序。**T9 不改 kb_search 的检索逻辑与 ACL 模型**，只改「是否注册」+「新增 kb_read」。

---

## 二、架构裁定（R1~R12）

- **R1 注入通道 = prompt_contributors（driver_prompt_hints 先例），非中间件、非 build_prompt 字符串拼接。**
  已确认 skills 走 `Toolkit(skills_or_loaders=skills)`（AgentScope 自渲，L184），KB 目录不搭 skills 车。本仓既有「工具采集顺带产出 prompt 块」范式 = `driver_prompt_hints`：`_collect_driver_tools_and_prompts` → `ctx.extras["driver_prompt_hints"]`（builder L491）→ `build_prompt` 经 `_get_driver_prompt_hints`（L644/L1044）→ `DriverPolicyHintContributor`（prompt_contributors L443-453）渲染。KB 目录同构，新增 `KbCatalogContributor`（priority 87，紧邻 driver 88），从 `ctx.extras["kb_catalog"]` 取串。**契合 plan 首选「向 prompt 渲染追加 kb_catalog」而非 fallback hook。**

- **R2 `catalog.py` API**：`render_kb_catalog(spaces: Sequence[KbSpace]) -> str`，空列表返回 `""`；输出 spec §7.2 模板 `<knowledge-bases>...<knowledge-base><id>..<name>..<description>...</knowledge-bases>`，含引导语「必须先调用 kb_search」。鸭子类型取 `.id/.name/.description`（兼容 KbSpace / KnowledgeBase）。

- **R3 `_collect_kb_tools` async 化**：`list_bound_space_ids` 是 async，调用点 L470 在 async build 流内 → 改 `async def` + `await`。逻辑：`bound = await list_bound_space_ids(agent_id)`；空 → 返回 `([], "")`（不注册不注入）；非空 → 取绑定空间的 name/description，注册 `kb_search`+`kb_read` 两工具（各经 `_wrap_tool`），渲染 catalog 块。

- **R4 注册语义变更**：现状 `if not get_kb_service().list_kbs(): return []`（任意库存在即注册）→ 改为「**该 Agent 有绑定库才注册**」。空绑定 Agent：工具不注册、prompt 不含 `<knowledge-bases>` 块（回归断言）。

- **R5 kb_read 数据源（三态）**：新增 `KbService.read_document(doc_id) -> Optional[str]`：pg 后端取 `kb_documents.content_md`（权威全文）；json/dual 后端从 chunks 按 doc_id 过滤、seq 排序、拼接 text（**遗留 JSONL 无独立 MD 源，chunk 重建是诚实的 best-effort**）；未命中返 None。

- **R6 kb_read ACL（最小守卫，不越界 T10）**：kb_read 复用现 kb_search 的人侧 `can_access`（`_current_identity()` → 解析 doc 所属 space → can_access），不可访问返错误 chunk、不泄漏正文。**完整绑定 S0 收敛仍是 T10**；T9 只保证「不按 id 裸取任意文档」。

- **R7 service.py 扩面正当性**：plan Files 未列 service.py，但 kb_read 必须经门面取全文（绕过门面直连 pg_store/engine 会破坏 T8「门面统一」）。service.py 是 T8 已提交、KB 线自有、当前干净 → 新增 `read_document` 无冲突、架构正确。

- **R8 json 后端 catalog 数据源**：`get_kb_service().list_kbs()`（registry）过滤到 bound ids，转 name/description。pg 后端同经门面（T8 已建三态）。

- **R9 逻辑外提，最小化 builder.py 触面**：绑定解析 + 目录渲染 + 工具装配的可测逻辑尽量落 `catalog.py`（新文件，零冲突），builder.py 只做「调用 + ctx.extras 塞值 + 注册」。`test_catalog.py` 覆盖纯逻辑，`test_kb_wiring.py` 覆盖 builder 接线。

- **R10 T8 延后项处理**：**T9 保持纯净（Agent 接入单一职责提交）**。仅当 `read_document` 的 pg 分支天然需要 `_pg_available()` 语义时，顺势纳入 P2-残留哨兵精化（有代码协同）；P3-1/P3-2（迁移脚本 tenant_id/白名单）+ 其余回归补强**无 T9 协同，另起 `fix(kb): T8 review follow-ups` 小提交或推 T10**，不污染 T9 feature 提交。

- **R11 skills 通道确认**：skills 经 `Toolkit(skills_or_loaders)` 对象注入（AgentScope 内部渲染 name/description catalog），QwenPaw 侧无 skills 字符串渲染函数 → plan「同函数追加参数」对 skills 不成立，故 KB 目录走 R1 的 contributor 通道（driver hints 同款），非 on_system_prompt hook。

- **R12 kb_read 契约**：仿只读工具（plan 提「仿 view_skill」，但仓内无 view_skill 符号，是概念引用）；返回 `===== [库名] 文档标题 =====\n<content_md>`，`ToolChunk`（复用 tool.py `_tool_chunk`）。

---

## 三、⚠️ builder.py 并发冲突提交协议（R9 核心，T8 事故教训延伸）

**现状**：`src/qwenpaw/runtime/builder.py` = ` M`（用户 PG 线未提交 WIP，54 行纯新增，散布 L125/179/231/260/282/290/322/374(+41)/554）。我的 T9 编辑区（L470 await、L615-657 build_prompt extras、L1044-1101 _collect_kb_tools 重写 + _get_kb_catalog）**与用户 WIP 区域不相交**。

**协议**：
1. **builder.py 接线放到最后做**（先完成 catalog.py / tool.py / service.py / prompt_contributors.py / test_catalog.py 全部无冲突部分并跑绿）。
2. SearchReplace 精确匹配我区域内唯一文本，**绝不触碰用户 WIP 行**（磁盘文件将同时含用户 WIP + 我的改动）。
3. **提交时严禁裸 `git add src/qwenpaw/runtime/builder.py`**（会连带暂存用户 54 行 WIP，重演 T8 索引污染）。
4. 提交前 `git diff --cached --name-only` + `git diff --cached -- builder.py` **逐 hunk 核对只含我的改动**；用 `git add -p`（或按 hunk 精确暂存）只选我的区域，用户 WIP 保持 unstaged。
5. 若届时用户已提交/回退其 builder.py WIP（文件转干净）→ 直接编辑 + 点名 add 即可。
6. 若 hunk 交错难以安全分离 → **暂停并向用户报告**，请其先提交/暂存 builder.py WIP，不强行操作。

---

## 四、验收标准

1. **AC1 目录渲染**：`render_kb_catalog([KbSpace(id,name,description)])` 输出含 `<knowledge-bases>`/`<id>`/`<name>`/`<description>`/「必须先调用 kb_search」；`render_kb_catalog([]) == ""`。
2. **AC2 注册门控**：无绑定 Agent → kb_search/kb_read 均不注册、prompt 无 `<knowledge-bases>` 块；有绑定 → 两工具注册 + 块注入且含绑定库 id/name。
3. **AC3 kb_read**：pg 态返回 content_md 权威全文；json 态返回 chunk 重建全文；doc 不存在返 not-found 错误 chunk；无权访问返 access-denied 错误 chunk（不泄正文）。
4. **AC4 零回归 + 零冲突**：kb 全量单测绿；消费方（路由/工具）绿；flake8 0 + black -l79 clean；T9 提交**只含我的文件、零用户 builder.py WIP 夹带**。

---

## 五、测试计划（先红后绿）

- `tests/unit/app/kb/test_catalog.py`（纯逻辑，零依赖）：AC1 渲染块 + 空返 ""；多库多 `<knowledge-base>` 节点；description 缺失容错。
- `tests/unit/runtime/test_kb_wiring.py`（接线，FakeStore/monkeypatch）：AC2 无绑定不注册不注入 / 有绑定注册+注入；AC3 kb_read pg/json/不存在/无权四态（复用 T8 FakeStore 范式 + read_document）。
- 均 `pytestmark = pytest.mark.unit`，干净环境（清 QWENPAW_STORAGE_BACKEND/PG_DSN），autouse 钉 json 后端防污染（T8 教训）。

---

## 六、变更文件预估

- 新建：`src/qwenpaw/app/kb/catalog.py`、`tests/unit/app/kb/test_catalog.py`、`tests/unit/runtime/test_kb_wiring.py`
- 改：`src/qwenpaw/app/kb/tool.py`（+`make_kb_read_tool`）、`src/qwenpaw/app/kb/service.py`（+`read_document` 三态）、`src/qwenpaw/runtime/prompt_contributors.py`（+`KbCatalogContributor`，干净文件）、`src/qwenpaw/runtime/builder.py`（`_collect_kb_tools` async 重写 + ctx.extras 塞 kb_catalog + build_prompt extras；**冲突协议见 §三**）
