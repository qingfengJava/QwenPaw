# -*- coding: utf-8 -*-
"""T8e：运行时个人技能（S2）overlay 目录解析。

只覆盖 ``AgentBuilder._resolve_skill_loader_dirs`` 的纯逻辑：
personal_skill_dir 为 None 时与既有完全一致（热路径零行为变化）；
命中个人目录时按「共享优先、个人兜底」解析；未知名称不注入。
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path

from qwenpaw.runtime.builder import AgentBuilder


def _make_skill(root: Path, name: str) -> Path:
    """在 root 下造一个含 SKILL.md 的技能目录。"""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    return skill_dir


def test_personal_dir_none_resolves_only_shared(tmp_path: Path) -> None:
    """personal_skill_dir=None → 仅解析共享目录（与既有一致）。"""
    shared_root = tmp_path / "skills"
    _make_skill(shared_root, "alpha")

    dirs = AgentBuilder._resolve_skill_loader_dirs(
        ["alpha"],
        str(tmp_path),
        None,
    )

    assert len(dirs) == 1
    assert Path(dirs[0]) == shared_root / "alpha"


def test_personal_skill_resolved_when_not_in_shared(tmp_path: Path) -> None:
    """共享/池/内置均未命中时，回退会话用户个人目录。"""
    (tmp_path / "skills").mkdir(parents=True)
    personal_root = tmp_path / ".personal_skills" / "alice"
    _make_skill(personal_root, "mine")

    dirs = AgentBuilder._resolve_skill_loader_dirs(
        ["mine"],
        str(tmp_path),
        str(personal_root),
    )

    assert len(dirs) == 1
    assert Path(dirs[0]) == personal_root / "mine"


def test_shared_wins_over_personal_on_name_conflict(tmp_path: Path) -> None:
    """同名冲突：共享优先，个人副本不覆盖共享。"""
    shared_root = tmp_path / "skills"
    _make_skill(shared_root, "dup")
    personal_root = tmp_path / ".personal_skills" / "alice"
    _make_skill(personal_root, "dup")

    dirs = AgentBuilder._resolve_skill_loader_dirs(
        ["dup"],
        str(tmp_path),
        str(personal_root),
    )

    assert len(dirs) == 1
    assert Path(dirs[0]) == shared_root / "dup"


def test_unknown_name_not_injected(tmp_path: Path) -> None:
    """个人目录也不存在的名称：不注入（返回空）。"""
    (tmp_path / "skills").mkdir(parents=True)
    personal_root = tmp_path / ".personal_skills" / "alice"
    personal_root.mkdir(parents=True)

    dirs = AgentBuilder._resolve_skill_loader_dirs(
        ["ghost"],
        str(tmp_path),
        str(personal_root),
    )

    assert dirs == []


def test_personal_ignored_when_dir_none_even_if_name_given(
    tmp_path: Path,
) -> None:
    """未传个人目录（无会话用户）时，个人技能名解析不到 → 不注入。"""
    (tmp_path / "skills").mkdir(parents=True)

    dirs = AgentBuilder._resolve_skill_loader_dirs(
        ["mine"],
        str(tmp_path),
        None,
    )

    assert dirs == []
