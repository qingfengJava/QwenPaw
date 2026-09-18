# T10-S3 `rerank` 裁定基准（brief）

> 切片：kb_search 检索管线 S3 精排——融合后、截断前对候选池做 qwen3-rerank
> 语义重排，凭证缺失自动降级 RRF 序。**不依赖 heading_path**（区别于 S2），
> 故现网即可达（非暗码）。上游 spec §6 L181-182；plan L816/L819。父提交
> T10-S2=`8bcd29b6`。

## 一、背景与硬约束（recon 实证）

1. **T4 精排管线已就绪**（`rerank.py`，复用不改）：`async rerank_hits(query,
   hits, top_n=5, agent_id="") -> List[_Rerankable]`。`_Rerankable` 协议只需
   `.text: str`；**返回原对象重排**（不复制、不改字段），调用方仍可读写 score。
2. **降级语义已内建**（rerank.py L10-11/L119-145）：≤1 条命中、`_resolve_rerank_config`
   返 None（未 enabled/无 model_name/无 memory 配置）、空 query、坏序 → 一律
   `items[:top_n]`（原序=RRF 序）返回。**检索永不因精排失败报错**，凭证缺失即
   透明降级。故本切片**不写任何凭证判定**，全交给 rerank_hits。
3. **超量取回是精排前提**（rerank.py L102-103）：调用方须给 RRF top20 候选，
   否则精排只能在已截断小集合内换位，收益有限。→ 现状 per-kb `svc.search(top_k=cap)`
   候选池仅 cap（单库=5），**不足以精排**，须拓宽到 `_RERANK_CANDIDATES=20`。
4. **凭证同源 + agent 归属**：`rerank_hits(agent_id=...)` 经 `resolve_memory_config`
   取该 agent 的 reranker 配置（凭证与 embedding 同源）。工具闭包已持有 agent_id
   （make_kb_search_tool 入参，T10-S0 注入）→ 直接透传。
5. **单测网络隔离**：单测环境若 ambient 存在 reranker 凭证，真 rerank_hits 会打
   外网。故 test_kb_search_tool.py 加 **autouse `_stub_rerank` 钉 passthrough**
   （items[:top_n]），S3 用例各自 monkeypatch 覆盖为记录/重排版，全程零网络。
6. **冲突面**：`src/qwenpaw/app/kb/` 当前全干净（T10-S2 已提交），本切片只动
   tool.py（我方文件）+ test_kb_search_tool.py，**不动 service.py/pg_engine.py/
   builder.py** → 无 hunk 分离。

## 二、设计裁定（D1–D6）

- **D1 执行点**：S1 融合（sort by score desc）→ 取候选池 `hits[:20]` → **S3
  rerank（top_n=cap）→ 得 top** → S2 expand=section（在 rerank 选定的 top 上富化）
  → 渲染。即 rerank 在「融合后、截断前、expand 前」（plan L819）。精排**选定**哪些
  命中，扩展只是给选定命中补上下文，二者顺序不可颠倒（先扩展再精排会对 20 个整节
  精排，成本与语义皆错）。
- **D2 候选池拓宽**：per-kb `svc.search(top_k=_RERANK_CANDIDATES=20)`（原为 cap），
  融合排序后 `pool = hits[:20]`。缺凭证时 rerank_hits 返回 `pool[:cap]` = RRF top-cap，
  **与拓宽前逐条一致**（单库 top_k=20 后 [:cap] 等价原 top_k=cap；多库则从更丰富
  候选池选 top-cap，融合更准）。
- **D3 chunk→(kb,score) 映射**：rerank_hits 返回重排的 chunk 对象（同一实例），
  用 `id(chunk) → (kb, score)` 内存映射还原三元组（pool 持引用保证对象存活，id 唯一）。
  不新增 wrapper 类、不改 rerank_hits 签名。
- **D4 展示分数仍是 RRF 融合分**：rerank_hits 不回传 relevance_score（T4 契约），
  故溯源行 `[score=x]` 仍显 RRF 分。**精排激活时顺序按 rerank 相关性，score 可能
  非单调**——这是已知取舍（order 才是给 agent 的权威信号，score 为粗略参考）；
  改 rerank_hits 回传 relevance 属 T4 扩面，记录留待需要时。缺凭证时顺序=RRF，
  score 单调（现有 AC2 降序断言成立）。
- **D5 agent_id 透传**：`rerank_hits(..., agent_id=agent_id)`，凭证按 agent 归属解析
  （与 embedding 同源）。空 agent_id → rerank.py 取当前生效 agent。
- **D6 不改 rerank.py/service.py**：S3 只在 tool.py 编排层接线，复用 T4 精排管线
  原样。冲突面最小化（同 T10-S2 R8 精神）。

## 三、验收标准（AC）

- **AC1**：精排在管线中生效——monkeypatch rerank_hits 返回**逆序**候选，工具输出
  顺序须反映逆序（首条=原候选末条），证明 rerank 结果被采用而非丢弃。
- **AC2**：缺凭证降级——rerank_hits 原序截断（passthrough）时，输出 = RRF top-cap，
  score 降序（现有 test_multi_bound_fusion_sorted_by_score 仍绿）。
- **AC3**：超量取回——`svc.search` 被以 `top_k=_RERANK_CANDIDATES(20)` 调用（spy 断言），
  证明候选池为精排拓宽（非 cap）。
- **AC4**：top_n=cap 且 agent_id 透传——rerank_hits 收到的 top_n == max_results 收敛值、
  agent_id == 工具构造入参（记录断言）。
- **AC5**：精排与 S2 协同——rerank 选定 top 后再 expand=section（顺序：先精排选定、
  后扩展富化）；缺凭证时 expand 行为与 T10-S2 一致。
- **AC6**：S0 绑定收敛不受影响——拓宽 top_k 不改变「搜哪些库」（仍只搜绑定库），
  越权库绝不触发引擎（现有 S0 spy 测仍绿）。

## 四、测试计划（test_kb_search_tool.py，json 后端 + autouse `_stub_rerank`）

- `test_rerank_reorders_hits`（AC1）：stub rerank_hits 逆序 → 输出首条=原末条。
- `test_rerank_degrades_to_rrf_order`（AC2）：passthrough → RRF 序、score 降序、cap 条。
- `test_rerank_overfetches_candidates`（AC3）：spy svc.search → top_k==20。
- `test_rerank_receives_top_n_and_agent_id`（AC4）：记录 rerank_hits 入参 → top_n==cap、
  agent_id=="agent_x"。
- `test_rerank_before_section_expand`（AC5）：rerank 选定 top1 后，expand=section 对
  选定命中回补小节（验证顺序：精排选定→扩展）。
- 现有 13 个 S2/S0 测试在 autouse `_stub_rerank` passthrough 下全绿（AC2/AC6 回归）。

## 五、SDD 流程

recon（本文）→ brief → Step1 写失败测试 → Step2 跑红 → Step3 实现（tool.py 接线
rerank_hits + 候选池拓宽 + id 映射）→ Step4 跑绿（kb 全量 + runtime）→ flake8/black
→ Step5 独立审查门（故障诊断工程师）→ receiving-code-review 逐条 → 修复 → 提交
（点名 add，核 git status）→ 台账（report + task_summary）。
