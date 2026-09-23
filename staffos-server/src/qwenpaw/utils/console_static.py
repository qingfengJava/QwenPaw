# -*- coding: utf-8 -*-
"""Resolve the web console static assets directory (shared by app and CLI)."""
from __future__ import annotations

import os
from pathlib import Path

from ..constant import EnvVarLoader

# Primary env key (``COPAW_CONSOLE_STATIC_DIR`` is accepted as a legacy
# fallback via :class:`~qwenpaw.constant.EnvVarLoader`).
CONSOLE_STATIC_ENV = "QWENPAW_CONSOLE_STATIC_DIR"


def _static_candidates(pkg_dir: Path) -> list[Path]:
    """Return resolution candidates after the env override, in order.

    新布局（项目级平铺）下仓库内最新构建（``staffos-console/dist``）
    优先于包内注入副本：注入副本可能滞后于 dist，导致线上服务旧
    前端（登录页/主题令牌不一致）。wheel 安装态下仓库路径不存在，
    自然回落到包内副本，行为不变。
    """
    return [
        # 项目级平铺布局：src/qwenpaw -> src -> staffos-server -> 仓库根
        pkg_dir.parents[2] / "staffos-console" / "dist",
        # 包内注入副本（wheel / 打包态）
        pkg_dir / "console",
        # 重组前旧布局兼容（仓库根 console/dist）
        pkg_dir.parents[1] / "console" / "dist",
    ]


def resolve_console_static_dir(base_dir: Path | None = None) -> str:
    """Return the directory expected to contain ``index.html`` for the console.

    Resolution order: env override, repo ``staffos-console/dist`` (fresh
    dev build), package ``qwenpaw/console`` (injected copy), legacy repo
    ``console/dist``, then cwd fallbacks.
    """
    static_dir = EnvVarLoader.get_str(CONSOLE_STATIC_ENV)
    if static_dir:
        return static_dir

    pkg_dir = base_dir or Path(__file__).resolve().parent.parent
    for candidate in _static_candidates(pkg_dir):
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return str(candidate)

    cwd = Path(os.getcwd())
    for subdir in ("console/dist", "console_dist"):
        candidate = cwd / subdir
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return str(candidate)

    return str(cwd / "console" / "dist")


def find_qwenpaw_source_repo_root() -> Path | None:
    """Return the git checkout root if this Python
    is running from QwenPaw source.

    Looks upward from :mod:`qwenpaw` for the console package metadata
    and the server-side ``qwenpaw`` package, supporting both the
    legacy layout (``console/`` + ``src/qwenpaw``) and the
    project-per-dir layout (``staffos-console/`` +
    ``staffos-server/src/qwenpaw``).
    Returns ``None`` for a normal pip/wheel install.
    """
    try:
        import qwenpaw  # noqa: PLC0415 — avoid import cycle at module load
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    cur = Path(qwenpaw.__file__).resolve().parent
    for _ in range(20):
        # 项目级平铺布局：staffos-console + staffos-server/src/qwenpaw
        staffos_con = cur / "staffos-console"
        if (
            (staffos_con / "package.json").is_file()
            and (staffos_con / "package-lock.json").is_file()
            and (cur / "staffos-server" / "src" / "qwenpaw").is_dir()
        ):
            return cur
        # 重组前旧布局：console + src/qwenpaw
        con = cur / "console"
        if (
            (con / "package.json").is_file()
            and (con / "package-lock.json").is_file()
            and (cur / "src" / "qwenpaw").is_dir()
        ):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None
