# T11 人侧 API 扩展完成报告

> 切片：KB 一期 T11——员工面文档 CRUD / multipart 上传 / chunk 预览 /
> 管理面 search-test。权威依据 `docs/superpowers/plans/2026-09-17-
> knowledge-base-architecture.md` T11 章节（L824-889，内嵌集成测试为
> 请求/响应形状基准）。代码提交 `e2e41b42`（feat(kb): employee document
> crud, upload, chunk preview and search-test apis），父 `5c98c704`
> （T10-S3 台账），台账补录于 2026-09-20。经两轮独立审查（第一轮
> Not Approved 9 必修项 → 全部修复；第二轮 Approved 附条件 → 收尾
> 修复后入库）。

## 一、交付概述

- **员工面 5 端点**（`/api/kb`，复用 `_access_kwargs` ACL 模式）：
  - `GET /{kb_id}/tree`：path 聚合目录树（O(n) dict 前缀索引建树，
    文档节点携带 doc_id/title/ingest_status）；
  - `GET /{kb_id}/documents/{doc_id}`：content_md 权威全文 + 当前
    版本 + 摄入状态（未命中/异库/已删 → 404）；
  - `PUT /{kb_id}/documents/{docId}`：content_md upsert 自动版本+1 +
    重切片重索引（复用 T6 `ingest_space_document`，hash 护栏 + 幂等
    短路）；版本读回失败显式 503，绝不假成功返回 version=0；
  - `POST /{kb_id}/documents/upload`：multipart 上传，1MB 分块限读
    （`utils.read_upload_bounded`，超限立即中止防内存击穿），白名单
    解析 → T6 版本化摄入；503 门控在读文件体之前（fail fast）；
  - `GET /{kb_id}/documents/{docId}/chunks`：chunk 预览（数据源
    `svc.document_chunks`，seq 升序含 heading_path；pg 面与详情端点
    同源判存，is_delete → 404）。
- **管理面**：`POST /api/admin/kb/search-test` 透传引擎 top-k + 得分
  （继承 `PERM_ADMIN_KB` 门控；请求体对齐 SearchBody 风格）。
- **503 显式门控**：`pg_ready()` 收紧为 `backend==pg` 且 pg 可达；
  tree/detail/PUT/upload 与 search-test 门控 503（dual/json 下显式
  提示而非静默分裂）；chunks 走三态门面（json 部署正常工作不 503）。
- **集成测试** `tests/integration/test_kb_api_phase1.py`（6 用例）：
  lifecycle 全链路（建库→上传 html→ready→PUT version==2→chunks 非空
  →检索命中→search-test 命中→tree 含 doc_id）+ 5 负例。

## 二、文件清单（`e2e41b42`，7 files，+1025/−15）

| 文件 | 内容 |
|---|---|
| `src/qwenpaw/app/routers/kb.py` | 5 端点 + `_ensure_kb_manage`/`_ensure_pg_ready`/`_build_tree` + delete 权限/归属校验收敛 |
| `src/qwenpaw/app/routers/admin/kb.py` | search-test + pg 门控 |
| `src/qwenpaw/app/kb/service.py` | T11 门面：`pg_ready`/`pg_list_documents`/`pg_document_detail`/`pg_ingest_document`（ValueError 重抛） |
| `src/qwenpaw/app/kb/pg_store.py` | `_get_engine()` 改 `create_pg_engine(dedicated=True)` |
| `src/qwenpaw/app/kb/pg_engine.py` | `PgVectorEngine._get_engine()` 同上 |
| `src/qwenpaw/app/utils.py` | 新增 `read_upload_bounded()`（分块限读） |
| `tests/integration/test_kb_api_phase1.py` | 新增，6 用例 |

## 三、关键裁定（D1–D7）

- **D1 pg_ready 收紧（backend==pg 且可达）**：仅探测 pg 可达不够——
  dual 后端下 T11 写端点走 pg 权威面而三态读面（chunks/search）读
  json 主面，读写分裂会让写入后 chunks 404、检索不命中。dual 下
  用户走既有 `ingest_text`（json 主写）+ 三态读面；search-test 补
  同一门控（json 部署 503 并指引改用员工面 `/api/kb/search`）；
  chunks 刻意不卷入门控（三态门面，避免误伤纯 json 部署）。
- **D2 T6 复用**：PUT/upload 不新写重摄入逻辑，经 service 层
  `pg_ingest_document` 同步门面复用 `ingest_space_document`（版本
  快照 + 重切片重索引 + 幂等短路 + failed 收敛不抛）。
- **D3 协程单循环收敛**：首版 async 端点直连 store 触发 `got Future
  attached to a different loop` + asyncpg `unknown protocol state 3`
  （共享池被主循环预热、bridge loop 复用致腐蚀）。修复：①
  pg_store/pg_engine 引擎改 `dedicated=True`（`db/engine.py` docstring
  明载 users/RBAC 后台 loop store 同款先例）；② T11 端点一律同步
  def + service 门面，KB 面 pg 协程收敛到 bridge 单循环。
- **D4 错误分类**：`pg_ingest_document` 门面 `except ValueError:
  raise`（值级拒绝，如空白 content_md），路由映射 400；桥接/基建
  异常收敛 None → 路由 500；`IngestResult(status=failed)` → 500。
- **D5 ACL 复用与匿名回退**：人侧端点复用 `_access_kwargs` +
  `can_access` + `_ensure_kb_manage`（personal: owner only；其他
  scope: kb:write）；`_caller` 空身份回退 `"local"`（无认证部署，
  xian/projects.py 同款先例）。
- **D6 门控与归属语义**：delete 先 `_ensure_kb_manage` 后判 doc∈kb
  （pg 分支 `pg_document_detail`、json/dual 分支 `get_document_meta`
  判 kb_id，对齐 detail/PUT/chunks 先判归属模式；doc_id 全局唯一，
  跨库误删防线）；PUT 版本读回失败 503 显式化。
- **D7 测试基建**：测试模块级**无条件** env 自举（`QWENPAW_PG_DSN`
  ← `QWENPAW_TEST_PG_DSN` 屏蔽 shell 残留 5432 DSN；
  `QWENPAW_STORAGE_BACKEND=pg` 防 dual 默认陷阱——write_gateway
  "有 DSN 即 dual"）；`app_server` 是 env 固定的子进程，无法在线切
  backend → json 503 / team kb:write 两负例走进程内直调路由 +
  monkeypatch（审查门允许的方案），桩断言 pg 取数零调用（门控先行）。

## 四、审查两轮过程

- **第一轮（Not Approved，9 必修项）**：P1-1 dual 读写分裂（pg_ready
  收紧 + search-test 同门控 + chunks 三态不误伤）；P2-1 错误分类
  （ValueError→400）；P2-2 上传内存击穿（分块限读）；P2-3 delete
  半段权限（补 kb:write，修 bug）；P3-1 死导入 INGEST_READY；P3-2
  chunks 已删文档 404 契约对齐；P3-3 PUT version==0 假成功显式化
  （503）；P3-4 `_build_tree` O(n²)→O(n)；P3-7 四类集成负例（非
  owner 403 / 跨库 404 / json 后端 503 / 幂等 version 不变）——全部
  落地并回归绿。
- **第二轮（Approved，附条件）**：P2-N1 delete 补 doc∈kb 归属校验
  （pg/json 双分支）+ 跨库删除 404 负例（含「A 库文档不受影响」
  反向断言）；P3-N1 team 库 kb:write 分支负例（进程内 stub RBAC，
  delete/upload → 403 且归属校验/取数零调用）——全部落地。
- **push back / 延后登记（不实施）**：
  - **P3-5** upload 覆盖同 path 返回 200 vs 201：延后。当前恒 201
    （幂等短路也 201），REST 语义瑕疵不影响正确性，与 T6 幂等契约
    对齐优先；
  - **P3-6** `_caller` 空身份回退 `"local"`：保持 xian/projects.py
    先例不动；无认证部署（测试/单机）依赖此回退，auth 部署下中间件
    恒绑定身份不触发；
  - **超时后落库竞态**（`_run_coro_blocking` 超时但协程仍完成落库）：
    既有桥接语义，`ingest_space_document` 幂等短路兜底重放，登记不修。

## 五、验证证据

- 集成测试：`pytest tests/integration/test_kb_api_phase1.py -v
  --timeout=240 --timeout-method=thread`（QWENPAW_TEST_PG_DSN 指向
  5433 pgvector 隔离库 `qwenpaw_integration_test`）→ **6 passed in
  28.50s，exit 0**；
- kb 定向单测：`pytest tests/unit --ignore=tests/unit/hub -k "kb"
  --import-mode=importlib -q` → **298 passed, 8 skipped，exit 0**
  （无回归）；upload 相关 60 passed；
- 静态检查：flake8 全部改动文件 0 违规（含多行中文注释 E501）；
  `black --check -l 79` 全部改动文件 clean；
- 提交：`e2e41b42`（7 files changed, 1025 insertions(+), 15
  deletions(-)，`git status --short` 核对暂存区仅含本任务 7 文件）。

## 六、已知遗留

- **bindings 路由 async 直连隐患**：既有 `kb.bindings` 相关路由存在
  async def 直连 store 的写法，pg 后端下与 bridge loop 混用有同类跨
  循环腐蚀风险（T11 测试不触发）；建议另开任务按 D3 模式收敛。
- **tests/unit 同名文件冲突**：`tests/unit/app/kb/test_pg_store.py`
  与 `tests/unit/app/driver_config/test_pg_store.py` 同名（均既有
  tracked），全量收集需 `--import-mode=importlib`（与本任务无关）。
- **tests/unit/hub 依赖 docker 包**：`.venv` 未装 `docker`，`-k`
  收集需 `--ignore=tests/unit/hub`（既有环境约束，与本任务无关）。
- 工作区 `_tmp_merge/`、`_tmp_oldrows/`、`_tmp_*.ps1` 为用户在途
  产物，全程未触碰、未纳入提交。
