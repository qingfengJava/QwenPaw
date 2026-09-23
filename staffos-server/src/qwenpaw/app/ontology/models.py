# -*- coding: utf-8 -*-
"""Ontology 平面领域模型与 L0/L1 种子定义（知识本体平台 T4，0047）。

三层架构中的「Ontology Runtime」数据面：L0 元模型（本体系统的九个概念
维度）+ L1 业务核心类型（十三个种子），以及对象/关系/状态迁移/规则/
动作/知识互引六类结构化实体。

设计原则（spec §3）：

- 本体 = PG 关系表 + CTE 遍历（≤3 跳），不引入图数据库；
- Rule/Action 仅建模（纯 CRUD 留档），无运行时——评估引擎与审批链
  为后续里程碑；
- ``trigger`` 在方案文档中为状态迁移触发器字段名，因 PostgreSQL 保留
  字更名 ``trigger_type``（COMMENT 已注明对应关系）。

@author qingfeng
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 枚举常量
# ---------------------------------------------------------------------------

#: 类型层级（L0 元模型 / L1 业务核心；L2+ 预留给企业自定义分层）
LAYER_L0 = "L0"
LAYER_L1 = "L1"
VALID_LAYERS = frozenset(
    {"L0", "L1", "L2", "L3", "L4", "L5"},
)

#: 对象生命周期状态（``ontology_objects.status``）
OBJECT_STATUS_ACTIVE = "active"
OBJECT_STATUS_ARCHIVED = "archived"
VALID_OBJECT_STATUSES = frozenset(
    {OBJECT_STATUS_ACTIVE, OBJECT_STATUS_ARCHIVED},
)

#: 结构化数据来源（LLM 抽取产物走 llm 源，仅经人工确认后落库）
SOURCE_MANUAL = "manual"
SOURCE_LLM = "llm"
SOURCE_IMPORT = "import"
VALID_ONTOLOGY_SOURCES = frozenset(
    {SOURCE_MANUAL, SOURCE_LLM, SOURCE_IMPORT},
)

#: 知识 ↔ 本体互引关系（``kb_object_links.relation``）
LINK_RELATION_MENTIONS = "knowledge_mentions"
LINK_RELATION_SUPPORTS = "knowledge_supports_object"
LINK_RELATION_DEFINES_RULE = "knowledge_defines_rule"
VALID_LINK_RELATIONS = frozenset(
    {
        LINK_RELATION_MENTIONS,
        LINK_RELATION_SUPPORTS,
        LINK_RELATION_DEFINES_RULE,
    },
)

# ---------------------------------------------------------------------------
# L0/L1 种子（alembic 0047 内联同款字面量；本常量供测试与文档共用）
# ---------------------------------------------------------------------------

#: L0 九类元类型：``(id, name, parent_id, description)``。
#: 与本体六表 + KB 两面（Evidence/Knowledge）一一对应：
#: object/relation/state/transition/rule/action 对应六张结构表，
#: event 对应迁移触发器分类，knowledge/evidence 对应知识两层。
L0_SEED_TYPES: Tuple[Tuple[str, str, str, str], ...] = (
    ("l0.object", "对象", "", "一切实体的元类型；L1 业务实体类型的父层"),
    ("l0.relation", "关系", "", "对象间有向关系的元类型"),
    ("l0.state", "状态", "", "对象生命周期阶段的元类型"),
    ("l0.transition", "状态迁移", "", "状态间受控流转的元类型"),
    ("l0.rule", "规则", "", "业务约束与自动行为的元类型（本期仅建模）"),
    ("l0.action", "动作", "", "可执行操作的元类型（本期仅建模）"),
    ("l0.event", "事件", "", "状态迁移触发器的分类元类型"),
    ("l0.knowledge", "知识", "", "LLM Wiki 层已审知识节点的元类型"),
    ("l0.evidence", "证据", "", "RAG 层原始证据材料（文档/切片）的元类型"),
)

#: L1 十三类业务核心类型：11 实体挂 ``l0.object``，
#: document 挂 ``l0.evidence``，knowledge 挂 ``l0.knowledge``。
L1_SEED_TYPES: Tuple[Tuple[str, str, str, str], ...] = (
    ("l1.person", "人员", "l0.object", "员工/联系人等自然人对象"),
    ("l1.org", "组织", "l0.object", "公司/法人主体（org 即租户边界）"),
    ("l1.department", "部门", "l0.object", "组织内部门（物化路径层级）"),
    ("l1.team", "团队", "l0.object", "跨部门协作团队/专家组"),
    ("l1.role", "角色", "l0.object", "岗位/职能角色"),
    ("l1.customer", "客户", "l0.object", "外部客户主体"),
    ("l1.supplier", "供应商", "l0.object", "外部供应商主体"),
    ("l1.product", "产品", "l0.object", "产品/服务线"),
    ("l1.contract", "合同", "l0.object", "合同/协议对象"),
    ("l1.project", "项目", "l0.object", "项目/工程对象"),
    ("l1.task", "任务", "l0.object", "任务/工单对象"),
    ("l1.document", "文档", "l0.evidence", "知识库文档（kb_documents 互引侧）"),
    ("l1.knowledge", "知识", "l0.knowledge", "已审知识节点（知识层挂接点）"),
)

#: 全部种子（22 条）；alembic 0047 与本常量保持字面一致（测试守护）
SEED_TYPES: Tuple[Tuple[str, str, str, str], ...] = (
    L0_SEED_TYPES + L1_SEED_TYPES
)


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class OntologyType(BaseModel):
    """本体类型（``ontology_types`` 行；种子后只读为主）。"""

    id: str
    name: str
    layer: str = LAYER_L1
    parent_id: str = ""
    description: str = ""
    attributes_schema: Dict[str, Any] = Field(default_factory=dict)


class OntologyObject(BaseModel):
    """本体对象实例（``ontology_objects`` 行）。"""

    id: str
    type_id: str
    name: str
    aliases: List[str] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    #: 当前状态（自由文本，业务侧状态机标签；状态迁移历史见
    #: ``ontology_state_transitions``）
    state: str = ""
    state_detail: Dict[str, Any] = Field(default_factory=dict)
    owner_id: str = ""
    org_id: str = ""
    department_id: str = ""
    status: str = OBJECT_STATUS_ACTIVE
    source: str = SOURCE_MANUAL
    evidence_refs: List[str] = Field(default_factory=list)
    is_delete: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class OntologyRelation(BaseModel):
    """本体关系（``ontology_relations`` 行；有向边，时效内建）。"""

    id: str
    type: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    confidence: float = 1.0
    source: str = SOURCE_MANUAL
    evidence_refs: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class OntologyStateTransition(BaseModel):
    """状态迁移留档（``ontology_state_transitions``；仅建模无运行时）。"""

    id: str
    object_id: str
    from_state: str = ""
    to_state: str = ""
    #: 方案文档字段名 ``trigger``（PG 保留字，此处更名）
    trigger_type: str = ""
    preconditions: Dict[str, Any] = Field(default_factory=dict)
    permission: str = ""
    postconditions: Dict[str, Any] = Field(default_factory=dict)
    audit_required: bool = False
    created_at: Optional[datetime] = None


class OntologyRule(BaseModel):
    """业务规则留档（``ontology_rules``；仅建模，条件 DSL 为后续里程碑）。"""

    id: str
    name: str
    scope: str = ""
    object_type: str = ""
    priority: int = 3
    conditions: Dict[str, Any] = Field(default_factory=dict)
    then_actions: Dict[str, Any] = Field(default_factory=dict)
    else_actions: Dict[str, Any] = Field(default_factory=dict)
    effective_from: Optional[datetime] = None
    version: int = 1
    evidence_refs: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class OntologyAction(BaseModel):
    """动作定义留档（``ontology_actions``；执行/审批链为后续里程碑，
    后续复用 ``app/approvals`` + tool 注册体系）。"""

    id: str
    name: str
    object_type: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    preconditions: Dict[str, Any] = Field(default_factory=dict)
    policy: Dict[str, Any] = Field(default_factory=dict)
    approval: Dict[str, Any] = Field(default_factory=dict)
    execution: Dict[str, Any] = Field(default_factory=dict)
    postconditions: Dict[str, Any] = Field(default_factory=dict)
    rollback: Dict[str, Any] = Field(default_factory=dict)
    auditable: bool = True
    created_at: Optional[datetime] = None


class KbObjectLink(BaseModel):
    """知识 ↔ 本体互引（``kb_object_links``；文档是知识权威源，
    本表只表达「知识支撑对象/定义规则/提及对象」的引用关系）。"""

    id: str
    kb_space_id: str
    kb_document_id: str
    object_type: str
    object_id: str
    relation: str = LINK_RELATION_MENTIONS
    created_at: Optional[datetime] = None


__all__ = [
    "LAYER_L0",
    "LAYER_L1",
    "VALID_LAYERS",
    "OBJECT_STATUS_ACTIVE",
    "OBJECT_STATUS_ARCHIVED",
    "VALID_OBJECT_STATUSES",
    "SOURCE_MANUAL",
    "SOURCE_LLM",
    "SOURCE_IMPORT",
    "VALID_ONTOLOGY_SOURCES",
    "LINK_RELATION_MENTIONS",
    "LINK_RELATION_SUPPORTS",
    "LINK_RELATION_DEFINES_RULE",
    "VALID_LINK_RELATIONS",
    "L0_SEED_TYPES",
    "L1_SEED_TYPES",
    "SEED_TYPES",
    "OntologyType",
    "OntologyObject",
    "OntologyRelation",
    "OntologyStateTransition",
    "OntologyRule",
    "OntologyAction",
    "KbObjectLink",
]
