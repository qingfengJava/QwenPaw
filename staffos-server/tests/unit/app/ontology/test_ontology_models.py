# -*- coding: utf-8 -*-
"""T4 ontology 种子与三轨一致守护。

锁定四条不变式：

1. **种子完备**：L0 九类元模型 + L1 十三类业务核心，id 全局唯一；
2. **父引用闭合**：L1 的 parent_id 必须指向存在的 L0 类型（杜绝
   悬挂父引用——grounding 与前端类型树都会沿 parent 遍历）；
3. **三轨字面一致**：alembic 0047 / changelog 05 / test.sql / prod.sql
   四处都含全部种子 id（防止「迁移改了快照漏改」的经典漂移）；
4. **枚举封闭**：VALID_* frozenset 与常量一一对应。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.ontology import models

pytestmark = pytest.mark.unit

#: 仓库根（tests/unit/app/ontology/ → 上溯四级）
# staffos-server 项目根（src/qwenpaw 与 db/ 所在）
_REPO_ROOT = Path(__file__).resolve().parents[4]

#: 含种子的三轨文件（相对 staffos-server 根）
_SEED_FILES = (
    Path("src/qwenpaw/db/alembic/versions/0047_kb_ontology.py"),
    Path(
        "db/feature/agent_run_logs_20260908/changelog/20260920/"
        "05_kb_ontology.sql",
    ),
    Path("db/feature/agent_run_logs_20260908/test.sql"),
    Path("db/feature/agent_run_logs_20260908/prod.sql"),
)


# ---------------------------------------------------------------------------
# 种子完备性
# ---------------------------------------------------------------------------


def test_seed_counts() -> None:
    """L0 九类 + L1 十三类 = 22 条种子。"""
    assert len(models.L0_SEED_TYPES) == 9
    assert len(models.L1_SEED_TYPES) == 13
    assert len(models.SEED_TYPES) == 22
    assert models.SEED_TYPES == (
        models.L0_SEED_TYPES + models.L1_SEED_TYPES
    )


def test_seed_ids_unique() -> None:
    """种子 id 全局唯一（幂等 ON CONFLICT 依赖主键不重复）。"""
    ids = [seed[0] for seed in models.SEED_TYPES]
    assert len(ids) == len(set(ids))


def test_seed_layer_split() -> None:
    """L0/L1 前缀与分段严格对应（layer 字段由 id 前缀可推导）。"""
    for type_id, _name, _parent, _desc in models.L0_SEED_TYPES:
        assert type_id.startswith("l0.")
    for type_id, _name, _parent, _desc in models.L1_SEED_TYPES:
        assert type_id.startswith("l1.")


def test_l1_parents_exist_in_l0() -> None:
    """L1 的 parent_id 必须是存在的 L0 id（无悬挂父引用）。"""
    l0_ids = {seed[0] for seed in models.L0_SEED_TYPES}
    for type_id, _name, parent_id, _desc in models.L1_SEED_TYPES:
        assert parent_id in l0_ids, f"{type_id} 悬挂父引用 {parent_id}"


def test_l0_parents_empty() -> None:
    """L0 元类型为根层（parent_id 全空串）。"""
    for _type_id, _name, parent_id, _desc in models.L0_SEED_TYPES:
        assert parent_id == ""


def test_expected_l1_entities() -> None:
    """L1 十三类与计划定稿清单一致（11 实体 + document + knowledge）。"""
    l1_ids = {seed[0] for seed in models.L1_SEED_TYPES}
    assert l1_ids == {
        "l1.person",
        "l1.org",
        "l1.department",
        "l1.team",
        "l1.role",
        "l1.customer",
        "l1.supplier",
        "l1.product",
        "l1.contract",
        "l1.project",
        "l1.task",
        "l1.document",
        "l1.knowledge",
    }


# ---------------------------------------------------------------------------
# 三轨字面一致
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel_path", _SEED_FILES)
def test_seed_files_contain_all_ids(rel_path: Path) -> None:
    """三轨四处都含全部种子 id（防快照漏同步漂移）。"""
    text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    missing = [
        type_id
        for type_id, _n, _p, _d in models.SEED_TYPES
        if f"'{type_id}'" not in text
    ]
    assert missing == [], f"{rel_path} 缺种子 id: {missing}"


def test_migration_mentions_trigger_rename() -> None:
    """迁移保留 trigger → trigger_type 更名说明（方案字段可追溯）。"""
    text = (
        _REPO_ROOT / "src/qwenpaw/db/alembic/versions/0047_kb_ontology.py"
    ).read_text(encoding="utf-8")
    assert "trigger_type" in text
    assert "0047_kb_ontology" in text
    assert 'down_revision = "0046_kb_wiki"' in text


# ---------------------------------------------------------------------------
# 枚举封闭性
# ---------------------------------------------------------------------------


def test_valid_sets_closed() -> None:
    """VALID_* 集合与对应常量封闭对应。"""
    assert models.VALID_LAYERS == frozenset(
        {"L0", "L1", "L2", "L3", "L4", "L5"},
    )
    assert models.VALID_OBJECT_STATUSES == frozenset(
        {models.OBJECT_STATUS_ACTIVE, models.OBJECT_STATUS_ARCHIVED},
    )
    assert models.VALID_ONTOLOGY_SOURCES == frozenset(
        {models.SOURCE_MANUAL, models.SOURCE_LLM, models.SOURCE_IMPORT},
    )
    assert models.VALID_LINK_RELATIONS == frozenset(
        {
            models.LINK_RELATION_MENTIONS,
            models.LINK_RELATION_SUPPORTS,
            models.LINK_RELATION_DEFINES_RULE,
        },
    )
