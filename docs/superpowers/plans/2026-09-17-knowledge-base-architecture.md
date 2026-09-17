# QwenPaw 知识库一期（知识中心四层架构）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `app/kb` 从 JSONL 轻量演示级升级为生产级知识中心：PG 五表权威平面 + 结构化切片 + pgvector/tsvector 混合检索 + Agent 绑定授权 + 目录注入自主检索 + 管理/员工前端三块页面。

**Architecture:** 四层架构（详见 spec `docs/superpowers/specs/2026-09-17-knowledge-base-architecture-design.md`）：知识组织层以 Markdown 文档为权威源；索引层用可插拔 RetrievalEngine（L0 文件 / L1 pgvector 主力 / L2 Milvus 三期）；检索管线 S0 ACL 收敛 → S1 混合检索 RRF → S2 结构扩展；Agent 接入层复用 skills 的「目录注入 + 按需拉取」契约。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy async + asyncpg / Alembic / pgvector / DashScope embedding（复用 ReMe 工厂）/ React 18 + antd + Vite（console）。

## Global Constraints

- 当前分支 `feature/agent_run_logs_20260908`；SQL 变更落 `db/feature/agent_run_logs_20260908/changelog/{YYYYMMDD}/{NN}_xxx.sql`，当天已有 `01`（employee_governance），本功能用 **`02`**；同步更新本分支 `test.sql` / `prod.sql` 快照。
- 所有新表：`tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'` 联合主键前缀、UTC `TIMESTAMPTZ`、枚举 `TEXT + CHECK`、全字段中文 `COMMENT`、幂等 DDL（`IF NOT EXISTS` / DO 块判定）——逐条对照 `0033_employee_governance_manage.py` 写法。
- 存储平面三态（json 零动作 / dual 影子写 / pg 权威读）统一走 `db.write_gateway`（`resolve_storage_backend()` / `pg_write_available()`），禁止自行判定 DSN。
- 引擎路由：`kb_chunks` 表缺失或 backend=json 时自动回退 FileEngine，启动不阻塞（对齐 `get_user_store()` 回退先例）。
- RRF 参数与现状一致：`k=60`、vector 权重 `0.7`、keyword 权重 `0.3`；切片目标 600 token。
- embedding 默认 DashScope `text-embedding-v4`（1024 维），凭证复用 ReMe `embedding_model_config`；`embedding` 列固定 `vector(1024)`。
- Python 注释规范：类/方法 docstring（`@author qingfeng`），方法体单行注释说明业务，禁止行尾注释；依赖注入构造器风格；提前返回减嵌套。
- 前端：表格列居中；枚举展示描述文本；关联 ID 用下拉；文案进 `knowledge.*` i18n 键并保持七语言基线（存量缺失不算回归，新增键必须七语言补齐）。
- 每个 Task 结束跑该任务测试 + 提交一次 commit（Conventional Commits）。

## File Structure（一期新建/修改总览）

```
src/qwenpaw/
├── db/alembic/versions/0034_kb_pg_plane.py          [新建] 五表迁移
├── app/kb/
│   ├── models.py                                     [修改] 增 Pg 平面模型（Space/Document/Chunk/Link/Binding）
│   ├── pg_store.py                                   [新建] KB PG 存储平面（三态工厂 + CRUD）
│   ├── chunker.py                                    [新建] Markdown 结构切片器
│   ├── embedding.py                                  [新建] embedding 复用管线
│   ├── engine.py                                     [新建] RetrievalEngine 抽象 + 工厂
│   ├── file_engine.py                                [新建] 现状 JSONL 检索逻辑收编为 L0
│   ├── pg_engine.py                                  [新建] L1 pgvector+tsvector 引擎
│   ├── ingest.py                                     [新建] 摄入服务（解析 md/txt/html + 异步状态）
│   ├── links.py                                      [新建] wikilink 解析落表
│   ├── service.py                                    [修改] 门面统一走引擎
│   ├── search.py                                     [修改] _tokenize 提取为共享 util 复用
│   ├── tool.py                                       [修改] kb_search 演进 + kb_read 工具
│   └── catalog.py                                    [新建] <knowledge-bases> 目录注入渲染
├── runtime/builder.py                                [修改] _collect_kb_tools 改造 + catalog 接线
├── app/routers/kb.py                                 [修改] 员工面端点扩展
├── app/routers/admin/kb.py                           [修改] 管理面扩展
├── app/routers/agents.py（或 workspace.py 的 agents 路由族） [修改] kb-bindings 三端点
└── scripts/migrate_kb_to_pg.py                       [新建] 存量 JSONL → PG 迁移
db/feature/agent_run_logs_20260908/
├── changelog/20260917/02_kb_pg_plane.sql             [新建] psql twin
└── test.sql / prod.sql                               [修改] 快照同步
console/src/
├── api/modules/employeeKb.ts                         [新建] 员工面 + bindings API
├── api/modules/admin/kb.ts                           [修改] 管理面新端点
├── pages/Admin/Knowledge.tsx                         [修改] 重构为卡片+树+编辑器+测试台
├── pages/Employee/Knowledge/index.tsx                [新建] 员工知识库工作区页
└── pages/Employee/Detail 知识 Tab                     [修改] 绑定列表/解绑
tests/
├── unit/app/kb/…                                     [新建/修改] chunker/engine/ingest/links/store 单测
├── integration/test_kb_pg_plane.py                   [新建] PG 门控集成（隔离库 DSN）
└── eval/kb/                                          [新建] golden query 评测集与指标脚本
```

---

### Task 1: Alembic 0034 五表迁移 + psql twin changelog

**Files:**
- Create: `src/qwenpaw/db/alembic/versions/0034_kb_pg_plane.py`
- Create: `db/feature/agent_run_logs_20260908/changelog/20260917/02_kb_pg_plane.sql`
- Modify: `db/feature/agent_run_logs_20260908/test.sql`、`prod.sql`（快照并入）
- Test: `tests/integration/test_kb_pg_plane.py`（迁移幂等用例，后续任务持续追加）

**Interfaces:**
- Consumes: alembic head `0033_employee_governance_manage`
- Produces: 表 `kb_spaces` / `kb_documents` / `kb_document_versions` / `kb_chunks` / `kb_links` / `agent_kb_bindings`（列定义见 spec §4.2，Task 2+ 全部 store 层据此写 SQL）

- [ ] **Step 1: 写迁移文件**（结构照抄 0033 的幂等模式）

```python
# -*- coding: utf-8 -*-
"""Knowledge base PG plane (M6 knowledge center, phase 1).

Revision ID: 0034_kb_pg_plane
Revises: 0033_employee_governance_manage

新建知识库权威平面五表：kb_spaces（库注册，替代 JSON registry）、
kb_documents（MD 权威源+文档级摄入状态）、kb_document_versions（版本快照）、
kb_chunks（派生索引：pgvector 1024 维 + tsvector + heading_path + parent_chunk_id）、
kb_links（wikilink 边）、agent_kb_bindings（数字员工↔库授权绑定）。
依赖 pgvector 扩展；扩展缺失时本迁移显式报错提示安装，不做静默降级。

（psql twin: changelog 20260917/02，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0034_kb_pg_plane"
down_revision = "0033_employee_governance_manage"
branch_labels = None
depends_on = None

_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE IF NOT EXISTS kb_spaces (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        id VARCHAR(64) NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL DEFAULT 'personal',
        owner_id VARCHAR(64) NOT NULL DEFAULT '',
        team_id VARCHAR(64) NOT NULL DEFAULT '',
        grants JSONB NOT NULL DEFAULT '{}'::jsonb,
        embedding_model TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_kb_spaces PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_kb_spaces_scope CHECK (scope IN ('personal','team','enterprise'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_documents (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        id VARCHAR(64) NOT NULL,
        space_id VARCHAR(64) NOT NULL,
        path TEXT NOT NULL DEFAULT '',
        title TEXT NOT NULL DEFAULT '',
        content_md TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'manual',
        source_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
        ingest_status TEXT NOT NULL DEFAULT 'ready',
        error TEXT NOT NULL DEFAULT '',
        is_delete BOOLEAN NOT NULL DEFAULT FALSE,
        updated_by VARCHAR(64) NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_kb_documents PRIMARY KEY (tenant_id, id)
    )
    """,
    # CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（照 0033 模式）
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_kb_documents_source'
        ) THEN
            ALTER TABLE kb_documents ADD CONSTRAINT ck_kb_documents_source
            CHECK (source IN ('manual', 'upload', 'url'));
        END IF;
    END
    $$;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_kb_documents_ingest_status'
        ) THEN
            ALTER TABLE kb_documents ADD CONSTRAINT ck_kb_documents_ingest_status
            CHECK (ingest_status IN ('pending', 'processing', 'ready', 'failed'));
        END IF;
    END
    $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_document_versions (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        document_id VARCHAR(64) NOT NULL,
        version INTEGER NOT NULL,
        content_md TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        created_by VARCHAR(64) NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_kb_document_versions PRIMARY KEY (tenant_id, document_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_chunks (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        id VARCHAR(64) NOT NULL,
        space_id VARCHAR(64) NOT NULL,
        document_id VARCHAR(64) NOT NULL,
        seq INTEGER NOT NULL,
        heading_path TEXT NOT NULL DEFAULT '',
        parent_chunk_id VARCHAR(64) NOT NULL DEFAULT '',
        token_count INTEGER NOT NULL DEFAULT 0,
        content_text TEXT NOT NULL DEFAULT '',
        tsv tsvector,
        embedding vector(1024),
        model_name TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_kb_chunks PRIMARY KEY (tenant_id, id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS kb_links (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        id VARCHAR(64) NOT NULL,
        space_id VARCHAR(64) NOT NULL,
        src_document_id VARCHAR(64) NOT NULL,
        dst_path TEXT NOT NULL DEFAULT '',
        dst_document_id VARCHAR(64) NOT NULL DEFAULT '',
        context_snippet TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_kb_links PRIMARY KEY (tenant_id, id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_kb_bindings (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        agent_id VARCHAR(64) NOT NULL,
        space_id VARCHAR(64) NOT NULL,
        granted_by VARCHAR(64) NOT NULL DEFAULT '',
        remark TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_agent_kb_bindings PRIMARY KEY (tenant_id, agent_id, space_id)
    )
    """,
)
```

列注释 `_COMMENTS` 元组按 spec §4.2 逐列生成（机械工作，内容源就是 §4.2 行尾注释），示例三条：

```python
_COMMENTS = (
    "COMMENT ON COLUMN kb_documents.content_hash IS "
    "'内容 sha256 指纹：与既有行相同则跳过重切重嵌（版本不抖动）'",
    "COMMENT ON COLUMN kb_documents.ingest_status IS "
    "'文档级异步摄入状态: pending-待处理, processing-解析中, ready-可检索, failed-失败（error 携带原因）'",
    "COMMENT ON COLUMN kb_chunks.heading_path IS "
    "'标题路径（如 孕产用药 > 甲减 > 妊娠早期），检索 embedding 拼接与 S2 结构扩展依据'",
)
```

> **注**：上面注释省略的五段 DDL 在实施时**必须**按 spec §4.2 字段清单逐列完整写出，并配 `_COMMENTS` 元组（中文 COMMENT 每列一条）。索引部分：

```python
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_kb_documents_space ON kb_documents (tenant_id, space_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_space ON kb_chunks (tenant_id, space_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_document ON kb_chunks (document_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_tsv ON kb_chunks USING GIN (tsv)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding ON kb_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS ix_kb_links_src ON kb_links (src_document_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_links_dst ON kb_links (dst_document_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_kb_bindings_space ON agent_kb_bindings (tenant_id, space_id)",
)
```

- [ ] **Step 2: 写失败测试（迁移幂等）** → `tests/integration/test_kb_pg_plane.py`

```python
# -*- coding: utf-8 -*-
"""M6-1: 0034 知识库 PG 平面迁移断言（PG 门控）。

夹具约定：复用 tests/integration 既有 PG 门控模式——DSN 取
QWENPAW_TEST_PG_DSN（未设则 pytest.skip），库为隔离库 qwenpaw_integration_test
（对齐 test_workforce_runs.py 的 enterprise_env 惯例）；本文件的 app_server
为仓内同名夹具（tests/integration/conftest.py），pg 连接用 asyncpg 直连 DSN。
"""
from __future__ import annotations

import os

import asyncpg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.p0]


def _dsn() -> str:
    dsn = os.environ.get("QWENPAW_TEST_PG_DSN", "")
    if not dsn:
        pytest.skip("QWENPAW_TEST_PG_DSN not set")
    return dsn


async def test_kb_tables_exist_after_upgrade(app_server) -> None:
    """执行 0034 后六张表与向量索引齐备。"""
    conn = await asyncpg.connect(_dsn().replace("postgresql+asyncpg", "postgresql"))
    try:
        for table in (
            "kb_spaces", "kb_documents", "kb_document_versions",
            "kb_chunks", "kb_links", "agent_kb_bindings",
        ):
            row = await conn.fetchval(
                "SELECT to_regclass($1)", f"public.{table}",
            )
            assert row is not None, f"missing table: {table}"
        idx = await conn.fetchval(
            "SELECT indexname FROM pg_indexes WHERE indexname = 'ix_kb_chunks_embedding'",
        )
        assert idx == "ix_kb_chunks_embedding"
    finally:
        await conn.close()


async def test_upgrade_is_idempotent(app_server) -> None:
    """重复执行 upgrade 到同 revision 不报错。"""
    app_server.run_alembic("upgrade", "head")
    app_server.run_alembic("upgrade", "head")
```

> 若仓内 `app_server` 夹具无 `run_alembic` 辅助方法，改用 `subprocess` 调 `alembic upgrade head` 两次并断言返回码 0（与 `conftest.py` 现有 PG bootstrap 方式对齐，实施时二选一，不得静默 skip 迁移用例）。

- [ ] **Step 3: 跑测试确认失败**（表不存在）：`pytest tests/integration/test_kb_pg_plane.py -v -o asyncio_default_fixture_loop_scope=session -o asyncio_default_test_loop_scope=session`，DSN 用隔离库 `postgresql+asyncpg://qwenpaw:qwenpaw_dev_pg@127.0.0.1:5432/qwenpaw_integration_test`（输出重定向到文件读取，勿用管道）
- [ ] **Step 4: 补全 Step 1 的完整 DDL 后跑通**：同上命令，Expected: 2 passed
- [ ] **Step 5: psql twin + 快照同步** — 将同一套 DDL 复制到 `changelog/20260917/02_kb_pg_plane.sql`，头部按规范注释（变更说明/时间/变更人=清风/适用环境/同步快照=是），并把建表段并入本分支 `test.sql`、`prod.sql`
- [ ] **Step 6: Commit** — `git add src/qwenpaw/db/alembic/versions/0034_kb_pg_plane.py db/feature/agent_run_logs_20260908 tests/integration/test_kb_pg_plane.py && git commit -m "feat(kb): add 0034 knowledge base pg plane migration"`

---

### Task 2: KB PG 存储平面 pg_store（三态工厂 + CRUD）

**Files:**
- Create: `src/qwenpaw/app/kb/pg_store.py`
- Modify: `src/qwenpaw/app/kb/models.py`（追加 `KbSpace`/`KbDocument` 等 PG 平面读模型）
- Test: `tests/unit/app/kb/test_pg_store.py`

**Interfaces:**
- Consumes: `db.write_gateway.pg_write_available()`；`0034` 表结构
- Produces: `kb_pg_plane_available() -> bool`；`KbPgStore` 类：`upsert_space(space) / get_space(space_id) / list_spaces() / delete_space(id)`、`upsert_document(doc, *, content_hash_changed: bool) -> bool`（hash 未变返回 False 不写快照）、`get_document(doc_id) / list_documents(space_id)`、`add_document_version(...)`；`models.py` 追加 PG 平面读模型 **`KbSpace` / `KbDocument`**（pydantic；旧 `KnowledgeBase` 保留为 json 后端兼容模型，service 门面统一转出）；后续 Task 5/6/7/8 全部经此访问 PG

- [ ] **Step 1: 写失败测试**（用与 `agent_docs` 同款的 FakeEngine 捕获参数化 SQL，参考 `tests/unit/app/agent_docs/test_store.py` 夹具）

```python
# -*- coding: utf-8 -*-
"""M6-2: KbPgStore 三态与幂等语义单测。"""
from __future__ import annotations

import pytest

from qwenpaw.app.kb import pg_store

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_upsert_document_hash_unchanged_skips(monkeypatch) -> None:
    """内容 hash 相同：WHERE 拦截 → 返回 False，版本不抖动。"""
    engine = _FakeEngine(unchanged=True)
    store = pg_store.KbPgStore(engine=engine)
    written = await store.upsert_document(
        _doc_row(space_id="kb_a", doc_id="d1", content_md="# hello"),
    )
    assert written is False


@pytest.mark.asyncio
async def test_backend_json_does_nothing(monkeypatch) -> None:
    """json 后端：所有写方法零动作零异常。"""
    monkeypatch.setattr(pg_store.write_gateway, "pg_write_available", lambda: False)
    store = pg_store.KbPgStore(engine=None)
    assert await store.upsert_space(_space_row()) is False
```

- [ ] **Step 2: 跑测试确认失败**：`pytest tests/unit/app/kb/test_pg_store.py -v` → ImportError/FAILED
- [ ] **Step 3: 最小实现** — `pg_store.py`：`KbPgStore` 构造器注入 engine（`get_engine()` 懒取，仿 `agent_docs/store_pg.py`）；写 SQL 全部参数化 + `ON CONFLICT ... DO UPDATE ... WHERE kb_documents.content_hash IS DISTINCT FROM excluded.content_hash`；`schedule_*` 异步写入口 fire-and-forget（复用 `catalog_store._schedule` 模式，同步调用方不阻塞）；读方法同步化用 `run_sync_io` 约定（与 workspace 路由同款）
- [ ] **Step 4: 跑测试确认通过**：Expected: 2 passed
- [ ] **Step 5: Commit** — `git commit -am "feat(kb): add pg store plane with hash-guarded upserts"`

---

### Task 3: Markdown 结构化切片器 chunker

**Files:**
- Create: `src/qwenpaw/app/kb/chunker.py`
- Modify: `src/qwenpaw/app/kb/search.py`（`_tokenize` 提升为 `tokenize_mixed` 共享导出）
- Test: `tests/unit/app/kb/test_chunker.py`

**Interfaces:**
- Consumes: frontmatter（python-frontmatter，若 pyproject 无则 `pip install` 并同步 `[project.dependencies]`）
- Produces: `ChunkSpec` dataclass：`seq:int, heading_path:str, text:str, parent_seq:int|None, token_count:int`；`split_markdown(md_text: str, *, target_tokens: int = 600, overlap_chars: int = 100) -> list[ChunkSpec]`；`embed_input(chunk: ChunkSpec) -> str`（`heading_path 拼接 + 正文`）。Task 5/6 依赖。

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M6-3: 结构化切片器——标题路径保留/长段父子/表格不拆。"""
from __future__ import annotations

import pytest

from qwenpaw.app.kb.chunker import embed_input, split_markdown

pytestmark = pytest.mark.unit

_MD = """# 孕产用药

## 甲减

### 妊娠早期
左甲状腺素剂量需增加约 20%-30%，每 4 周复查 TSH。

| 分期 | TSH 目标 |
| --- | --- |
| 早期 | <2.5 |
| 中期 | <3.0 |
"""


def test_heading_path_attached_to_chunks() -> None:
    """每个切片携带完整标题路径。"""
    chunks = split_markdown(_MD)
    target = next(c for c in chunks if "左甲状腺素" in c.text)
    assert target.heading_path == "孕产用药 > 甲减 > 妊娠早期"
    assert "孕产用药 > 甲减 > 妊娠早期" in embed_input(target)


def test_table_kept_whole() -> None:
    """表格整体成 chunk，禁止按行拆散。"""
    chunks = split_markdown(_MD)
    table_chunk = next(c for c in chunks if c.text.lstrip().startswith("|"))
    assert "早期" in table_chunk.text and "中期" in table_chunk.text


def test_long_section_parent_linkage() -> None:
    """超长段拆出的子块 parent_seq 指向父语义块（首块 parent 为 None）。"""
    long_md = "# T\n## H\n" + "\n\n".join("段" * 500 for _ in range(6))
    chunks = split_markdown(long_md)
    assert len(chunks) >= 2
    child = next(c for c in chunks if c.parent_seq is not None)
    assert any(c.seq == child.parent_seq for c in chunks)


def test_tokenize_mixed_exported() -> None:
    """共享分词器兼容 CJK bigram 与英文词。"""
    from qwenpaw.app.kb.search import tokenize_mixed

    toks = tokenize_mixed("甲减 levothyroxine")
    assert "levothyroxine" in toks and "甲减" in toks
```

- [ ] **Step 2: 跑测试确认失败**：`pytest tests/unit/app/kb/test_chunker.py -v` → 4 failed
- [ ] **Step 3: 实现** — mistune/python-markdown 任选（优先仓内已有）解析 AST；标题栈维护 `heading_path`；token 估算 `len(text)//2`（CJK 近似）或 tiktoken（已有则用）；打包沿用旧 `chunk_text` 的 overlap 思想但输出 `ChunkSpec`；表格节点在 AST 层整体成 chunk
- [ ] **Step 4: 跑测试通过 + 回归旧测试**：`pytest tests/unit/app/kb -v` → all passed（`test_kb.py` 旧用例若依赖 `chunk_text` 则保留别名兼容）
- [ ] **Step 5: Commit** — `git commit -am "feat(kb): markdown structural chunker with heading paths"`

---

### Task 4: embedding 复用管线

**Files:**
- Create: `src/qwenpaw/app/kb/embedding.py`
- Test: `tests/unit/app/kb/test_kb_embedding.py`

**Interfaces:**
- Consumes: `agents.memory.embedding_model.create_embedding_model` + 全局 `embedding_model_config`；`kb_spaces.embedding_model`（空=全局默认）
- Produces: `async def embed_texts(texts: list[str], model: str = "") -> list[list[float]] | None`（未配置凭证返回 None，调用方降级 BM25-only）；`async def embed_query(query: str, model: str = "") -> list[float] | None`；维度常量 `EMBEDDING_DIM = 1024`

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M6-4: embedding 复用管线——凭证缺失降级 / 批量透传。"""
from __future__ import annotations

import pytest

from qwenpaw.app.kb import embedding as kb_emb

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_embed_unconfigured_returns_none(monkeypatch) -> None:
    """未配置 embedding 模型：embed_texts 返回 None（BM25-only 降级信号）。"""
    monkeypatch.setattr(kb_emb, "_resolve_config", lambda: None)
    assert await kb_emb.embed_texts(["a"]) is None


@pytest.mark.asyncio
async def test_embed_batch_passthrough(monkeypatch) -> None:
    """批量输入 → 等长向量列表，顺序对齐。"""
    async def _fake(texts):
        return [[0.1] * 1024 for _ in texts]

    monkeypatch.setattr(kb_emb, "_call_model", _fake)
    out = await kb_emb.embed_texts(["x", "y"])
    assert out is not None and len(out) == 2
```

- [ ] **Step 2: 跑测试确认失败** → FAILED
- [ ] **Step 3: 实现**：`_resolve_config()` 读 `reme_light_memory_config.embedding_model_config`；`_call_model()` 走 `create_embedding_model`；异常仅 WARN 并返回 None（fail-soft，BM25 永远可用）
- [ ] **Step 4: 跑测试通过**；Step 5: `git commit -am "feat(kb): embedding pipeline reusing reme credential factory"`

---

### Task 5: RetrievalEngine 抽象 + FileEngine(L0) + PgVectorEngine(L1)

**Files:**
- Create: `src/qwenpaw/app/kb/engine.py`、`file_engine.py`、`pg_engine.py`
- Modify: `src/qwenpaw/app/kb/service.py`（`search()`/`ingest_text()` 内部改走引擎）
- Test: `tests/unit/app/kb/test_engine_factory.py`、`tests/integration/test_kb_pg_plane.py`（追加 L1 检索用例）

**Interfaces:**
- Consumes: Task 3 `ChunkSpec`/`embed_input`；Task 4 `embed_texts`；`0034` 表
- Produces: `KbSearchHit` dataclass：`space_id, document_id, chunk_id, seq, heading_path, text, score, parent_seq`；引擎协议 `KbRetrievalEngine`（`index_document / delete_document / search(space_ids, query, query_embedding, top_k) -> list[KbSearchHit]`）；`get_kb_engine() -> KbRetrievalEngine` 工厂（json→FileEngine，pg/dual 且 `kb_chunks` 表存在→PgVectorEngine，否则回退 FileEngine）

- [ ] **Step 1: 写失败测试（工厂路由）**

```python
# -*- coding: utf-8 -*-
"""M6-5: 引擎工厂路由与回退。"""
from __future__ import annotations

import pytest

from qwenpaw.app.kb import engine as eng

pytestmark = pytest.mark.unit


def test_factory_json_backend(monkeypatch) -> None:
    monkeypatch.setattr(eng.write_gateway, "resolve_storage_backend", lambda: "json")
    assert isinstance(eng.get_kb_engine(), eng.FileKbEngine)


def test_factory_pg_backend_without_table_falls_back(monkeypatch) -> None:
    """pg 后端但 kb_chunks 表缺失：回退 FileEngine，启动不阻塞。"""
    monkeypatch.setattr(eng.write_gateway, "resolve_storage_backend", lambda: "pg")
    monkeypatch.setattr(eng, "_kb_chunks_table_exists", lambda: False)
    assert isinstance(eng.get_kb_engine(), eng.FileKbEngine)


def test_factory_pg_backend_with_table(monkeypatch) -> None:
    monkeypatch.setattr(eng.write_gateway, "resolve_storage_backend", lambda: "pg")
    monkeypatch.setattr(eng, "_kb_chunks_table_exists", lambda: True)
    assert isinstance(eng.get_kb_engine(), eng.PgVectorEngine)
```

- [ ] **Step 2: 跑测试确认失败** → ImportError
- [ ] **Step 3: 实现 engine.py + file_engine.py** — 模块组织：`engine.py` 定义 `KbRetrievalEngine` 协议、`KbSearchHit`、工厂 `get_kb_engine()`，并在顶部 `from .file_engine import FileKbEngine` / `from .pg_engine import PgVectorEngine` 重导出（Step 1 测试从 `engine` 导入类名即源于此）；**file_engine/pg_engine 禁止反向 import engine.py（循环依赖）**，实现体仅 duck-type 协议。`FileKbEngine` 直接包装现状 `service.search()` 的 `_load_chunks + search_chunks`（逻辑原样搬移，不改语义）；`index_document` 写 JSONL 现状格式
- [ ] **Step 4: 实现 pg_engine.py（混合检索单 SQL）**

```python
# 混合检索：两个 CTE 各取 top50 排名，SQL 内 RRF 融合（k=60，0.7/0.3 权重）
_SEARCH_SQL = """
WITH vec AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> CAST(:qv AS vector)) AS rank
    FROM kb_chunks
    WHERE tenant_id = :tenant AND space_id = ANY(:space_ids)
      AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:qv AS vector)
    LIMIT 50
), kw AS (
    SELECT id, row_number() OVER (ORDER BY ts_rank(tsv, to_tsquery('simple', :tsq)) DESC) AS rank
    FROM kb_chunks
    WHERE tenant_id = :tenant AND space_id = ANY(:space_ids)
      AND tsv @@ to_tsquery('simple', :tsq)
    LIMIT 50
)
SELECT c.id, c.space_id, c.document_id, c.seq, c.heading_path,
       c.content_text, c.parent_chunk_id,
       COALESCE(0.7 / (60 + vec.rank), 0) + COALESCE(0.3 / (60 + kw.rank), 0) AS score
FROM kb_chunks c
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN kw ON kw.id = c.id
WHERE COALESCE(0.7 / (60 + vec.rank), 0) + COALESCE(0.3 / (60 + kw.rank), 0) > 0
ORDER BY score DESC
LIMIT :top_k
"""
```

（无 query_embedding 时仅 kw CTE；tsquery 词串由应用层 `tokenize_mixed` 后以 `' & '` 连接生成，保证与索引侧同分词。）
- [ ] **Step 5: PgVectorEngine 集成测试追加**（隔离库：index 3 条含专有名词的 chunk → query 命中且向量缺失时 BM25 仍命中）——`pytest tests/integration/test_kb_pg_plane.py -v -o asyncio_default_fixture_loop_scope=session -o asyncio_default_test_loop_scope=session`
- [ ] **Step 6: 全量单测通过**：`pytest tests/unit/app/kb -v`
- [ ] **Step 7: Commit** — `git commit -am "feat(kb): pluggable retrieval engine with pgvector hybrid RRF search"`

---

### Task 6: 摄入服务（上传解析 + 异步状态机 + 版本快照 + wikilink 落表）

**Files:**
- Create: `src/qwenpaw/app/kb/ingest.py`、`src/qwenpaw/app/kb/links.py`
- Test: `tests/unit/app/kb/test_ingest.py`、`tests/unit/app/kb/test_links.py`

**Interfaces:**
- Consumes: Task 2 store、Task 3 chunker、Task 4 embedding、Task 5 engine
- Produces: `IngestResult` dataclass（`doc_id, chunk_count, status`）；`async def ingest_space_document(*, space_id, title, path, content_md, source, source_meta, uploaded_from: bytes | None) -> IngestResult`（**权威源=MD**：先写 document+版本，再切片+索引+links，状态机 pending→processing→ready/failed）；`extract_wikilinks(md) -> list[tuple[dst_path, context_snippet]]`；`parse_upload(filename, data: bytes) -> str`（md/txt 直读、html→readability 抽正文转 MD、其余抛 `UnsupportedFormat`）

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M6-6: 摄入管线——状态机/幂等/html 解析/链接抽取。"""
from __future__ import annotations

import pytest

from qwenpaw.app.kb import ingest, links

pytestmark = pytest.mark.unit


def test_extract_wikilinks_with_context() -> None:
    """抽取 [[路径]] 并携带所在行上下文。"""
    md = "妊娠期甲减见 [[孕产/用药/甲减]]，分期标准见 [[妊娠分期]]。\n正文"
    found = links.extract_wikilinks(md)
    assert [p for p, _ in found] == ["孕产/用药/甲减", "妊娠分期"]
    assert "妊娠期甲减" in found[0][1]


def test_parse_html_to_markdown() -> None:
    """HTML 抽取标题与段落为 MD（脚本/样式剔除）。"""
    md = ingest.parse_upload("guide.html", b"<h1>T</h1><script>x()</script><p>a</p>")
    assert "# T" in md and "a" in md and "x()" not in md


def test_parse_upload_rejects_unknown() -> None:
    with pytest.raises(ingest.UnsupportedFormat):
        ingest.parse_upload("book.pdf", b"%PDF-1.4")


@pytest.mark.asyncio
async def test_ingest_hash_dedup_short_circuit(monkeypatch) -> None:
    """同 content_hash 重复摄入：直接返回既有 doc，不重建索引。"""
    calls: list[str] = []
    monkeypatch.setattr(ingest, "_write_chunks", lambda *a, **k: calls.append("w"))
    r1 = await ingest.ingest_space_document(
        space_id="kb_a", title="t", path="", content_md="# a",
        source="manual", source_meta={},
    )
    r2 = await ingest.ingest_space_document(
        space_id="kb_a", title="t", path="", content_md="# a",
        source="manual", source_meta={},
    )
    assert r1.doc_id == r2.doc_id
    assert calls == ["w"]  # 仅首次建索引
```

- [ ] **Step 2: 跑测试确认失败** → 4 failed/ImportError
- [ ] **Step 3: 实现 ingest.py + links.py**：`parse_upload` 一期白名单 `{.md, .markdown, .txt, .html, .htm}`；html 用 `readability-lxml`+`markdownify`（或仓内已有 bs4+lxml 降级：h1-h6→#、p→段落、table→GFM 表）；摄入主流程按 spec §5.3：hash 短路 → document(upsert)+version → chunker → **embedding 接线：调 `kb.embedding.embed_texts([embed_input(c) for c in specs])`，None 则 chunk.embedding 全空走 BM25-only** → engine.index_document → links 重建本 doc 出边；异常路径状态机落 failed + error 字段
- [ ] **Step 4: 跑测试通过**：`pytest tests/unit/app/kb -v`
- [ ] **Step 5: Commit** — `git commit -am "feat(kb): async ingestion with versioning and wikilinks"`

---

### Task 7: agent_kb_bindings 存储与绑定授权 API

**Files:**
- Create: `src/qwenpaw/app/kb/bindings.py`
- Modify: `src/qwenpaw/app/routers/agents.py`（或 workspace agents 路由族挂载点，实施时定位 `/{agent_id}` 路由组）
- Test: `tests/unit/app/kb/test_bindings.py`、`tests/integration/test_kb_bindings_api.py`

**Interfaces:**
- Consumes: Task 2 store（spaces）、RBAC `can_access`/管理权判定、`agent_docs` 的 PG 可用性门控惯例
- Produces: `list_bound_space_ids(agent_id) -> list[str]`；`bind_agent_kb(*, agent_id, space_id, granted_by) -> bool`（内部校验 `granted_by` 对 `space_id` 有管理权，无权 False）；`unbind_agent_kb(agent_id, space_id) -> bool`；HTTP `GET/PUT/DELETE /api/agents/{agentId}/kb-bindings[/{spaceId}]`

- [ ] **Step 1: 写失败测试（管理权校验矩阵）**

```python
# -*- coding: utf-8 -*-
"""M6-7: 绑定授权矩阵——越权绑定必须被拒。"""
from __future__ import annotations

import pytest

from qwenpaw.app.kb import bindings

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_bind_requires_space_manage(monkeypatch) -> None:
    """无管理权用户绑定 → False，不落库。"""
    monkeypatch.setattr(bindings, "can_manage_space", lambda sid, user: False)
    assert await bindings.bind_agent_kb(
        agent_id="analyst", space_id="kb_a", granted_by="bob",
    ) is False


@pytest.mark.asyncio
async def test_bind_owner_ok_and_idempotent(monkeypatch) -> None:
    """owner 绑定成功；重复绑定幂等返回 True。"""
    written: list[tuple] = []
    monkeypatch.setattr(bindings, "can_manage_space", lambda sid, user: user == "alice")
    monkeypatch.setattr(bindings, "_insert_binding", lambda *a: written.append(a) or True)
    assert await bindings.bind_agent_kb(
        agent_id="analyst", space_id="kb_a", granted_by="alice",
    ) is True
```

- [ ] **Step 2: 跑测试确认失败** → FAILED
- [ ] **Step 3: 实现**：`can_manage_space(space_id, username)` 语义=admin 或（personal→owner / team→团队成员且 grants 用户 / enterprise→管理员）；路由层三端点，`PUT` body `{space_id}`，成功返回 201、无权 403、库不存在 404；json 后端时绑定写工作区 `kb_bindings.json` manifest（FileEngine 路径同样支持，保证三态一致）
- [ ] **Step 4: 集成测试（PG 门控）通过**
- [ ] **Step 5: Commit** — `git commit -am "feat(kb): agent knowledge base binding api with manage-gated grants"`

---

### Task 8: KbService 门面统一 + 存量 JSONL 迁移脚本

**Files:**
- Modify: `src/qwenpaw/app/kb/service.py`（registry→pg_store；search/ingest→engine）
- Create: `src/qwenpaw/scripts/migrate_kb_to_pg.py`
- Test: `tests/unit/app/kb/test_service_facade.py`、`tests/integration/test_kb_migrate_script.py`

**Interfaces:**
- Consumes: Task 2/5/6
- Produces: `KbService` 对 routers/tool 的**既有方法签名不变**（`list_kbs / get_kb / create_kb / delete_kb / can_access / accessible_kbs / search / ingest_text / list_documents / delete_document`），内部按 backend 分流；CLI：`python -m qwenpaw.scripts.migrate_kb_to_pg [--dry-run]`（spec §13 风险 4：双校验后 30 天保留旧文件）

- [ ] **Step 1: 写失败测试**：`KbService` 在 pg backend 下 `search(kb_id,...)` 走引擎、json backend 下行为与旧实现逐字节一致（用现状 fixture 数据断言同结果）
- [ ] **Step 2: 跑失败** → **Step 3: 实现门面分流 + 迁移脚本**（脚本：读 registry→upsert spaces/documents→切片重嵌→count 校验→输出 `migrated/skipped/failed` 计数；`--dry-run` 只报告）
- [ ] **Step 4: 迁移脚本集成测试通过**（临时目录造 2 库 3 文档 fixture → 跑脚本 → 表行数+chunk 行数一致）
- [ ] **Step 5: Commit** — `git commit -am "refactor(kb): service facade routes through engines; add pg migration script"`

---

### Task 9: Agent 接入——目录注入 + 工具注册改造 + kb_read

**Files:**
- Create: `src/qwenpaw/app/kb/catalog.py`
- Modify: `src/qwenpaw/runtime/builder.py:1019-1044`（`_collect_kb_tools`）、system prompt 组装链（实施时定位 skills 目录注入通道，同通道并行注入）
- Modify: `src/qwenpaw/app/kb/tool.py`（新增 `make_kb_read_tool`）
- Test: `tests/unit/app/kb/test_catalog.py`、`tests/unit/runtime/test_kb_wiring.py`

**Interfaces:**
- Consumes: Task 7 `list_bound_space_ids`、Task 2 spaces（name/description）
- Produces: `render_kb_catalog(spaces: list[KbSpace]) -> str`（输出 `<knowledge-bases>...</knowledge-bases>` 块，空列表返回 ""）；builder 规则：**Agent 有绑定库才注册 `kb_search`/`kb_read` 并注入目录**（替代现状"任意库存在即注册"）；`kb_read(doc_id)` 工具返回文档权威 MD 全文

- [ ] **Step 1: 写失败测试**

```python
# -*- coding: utf-8 -*-
"""M6-9: 目录注入渲染与空绑定零注入。"""
from __future__ import annotations

import pytest

from qwenpaw.app.kb.catalog import render_kb_catalog
from qwenpaw.app.kb.models import KbSpace

pytestmark = pytest.mark.unit


def test_render_catalog_block() -> None:
    spaces = [KbSpace(id="kb_yunchan", name="孕产知识库",
                      description="涉及孕产用药、产检问题时检索本库。")]
    out = render_kb_catalog(spaces)
    assert "<knowledge-bases>" in out
    assert "<id>kb_yunchan</id>" in out
    assert "必须先调用 kb_search" in out


def test_render_empty_returns_blank() -> None:
    assert render_kb_catalog([]) == ""
```

- [ ] **Step 2: 跑失败**
- [ ] **Step 3: 实现 catalog.py + builder 接线** — `_collect_kb_tools` 查 `list_bound_space_ids(agent_id)` → 非空才注册 `kb_search`+`kb_read` 两工具并产出 catalog 块，空则不注册不注入（替代现状「任意库存在即注册」）；**注入通道定位（实施首步）**：`grep -rn "active_skills" src/qwenpaw/runtime src/qwenpaw/agents` 找到 skills 目录进 system prompt 的渲染函数（已知传参链 `builder.py` L146 `active_skills=effective_skills`），在同函数尾部按相同模式追加 `kb_catalog: str` 参数；若 skills 实际经 `Toolkit(skills_or_loaders=...)` 对象注入而非字符串拼接，则改用 `on_system_prompt` hook 追加（参照 `SpanRecorderMiddleware` 的 hook 注册点）；json 后端 catalog 数据源=文件 registry（spaces 列表取 name/description）
- [ ] **Step 4: 接线单测通过**（无绑定 Agent：工具不注册、prompt 不含块；有绑定：含块且注册）
- [ ] **Step 5: Commit** — `git commit -am "feat(kb): inject knowledge-base catalog into agent prompt on bindings"`

---

### Task 10: kb_search 演进（kb_id/expand/结构扩展/溯源）

**Files:**
- Modify: `src/qwenpaw/app/kb/tool.py`、`service.py`
- Test: `tests/unit/app/kb/test_kb_search_tool.py`

**Interfaces:**
- Consumes: Task 5 引擎、Task 7 绑定（Agent 身份→space_ids，S0 收敛）、`kb_documents` 全文（S2 回补）
- Produces: `kb_search(query, kb_id="", max_results=5, expand="none")`；S0：绑定集合 ∩ 指定库；S2 `expand=section` 合并同 heading_path 兄弟块；输出格式 `===== [库名] 文档标题 #heading [score=x] =====`（沿用现状溯源行）

- [ ] **Step 1: 写失败测试**（三断言：越权库查不到 / expand=section 输出含父块全文 / 未指定库时多库融合按分排序）
- [ ] **Step 2: 跑失败** → **Step 3: 实现**（Agent 身份解析复用 `_current_identity()` + `request_context` 的 agent_id；expand=graph 一期返回占位提示文本，二期实装）
- [ ] **Step 4: 通过** → **Step 5: Commit** — `git commit -am "feat(kb): kb_search with binding-acl convergence and section expansion"`

---

### Task 11: 人侧 API 扩展（文档 CRUD / 上传 / chunk 预览 / search-test）

**Files:**
- Modify: `src/qwenpaw/app/routers/kb.py`、`src/qwenpaw/app/routers/admin/kb.py`
- Test: `tests/integration/test_kb_api_phase1.py`

**Interfaces:**
- Consumes: Task 6 ingest、Task 5 engine、RBAC
- Produces: spec §10 端点表全量；`GET /api/kb/{spaceId}/tree`（path 聚合目录树）；`GET/PUT/DELETE /api/kb/{spaceId}/documents/{docId}`（MD 编辑=content_md upsert 自动版本+重索引）；`POST .../documents/upload`（multipart，管理权校验）；`GET .../documents/{docId}/chunks`；`POST /api/admin/kb/search-test`（透传引擎 top-k + 得分）

- [ ] **Step 1-2: 先写失败集成测试**（建库→上传 html→200 且 ready→PUT 编辑 MD→版本+1→chunks 预览非空→search-test 命中）

```python
# -*- coding: utf-8 -*-
"""M6-11: 员工面文档 CRUD / 上传 / 预览 / search-test 全链路。"""
from __future__ import annotations

from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.p0]


app_server: Any  # 复用 tests/integration 既有 app_server 夹具


def test_kb_document_lifecycle(app_server) -> None:
    """建库→上传→编辑→预览→检索测试。"""
    space = app_server.api_request(
        "POST", "/api/kb", json={"name": "孕产库", "description": "孕产用药问题检索本库"},
    )
    assert space.status_code == 201, app_server.logs_tail()
    space_id = space.json()["id"]

    up = app_server.api_request(
        "POST", f"/api/kb/{space_id}/documents/upload",
        files={"file": ("guide.html", b"<h1>甲减</h1><p>左甲状腺素</p>", "text/html")},
    )
    assert up.status_code == 201, app_server.logs_tail()
    doc_id = up.json()["doc_id"]

    got = app_server.api_request("GET", f"/api/kb/{space_id}/documents/{doc_id}")
    assert got.json()["ingest_status"] == "ready"

    put = app_server.api_request(
        "PUT", f"/api/kb/{space_id}/documents/{doc_id}",
        json={"content_md": "# 甲减\n\n左甲状腺素剂量增加 20%-30%。"},
    )
    assert put.status_code == 200 and put.json()["version"] == 2

    chunks = app_server.api_request(
        "GET", f"/api/kb/{space_id}/documents/{doc_id}/chunks",
    )
    assert len(chunks.json()) >= 1

    hit = app_server.api_request(
        "POST", f"/api/kb/search", json={"query": "左甲状腺素", "kb_id": space_id},
    )
    assert hit.json()["hits"], "混合检索应命中"
```
- [ ] **Step 3: 实现路由**（复用 `_access_kwargs` 人侧 ACL；pg 不可用时路由返回 503 显式提示而非静默失败）
- [ ] **Step 4: 集成通过**（隔离库 DSN 跑法同前）
- [ ] **Step 5: Commit** — `git commit -am "feat(kb): employee document crud, upload, chunk preview and search-test apis"`

---

### Task 12: 前端——API 模块与 Admin 知识页重构

**Files:**
- Modify: `console/src/api/modules/admin/kb.ts`（新端点）；Create: `console/src/api/modules/employeeKb.ts`
- Modify: `console/src/pages/Admin/Knowledge.tsx`（重构）
- Test: `console/src/api/modules/admin/adminApi.test.ts` 追加；`employeeKb.test.ts`
- Modify: i18n 七语言文件（`knowledge.*` 键）

**Interfaces:**
- Consumes: Task 11 端点
- Produces: 三个页面组件（见 Task 13）消费的 hooks；`employeeKbApi = {listSpaces, createSpace, getTree, getDoc, saveDoc, uploadDoc, listChunks, searchTest, bindAgent, listBindings, unbind}`

- [ ] **Step 1: 先写 API 层失败单测**（对齐 `adminApi.test.ts` 现有 mockRequest 断言模式：路径/方法/body 严格一致）
- [ ] **Step 2: 跑失败** → **Step 3: 实现 api 模块** → **Step 4: 通过**
- [ ] **Step 5: Admin/Knowledge.tsx 重构**：卡片网格（scope 筛选器+域标签）→ 库详情 Drawer（宽）内左目录树右 MD 编辑器（复用员工详情档案 MD 编辑器组件）+ 上传（antd Upload 接 `/upload`）+ chunk 预览表（列居中）+ 检索测试台（query 输入→命中列表带 score）
- [ ] **Step 6: `npm run build` 类型检查通过 + i18n 七语言补齐 → Commit** — `git commit -am "feat(console): rebuild admin knowledge page with tree editor upload and search-test"`

---

### Task 13: 前端——员工知识库工作区页 + Agent 详情知识 Tab

**Files:**
- Create: `console/src/pages/Employee/Knowledge/index.tsx`（+ 子组件同目录）
- Modify: 员工路由注册、侧边栏入口、Agent 详情页知识 Tab、i18n 七语言
- Test: 路由解析 + 页面组件渲染单测（React Testing Library）

**Interfaces:**
- Consumes: Task 12 api、Task 7 bindings 端点
- Produces: 业务人员建库→传文档→绑定员工三步流；Agent 详情 Tab 展示绑定库（名称/scope/授权人）与解绑

- [ ] **Step 1: 组件失败测试**（建库表单：description 必填校验；绑定下拉只列管理权内 space）
- [ ] **Step 2-4: 实现并跑通**（表单「检索场景描述」字段带编写指引 tooltip；枚举下拉数据来自 space 列表非硬编码）
- [ ] **Step 5: `npm run build` 通过 + Commit** — `git commit -am "feat(console): employee knowledge workspace and agent kb bindings tab"`

---

### Task 14: 检索质量评测集与 CI 回归

**Files:**
- Create: `tests/eval/kb/golden_yunchan.json`（20~30 条 query→期望 doc）、`tests/eval/kb/run_eval.py`、样例语料 `tests/eval/kb/corpus/*.md`
- Test: `tests/eval/kb/test_eval_harness.py`（指标计算逻辑单测，不依赖真库）

**Interfaces:**
- Consumes: Task 5/6/10/11 全链路
- Produces: `python -m tests.eval.kb.run_eval --space <id>` 输出 `recall@5 / mrr`；阈值 **Recall@5 ≥ 0.9 / MRR ≥ 0.7**（spec §12）

- [ ] **Step 1: 指标计算单测**（构造 hits 断言 recall/mrr 正确）
- [ ] **Step 2: 实现 run_eval**（摄入 corpus 到隔离库→逐 query 检索→比对 expected_doc→汇总表）
- [ ] **Step 3: 全链路跑通**（隔离库 + session loop 覆盖）；未达标则回填切片/权重调优（调优记录写进本文件末尾）
- [ ] **Step 4: Commit** — `git commit -am "test(kb): golden-query recall evaluation harness"`

---

### Task 15: 端到端验收与收尾

**Files:**
- Modify: 部署文档/compose（pgvector 扩展标注）、`CLAUDE.md` 模块速览（如含 kb 章节）
- Test: 端到端集成用例

- [ ] **Step 1: E2E 链路测试**：建库→传 3 篇 MD（含交叉 wikilink）→绑定 Agent→以该 Agent 对话触发 `kb_search`→结果含溯源行且解绑后查不到（越权断言收口）
- [ ] **Step 2: `make quick` / 全量 `pytest tests/unit/app/kb tests/integration/test_kb_*` 绿**
- [ ] **Step 3: 页面走查交付**：按团队分工由用户人工验收（浏览器路径：Admin 页 + 员工页 + Agent Tab）
- [ ] **Step 4: Commit** — `git commit -am "test(kb): phase-1 end-to-end acceptance suite"`

---

## 依赖顺序

```
T1 → T2 → {T3, T4} → T5 → T6 → {T7, T8} → {T9, T10} → T11 → {T12, T13} → T14 → T15
```

T3/T4、T7/T8、T9/T10、T12/T13 可并行；前端（T12/13）可在 T11 后与 T14 并行。

## 验收标准（对照 spec §12）

- 迁移幂等：0034 执行两遍零报错
- 检索质量：golden query Recall@5 ≥ 0.9、MRR ≥ 0.7
- 权限：越权用例全绿（S0 先于 S1；未绑定 Agent 查不到；无权用户列不出库）
- 回退：backend=json 时行为与一期前逐字节一致（旧单测全绿）
- 前端：build 零类型错误，i18n 新增键七语言齐全
