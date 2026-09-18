# T10-S2 `expand=section` 裁定基准（brief）

> 切片：kb_search 检索管线 S2 结构扩展的第一支——`expand=section`（命中块回补同
> `heading_path` 完整小节）。**不含** S2 `expand=graph`、S3 `rerank`（各自独立切片）。
> 上游 spec §6 L178-179；plan L808-820。父提交 T10-S0=`48b5bb50`。

## 一、背景与硬约束（recon 实证）

1. **数据模型缺口**：`KbSearchHit`（hits.py）带 `heading_path`+`parent_seq`，但
   `KbChunk`（models.py L106-116）**不带**；`_hit_to_chunk`（service.py L298-308）
   转换时丢弃这两字段。工具拿到的 `svc.search()` 结果是 `KbChunk`，无法定位小节。
2. **L0/json 面结构上不承载结构锚点**（file_engine.py L8-12 明文边界）：文件引擎
   读出的命中 `heading_path` 恒空串、`parent_seq` 恒 None。**故 expand=section 是
   pg/milvus-only 生产能力**；json 后端必须优雅降级为「只返回命中块本身」，不报错。
3. **单测钉桩跑 json 后端**（test_kb_search_tool.py `_json_backend` autouse）：真库
   heading_path 恒空 → S2 的工具层合并逻辑**只能用 monkeypatch/stub 喂结构化数据**
   来测；pg 兄弟块 SQL 用 DSN 门控的集成测验证（5433 可用，无 DSN 整文件 skip）。
4. **T6 ingest 走 `split_markdown`**（ingest.py L267）→ pg 面 kb_chunks 真实落
   heading_path/parent_seq；facade `_pg_ingest_async`（service.py L398-407）用扁平
   `chunk_text`（heading_path=""）——即只有 T6 结构化摄入的文档才有小节可回补。
5. **冲突面**：`src/qwenpaw/app/kb/` 当前全干净，仅 builder.py 有用户 PG 线 WIP；
   本切片**不动 builder.py**（expand 是工具运行时入参，注册链不变）→ 预计无需
   git add -p。提交前仍核 git status，若 service.py/pg_engine.py 出现用户 hunk 再分离。

## 二、设计裁定（D1–D7）

- **D1 KbChunk 增字段（附加式）**：`heading_path: str = ""`、`parent_seq:
  Optional[int] = None`。默认值向后兼容（旧 JSONL 无此键仍可读；文件面写空值不违
  L0 边界——该面 heading_path 本就恒空）。`_hit_to_chunk` 回填这两字段（pg/milvus
  命中带真值，文件命中带空）。
- **D2 兄弟块取数入口 = `document_chunks(kb_id, doc_id)`**（service.py 新方法）：
  返回一份文档全部切片（seq 升序，带 heading_path/parent_seq）。**每 doc 只查一次**
  ——工具层按 doc_id 去重后批量取，杜绝 per-hit N+1（项目规范 §2.4）。此方法同时是
  **T11 `GET .../documents/{docId}/chunks` 预览的数据源**（共享基建，一次建两处用）。
- **D3 pg 取数落 pg_engine**：`PgVectorEngine.list_document_chunks(space_id, doc_id)
  -> List[KbSearchHit]`（`SELECT ... WHERE tenant_id AND document_id ORDER BY seq`，
  走已存在的 `ix_kb_chunks_document` 索引，复用 `_hit_from_row`）。chunk SQL 归
  pg_engine（pg_store 只管 spaces/documents/versions）。`FileKbEngine` 同名方法过滤
  load_chunks（heading_path 恒空，降级）。
- **D4 service pg 桥接**：`_pg_list_document_chunks(kb_id, doc_id) ->
  Optional[List[KbSearchHit]]` 镜像 `_pg_search` 语义——**None=pg 不可用（回退文件
  面）/ []=就绪但空（权威空，不回退）**。`document_chunks` 据此分派：PG 后端且引擎
  有 `list_document_chunks`（getattr 守卫，milvus 未实现则降级）→ 走 pg；否则文件面
  过滤。任何异常 fail-soft WARN + 回退，绝不抛给工具。
- **D5 合并逻辑在工具层**（可单测）：`expand=="section"` 时——(a) 命中 fuse+sort+
  截断到 cap 后，按 doc_id 去重批量 `svc.document_chunks`；(b) 内存建
  `{(doc_id, heading_path): [chunks by seq]}` 索引；(c) 每个 hit 若 heading_path 非
  空则取同小节全部兄弟块按 seq 拼接（含命中块自身，天然去重）替换单块 snippet；
  heading_path 空（json/无结构）→ 保持单块。合并文本超 `_MAX_SECTION_CHARS` 截断加
  「…」。分组合并纯内存，零额外查询。
- **D6 溯源行加 `#heading`**（plan L816 输出格式）：heading_path 非空时溯源行为
  `===== [库名] 标题 #heading_path [score=x] =====`；空则维持现状 `===== [库名]
  标题 [score=x] =====`。两种 expand 模式一致（pg 面即使 expand=none 也显示面包屑）。
- **D7 milvus 面本切片降级**：MilvusEngine 暂不实现 list_document_chunks（getattr
  守卫 → milvus-routed 库 expand=section 回退单块，不报错）。理由：milvus「按库可选」
  且需标量 query 单独验证；留 T14 评测/后续切片补全，report + 记忆记录此偏差。

## 三、验收标准（AC）

- **AC1**：`expand="section"` 时，命中块的输出含**同 heading_path 的全部兄弟块文本**
  （按 seq 顺序拼接），而非仅命中块——单测 monkeypatch `svc.document_chunks` 喂 3 块
  同小节数据，断言输出含首/中/尾三块文本。
- **AC2**：`expand="none"`（默认）行为与 T10-S0 逐字不变（现有 8 个 S0 测试全绿）。
- **AC3**：heading_path 为空（json/L0 面）时 `expand="section"` **优雅降级**为单块，
  不报错、不空转（`document_chunks` 返回的块 heading_path 全空 → 无可合并兄弟）。
- **AC4**：溯源行在 heading_path 非空时含 `#heading_path` 面包屑；为空时不含 `#`。
- **AC5**：S0 绑定收敛不受影响——expand=section 只在**已收敛的绑定库命中**上做扩展，
  绝不因扩展触碰未绑定库（document_chunks 只对命中 hit 的 doc 调用，而 hit 只来自
  绑定库）。

## 四、测试计划

**单测（json 后端，tests/unit/app/kb/test_kb_search_tool.py 追加）**：
- `test_expand_section_merges_sibling_chunks`（AC1）：monkeypatch `svc.search` 返回
  1 个带 heading_path 的命中 + `svc.document_chunks` 返回同小节 3 块 → 输出含三块文本。
- `test_expand_section_shows_heading_breadcrumb`（AC4）：断言溯源行含 `#h1 > h2`。
- `test_expand_none_unchanged`（AC2）：expand 默认 → 单块，不含兄弟块文本。
- `test_expand_section_degrades_on_empty_heading`（AC3）：document_chunks 返回
  heading_path 全空的块 → 输出=单块，不报错。
- `test_expand_section_batches_per_doc`（D2/D5 防 N+1）：两个命中同 doc →
  `document_chunks` 对该 doc **只调一次**（spy 计数）。

**单测（service 层，test_service_facade.py 追加）**：
- `test_document_chunks_filters_and_sorts_by_seq`（D2）：monkeypatch `_load_chunks`
  返回乱序 + 混 doc 的块 → document_chunks 只返目标 doc、seq 升序。
- `test_hit_to_chunk_carries_heading_path`（D1）：`_hit_to_chunk` 回填 heading_path/
  parent_seq。

**集成测（DSN 门控，test_kb_pg_plane.py 追加）**：
- `test_list_document_chunks_pg_roundtrip`：T6 结构化摄入含多级标题的 MD →
  `document_chunks` 从 pg 返回带真实 heading_path 的块，同小节兄弟块 seq 连续。
  无 QWENPAW_PG_DSN 时 skip（沿用文件既有门控）。

## 五、SDD 流程

recon（本文）→ brief → **Step1 写失败测试**（上述单测）→ Step2 跑红 →
**Step3 实现**（models→service→pg_engine→file_engine→tool）→ Step4 跑绿（kb 全量 +
runtime 回归）→ flake8/black → **Step5 独立审查门**（故障诊断工程师，中性措辞）→
receiving-code-review 逐条评估 → 修复轮 → 提交（点名 add，核 git status 决定 hunk
分离）→ 台账（report + task_summary + 必要 pitfall）。
