# -*- coding: utf-8 -*-
"""Workforce 领域包：企业级数字员工平台的两级 Harness 运行时。

实现 ``app/experts/team_runtime.py`` 预留的 :class:`TeamOrchestrator`
升级路径：中央大脑（L1 Workforce ReAct）做 Plan-then-Execute 的 DAG
编排——需求识别 → 上下文构建 → 能力发现 → 任务拆解 → Task Contract
委派 → 子员工（L2，已发布专家 agent）执行 → Result Contract 回传 →
中央验收 → Repair 返工循环 → 熔断升级人工 → 最终汇总回推聊天。

模块地图（引擎 → 契约 单向依赖，contracts 不 import 引擎）：

- :mod:`contracts`  结构化契约（Task/Result/Repair/Handover/DagPlan/
                    ContextBundle/RunPolicy/OrchestrationSpec/Clarification）
- :mod:`run_store`  run/node 持久化、feed 事件双写、checkpoint、启动恢复
- :mod:`bundle`     Context Engine：上下文构建 / 投影 / 版本化
- :mod:`planner`    Planning Engine：orchestration 模板 + 中央大脑 DAG 生成
- :mod:`delegator`  Execution Engine：TaskContract 投影 → 委派成员专家
- :mod:`verifier`   Verification Engine：结构化验收裁决 + RepairContract
- :mod:`engine`     编排状态机心脏（波次调度 / 返工 / 熔断 / 恢复）
- :mod:`intent`     双态入口的意图分类（规则优先 + 廉价 LLM 兜底）
- :mod:`budget`     run 级 token 预算聚合与配额预检

@author qingfeng
"""
