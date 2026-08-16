-- ============================================================
-- 变更说明: media_files 表扩展 —— 升级为「会话文件登记表」
--           新增 7 列：chat_id / session_id / owner_id /
--           source（upload=用户上传 | agent_output=Agent 产出）/
--           storage_type（db=本地+PG 双写可恢复 | local=仅本地 |
--           minio/oss=对象存储预留）/
--           storage_uri（本地绝对路径或对象存储 URI）/
--           sha256（内容指纹，Agent 产出按内容寻址去重）
--           + 2 个查询索引（按会话 / 按会话 ID）
--           修复链：上传文件与会话无关联查不到出处、
--           Agent 产出报告本地误删无法恢复两项需求的数据基座
-- 变更时间: 2026-08-16
-- 变更人:   清风
-- 适用环境: 测试环境（在已有库基础上增量执行）
-- 对应迁移: alembic 0007_media_registry（Revises 0006_xian_workspaces）
-- [同步至 db/feature/xianwork_enterprise_20260814/test.sql] 是
-- [同步至 db/feature/xianwork_enterprise_20260814/prod.sql] 是
-- 执行方式: psql 单事务执行；全部语句幂等（IF NOT EXISTS），可重复执行
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. media_files 扩展列（全部可空或有默认值，存量行语义不变：
--    source 缺省 upload、storage_type 缺省 db，即上传双写副本）
-- ------------------------------------------------------------

ALTER TABLE media_files ADD COLUMN IF NOT EXISTS chat_id VARCHAR(128);
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS session_id VARCHAR(255);
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS owner_id VARCHAR(128);
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS source VARCHAR(32) NOT NULL DEFAULT 'upload';
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS storage_type VARCHAR(16) NOT NULL DEFAULT 'db';
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS storage_uri TEXT;
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS sha256 VARCHAR(64);

COMMENT ON COLUMN media_files.chat_id IS '关联会话 ID（console 面 chat_id；用户上传时必填，Agent 产出写入时可能为空、经 session_id 关联）';
COMMENT ON COLUMN media_files.session_id IS '会话的 agent 侧 session_id（上传与 Agent 产出两条链路都能取到，是会话关联的可靠键）';
COMMENT ON COLUMN media_files.owner_id IS '归属账号（上传链路取 request.state.user；Agent 产出可能为空，读取时经会话归属二次校验）';
COMMENT ON COLUMN media_files.source IS '文件来源：upload=用户聊天上传；agent_output=Agent 任务过程中产出/输出';
COMMENT ON COLUMN media_files.storage_type IS '存储方式：db=本地工作副本+PG 字节副本双写（可恢复）；local=仅本地登记；minio/oss=对象存储（预留）';
COMMENT ON COLUMN media_files.storage_uri IS '存储定位：本地存储为绝对路径（服务端落库前 resolve）；对象存储为 minio://bucket/key 或 oss://bucket/key';
COMMENT ON COLUMN media_files.sha256 IS '内容 SHA-256 指纹（Agent 产出以 sha256 前 16 位参与 stored_name 内容寻址去重，同内容不重复入库）';

-- ------------------------------------------------------------
-- 2. 查询索引（会话维度列表 / 会话 ID 维度匹配）
-- ------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_media_files_chat
    ON media_files (tenant_id, chat_id);

CREATE INDEX IF NOT EXISTS ix_media_files_session
    ON media_files (tenant_id, session_id);

-- ------------------------------------------------------------
-- 3. Alembic 版本标记
-- ------------------------------------------------------------

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM alembic_version) THEN
        UPDATE alembic_version SET version_num = '0007_media_registry';
    ELSE
        INSERT INTO alembic_version (version_num) VALUES ('0007_media_registry');
    END IF;
END $$;

COMMIT;
