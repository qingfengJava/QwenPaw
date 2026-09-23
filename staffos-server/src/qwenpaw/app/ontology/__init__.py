# -*- coding: utf-8 -*-
"""Ontology 平面（知识本体平台 T4/T5）：数据模型 + PG 存储 + 只读运行时。

模块布局：

- :mod:`models` —— 枚举常量、L0/L1 种子、Pydantic 领域模型；
- :mod:`store` —— ``PgOntologyStore``（仅 PG，无 json 面——
  enterprise-engine 门控，与 kb 平面三态策略解耦）；
- :mod:`service` —— 业务校验与 ID 生成的薄封装；
- :mod:`api` —— ``/api/admin/ontology`` 管理端点；
- :mod:`grounding` —— 名称/别名 grounding 与关系图遍历（T5）。

@author qingfeng
"""
