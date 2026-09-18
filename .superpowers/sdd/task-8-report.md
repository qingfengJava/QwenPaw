# Task 8 完成报告 —— KbService 门面三态统一 + 存量 JSONL→PG 迁移

> 分支 `feature/agent_run_logs_20260908` · HEAD **47877b32**（父 = T7 5df13c4c）
> 复审门裁定：**达标（PASS）** · 6 文件 2007+/7- · 全程点名提交零夹带用户在制品
> 说明：本报告是 T8 唯一存留台账；原 progress.md / task-8-brief.md 已被外部清理（sdd 目录 gitignore，未追踪），不重建。

---

## 一、T8 交付内容

**本质**：不是从零建 pg 实现，而是把已建成的 pg 组件（T2 pg_store / T5 engine / T6 ingest）wiring 到**同步 KbService 门面**后 + 存量迁移脚本。所有 public 方法签名不变，消费方（admin/kb.py、kb/tool.py、workforce/engine.py、runtime/builder.py、bindings.py）**零改动**。

**三态分流**（spec §4.3，按 `resolve_storage_backend()`）：
- `json`：现状文件面逐条不变（回归基线）
- `dual`：json primary 读写 + 每个写操作 `submit_shadow_write` 影子写 pg（fire-and-forget，读仍 json）
- `pg`：pg_store/引擎权威读写，经 kb 局部后台事件循环线程桥接（镜像 `app/users/store_pg.py` 的 `run_coroutine_threadsafe` 先例；不改 `engine._run_blocking`、不动 `db/` 共享设施，避开与并发 PG 需求线冲突）

**迁移脚本** `scripts/migrate_kb_to_pg.py`（镜像 `migrate_storage_to_pg.py`）：Idempotent / Verifiable（逐库双校验：registry 文档数 + chunk 行数 vs pg kb_chunks）/ Non-destructive（绝不删源，写 receipt，30 天保留交运维）。裁定放**根 scripts/**（非 plan 字面 src/qwenpaw/scripts/），理由：与既有 migrate_storage_to_pg.py 同目录同范式，一致性 > plan 字面。

---

## 二、审查闭环（SDD 独立门）

| 轮次 | 结论 | 要点 |
| --- | --- | --- |
| 初审（故障诊断工程师） | 有条件达标 | P1-1~P1-5（4 阻断）+ P2-1~P2-7 + P3-1~P3-7 |
| 修复轮（本轮） | 全修 P1×5 + P2-3/5/6/7 | 见下 |
| 复审门（故障诊断工程师） | **达标 PASS** | P1×5 逐项确认解除、无新 P1、签名零变更、json 基线完好、迁移幂等/双校验/Non-destructive 仍成立 |

### P1×5 修复（均已复审确认解除）
- **P1-1** 摄入推进 ready：pg `upsert_document` 强制落 pending（pg_store 不变式），门面 `_pg_ingest_async` 切片写完后显式 `update_ingest_status(doc_id, INGEST_READY)`，否则文档永久卡 pending。
- **P1-2** 迁移同源：脚本每文档 upsert 后同样推进 ready。
- **P1-3** dual 影子复用 doc_id：`_pg_ingest_async` 加 `doc_id` 参数，dual 分支传 json 主写 doc_id，否则影子 delete 在 pg 找不到行 → 孤儿残留。
- **P1-4** pg 就绪即权威（防复活）：`get_kb/list_kbs` 用 `_pg_available()`（`ensure_ready()` 门控）区分「pg 不可用→回退文件面」与「pg 就绪但空→权威空结果绝不回退」，防已删空间被 30 天保留的 json 复活。**未采用初审建议的 Optional 哨兵法**——真 pg_store 对不可用和空都返 None/[]，异常法无效；复审确认门控决策成立。
- **P1-5** 迁移保真 created_at：pg_store upsert 的 INSERT 强制 created_at=now，脚本 `_preserve_created_at()` upsert 后按源值 UPDATE 回写。

### P2 修复
P2-3（dual update_grants 走 read-modify-write，不覆盖 pg 已配 embedding_model/engine）、P2-5（--dsn 默认取 $QWENPAW_PG_DSN）、P2-6（双校验期望切片数用 registry 文档名下计数，孤儿切片不计）、P2-7（receipt 补 content_md 为空 caveat）。

---

## 三、验证证据

| 项 | 结果 |
| --- | --- |
| kb 单测（含门面 24，新增 3 守护） | **221 passed** |
| KB 绑定路由（消费方） | **11 passed** |
| 迁移集成（5433 pgvector 真库隔离库，新增 created_at/ready 守护） | **4 passed** |
| flake8（6 文件） | **exit 0** |
| black -l 79（6 文件） | **clean** |

守护测试：`test_pg_ingest_advances_status_to_ready`（P1-1）、`test_pg_ready_but_absent_no_json_fallback`（P1-4）、`test_dual_shadow_ingest_reuses_doc_id`（P1-3）、`test_migration_preserves_created_at_and_status`（P1-5/P1-2，断言 pg created_at 年份=源 2020 + 文档全 ready）。

---

## 四、Git 事故与恢复（审计trail）

amend 折叠修复轮时踩坑：**裸 `git commit --amend` 提交整个索引**，而索引含用户会话间隙 `git rm` 的 128 个 `.qoder/` 预暂存删除 → T8 提交被污染成 134 文件（坏提交 f9ca687a）。

**恢复**（不丢用户暂存、不丢修复）：`git reset --soft 802e3740` 复原索引状态 → `git commit --amend --only -F <msg> -- <我的4文件>`（`--only` 取 HEAD 树叠加指定路径、无视其他已暂存路径；`-F` 选项必须在 `--` 前）。结果 HEAD=47877b32 恰含 6 T8 文件、零 .qoder，用户 128 删除仍 staged 完好。已沉淀记忆。

**教训**：共享工作树里任何 commit/--amend 前先 `git diff --cached --name-only` 核对索引只含自己文件；有他人预暂存内容时一律 `--only -- <paths>` 点名提交。

---

## 五、延后项（登记 T9，复审认可均非阻断）

| 项 | 内容 | 去向 |
| --- | --- | --- |
| **P2-残留** | `_pg_available()` 粘性正缓存：PG 启动就绪后查询期瞬断时，读路径短暂不可见而非回退 json。复审判「一致性优先于可用性」契合 PG 权威目标、比修复前「已删永久复活」严重度更低，非阻断。建议 T9 用 `_PG_UNAVAILABLE` 哨兵区分「桥接/SQL 异常→回退」与「真 None→权威」，并补守护测试（FakeStore 令 get_space 抛异常而非返 None） | T9 |
| P2-1 | search hit 的 `_hit_to_chunk` title 置空（检索投影问题，非三态分流） | T9/T10 |
| P2-2 | `_doc_to_meta` chunk_count 与 T6 摄入侧口径对齐 | T10 |
| P2-4 | 桥接超时不 cancel 协程（inherited 自 store_pg 先例，统一治理宜后续专项） | inherited |
| P3-1 | `_preserve_created_at` UPDATE 未带 tenant_id 过滤（单租户 + uuid ID 无实风险；建议补 `AND tenant_id=:tid` 或注明离线单租户假设） | T9 |
| P3-2 | `_preserve_created_at` 表名 f-string 内插（当前仅硬编码字面量，无注入；建议加白名单断言） | T9 |
| P3-7 | brief R5 search 路由文字与 R2 dual 矛盾（brief 已被清理，此条随之失效） | 失效 |

**T9 回归补强建议**（复审提出）：① P2-残留守护测试；② dual update_grants 不覆盖 pg embedding_model/engine 的显式断言；③ 迁移脚本「源含孤儿切片时双校验仍 OK」用例钉住 P2-6。

---

## 六、变更文件（6）

- `src/qwenpaw/app/kb/service.py`（门面三态分流 + 桥接 + P1×4 修复）
- `scripts/migrate_kb_to_pg.py`（迁移脚本 + P1-2/P1-5/P2-5/P2-6/P2-7）
- `tests/unit/app/kb/test_service_facade.py`（24 用例，含 3 守护）
- `tests/unit/app/kb/test_kb.py`（autouse `_json_backend` 钉桩防环境污染）
- `tests/integration/test_kb_migrate_script.py`（4 用例，PG 门控隔离库）
- `src/qwenpaw/app/routers/admin/kb.py`（仅注释更新）
