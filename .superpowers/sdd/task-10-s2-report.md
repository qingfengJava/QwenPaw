# T10-S2 `expand=section` 完成报告

> 切片：kb_search 检索管线 S2 结构扩展第一支——命中块回补同小节兄弟块。
> HEAD=`8bcd29b6`（父 T10-S0=`48b5bb50`）。裁定基准 `task-10-s2-brief.md`。

## 一、交付

`kb_search(query, kb_id="", max_results=5, expand="none")` 新增 `expand` 入参；
`expand="section"` 时命中块回补同小节完整兄弟块（父子合并），提升上下文完整度。
S0 绑定收敛、人侧 HTTP `/api/kb/search` 均不受影响。8 文件、777+/8−、零 .qoder。

- `models.py`：KbChunk += `heading_path`/`parent_seq`（附加式，向后兼容）。
- `service.py`：`_hit_to_chunk` 回填结构锚点；新增 `document_chunks(kb_id, doc_id)`
  （一份文档全部切片 seq 升序，S2 兄弟块来源 + T11 chunk 预览共享数据源）+
  `_pg_list_document_chunks`（None=引擎未实现/桥接失败→回退；[]=权威空）。
- `pg_engine.py`：`list_document_chunks`（WHERE tenant+space+document ORDER BY seq，
  走 ix_kb_chunks_document，fail-soft 返 []）。
- `file_engine.py`：`list_document_chunks`（L0 面 heading_path 恒空，降级单块）。
- `tool.py`：`_build_section_index`（section_key=parent_seq 精确归组，键含 S0 校验的
  kb.id）+ `_join_blocks_cap`（块边界截断+标记）+ `_section_key` + expand 白名单校验。

## 二、⚠️ 现网可达性（审查 P1-1，关键定位）

**expand=section 当前是「机制就绪、生产暗码」**：结构化摄入 `ingest_space_document`
（`split_markdown`，heading_path 唯一生产源）在 `src/` 内**零路由调用方**（git grep
证实），生产摄入仍走 `service.ingest_text`→`chunk_text`（扁平，heading_path=""）。
故生产中 heading_path 恒空 → expand=section 恒降级为单块。

**激活点在 T11**：人侧上传/CRUD 路由须接 `ingest_space_document`（结构化摄入），
heading_path 才落库，S2 方在生产可达。本切片交付的是 T11 激活所需的**正确机制**
（工具+门面+引擎+模型+真库验证的 SQL），非无效工作——机制必须先于接线存在。

## 三、审查闭环（故障诊断工程师，无 P0）

**已修复**：
- P1-2 合并小节从头截断可丢命中块 → 改**块边界截断**（不切断表格/代码）+ 显式标记
  `…[小节共 N 块，已显示 M 块]`（不静默丢证据）。
- P1-5 `list_document_chunks` 无 space_id 谓词（T11 越权前兆）→ SQL 补
  `AND c.space_id = :space_id`，空 space/doc 返 []，两平面语义一致 + 越权测。
- P2-1 去重/取数键缺 kb 维度、用 `chunk.kb_id` 而非 S0 校验的 `kb.id` → 键改
  `(kb.id, doc_id, section_key)`，取数用命中元组里 S0 校验过的 kb.id（AC5 收紧）。
- P2-2 按 heading_path **字符串**归组，同名标题两节被误并 → 改 `section_key`
  （parent_seq 精确键，节首 seq 兜底），同名 heading 不串号（同时消费 parent_seq，
  解 P3-3 死字段）。
- P2-4 无总输出预算（最坏 ~144KB 超 tool-result 裁剪阈值 50KB）→ 每节额度按命中数
  动态分配，总额受 `_MAX_TOTAL_CHARS=16000` 约束。
- P2-6 expand 未知值（含 spec 的 graph）静默按 none → 白名单校验，非法值显式报错。
- P2-7 扩展路径无异常隔离、expand 非 str 崩 → `str(expand or ...)` + `_build_section_index`
  整体 try/except + 每 doc 取数 try/except，异常一律降级单块（守「检索面永不抛」）。
- P2-5（部分）不为整篇所有小节建索引 → 仅归组**命中所在小节**。

**延后并记录（附裁定理由）**：
- P1-1 接线 = T11 职责（见 §二），非本切片缺陷。
- P1-4 `document_chunks` 经同步桥接阻塞事件循环（≤20 doc×10s）→ 现网不可达
  （heading_path 恒空，targets 空，从不调用）；且属既有 sync-facade-over-async-pg
  模式（`svc.search` 同款）。批量 SQL（`document_id = ANY`）+ `to_thread` + deadline
  留 **T11 激活时**做（届时才可达、才值得）。
- P2-3 同小节去重后不回填致条数 < max_results → expand=section 折叠同节命中是**预期
  行为**（不要 N 份同节）；过量召回（cap*2）再截断的调优留 T14 评测驱动。
- P3-2 pg 面 `_hit_to_chunk` title="" → 溯源行显 doc_id 而非标题：**既有**（非本切片
  引入），title 回填需联表 kb_documents，超出 S2 范围，记录待后续。
- P3-4 合并小节含 chunker overlap 重复前缀（~100 字/块）：cosmetic，去重需 chunker
  改动或另存展示文本列，延后；原子块截断已由 P1-2 块边界截断解决。
- P3-9 无缓存（同轮重复 kb_search 重拉切片）：优化项，暗码期不紧迫，延后。

**书面裁定（不改代码）**：
- P3-1 AC2「逐字不变」限定 **json/L0 面**；pg 面 expand=none 也显 `#heading` 面包屑
  是 D6 有意变更（现网 heading_path 恒空故无实际差异）。
- P3-7 `FileKbEngine.index_document` 不透传 heading_path/parent_seq：L0 面**结构上
  不承载结构字段**是 spec/file_engine.py L8-12 明定边界（非「自然降级」而是有意裁定），
  json 后端永久无 S2 能力，需结构扩展须切 pg/milvus。
- P3-5 集成测 specs 存在「父块 heading≠子块 heading」违反 chunker 不变式：**既有测试
  数据**（非本切片），我新增的断言只验 list_document_chunks 的 SQL 往返（seq/heading/
  score/parent_seq/space_id），与归组正确性无关；新单测已用不变式正确的 parent_seq。
- P3-8 KbChunk 未显式 `extra="ignore"`：pydantic v2 默认即 ignore，向后兼容已成立，
  低价值，跳过。

## 四、验证证据

- kb 单测 **262 passed**（+9 S2 用例：合并/降级/去重/N+1 每 doc 一次/截断标记/
  同名 heading 不并/非法 expand 报错/异常降级/space 越权空）。
- runtime **102 passed 1 skipped**（expand 新参不破坏工具注册接线）。
- pg **真库集成测** `test_kb_pg_engine_roundtrip` passed（5433 pgvector）：验
  list_document_chunks 的 seq 升序 / heading_path 随行 / score=0 / parent_seq 反解 /
  空文档 []，SQL 加 space_id 谓词后复验通过。
- TDD 红 **8 failed**（精准红）→ 绿；flake8 exit 0；black clean。

## 五、并发冲突处理

`src/qwenpaw/app/kb/` 本轮全干净，8 文件均纯我方 ` M`，**不动 builder.py**（expand
是运行时入参，注册链不变）→ 无需 git add -p hunk 分离。index 128 张 .qoder 预暂存
删除：`git reset HEAD -- .qoder` 撤出 → add 我方 8 → commit → `git add -A -- .qoder`
还原 128。用户 WIP（builder.py 等 ~124 文件）零触碰，提交后 builder.py 仍 ` M`。

## 六、T11 激活清单（本切片遗留的下游接线）

1. 人侧上传/CRUD 路由接 `ingest_space_document`（结构化摄入）→ heading_path 落库。
2. 激活时补 P1-4：`document_chunks_multi`（`document_id = ANY(:doc_ids)` 批量）+
   `asyncio.to_thread` + S2 总 deadline，消除事件循环阻塞放大。
3. T11 chunk 预览端点直接复用 `document_chunks`（已建好的共享数据源）。
4. 补端到端集成测：ingest_space_document → search → kb_search(expand=section) 链路可达。
