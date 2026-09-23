# -*- coding: utf-8 -*-
"""Knowledge base PG plane (M6 knowledge center, phase 1).

Revision ID: 0034_kb_pg_plane
Revises: 0033_employee_governance_manage
Create Date: 2026-09-17

新建知识库权威平面六表（设计 spec：
docs/superpowers/specs/2026-09-17-knowledge-base-architecture-design.md §4）：

- ``kb_spaces``：知识库注册（替代 JSON ``kb_registry.json``），含 scope/grants
  与 ``engine`` 索引引擎路由列（auto/pgvector/milvus，双引擎一期全实现）；
- ``kb_documents``：Markdown 权威源（Single Source of Truth），含 content_hash
  幂等拦截、文档级异步摄入状态机（ingest_status/error）与逻辑删除；
- ``kb_document_versions``：文档版本快照（编辑可回溯，复用 agent_docs 版本模式）；
- ``kb_chunks``：派生索引（可全量重建）——pgvector 1024 维稠密向量 + tsvector
  全文（应用层分词写入）+ heading_path 结构锚点 + parent_chunk_id 父子回补；
- ``kb_links``：wikilink 边（``[[路径]]`` 解析落表，S2 图扩展数据源）；
- ``agent_kb_bindings``：数字员工↔知识库授权绑定（绑定即授权，决策点 1）。

依赖 pgvector 扩展（``CREATE EXTENSION`` 失败即显式报错，不做静默降级）。
全部 DDL 幂等（IF NOT EXISTS / DO 块按约束名判定），重复执行零副作用。

（psql twin: changelog 20260917/02，分支 agent_run_logs_20260908）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0034_kb_pg_plane"
down_revision = "0033_employee_governance_manage"
branch_labels = None
depends_on = None

# 向量扩展：本机/部署 PG 镜像须为 pgvector/pgvector:pg16（spec §13 部署变更）
_CREATE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector"

# 六表 DDL（联合主键带 tenant_id、UTC timestamptz、枚举 TEXT，对齐项目 PG 平面惯例）
_CREATE_TABLES = (
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
        engine TEXT NOT NULL DEFAULT 'auto',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_kb_spaces PRIMARY KEY (tenant_id, id),
        CONSTRAINT ck_kb_spaces_scope
            CHECK (scope IN ('personal', 'team', 'enterprise')),
        CONSTRAINT ck_kb_spaces_engine
            CHECK (engine IN ('auto', 'pgvector', 'milvus'))
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
    """
    CREATE TABLE IF NOT EXISTS kb_document_versions (
        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
        document_id VARCHAR(64) NOT NULL,
        version INTEGER NOT NULL,
        content_md TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        created_by VARCHAR(64) NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT pk_kb_document_versions
            PRIMARY KEY (tenant_id, document_id, version)
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
        CONSTRAINT pk_agent_kb_bindings
            PRIMARY KEY (tenant_id, agent_id, space_id)
    )
    """,
)

# CHECK 约束无 IF NOT EXISTS 语法，用 DO 块按名称判定（幂等，照 0033 模式）
_ADD_DOC_CHECKS = (
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
            ALTER TABLE kb_documents
                ADD CONSTRAINT ck_kb_documents_ingest_status
                CHECK (
                    ingest_status IN (
                        'pending', 'processing', 'ready', 'failed'
                    )
                );
        END IF;
    END
    $$;
    """,
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_kb_spaces_scope ON kb_spaces (tenant_id, sc"
    "ope)",
    "CREATE INDEX IF NOT EXISTS ix_kb_documents_space "
    "ON kb_documents (tenant_id, space_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_documents_path "
    "ON kb_documents (tenant_id, space_id, path) WHERE NOT is_delete",
    "CREATE INDEX IF NOT EXISTS ix_kb_document_versions_doc "
    "ON kb_document_versions (tenant_id, document_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_space "
    "ON kb_chunks (tenant_id, space_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_document ON kb_chunks (document_i"
    "d)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_tsv ON kb_chunks USING GIN (tsv)",
    "CREATE INDEX IF NOT EXISTS ix_kb_chunks_embedding "
    "ON kb_chunks USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS ix_kb_links_src ON kb_links (src_document_id)",
    "CREATE INDEX IF NOT EXISTS ix_kb_links_dst ON kb_links (dst_document_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_kb_bindings_space "
    "ON agent_kb_bindings (tenant_id, space_id)",
)

# 逐列中文注释（内容源 = spec §4.2 字段清单）
_COMMENTS = (
    "COMMENT ON TABLE kb_spaces IS "
    "'知识库注册表（知识中心权威平面：库名/描述/scope/grants/引擎路由；"
    "JSON kb_registry.json 的 PG 投影，json 后端零动作、pg 权威读）'",
    "COMMENT ON COLUMN kb_spaces.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN kb_spaces.id IS '知识库 ID（业务侧生成，与 tenant_id 组成联合主键）'",
    "COMMENT ON COLUMN kb_spaces.name IS '知识库名称（目录注入展示用）'",
    "COMMENT ON COLUMN kb_spaces.description IS "
    "'检索场景描述（路由信号：回答数字员工何时该查本库，建库必填）'",
    "COMMENT ON COLUMN kb_spaces.scope IS '可见范围: personal-个人私有, team-团队共享, ent"
    "erprise-企业全员'",
    "COMMENT ON COLUMN kb_spaces.owner_id IS '归属用户（personal scope：库所有者）'",
    "COMMENT ON COLUMN kb_spaces.team_id IS '归属团队（team scope：团队 id）'",
    "COMMENT ON COLUMN kb_spaces.grants IS '范围外显式授权 JSONB {roles,users,teams}（"
    "与 M4-3 agent/model grant 语义一致）'",
    "COMMENT ON COLUMN kb_spaces.embedding_model IS '本库 embedding 模型名（空串=全局默认 "
    "text-embedding-v4）'",
    "COMMENT ON COLUMN kb_spaces.engine IS '索引引擎路由: auto/pgvector-默认 pgvector "
    "引擎, milvus-大库显式启用 Milvus（按库开关）'",
    "COMMENT ON COLUMN kb_spaces.created_at IS '创建时间（DB 自动维护，UTC）'",
    "COMMENT ON COLUMN kb_spaces.updated_at IS '更新时间（DB 自动维护，UTC）'",
    "COMMENT ON TABLE kb_documents IS '知识文档表（Markdown 权威源：Single Source of Tru"
    "th，向量索引是其可重建派生缓存）'",
    "COMMENT ON COLUMN kb_documents.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN kb_documents.id IS '文档 ID（业务侧生成）'",
    "COMMENT ON COLUMN kb_documents.space_id IS '所属知识库 id（关联 kb_spaces）'",
    "COMMENT ON COLUMN kb_documents.path IS '库内目录路径（如 孕产/用药/甲减.md，前端目录树数据源；可空）"
    "'",
    "COMMENT ON COLUMN kb_documents.title IS '文档标题'",
    "COMMENT ON COLUMN kb_documents.content_md IS 'Markdown 正文全文（权威源，人工可修正，修正即"
    "重切重嵌）'",
    "COMMENT ON COLUMN kb_documents.content_hash IS '内容 sha256 指纹：与既有行相同则跳过重切重"
    "嵌（版本不抖动）'",
    "COMMENT ON COLUMN kb_documents.source IS '来源: manual-页面编辑, upload-文件上传, u"
    "rl-网页抓取'",
    "COMMENT ON COLUMN kb_documents.source_meta IS '来源元数据 JSONB（原始文件名/大小/URL 等"
    "）'",
    "COMMENT ON COLUMN kb_documents.ingest_status IS '文档级异步摄入状态: pending-待处理, "
    "processing-解析中, ready-可检索, failed-失败（error 携带原因）'",
    "COMMENT ON COLUMN kb_documents.error IS '摄入失败原因（failed 时可读；空串=无错误）'",
    "COMMENT ON COLUMN kb_documents.is_delete IS '逻辑删除标记（核心知识数据禁止物理删除）'",
    "COMMENT ON COLUMN kb_documents.updated_by IS '最后更新人（用户账号）'",
    "COMMENT ON COLUMN kb_documents.created_at IS '创建时间（DB 自动维护，UTC）'",
    "COMMENT ON COLUMN kb_documents.updated_at IS '更新时间（DB 自动维护，UTC）'",
    "COMMENT ON TABLE kb_document_versions IS '文档版本快照（编辑回溯：内容变更时追加一行）'",
    "COMMENT ON COLUMN kb_document_versions.tenant_id IS '租户 ID（多租户预留，现阶段固定 de"
    "fault）'",
    "COMMENT ON COLUMN kb_document_versions.document_id IS '文档 id（关联 kb_docume"
    "nts）'",
    "COMMENT ON COLUMN kb_document_versions.version IS '版本号（同文档单调递增）'",
    "COMMENT ON COLUMN kb_document_versions.content_md IS '该版本 Markdown 全文快照'",
    "COMMENT ON COLUMN kb_document_versions.content_hash IS '该版本内容指纹'",
    "COMMENT ON COLUMN kb_document_versions.created_by IS '写入人（用户账号）'",
    "COMMENT ON COLUMN kb_document_versions.created_at IS '快照时间（DB 自动维护，UTC）'",
    "COMMENT ON TABLE kb_chunks IS '切片派生索引表（可全量重建：pgvector 稠密向量 + tsvector 全文 "
    "+ 结构锚点）'",
    "COMMENT ON COLUMN kb_chunks.id IS '切片 ID（doc_id_seq 稳定生成）'",
    "COMMENT ON COLUMN kb_chunks.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN kb_chunks.space_id IS '所属知识库 id（S0 ACL 收敛过滤列）'",
    "COMMENT ON COLUMN kb_chunks.document_id IS '所属文档 id（关联 kb_documents）'",
    "COMMENT ON COLUMN kb_chunks.seq IS '切片在文档内的序号（单调递增）'",
    "COMMENT ON COLUMN kb_chunks.heading_path IS '标题路径（如 孕产用药 > 甲减 > 妊娠早期），emb"
    "edding 拼接与 S2 结构扩展依据'",
    "COMMENT ON COLUMN kb_chunks.parent_chunk_id IS '父切片 id（长段拆分时回指原语义块；空串=无父块"
    "）'",
    "COMMENT ON COLUMN kb_chunks.token_count IS '切片 token 估算数（切片器目标 600）'",
    "COMMENT ON COLUMN kb_chunks.content_text IS '切片正文（不含 heading_path 拼接前缀）'",
    "COMMENT ON COLUMN kb_chunks.tsv IS '全文检索向量（应用层分词后以 simple 配置写入：英文词 + CJK "
    "bigram）'",
    "COMMENT ON COLUMN kb_chunks.embedding IS '稠密向量 1024 维（DashScope text-embe"
    "dding-v4，HNSW cosine 索引）'",
    "COMMENT ON COLUMN kb_chunks.model_name IS "
    "'产生该向量的 embedding 模型名"
    "（换模型重建依据）'",
    "COMMENT ON COLUMN kb_chunks.created_at IS '索引写入时间（DB 自动维护，UTC）'",
    "COMMENT ON TABLE kb_links IS 'wikilink 边表（文档正文 [[路径]] 解析落表；S2 expand=grap"
    "h 图扩展数据源）'",
    "COMMENT ON COLUMN kb_links.tenant_id IS '租户 ID（多租户预留，现阶段固定 default）'",
    "COMMENT ON COLUMN kb_links.id IS '链接边 ID（业务侧生成，与 tenant_id 组成联合主键）'",
    "COMMENT ON COLUMN kb_links.space_id IS '所属知识库 id'",
    "COMMENT ON COLUMN kb_links.src_document_id IS '链接源文档 id'",
    "COMMENT ON COLUMN kb_links.dst_path IS '链接目标路径（[[路径]] 原文）'",
    "COMMENT ON COLUMN kb_links.dst_document_id IS '解析到的目标文档 id（悬挂链接为空串）'",
    "COMMENT ON COLUMN kb_links.context_snippet IS '链接所在句子上下文（图扩展摘要展示用）'",
    "COMMENT ON COLUMN kb_links.created_at IS '解析落表时间（DB 自动维护，UTC）'",
    "COMMENT ON TABLE agent_kb_bindings IS '数字员工↔知识库授权绑定表（绑定即授权，决策点 1：Agent 检索"
    "可见性=其绑定库集合）'",
    "COMMENT ON COLUMN agent_kb_bindings.tenant_id IS '租户 ID（多租户预留，现阶段固定 defau"
    "lt）'",
    "COMMENT ON COLUMN agent_kb_bindings.agent_id IS '数字员工 id'",
    "COMMENT ON COLUMN agent_kb_bindings.space_id IS '知识库 id（写入前经 can_manage_s"
    "pace 管理权校验）'",
    "COMMENT ON COLUMN agent_kb_bindings.granted_by IS '授权人（用户账号）'",
    "COMMENT ON COLUMN agent_kb_bindings.remark IS '备注（授权说明）'",
    "COMMENT ON COLUMN agent_kb_bindings.created_at IS '绑定时间（DB 自动维护，UTC）'",
)


def upgrade() -> None:
    # 向量扩展（缺失时显式报错，提示换 pgvector/pgvector:pg16 基线）
    op.execute(_CREATE_EXTENSION)
    # 六表幂等建表
    for statement in _CREATE_TABLES:
        op.execute(statement)
    # 文档表枚举 CHECK 约束
    for statement in _ADD_DOC_CHECKS:
        op.execute(statement)
    # 检索/权限/图扩展索引（含 HNSW 向量索引与 GIN 全文索引）
    for statement in _INDEXES:
        op.execute(statement)
    # 逐列中文注释
    for comment in _COMMENTS:
        op.execute(comment)


def downgrade() -> None:
    # 逆序清理（快照文件退役前本分支只跑一次，物理删表仅限开发回滚场景）
    for table in (
        "agent_kb_bindings",
        "kb_links",
        "kb_chunks",
        "kb_document_versions",
        "kb_documents",
        "kb_spaces",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
