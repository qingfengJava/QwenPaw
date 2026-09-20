# T10-S3 `rerank` 精排完成报告

> 切片：kb_search 检索管线 S3 精排——S1 融合后、截断前对候选池（top20）做
> qwen3-rerank 语义重排，凭证缺失透明降级 RRF 序。不依赖 heading_path
> （区别于 S2），**现网即可达（非暗码）**。裁定基准 `task-10-s3-brief.md`。
> 代码随混合提交 `30113144`（"架构优化"）入库；台账补录于 2026-09-20，
> 补录时 HEAD=`71296bc0`（父 T10-S2=`8bcd29b6`）。

## 一、交付概述

`kb_search` 管线接入 T4 精排（复用 `rerank.py` 原样，D6）：
S1 融合（score desc）→ 候选池 `pool = hits[:_RERANK_CANDIDATES(20)]` →
`rerank_hits(query, pool, top_n=cap, agent_id=agent_id)` 精排选 cap 条 →
S2 `expand=section` 在精排选定命中上富化 → 渲染。降级语义由 rerank_hits
内建（≤1 条命中/未 enabled/无 model_name/无 memory 配置/空 query/坏序 →
`items[:top_n]` 原序=RRF 序），检索永不因精排失败报错。

- `src/qwenpaw/app/kb/tool.py`（+41/−10）：`_RERANK_CANDIDATES=20` 常量；
  per-kb `svc.search(top_k=20)` 超量取回（D2，精排前提）；`id(chunk) →
  (kb, score)` 内存映射还原三元组（D3）；编排层接线 `rerank_hits`
  （top_n=cap、agent_id 透传，D5）；expand 白名单校验前移至检索之前
  （非法值不浪费 S1/S3）。
- `tests/unit/app/kb/test_kb_search_tool.py`（+175）：autouse `_stub_rerank`
  钉 passthrough（单测零网络，ambient reranker 凭证不外泄，T4 教训）+
  5 个 S3 用例（AC1–AC5 直证）。

## 二、关键裁定（D1–D6 摘要）

- **D1 执行点**：rerank 在「融合后、截断前、expand 前」（plan L819 /
  spec §6 L181）——精排**选定**在前、扩展富化在后，顺序不可颠倒
  （先扩展再精排会对 20 个整节精排，成本与语义皆错）。
- **D2 候选池拓宽**：per-kb top_k 由 cap → `_RERANK_CANDIDATES=20`；
  缺凭证时 rerank_hits 返回 `pool[:cap]` = RRF top-cap，**与拓宽前逐条
  一致**（单库等价、多库从更丰富候选池选 top-cap 融合更准）。
- **D3 chunk→(kb,score) 映射**：`id(chunk)` 内存映射（pool 持引用保证
  对象存活，id 唯一）；不新增 wrapper 类、不改 `rerank_hits` 签名。
- **D4 展示分数仍为 RRF 融合分**：`rerank_hits` 不回传 relevance_score
  （T4 契约），溯源行 `[score=x]` 仍显 RRF 分；精排激活时顺序按 rerank
  相关性、score 可能非单调——已知取舍（order 才是给 agent 的权威信号，
  score 为粗略参考）；改回传属 T4 扩面，记录留待需要时。缺凭证时
  顺序=RRF、score 单调。
- **D5 agent_id 透传**：凭证与 embedding 同源（`resolve_memory_config`
  按 agent 归属）；空 agent_id → rerank.py 取当前生效 agent。
- **D6 不改 rerank.py/service.py**：只在 tool.py 编排层接线，复用 T4
  精排管线原样，冲突面最小化。

## 三、AC1–AC6 对照

- **AC1 精排生效**：`test_rerank_reorders_hits`——stub 返回逆序候选，
  输出首条=原候选末条，证明 rerank 结果被采用而非丢弃 ✓
- **AC2 缺凭证降级**：`test_rerank_degrades_to_rrf_order`——passthrough →
  RRF 序、score 降序、cap 条；`test_multi_bound_fusion_sorted_by_score`
  仍绿 ✓
- **AC3 超量取回**：`test_rerank_overfetches_candidates`——spy 断言
  `svc.search` 以 `top_k=20`（候选池）被调用，非 cap ✓
- **AC4 top_n=cap 且 agent_id 透传**：`test_rerank_receives_top_n_and_agent_id`
  ——rerank_hits 收到 top_n==max_results 收敛值、agent_id=="agent_x" ✓
- **AC5 精排与 S2 协同**：`test_rerank_before_section_expand`——精排把
  RRF 低分的 B 节选为 top1 后 expand=section，输出为精排选定节；缺凭证
  时 expand 行为与 T10-S2 一致 ✓
- **AC6 S0 绑定收敛不受影响**：拓宽 top_k 不改「搜哪些库」，越权库绝不
  触发引擎；现有 S0 spy 测在 autouse passthrough 下仍绿 ✓

## 四、验证证据

- kb 单测 **267 passed**（+5 S3 用例；13 个 S2/S0 既有用例在 autouse
  `_stub_rerank` passthrough 下全绿，AC2/AC6 回归）。
- S3 五用例全绿（AC1–AC5 直证 + AC6 回归）。
- flake8 exit 0；black clean。
- 代码入库 `30113144`（tool.py +41/−10、test_kb_search_tool.py +175，
  `git show --stat` 核实）；验证时点 HEAD=`71296bc0`。

## 五、备注

- 代码随 `30113144`（"架构优化"混合提交）入库，非独立切片提交；台账
  补录于 2026-09-20（本提交）。
- `expand=graph`：计划文本（spec §6）提及但实现未包含（`_VALID_EXPAND =
  {"none", "section"}`，未支持值显式报错而非静默降级）；计划文本与实现
  偏差已登记后置。
