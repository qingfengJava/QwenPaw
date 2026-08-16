# XianWork 会话文件存储设计（media_files 登记体系）

> 日期：2026-08-16　作者：qingfeng　分支：feature/xianwork_enterprise_20260814
> 关联：alembic 0007_media_registry / changelog 20260816/03_media_registry.sql
> 需求来源：企业落地版（workbuddy 类产品）文件链路专项需求

---

## 1. 现状确认（你问的"文件到底存在哪"）

改造前 `media_files` 只是一张"字节缓存表"，两条链路的真实存储情况：

| 链路 | 本地磁盘 | PostgreSQL `media_files` | 会话关联 | 可恢复性 |
| --- | --- | --- | --- | --- |
| 用户聊天上传（`POST /api/console/upload`） | ✅ `{会话生效项目目录}/media/{stored_name}`（Agent 工具的工作副本） | ✅ BYTEA 全量副本（回显端点优先读它） | ❌ 无 chat_id/session_id/owner | 回显可恢复（刷新/换机），**但查不到"这个会话传过哪些文件"** |
| Agent 产出（write_file/edit_file/append_file 等） | ✅ 直接写工作空间目录 | ❌ 完全无记录 | ❌ | **本地误删即永久丢失** |

结论：**上传文件是"本地 + 数据库"双写；Agent 产出只有本地单份**。两者都缺会话关联元数据 —— 这正是本次改造补齐的部分。

## 2. 目标架构：统一「会话文件登记表」

`media_files` 升级为所有会话相关文件的唯一登记处（0007 迁移新增 7 列）：

| 列 | 语义 |
| --- | --- |
| `chat_id` | console 面会话 ID（上传链路必填；Agent 产出行可空，经 session_id 关联） |
| `session_id` | agent 侧会话 ID（两条链路都能取到的可靠关联键） |
| `owner_id` | 归属账号（上传取登录用户；Agent 产出可空，读取时经会话归属二次校验） |
| `source` | `upload`＝用户聊天上传；`agent_output`＝Agent 任务产出 |
| `storage_type` | `db`＝本地工作副本＋PG 字节副本双写（可恢复）；`local`＝仅本地登记；`minio`/`oss`＝对象存储（预留） |
| `storage_uri` | 存储定位：本地为服务端 resolve 后的绝对路径；对象存储为 `minio://bucket/key` / `oss://bucket/key` |
| `sha256` | 内容指纹；Agent 产出用哈希前 16 位参与 `stored_name`（`{hash16}_{安全文件名}`）实现内容寻址去重与多版本保留 |

保留原主键 `(tenant_id, stored_name)`，`stored_name` 同时是回显端点
`GET /api/console/media/{stored_name}` 的 URL 段（上传用 uuid 前缀、
Agent 产出用哈希前缀，均不可猜、不含路径分隔符）。

## 3. 用户聊天上传：完整处理流

```
用户在 XianWork 聊天框选文件
  → POST /api/console/upload (multipart, 可带 chat_id)
  → 服务端：
     1. 校验会话归属（未认证本地模式放行）
     2. 解析会话生效项目目录（workspace 绑定 > agent 配置 > 默认）
     3. 写本地工作副本 {project_dir}/media/{uuid}_{安全文件名}
     4. PG 登记完整元数据 + BYTEA 副本（source=upload,
        storage_type=db, storage_uri=本地绝对路径, sha256, chat_id,
        session_id, owner_id）
  → 前端拿到 {url, stored_name}，消息以 stored_name 引用
  → 回显/历史回放：GET /api/console/media/{stored_name}
     （PG 优先 → 本地回退；PG 挂掉只影响回显旧图，不影响上传）
```

该链路已实现（本次改造补齐第 4 步的元数据）。

## 4. Agent 产出文件：登记 + 恢复

### 4.1 写入登记（已实现：`tool_calls/media_hooks.py`）

- 挂点：`ToolHookRegistry` 对 `write_file` / `edit_file` / `append_file` 的 before/after 钩子（`react_agent._register_tool_call_hooks` 注册；与超时元数据字段合并不互斥）。
- before 钩子把 `file_path` 暂存 `ctx.extra`；after 钩子在 `ToolResultState.SUCCESS` 后：
  1. 复用 `file_io._resolve_file_path` 展开相对路径；
  2. 超过 20MB 快照上限的产物跳过（只留本地，避免 PG 膨胀）；
  3. 读内容算 sha256，以 `{hash16}_{安全文件名}` 内容寻址 upsert
     （同内容幂等去重，内容变化生成新版本行 → 保留版本历史）；
  4. `source='agent_output'`、`session_id=ctx.session_id`、`storage_uri=绝对路径`。
- 全程 best-effort：PG 不可用 / 读失败仅记日志，绝不影响工具执行。

### 4.2 查询与恢复（已实现：`app/routers/xian/files.py`）

- `GET /api/xian/files?chat_id=`：列出该会话全部登记文件（上传＋产出），每项带 `exists_local`（本地副本是否还在）、`url`（回显地址），新到旧。
- `POST /api/xian/files/{stored_name}/restore`：把 PG 副本写回 `storage_uri`（父目录缺失自动重建 —— 覆盖"整个工作空间目录被删"的场景）。多版本行可各自恢复。
- 权限：恢复端点要求登记行能解析到归属当前用户的会话（chat_id 直连或 session_id 反查），跨用户越权一律 404 不泄露存在性。

### 4.3 误删恢复的兜底边界

| 场景 | 能否恢复 | 说明 |
| --- | --- | --- |
| 报告文件被删、工作空间目录还在 | ✅ | restore 写回原路径 |
| 工作空间整个目录被删 | ✅ | restore 自动 mkdir -p 父目录后写回 |
| 产物 > 20MB（数据集/视频等） | ❌ | 快照上限外，仅本地；后续可选升 MinIO |
| 产物由非 file_io 工具生成（如浏览器下载） | ❌（本期） | 见 §6 扩展点 |
| PG 未配置（纯本地单机无 DSN） | ❌ | 登记表本身不可用，维持旧行为 |

## 5. 云存储模式（OSS / MinIO）—— 设计与落地路径

企业落地建议优先 **MinIO（私有化）**，公有云用阿里 OSS。表结构已预留
（`storage_type` + `storage_uri`），本期未启用对象存储客户端，落地方案：

### 5.1 配置开关（渐进迁移，不开不生效）

```yaml
# qwenpaw 配置（config.yaml 或环境变量）
media:
  storage_mode: local        # local=现状(db 双写) | minio | oss
  minio:
    endpoint: minio.internal:9000
    access_key: ***
    secret_key: ***
    bucket: qwenpaw-media
    secure: true
  oss:
    endpoint: oss-cn-hangzhou.aliyuncs.com
    access_key_id: ***
    access_key_secret: ***
    bucket: qwenpaw-media
```

### 5.2 写入流（对象存储模式）

1. 上传/登记时先落本地工作副本（Agent 工具仍需要本地文件，行为不变）；
2. 异步（线程池）推对象存储：`put_object(bucket, key)`，key =
   `{tenant}/{chat_id 或 session}/{stored_name}`；
3. 登记行写 `storage_type='minio'/'oss'`、`storage_uri='minio://bucket/key'`、
   **`data` 列不再存字节**（BYTEA 仅 `storage_type='db'` 时使用）；
4. 回显端点按 storage_type 分派：对象存储行走 presigned URL（302）或
   服务端代理流式转发（内网更简单，避免 URL 泄露）。

### 5.3 恢复流（对象存储模式）

restore 端点按 `storage_uri` 拉对象 → 写回本地 `storage_uri` 对应的
本地路径字段（需补一列 `local_path` 或复用 metadata）。误删恢复语义
与 §4.2 完全一致，只是字节来源从 PG BYTEA 换成对象存储。

### 5.4 存量迁移

`storage_mode` 切换后跑一次性任务：扫描 `storage_type='db'` 行 →
逐条 put_object → 更新 storage_type/storage_uri → （可选）`UPDATE media_files
SET data = NULL`。幂等可重跑；上传/恢复链路按行内 storage_type 分派，
新旧模式可长期共存（灰度友好）。

### 5.5 选型对比

| 维度 | 本地+PG 双写（现状） | MinIO | OSS |
| --- | --- | --- | --- |
| 部署 | 零依赖 | +1 组件（容器很轻） | 零组件（用云） |
| 大文件 | PG 存大 BYTEA 有压力（已设 20MB 上限） | 对象存储天然适合 | 同左 |
| 多主机部署 | PG 副本已解决回显 | 天然共享 | 天然共享 |
| 合规/私有化 | ✅ | ✅（私有化首选） | 需公网/专线 |
| 成本 | DB 容量成本 | 磁盘成本最低 | 按量付费 |

## 6. 容量治理与后续扩展点

- **保留策略**：按 `source='agent_output'` 的 `updated_at` 定期归档/清理
  （例如保留 90 天）；`upload` 行跟随会话删除策略（可加会话删除时的
  级联清理任务 —— 当前删会话不删文件，行为保持）。
- **去重**：内容寻址 stored_name 已天然去重；跨会话同内容文件可进一步
  抽出 `sha256` 索引做引用计数（YAGNI，暂不做）。
- **非 file_io 产物**：浏览器下载、exec 生成的文件可通过同样的 after 钩子
  模式扩展（钩子按工具名注册，机制通用）。
- **前端面板**：`GET /api/xian/files` 已就绪，XianWork 聊天页可加"会话文件"
  抽屉（上传/产出分组 + 一键恢复），作为下个迭代需求。

## 7. 本次代码落点清单

| 文件 | 变更 |
| --- | --- |
| `db/feature/xianwork_enterprise_20260814/changelog/20260816/03_media_registry.sql` | 7 列 + 2 索引（幂等） |
| `db/feature/xianwork_enterprise_20260814/test.sql` / `prod.sql` | 快照同步（第 9/10 节） |
| `src/qwenpaw/db/alembic/versions/0007_media_registry.py` | 迁移（Revises 0006） |
| `src/qwenpaw/db/models_media.py` | ORM 补列 + 索引 |
| `src/qwenpaw/app/media_store.py` | `save_media_blob` 元数据扩展；`load_media_record` / `list_media_records` |
| `src/qwenpaw/app/routers/console.py` | `/console/upload` 登记 chat/session/owner/source/storage_uri/sha256 |
| `src/qwenpaw/tool_calls/media_hooks.py` | Agent 产出登记钩子（20MB 上限、内容寻址） |
| `src/qwenpaw/agents/react_agent.py` | 挂载钩子 |
| `src/qwenpaw/app/routers/xian/files.py` | `GET /api/xian/files`、`POST /api/xian/files/{id}/restore` |
