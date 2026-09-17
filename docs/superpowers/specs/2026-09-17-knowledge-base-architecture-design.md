# QwenPaw 知识库架构设计（知识中心四层架构）

- 日期：2026-09-17
- 分支：feature/agent_run_logs_20260908（实施 SQL 按分支映射落 `db/feature/agent_run_logs_20260908/`）
- 状态：设计已经用户确认（方案 B「文档权威源 + 可插拔混合检索层」+ 方案 C 实施节奏；
  决策点 1 = 绑定即授权；决策点 2 = 目录式注入 + 全库兜底）

## 1. 背景与问题

系统需要为数字员工建设知识中心：Agent 执行业务时自主判断是否检索、检索哪个知识库
（如「孕产知识库」只在孕产话题时触发）。存在两类建库主体：

1. **基础知识库**：后台管理员维护，面向全员/指定团队（类比飞书知识库管理模式）；
2. **业务域独立知识库**：前台业务人员按业务域自建，建好之后**授权绑定给数字员工**，
   员工即获得检索权限。

核心顾虑：直接建 Milvus 向量知识库**检索质量不可靠**——纯向量对专有名词/编号/表格召回差、
文档结构被压平、动态 ACL 过滤别扭、向量库无法承担人工浏览编辑的管理形态。
同时小规模（几十篇）与大规模（数十万 chunk）都要能支撑。

## 2. 现状盘点（设计锚点）

| 模块 | 现状 | 与本设计关系 |
| --- | --- | --- |
| `src/qwenpaw/app/kb/`（M4-5） | 三层 scope（personal/team/enterprise）+ grants ACL；JSONL 存储；纯 Python BM25（CJK bigram）+ 可选 cosine，RRF 融合；注释已预留「pg vector path」 | 保留 ACL 语义与工具入口，替换存储平面与索引层 |
| `kb_search` 工具 | `app/kb/tool.py`，注册点 `runtime/builder.py`（有库即注册） | 演进为目录驱动检索 |
| ReMe 长期记忆 | `memory/` 日志 + `digest/`（personal/procedure/wiki 节点）+ Wikilink 图 + BM25/向量/RRF/渐进展开 | 作为「知识组织层」的成熟范式被借鉴（wikilink + 结构展开 + 读原文渐进） |
| skills 体系 | PG 平面三态分发（json 零动作 / dual 影子写 / pg 权威读，`skill_catalog` 0023）、system prompt 目录注入（name/description catalog + 按需拉全文） | 授权绑定、存储工厂、目录注入三个模式直接复用 |
| PG 基础设施 | 项目全面 PG 化（alembic 当前至 0033）；`experts` 等表带 `tenant_id` 预留列 | 本设计新增 0034 迁移 |
| embedding 接入 | ReMe `embedding_model_config`（DashScope text-embedding-v4）+ `create_embedding_model` 工厂 | 知识库复用同一工厂与配置，不引入新 embedding 栈 |

## 3. 核心决策：四层分层架构

一句话：**Markdown 文档树是知识的权威源（Single Source of Truth），向量索引是它的可重建派生缓存；
检索不是「一次向量相似度」，而是「ACL 收敛 → 混合检索 → 结构扩展」的管线。**

```text
┌─ ④ Agent 接入层 ──────────────────────────────────────────────┐
│ system prompt 注入 <knowledge-bases> 目录（绑定库清单，仿 skills）   │
│ kb_search(query, kb_id?, expand?) 工具 · kb_read(doc_id) 工具      │
├─ ③ 检索管线层 ────────────────────────────────────────────────┤
│ S0 ACL 收敛 → S1 库内混合检索(BM25+向量+RRF) → S2 结构扩展          │
│ （父子章节回补 / wikilink 邻接）→ S3 rerank 精排                  │
├─ ② 索引层（可插拔 RetrievalEngine）────────────────────────────┤
│ L0 文件引擎（现状 JSONL 收编，无 PG 回退）                         │
│ L1 pgvector + tsvector（默认引擎，auto 路由落点）                  │
│ L2 Milvus adapter（一期实现，按库 engine=milvus 显式启用）         │
├─ ① 知识组织层（权威源）────────────────────────────────────────┤
│ KB（库）→ 目录路径 → Document（MD 正文 + frontmatter 元数据）        │
│ + 版本快照 + Wikilink + 授权模型（scope + grants + agent 绑定）     │
└──────────────────────────────────────────────────────────────┘
```

「小规模 wiki 模式、大规模向量库」的诉求在本设计中统一为一件事：
组织层永远 wiki 式，索引层按规模换引擎，上层检索语义不变。

## 4. 数据模型（PG 平面，alembic 0034）

命名与字段惯例对齐 `skill_catalog` / `agent_docs` / `experts`：`tenant_id` 联合主键前缀、
UTC `TIMESTAMPTZ`、枚举 `TEXT + CHECK`、幂等 DDL（`IF NOT EXISTS`）。

### 4.1 表清单

| 表 | 角色 | 说明 |
| --- | --- | --- |
| `kb_spaces` | 知识库注册 | 替代 JSON `kb_registry.json`（pg 平面下） |
| `kb_documents` | 文档权威源 | 一篇 Markdown 文档一行，含正文全文 |
| `kb_document_versions` | 文档版本快照 | 内容变更时写快照，复用 agent_docs 版本模式 |
| `kb_chunks` | 派生索引 | 切片 + embedding + tsvector，可全量重建 |
| `kb_links` | Wikilink 边 | 从文档正文解析 `[[路径]]` 落表，供图扩展 |
| `agent_kb_bindings` | 员工↔库授权绑定 | 绑定即授权（决策点 1） |

### 4.2 关键字段

```text
kb_spaces:
  (tenant_id, id) PK; name; description; scope CHECK(personal|team|enterprise);
  owner_id; team_id; grants JSONB {roles,users,teams};
  embedding_model TEXT NOT NULL DEFAULT ''   -- 空=全局默认;
  engine TEXT NOT NULL DEFAULT 'auto'        -- 索引引擎路由: auto|pgvector|milvus;
  created_at; updated_at

kb_documents:
  (tenant_id, id) PK; space_id FK; path TEXT      -- 库内目录路径，可空;
  title; content_md TEXT                           -- 权威源全文;
  content_hash TEXT;                               -- sha256，未变则不重切重嵌
  source CHECK(manual|upload|url);
  source_meta JSONB DEFAULT '{}';                  -- 原始文件名/大小/URL 等
  ingest_status CHECK(pending|processing|ready|failed) DEFAULT 'ready';
  error TEXT DEFAULT '';                           -- 文档级异步摄入状态机
  is_delete BOOLEAN DEFAULT FALSE;                 -- 逻辑删除（核心数据禁物理删）
  updated_by; created_at; updated_at
  UNIQUE (tenant_id, space_id, path) WHERE NOT is_delete

kb_document_versions:
  (tenant_id, document_id, version) PK; content_md; content_hash; created_by; created_at

kb_chunks:
  (tenant_id, id) PK; space_id; document_id; seq INT;
  heading_path TEXT;                               -- 如 "孕产用药 > 甲减 > 妊娠早期"
  parent_chunk_id TEXT DEFAULT '';                 -- 长段拆分时回指父语义段
  token_count INT;
  content_text TEXT;                               -- 切片正文（不含拼接前缀）
  tsv tsvector;                                    -- GIN 索引；应用层分词写入
  embedding vector(1024);                          -- HNSW 索引；模型维度 1024
  model_name TEXT;                                 -- 产生该向量的模型（换模型重建依据）
  created_at
  INDEX (space_id), INDEX (document_id)

kb_links:
  (tenant_id, id) PK; space_id;
  src_document_id; dst_path TEXT; dst_document_id TEXT DEFAULT ''  -- 解析失败时仅存 dst_path（悬挂链接）
  context_snippet TEXT; created_at
  INDEX (src_document_id), INDEX (dst_document_id)

agent_kb_bindings:
  (tenant_id, agent_id, space_id) PK; granted_by; remark; created_at
  INDEX (space_id)
```

### 4.3 存储平面三态工厂

完全复用 `catalog_store.skill_pg_plane_available()` 的模式：

- **json 后端**（默认/无 PG）：行为与现状一致，`kb_registry.json` + `kb_data/<kb_id>/chunks.jsonl`，
  引擎走 L0，**零 PG 动作**；
- **pg 后端**（`QWENPAW_PG_DSN` 且 `kb_spaces` 表存在）：PG 为权威读，写路径走 PG；
- 过渡期可选 **dual 影子写**（写 json 同时影子写 PG，读仍 json），与项目既往迁移节奏对齐。

`get_kb_engine()` 工厂先 `to_regclass('kb_chunks')` 探测，表缺失即回退 FileEngine——
保证迁移未跑时启动不阻塞、行为不变（对齐 `get_user_store()` 回退先例）。

## 5. 知识组织层

### 5.1 权威源形态

- 一篇知识 = 一个 Markdown 文档：YAML frontmatter（title / domain 业务域标签 / tags / source）+ 正文；
- 库内目录 = `kb_documents.path`（如 `孕产/用药/甲减用药指南.md`），前端渲染为目录树；
- 文档间关联 = 正文中的 `[[目标路径]]` wikilink，解析落 `kb_links`，构成轻量知识图；
  **不建设 Neo4j 式实体知识图谱**（成本高、维护难，wikilink 图已满足检索图扩展需求）。

### 5.2 结构化切片器（决定检索上限的核心环节）

```text
输入: kb_documents.content_md
1. 解析 Markdown AST（python-markdown / mistletoe，实施时按仓内已有依赖选型）；
2. 按标题层级切分语义段，每段携带完整 heading_path；
3. 段 token ≤ 600 → 单 chunk；超长段 → 段落打包（沿用现有 chunk_text 的 overlap 思路）
   并挂 parent_chunk_id 回指原语义段；
4. 表格、代码块整体成 chunk，禁止拆散；
5. embedding 输入 = heading_path 拼接 + 正文
   （"孕产用药 > 甲减 > 妊娠早期" + 段落文本）——提升专有名词召回的关键设计；
6. 产出 kb_chunks 行：tsv 由应用层分词器写入（英文 word + CJK bigram，
   与现有 _tokenize 行为一致，PG 侧用 'simple' 配置保证幂等）。
```

### 5.3 摄入管线（文件上传）

- 摄入格式一期全量支持：`md / txt / html`（html 抽取正文转 MD）+ `pdf`(pymupdf4llm) / `docx`(python-docx)；
- 上传原始文件落工作区 `kb_data/uploads/<space_id>/<doc_id>.<ext>`；
  **解析产物（规范 MD）写入 `kb_documents.content_md`——解析器只是搬运工，权威源仍是 MD，人工可修正，修正即重切重嵌**；
- 大文件异步化：`ingest_status` 状态机 pending → processing → ready/failed + `error` 字段，
  前端轮询展示，失败可重触发；
- 幂等：同内容 hash 重复上传直接短路返回既有 doc。

## 6. 检索管线

```text
kb_search(query, kb_id?, top_k=5, expand=none|section|graph)
  │
  ├─ S0 权限收敛：候选 space_ids = agent_kb_bindings(agent) ∩ kb_id(可选)
  │     —— 先过滤后检索，杜绝越权召回；这是权限安全的根。
  │     人侧（HTTP /api/kb/search）仍走既有 can_access ACL。
  ├─ S1 库内混合检索：引擎单查询同时做 向量 ANN + 全文，RRF 融合
  │     L1: 单 SQL —— 两个 CTE（embedding <=> $1 / tsv @@ query）各取 top50 排名，
  │         融合权重 vector 0.7 / keyword 0.3，k=60（与 ReMe/app-kb 现参数一致）
  │     L0: 现状 Python BM25+cosine 原样保留
  ├─ S2 结构扩展：
  │     expand=section → 命中 chunk 回补同 heading_path 完整小节（父子合并）
  │     expand=graph   → 附带该文档出/入链节点摘要，引导 Agent kb_read 关联文档（一期实装）
  └─ S3 rerank（一期）：候选 20 → qwen3-rerank 精排（OpenAI 兼容 /reranks）→ top 5
     （凭证与 embedding 同源；未配置模型时自动跳过 rerank 返回 RRF 序）
```

**RetrievalEngine 抽象**（`app/kb/engine.py`）：

```python
class KbRetrievalEngine(Protocol):
    """知识库索引与检索引擎抽象。"""

    async def index_document(self, space_id: str, doc_id: str,
                             chunks: list[KbChunkInput]) -> None: ...
    async def delete_document(self, space_id: str, doc_id: str) -> None: ...
    async def search(self, space_ids: list[str], query: str,
                     query_embedding: list[float] | None,
                     top_k: int) -> list[KbSearchHit]: ...
```

L2 Milvus adapter **一期实现**：collection schema=`chunk_id + space_id partition key + 稠密向量 + 稀疏向量（Milvus 内置 BM25 function）`，
ACL 预过滤走 `space_id in [...]` 标量表达式，混合检索用内置 WeightedRanker；默认 `engine='auto'` 仍落 pgvector，
业务方在库设置页显式切 `milvus`（适用判据：单库 > 50 万 chunk 或检索 P95 > 300ms）。
`kb_spaces.engine` 路由字段（auto/pgvector/milvus）一期随建表落地，双引擎共用同一套上层语义。

## 7. Agent 接入层（自主判断检索的落地）

复用 skills 已验证的「目录 + 按需拉取」契约：

1. **目录注入**：runtime 组装 system prompt 时查 `agent_kb_bindings`，注入绑定库清单
   （id / name / description），注册点即 `runtime/builder.py` 现有 M4-5 块——
   从「任意库存在即注册」改为「Agent 有绑定即注册 + 注入目录」。
2. **description 即路由信号**：建库表单强制填写「检索场景描述」并给出编写指引
   （回答 Agent「何时该查这个库」）。目录模板：

```xml
<knowledge-bases>
以下是当前数字员工可检索的知识库。涉及以下领域问题时，必须先调用 kb_search
检索对应知识库，再结合结果作答；闲聊或不相关话题不要检索。
<knowledge-base>
<id>kb_yunchan</id>
<name>孕产知识库</name>
<description>孕期/产褥期用药指南、检查项目解读、妊娠分期标准。
涉及孕产用药、产检问题时检索本库。</description>
</knowledge-base>
</knowledge-bases>
```

3. **工具演进**：`kb_search` 增加 `kb_id`（引导指定库）与 `expand` 参数；不指定库时
   并行检索所有绑定库再融合（全库兜底）。返回格式保留 `===== [库名] 文档标题 #heading [score=..] =====` 溯源行。
4. **kb_read(doc_id)**：按 document_id 拉权威 MD 全文，仿 `view_skill` 的只读契约，
   支撑渐进式检索（命中片段不够 → 读原文 → 沿 wikilink 扩展）。

## 8. 授权与隔离模型

| 隔离维度 | 载体 | 判定 |
| --- | --- | --- |
| 员工域（人的归属） | `kb_spaces.scope + owner_id/team_id + grants`（沿用 M4-5 语义） | 决定**人**能否建/管/看库 |
| Agent 授权域（员工的装备） | `agent_kb_bindings` | 决定**数字员工**能检索哪些库；绑定操作受库管理权校验 |
| 租户 | `tenant_id` 全表贯穿（单租户恒 default） | 对齐 experts 既有模式 |

**决策点 1（已确认）：绑定即授权。** Agent 运行时检索可见性 = 其绑定库集合，不叠加对话
用户 ACL（知识是给员工配的装备），`kb_search`/`kb_read` 工具链一期均按此语义。
人侧 HTTP 接口（`/api/kb/*`）不受影响，始终走既有 `can_access` ACL。
严格模式（Agent 检索再 ∩ 对话用户可见库）作为未来配置项预留，一期不开启。
绑定动作本身必须通过 `can_manage_kb` 校验（谁能授权），权限不旁路。

**决策点 2（已确认）：目录式 + 全库兜底。** 目录注入 system prompt 让 Agent 自主路由；
不指定 kb_id 时全绑定库并行检索融合。

权限矩阵：

- personal：owner 可管理/绑定；他人不可见（grants 除外）
- team：成员可读；owner/管理员可管理、可绑定
- enterprise：全员可读；管理员维护（基础知识库即此类）
- grants 扩展：管理员显式加白（role/user/team），与 M4-3 agent/model grant 语义一致

## 9. 前端形态（console，三块）

1. **Admin → Knowledge 页升级**（现有 `Admin/Knowledge.tsx` 重构）：库卡片网格 +
   scope/团队/域标签筛选；库详情 = 文档目录树（左树 + 右 Markdown 编辑器）+ 文件上传
   （md/txt/html）+ chunk 预览 + **检索测试台**（输入 query 看命中与得分，用于调优
   description 与切片）；
2. **员工工作台 → 知识库页（新）**：业务人员建库（名称 + 必填「检索场景描述」+ 业务域标签）
   → 文档管理 → 绑定数字员工（下拉选择自己有权限的 Agent）；
3. **数字员工详情 → 知识 Tab**：展示已绑定库（来源/授权人），支持解绑；交互对齐现有技能装配页。

UI 遵循项目规范：表格列居中、枚举展示描述文本、关联 ID 一律下拉选择。
多语言文案进 `staffdeck` 同级 i18n 命名空间（新增 `knowledge.*` 键，七语言对齐存量基线）。

## 10. API 设计（FastAPI，沿用 /api 前缀）

| 端点 | 说明 |
| --- | --- |
| `GET/POST/DELETE /api/admin/kb[...]` | 管理面：库 CRUD（权限 RBAC 门控不变）、ingest、documents、**新增 search-test** |
| `GET/POST/DELETE /api/kb[...]` | 员工面：list accessible / create personal / ingest / search（人侧 ACL） |
| `PUT/DELETE /api/agents/{agentId}/kb-bindings[/{spaceId}]` | 绑定授权（新，校验调用者对 space 的管理权） |
| `GET /api/agents/{agentId}/kb-bindings` | 员工详情知识 Tab 数据源 |
| `POST /api/kb/{spaceId}/documents/upload` | 文件上传摄入（multipart，异步状态；按 space 管理权校验，owner/管理员均可） |
| `GET /api/kb/{spaceId}/documents/{docId}/chunks` | chunk 预览（检索测试台/调优用） |

## 11. 分期实施

**一期（知识中心全量闭环，本设计交付范围，无后置返工项）**：

1. alembic 0034 六表（含 `kb_spaces.engine` 路由字段）+ `CREATE EXTENSION IF NOT EXISTS vector`；
2. `app/kb` PG 平面 + 三态工厂（FileEngine 收编现状逻辑）；
3. 结构化切片器（MD AST + heading_path + 拼接 embedding）；
4. **双检索引擎一期全实现**：`PgVectorEngine`（tsvector + pgvector 单 SQL RRF）+ `MilvusEngine`（pymilvus hybrid + WeightedRanker，按库 engine 字段路由）；
5. `agent_kb_bindings` 全链路（API + 校验 + builder 接线）；
6. `<knowledge-bases>` 目录注入 + `kb_search`/`kb_read` 演进；
7. **检索管线全装**：S0 ACL 收敛 + S1 混检 + S2 section/graph 双模式结构扩展 + S3 qwen3-rerank 精排（凭证缺失自动降级；gte-rerank 已于 2026-05-30 下线，官方替代为 qwen3-rerank）；
8. Admin 知识页重构（树+编辑器+上传+chunk 预览+检索测试台）；
9. 员工知识库页 + 员工详情知识 Tab；
10. 摄入格式全量：md/txt/html + **pdf/docx** 异步状态机；
11. 存量 registry/JSONL 迁移脚本（校验行数一致后 30 天保留旧文件）；
12. 部署：docker-compose 增 `milvus` profile（etcd+minio+milvus standalone），PG 镜像基线换 `pgvector/pgvector:pg16`。

**后续增强（真·可选，不阻塞一期验收）**：表格/FAQ 结构化条目类型、Auto-Dream 式「对话沉淀为知识草稿」闭环（复用 ReMe 管道思路）、embedding 多维度模型共存。

## 12. 测试与验收

| 层 | 内容 |
| --- | --- |
| 单测 | 切片器（标题路径/父子回补/表格不拆/overlap）、RRF 融合、bigram 分词、绑定 ACL 矩阵、三态工厂回退、摄入状态机 |
| 集成 | PG 门控用例：隔离库 `qwenpaw_integration_test` DSN + session loop scope（沿用 workforce 套件跑法）；0034 迁移幂等（跑两遍不报错） |
| 检索质量 | 每业务域 golden query 集（20~30 条真实问题 + 标注应命中文档），指标 **Recall@5 ≥ 0.9 / MRR ≥ 0.7**，**pgvector 与 Milvus 双引擎各自达标 + rerank 开关消融对比**；回归脚本入库 `tests/eval/kb/`，CI 可跑 |
| 权限 | 越权用例：未绑定 Agent 检索不到目标库、无权限用户列不出该库、S0 收敛先于 S1 的强制断言 |
| E2E | 接口链路：建库→传文档→绑定→对话触发检索→结果溯源展示；浏览器页面走查由用户人工验收（团队分工惯例） |

## 13. 部署变更与风险对策

**部署变更**：PG 实例需 `pgvector` 扩展（`CREATE EXTENSION vector`）；docker-compose 新增 `milvus` profile（etcd + minio + milvus-standalone，默认不启动）；PG 镜像基线由 `postgres:16` 换为 `pgvector/pgvector:pg16`（本机开发库需同步：pg_dump 逻辑迁移至 pgvector 实例，**禁止 alpine 与 glibc 镜像混用同一数据目录**）。

| # | 风险 | 对策 |
| --- | --- | --- |
| 1 | description 写得差 → Agent 不查库/查错库 | 建库表单强提示 + 编写指引 + 检索测试台可视化验证 |
| 2 | PG 中文全文检索能力有限 | 应用层分词（英文 word + CJK bigram）入 tsvector（'simple'）；若召回不足评估 zhparser/pg_jieba；极端情况该库回退 L0 Python 混检 |
| 3 | 换 embedding 模型 = 全量重建成本 | `kb_spaces.embedding_model` 字段 + 版本化后台重建任务，重建期间旧索引（`model_name` 过滤）仍可用 |
| 4 | 存量 JSONL 迁移丢数据 | 迁移脚本双校验（registry 计数 + chunk 行数），校验通过才切换，旧文件保留 30 天 |
| 5 | 大文件上传阻塞请求 | 异步状态机 + 前端轮询 + 失败可重触发 |
| 6 | 权限旁路（越权召回） | S0 收敛在引擎查询之前；绑定写操作强制管理权校验；单测覆盖越权矩阵 |

## 14. 非目标（明确不做）

- Neo4j 式实体知识图谱（wikilink 图已覆盖检索场景）；
- 多模态/图片 OCR 入知识、音视频转录入知识；
- 外部 wiki 系统（语雀/Confluence）实时双向同步；
- embedding 模型微调；
- 一期同时双写两引擎（每库单引擎路由，Milvus 为可选项非叠加项）。
