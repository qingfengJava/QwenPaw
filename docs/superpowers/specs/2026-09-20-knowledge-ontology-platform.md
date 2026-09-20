# QwenPaw 企业知识本体平台架构设计（Knowledge / Ontology / Orchestrator）

- 日期：2026-09-20
- 分支：feature/agent_run_logs_20260908（实施 SQL 按分支映射落 `db/feature/agent_run_logs_20260908/`）
- 状态：设计已经用户确认（完整落地方案，分 T0~T8 期实施；向量主引擎 = Milvus；
  本体本期只读 MVP；组织 = 公司级租户边界）

## 1. 背景与目标

以《企业级知识库 + 业务本体 + Multi-Agent 数字员工平台技术方案》
（RAG Evidence → LLM Wiki Knowledge → Ontology Runtime 三层）为蓝本，在 QwenPaw
既有知识库（0034 六表平面）、组织（orgs/departments）、RBAC（0042 PG 化）、
数字员工/专家团（experts + workforce）底座上，落地企业级知识基础设施：

1. **Evidence 层补强**：查询向量接线、摄入统一、chunk 元数据增强、Milvus 主引擎；
2. **Knowledge 层（LLM Wiki）**：知识条目生命周期（draft→in_review→published→archived）、
   审核留痕、冲突检测、有效期治理；
3. **Ontology 层（只读 MVP）**：L0/L1 本体模型 + 对象/关系/状态只读查询与 grounding；
   Rule/Action 仅建模预留；
4. **统一检索编排器**：检索计划 → 多路并发检索 → 融合 → Context Builder；
5. **四级权限**：个人 / 团队 / 组织 / 企业，检索前鉴权（PG SQL WHERE + Milvus expr 下推）；
6. **数字员工 + 专家团接入**：绑定主体泛化（agent|team）；
7. **前端**：管理端知识中心升级 + 本体管理页 + 员工端知识工作区；
8. **治理与评测**：审计接入 + Recall@5/MRR/权限安全评测。

本期明确不做（仅建模预留）：Rule 评估运行时、Action 执行与审批链、
Multi-Agent Task DAG 改造、图数据库、LLM 自动本体抽取管线。

## 2. 现状锚点（已核实）

| 底座 | 现状 | 复用点 |
| --- | --- | --- |
| `app/kb/`（0034） | 六表平面 + json/pg 双平面门面 + 三引擎 + S0~S3 管线 + 绑定即授权 | 全量复用；`kb_document_versions` 充当 Wiki 版本链；`kb_links` 充当知识关联图 |
| `app/orgs/` | org 即租户边界（org.id==tenant_id）、部门物化路径、`resolve_user_scope` | scope='org' 成员判定与部门树授权 |
| `app/rbac/`（0042） | roles/permissions/menus/DataScope/grants + `require_perm` | 权限种子与数据范围解析直接扩展 |
| `app/experts/` | publish 物化真实 agent；`employee_governance.department_id`；确定性 ID 助手 | 员工-部门归属 → 组织库授权；团队绑定主体解析 |
| workforce | `team_runs/team_run_nodes` DAG 台账 | 团队共享上下文的后续锚点 |
| 已知缺陷 | ①`embed_query` 零调用（向量分支生产不可达）②文本/admin 摄入 `heading_path=""` | T2 前置修复 |

## 3. 核心决策

1. **向量主引擎 = Milvus**（用户决策）：pymilvus 可用即 milvus；
   pgvector 降级为无 Milvus 环境回退；回退链 milvus→pgvector→file。
2. **文档 = 知识唯一权威**：Wiki 化走 `kb_documents` 加列，不建平行知识表。
3. **本体 = PG 关系表 + CTE 遍历**（≤3 跳）：不引入图数据库/规则引擎；
   Rule 后续用 JSONB 条件 DSL；Action 后续复用 `app/approvals` + tool 注册体系。
4. **检索前鉴权**：所有检索以 ACL 解析后的 space_ids 前置收敛
   （PG 走 SQL WHERE，Milvus 走 expr `space_id in [...]`），禁止先搜后滤。
5. **绑定主体泛化**：`agent_kb_bindings.principal_type`（agent|team），不新建团队绑定表。
6. **LLM 产物不直接写权威**：摘要/关联建议/冲突辅助/抽取草稿一律「候选 + 审核」入库。
7. **零破坏演进**：全部增量迁移（幂等 DDL + 三轨同步），新 API 字段 optional，新列不删。

## 4. 数据模型（增量迁移 0044~0048）

命名惯例对齐 0034：`(tenant_id, id)` 联合主键、UTC TIMESTAMPTZ、枚举 TEXT+CHECK、
幂等 DDL、全列 COMMENT。

| 迁移 | 内容 |
| --- | --- |
| `0044_kb_org_scope` | `kb_spaces.org_id` 列 + scope CHECK 扩 `'org'` + 索引 |
| `0045_kb_chunk_meta` | `kb_chunks.knowledge_id/entity_ids/valid_from/valid_to` |
| `0046_kb_wiki` | `kb_documents` wiki 化列（knowledge_status/domain/doc_type/confidence/valid_from/valid_to/reviewed_by/review_note）+ `kb_reviews` + `kb_conflicts` |
| `0047_ontology_plane` | `ontology_types/ontology_objects/ontology_relations/ontology_state_transitions/ontology_rules/ontology_actions/kb_object_links` + L0/L1 种子 |
| `0048_binding_principal` | `agent_kb_bindings.principal_type`（agent|team） |

## 5. 权限模型（四级，决策定稿）

```text
解析链（读）: admin → grants(users/roles/teams) → scope语义
  personal:   owner 本人
  team:       kb.team_id ∈ caller teams（RBAC teams，部门已镜像）
  org:        caller org == kb.org_id（经 OrgService.resolve_user_scope；部门级共享用 team 表达）
  enterprise: 全部认证用户
解析链（管）: admin → grants → scope 管理语义（org: DataScope dept_and_child 对 departments.path 前缀匹配）
Agent 侧  : 绑定即授权（principal agent|team），不叠加对话人 ACL（决策点1 维持）
检索前鉴权: 所有检索前置 space_ids ACL 收敛（PG SQL WHERE / Milvus expr），禁止先搜后滤
```

## 6. 检索编排器（Retrieval Orchestrator）

- 输入 `{query, principal(acl resolved space_ids), retrieval_plan?}`；
  缺省 plan 由轻量意图规则生成（不引入额外 LLM 调用）；
- 多路 retriever（knowledge/evidence/object/state）asyncio.gather 并发，单路 timeout 3s；
- 融合：对象/状态结构化块置顶 + RRF 文档块；Context Builder 总预算对齐 `_MAX_TOTAL_CHARS`；
- `kb_search` 增 `expand=graph`（kb_links CTE ≤3 跳）；新工具 `kb_objects` 返回对象卡。

## 7. 分期实施

T0 spec → T1 权限组织底座(0044) → T2 Evidence 修复+Milvus(0045) ∥ T3 Wiki(0046)
→ T4 本体模型(0047) → T5 编排器 → T6 员工/专家团绑定(0048) → T7 前端 → T8 治理评测。

## 8. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| scope CHECK 换约束失败 | 幂等 DO 块先查 pg_constraint 再 DROP/ADD；模型层 validator 先行 |
| dual 平面语义漂移 | `VALID_SCOPES` 单点扩枚举；can_access 单实现双面共用 |
| upsert 不变式回归 | 遵守 pending/created_at 两条不变式；回填用独立 UPDATE |
| Milvus 部署依赖 | docker-compose 一键编排；引擎工厂自动回退 |
| CTE 深度失控 | depth ≤3 + 节点数上限，超限标注 truncated |
| 存量兼容 | 新列 DEFAULT 回填语义等价；不删任何列 |

@author qingfeng
