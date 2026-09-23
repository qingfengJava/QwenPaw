# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for console static dir resolution and source repo detection.

回归背景（2026-09-23 重组）：项目级平铺布局下，旧的
``repo/console/dist`` 回退失效，包内注入副本可能滞后于
``staffos-console/dist``，导致服务端持续供旧前端构建。
"""
from __future__ import annotations

from pathlib import Path

from qwenpaw.utils import console_static as cs


def _make_pkg(tmp_path: Path) -> Path:
    """Build a fake source layout, return the qwenpaw package dir."""
    pkg = tmp_path / "repo" / "staffos-server" / "src" / "qwenpaw"
    pkg.mkdir(parents=True)
    return pkg


def _write_index(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text("<html></html>", encoding="utf-8")


class TestResolveConsoleStaticDir:
    def test_prefers_fresh_repo_dist_over_injected_copy(
        self,
        tmp_path,
        monkeypatch,
    ):
        """仓库内最新构建必须优先于（可能滞后的）包内注入副本。"""
        monkeypatch.delenv("QWENPAW_CONSOLE_STATIC_DIR", raising=False)
        pkg = _make_pkg(tmp_path)
        fresh = tmp_path / "repo" / "staffos-console" / "dist"
        _write_index(fresh)
        injected = pkg / "console"
        _write_index(injected)

        assert cs.resolve_console_static_dir(base_dir=pkg) == str(fresh)

    def test_falls_back_to_injected_copy_when_repo_dist_missing(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.delenv("QWENPAW_CONSOLE_STATIC_DIR", raising=False)
        pkg = _make_pkg(tmp_path)
        injected = pkg / "console"
        _write_index(injected)

        assert cs.resolve_console_static_dir(base_dir=pkg) == str(injected)

    def test_env_override_wins(self, tmp_path, monkeypatch):
        env_dir = tmp_path / "custom-dist"
        _write_index(env_dir)
        monkeypatch.setenv("QWENPAW_CONSOLE_STATIC_DIR", str(env_dir))
        pkg = _make_pkg(tmp_path)
        injected = pkg / "console"
        _write_index(injected)

        assert cs.resolve_console_static_dir(base_dir=pkg) == str(env_dir)

    def test_cwd_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("QWENPAW_CONSOLE_STATIC_DIR", raising=False)
        pkg = _make_pkg(tmp_path)
        cwd_dist = tmp_path / "cwd" / "console" / "dist"
        _write_index(cwd_dist)
        monkeypatch.chdir(tmp_path / "cwd")

        assert cs.resolve_console_static_dir(base_dir=pkg) == str(cwd_dist)

    def test_candidates_order_and_paths(self, tmp_path):
        pkg = _make_pkg(tmp_path)
        candidates = cs._static_candidates(pkg)
        assert candidates[0] == tmp_path / "repo" / "staffos-console" / "dist"
        assert candidates[1] == pkg / "console"
        # 旧布局兼容：staffos-server/console/dist（重组前为仓库根）
        assert candidates[2] == (
            tmp_path / "repo" / "staffos-server" / "console" / "dist"
        )


class TestFindQwenPawSourceRepoRoot:
    def test_detects_project_per_dir_layout(self, tmp_path, monkeypatch):
        """新布局：staffos-console + staffos-server/src/qwenpaw。"""
        repo = tmp_path / "repo"
        pkg = repo / "staffos-server" / "src" / "qwenpaw"
        pkg.mkdir(parents=True)
        con = repo / "staffos-console"
        con.mkdir(parents=True)
        (con / "package.json").write_text("{}", encoding="utf-8")
        (con / "package-lock.json").write_text("{}", encoding="utf-8")

        import qwenpaw

        monkeypatch.setattr(
            qwenpaw,
            "__file__",
            str(pkg / "__init__.py"),
        )
        assert cs.find_qwenpaw_source_repo_root() == repo

    def test_detects_legacy_layout(self, tmp_path, monkeypatch):
        """旧布局：console + src/qwenpaw 兼容保留。"""
        repo = tmp_path / "repo"
        pkg = repo / "src" / "qwenpaw"
        pkg.mkdir(parents=True)
        con = repo / "console"
        con.mkdir(parents=True)
        (con / "package.json").write_text("{}", encoding="utf-8")
        (con / "package-lock.json").write_text("{}", encoding="utf-8")

        import qwenpaw

        monkeypatch.setattr(
            qwenpaw,
            "__file__",
            str(pkg / "__init__.py"),
        )
        assert cs.find_qwenpaw_source_repo_root() == repo
