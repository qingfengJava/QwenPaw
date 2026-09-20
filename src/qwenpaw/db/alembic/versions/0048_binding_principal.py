# -*- coding: utf-8 -*-
"""Binding principal generalization: agent | team (ontology T6).

Revision ID: 0048_binding_principal
Revises: 0047_kb_ontology
Create Date: 2026-09-20

知识本体平台 T6（数字员工与专家团接入，绑定主体泛化）：

- ``agent_kb_bindings.principal_type``（``agent`` | ``team``，存量回填
  ``agent`` 语义 = 现行行为不变）；**team 行的 ``agent_id`` 列存
  ``expert_teams.id`` 的运行态形态 ``team_{team_id}``（即
  ``expert_team_agent_id`` 惯例），列名不改以保兼容**；
- 纯加列（NOT NULL DEFAULT 'agent'），不动 ``(tenant_id, agent_id,
  space_id)`` 唯一键——supervisor 直绑与团队绑同库的重叠行按幂等
  语义收敛（INSERT ON CONFLICT DO NOTHING）；
- 团队绑定解析（supervisor 归属 + 成员归属反查）在应用层
  ``kb/bindings.py``，本迁移只承载存储列。

全部 DDL 幂等。（psql twin: changelog 20260920/06）。

@author qingfeng
"""

from __future__ import annotations

from alembic import op

revision = "0048_binding_principal"
down_revision = "0047_kb_ontology"
branch_labels = None
depends_on = None

_ADD_COLUMN = (
    "ALTER TABLE agent_kb_bindings ADD COLUMN IF NOT EXISTS principal_type "
    "VARCHAR(16) NOT NULL DEFAULT 'agent'",
)

_COMMENT = (
    "COMMENT ON COLUMN agent_kb_bindings.principal_type IS "
    "'绑定主体类型: agent-数字员工直绑(存量语义), team-专家组绑"
    "(agent_id 列存 team_{team_id} 运行态形态, 列名不改保兼容)'",
)


def upgrade() -> None:
    for statement in _ADD_COLUMN:
        op.execute(statement)
    for comment in _COMMENT:
        op.execute(comment)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_kb_bindings "
        "DROP COLUMN IF EXISTS principal_type",
    )
