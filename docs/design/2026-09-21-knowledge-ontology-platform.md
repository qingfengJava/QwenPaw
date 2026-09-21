# 企业知识本体平台落地架构说明（T0~T8）

> 计划来源：《企业级知识库 + 业务本体 + Multi-Agent 数字员工平台技术方案》
> （RAG Evidence → LLM Wiki Knowledge → Ontology Runtime 三层）
> 设计 spec：`docs/superpowers/specs/2026-09-20-knowledge-ontology-platform.md`
> 状态：**T0~T8 已全部实施**（本文为落地后的维护者视角架构说明）
> 分支：`feature/agent_run_logs_20260908`（实施 SQL 按分支映射落 `db/feature/agent_run_logs_20260908/`）
> 作者：qingfeng（AI 协助）　日期：2026-09-21

---

## 0. 一句话总结

在既有 0034 知识库六表平面上增量落地三层知识基础设施——**Evidence 补强（T2）→
LLM Wiki 知识层（T3）→ 业务本体只读 MVP（T4）**——外加统一检索编排器（T5）、
绑定主体泛化（T6）、前端三页（T7）与治理审计 + 检索评测（T8）；
共 5 个增量迁移（0044~0048），全部幂等 DDL 三轨同步，零破坏演进。

---

## 1. 分层总览（模块地图）

| 层 | 模块 / 文件 | 职责 | 上游依赖 |
| --- | --- | --- | --- |
| Evidence | `app/kb/pg_engine.py` `milvus_engine.py` `embedding.py` | 结构化切片 + 自动向量化；查询向量 TTL+LRU 缓存 | pgvector / Milvus |
| 引擎路由 | `app/kb/engine.py` | 回退链 milvus→pgvector→file；库级 `engine` 钉住（`pgvector` 显式钉 pg 面） | `db/write_gateway.py` backend 判定 |
| 存储 | `app/kb/pg_store.py` | 六表平面 + 0044~0048 新列/新表；表探测负 TTL 缓存 | PG |
| 检索 | `app/kb/search.py` `rerank.py` | `tokenize_mixed`（正则 token + CJK bigram）写读两侧同 tokenizer | — |
| Knowledge(Wiki) | `app/kb/wiki.py` + `kb_documents` wiki 列 + `kb_reviews`/`kb_conflicts` | 知识条目生命周期 draft→in_review→published→archived、审核留痕、冲突检测、有效期治理 | Evidence |
| Ontology | `app/ontology/`（`models.py` `store.py` `service.py` `api.py` `grounding.py`） | L0/L1 本体模型 + 对象/关系/状态只读查询 + grounding + 图遍历（PG CTE ≤3 跳） | Knowledge（`kb_object_links` 互引） |
| 编排器 | `app/kb/orchestrator.py` | 意图规则生成检索计划 → 多路 retriever 并发（单路 timeout 3s）→ RRF 融合 → 总预算收敛 | 全部下层 |
| 工具面 | `app/kb/tool.py` | `kb_search`（含 `expand=graph`）+ `kb_objects`（对象卡）注册进 builder | 编排器 / Ontology |
| 绑定 | `app/kb/bindings.py` | 绑定即授权；`principal_type`（agent\|team）泛化；团队解析 60s TTL 缓存 | orgs / RBAC |
| 审计 | `app/write_audit.py` + 路由接线 | T3/T4/T6 关键写路径接 `audit_events`（operator/action/target/before/after） | `app/audit` |
| 前端 | `console/src`（治理 tab / Ontology 页 / 员工知识工作区） | 管理端知识中心升级 + 本体管理 + 员工端；i18n 7 语言 | 各层 API |
| 评测 | `tests/eval/kb/` | Recall@5 / MRR / 溯源 / 越权安全四门（PG 门控） | 全部下层 |

---

## 2. 数据模型（增量迁移 0044~0048）

命名惯例对齐 0034：`(tenant_id, id)` 联合主键、UTC TIMESTAMPTZ、枚举 TEXT+CHECK、
幂等 DDL、全列 COMMENT。三轨同步：alembic + `db/feature/agent_run_logs_20260908/`
的 changelog 与 test/prod 快照。

| 迁移 | 内容 | 消费方 |
| --- | --- | --- |
| `0044_kb_org_scope` | `kb_spaces.org_id` + scope CHECK 扩 `'org'` + 索引 | 四级权限 org 分支 |
| `0045_kb_chunk_meta` | `kb_chunks.knowledge_id/entity_ids/valid_from/valid_to` | Wiki 关联 / 本体互引 / 有效期过滤 |
| `0046_kb_wiki` | `kb_documents` wiki 化列 + `kb_reviews` + `kb_conflicts` | 知识生命周期与审核 |
| `0047_ontology_plane` | `ontology_types/objects/relations/state_transitions/rules/actions` + `kb_object_links` + L0/L1 种子 22 条 | 本体平面 |
| `0048_binding_principal` | `agent_kb_bindings.principal_type`（agent\|team） | 员工/专家团绑定 |

---

## 3. 关键机制

### 3.1 检索前鉴权（ACL 收敛，禁止先搜后滤）

所有检索以 ACL 解析后的 `space_ids` 前置收敛：个人/团队/组织/企业四级
（org 分支经 `OrgService.resolve_user_scope` 判定成员），PG 走 SQL WHERE，
Milvus 走 expr `space_id in [...]` 下推。Agent 侧不叠加对话人 ACL——
**绑定即授权**（admin 绑定时已做过管理面鉴权）。

### 3.2 引擎路由与回退链

```text
space.engine = 'pgvector' → 显式钉 pg 面（默认引擎已升级 Milvus 后仍受尊重）
space.engine = 'auto'|'milvus' → 默认引擎工厂：
    milvus 可达（驱动 + 服务探测）→ Milvus
    backend ∈ {pg,dual} 且 kb_chunks 表就绪 → PgVector
    否则 → File
```

注意：`resolve_storage_backend` 是**进程级双检锁缓存**（env 不可变假设），
测试或运行期切换 `QWENPAW_*` env 后必须调 `write_gateway.reset_backend_cache()`，
否则 backend 判定沿用旧值导致静默错路由（T8 评测踩过的坑）。

### 3.3 检索编排器（T5）

- 输入 `{query, principal(acl resolved space_ids), retrieval_plan?}`；缺省 plan
  由轻量意图规则生成（**不引入额外 LLM 调用**）；
- 多路 retriever（knowledge / evidence / object / state）`asyncio.gather` 并发，
  单路 timeout 3s；
- 融合：对象/状态结构化块置顶 + 文档块 RRF；Context Builder 总预算对齐
  `_MAX_TOTAL_CHARS`；
- `kb_search` 增 `expand=graph`（`kb_links` 递归 CTE ≤3 跳，超限标注 truncated）；
  `kb_objects` 返回对象卡（`get_objects_batch` 单次批量）。

### 3.4 绑定主体泛化（T6）

`agent_kb_bindings.principal_type ∈ {agent, team}`（缺省 agent，兼容存量行）：
- `bind_principal` 统一入口；team 主体解析（团队成员 → agent 集合）带 **60s TTL 缓存**；
- 三端点：agents.py（兼容旧形状）、admin expert-teams 绑定、xian knowledge 员工流。

### 3.5 治理审计（T8-a）

统一走 [write_audit.py](../../src/qwenpaw/app/write_audit.py) 的
`record_write_audit(tool_name, target, actor_id, before, after)`：
- 快照形状沿用 `providers._audit_agent_model_change` 模式
  （`ToolCallSpec.raw_params = {"before": ..., "after": ...}` + ALLOW decision）；
- **best-effort**：内部 try/except 全吞，审计失败仅 WARN，绝不阻断业务写；
- 接线清单：admin KB（审核/元数据/冲突裁决）、ontology（对象/关系/链接
  create-update-delete 7 端点，删除仅 `deleted is True` 才记）、agent KB 绑定
  bind/unbind、专家团 KB 绑定 bind/unbind。

---

## 4. 评测体系（T8-b，tests/eval/kb）

### 4.1 运行方式与门控

```bash
python scripts/run_tests.py -e        # 或 pytest tests/eval/kb
```

宿主机未设 `QWENPAW_PG_DSN` 时整目录 skip（评测语义 = 真实 PG 检索管线质量回归）。
pyproject 已注册 `eval` marker。

### 4.2 隔离语义

- 专用一次性库 `qwenpaw_eval_test`（幂等建库 + alembic 全量迁移），
  **绝不读写开发者库**（2026-09-10 provider 配置覆盖事故的隔离教训）；
- 独立 `KbService` 实例（不取模块级单例）；
- 环境切换三件套，缺一即静默错路由：
  1. `pg_store.reset_store_for_tests()`（store 单例绑定旧 DSN）；
  2. `write_gateway.reset_backend_cache()`（backend 双检锁缓存）；
  3. teardown 逐键还原 env 后再次双 reset；
- 库级 `engine='pgvector'` 钉住（评测不依赖外部 Milvus）。

### 4.3 评测集设计（为什么 query 是原文子串）

`tokenize_mixed`（`app/kb/search.py`）是**纯局部确定性**分词：正则 token + CJK
串内 bigram，无词典。因此 **query 为某篇语料的逐字子串** ⇒ query 的 token 集
必然 ⊆ 该文档的 token 集 ⇒ PG `tsquery` AND 必命中——评测稳定性不依赖任何
分词黑魔法。`evalset.SNIPPETS` 以 `_validate_snippets()` 强制逐字校验
（健全性门用例第一时间抓住了手抄空格偏差）。

### 4.4 四道门

| 用例 | 门 | 断言 |
| --- | --- | --- |
| `test_kb_eval_corpus_snippets_verbatim` | 健全性 | 全部片段逐字在语料中 |
| `test_kb_eval_recall_and_mrr` | 指标 | Recall@5 ≥ 0.9 且 MRR ≥ 0.7（附 summary） |
| `test_kb_eval_hits_carry_provenance` | 溯源 | 命中带 `kb_id`（== 评测库）/ `doc_id` / `chunk_id` |
| `test_kb_eval_unbound_agent_no_leak` | 安全 | 无绑定 agent 检索 12 篇全部为空（越权必空） |

### 4.5 清理语义（幽灵孤儿教训）

`kb_documents/chunks/bindings` 对 `kb_spaces` 无外键（0034），space 行删除后
子行可残留为**幽灵孤儿**（space_id 指向已不存在的 space），按库名锚点永远
匹配不到；且 `delete_space` 有活文档软删守卫——业务删除链路不可靠。
清理统一走 `conftest._wipe_eval_kb` 直连 SQL 双口径：
- 孤儿：`DELETE ... WHERE space_id NOT IN (SELECT id FROM kb_spaces)`（**反连接**；
  `= ANY(空数组)` 在 SQL 语义上恒 FALSE，删不到任何行——实测踩坑）；
- 命名库子行：`WHERE space_id IN (SELECT id FROM kb_spaces WHERE name = ...)`。
setup（迁移后）与 teardown 复用同一函数，幂等。

### 4.6 测试夹具的 loop 纪律

KB pg 面（`KbPgStore` / `PgVectorEngine`）协程固定收敛在专用 bridge loop；
**测试里的 async 调用必须经 `_run_coro_blocking` 桥接**（评测用例全部为同步
`def`），禁止 pytest-asyncio function loop 直连 store——跨 loop 共池会报
"Future attached to a different loop" 或取到死连接。

---

## 5. 已知约束与运维注意

| 项 | 说明 | 影响 / 缓解 |
| --- | --- | --- |
| `_run_blocking` 一次性 loop 探测 | `engine.py` 探测在临时 loop 里 `asyncio.run`，可能向 store 共享池留下绑定死 loop 的连接 | 生产按现有调用顺序避开；产品级修复（探测走独立短连）列入后续 |
| pg readiness probe 偶发 WARN | `[kb] pg readiness probe failed` 为 fail-soft 正确降级 | 无需处理；评测/回归均绿 |
| 本体只读 MVP | Rule/Action 仅建模预留（0047 建表 + 种子），无评估/执行运行时 | 演进方向见 §6 |
| 团队解析 TTL 60s | 团队成员变更后最长 60s 才反映到绑定解析 | 可接受；需即时可清缓存 |
| 评测依赖真实 PG | `-e` 在无 DSN 环境自动 skip | CI 无 PG 不阻塞 |

---

## 6. 后续演进方向（本期明确不做）

1. **Rule 评估运行时**：JSONB 条件 DSL + 检索/工具调用前评估挂钩；
2. **Action 执行与审批链**：复用 `app/approvals` + tool 注册体系；
3. **LLM 自动本体抽取管线**：抽取草稿 →「候选 + 审核」入库（LLM 产物不直写权威）；
4. **Multi-Agent Task DAG 改造**：团队共享上下文落 `team_runs/team_run_nodes`；
5. **图数据库**：本体规模超出 PG CTE（≤3 跳）舒适区后再评估；
6. KnowledgeDrawer 内嵌绑定向导 tab（`expertTeams.bindKb` API 已备）。

---

## 7. 验证基线

- 后端回归：`pytest tests/unit tests/contract`（871 passed @ T8-a；T8-b 后含
  eval 门控目录不回退）；
- 评测：`scripts/run_tests.py -e`（4/4 passed；指标门 Recall@5=1.00 / MRR=1.00
  @ 60 QA 对、12 篇语料）；
- lint：`flake8 src/qwenpaw/app tests/eval tests/unit/app/test_write_audit.py`
  干净。

@author qingfeng
