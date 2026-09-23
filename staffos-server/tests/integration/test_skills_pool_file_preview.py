# -*- coding: utf-8 -*-
"""Integration tests for pool skill detail-page file preview APIs.

Covers the skill detail page's backend plane added with the detail-drawer
redesign:

  - GET  /api/skills/pool/{skill_name}/files   (directory tree preview)
  - GET  /api/skills/pool/{skill_name}/file    (single file content preview)
  - GET  /api/skills/pool/{skill_name}         (version / used_by extension)

Happy path first; traversal attempts must be rejected with 400 and never
leak files outside the skill directory. No LLM / network deps.
"""
from __future__ import annotations

from typing import Any

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(15.0)
_POOL_BASE = "/api/skills/pool"


# ------------------------------------------------------------------ #
# helpers (mirror test_skills_pool_autosync.py house style)
# ------------------------------------------------------------------ #


def _skill_md(name: str, description: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "version: 1.2.3\n"
        "---\n\n"
        "# File Preview Skill\n"
        "Created by file-preview integration tests.\n"
    )


def _create_pool_skill(app_server, name: str) -> dict[str, Any]:
    resp = app_server.api_request(
        "POST",
        f"{_POOL_BASE}/create",
        json={
            "name": name,
            "content": _skill_md(name, "file preview test skill"),
            "references": {"guide.md": "# Guide\n\nStep by step.\n"},
            "scripts": {"helper.py": "print('hello preview')\n"},
            "enable": False,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()


def _delete_pool_skill_quietly(app_server, name: str) -> None:
    try:
        app_server.api_request(
            "DELETE",
            f"{_POOL_BASE}/{name}",
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:
        pass


def _flatten_files(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Flatten the tree response into {path: node} for easy assertions."""
    flat: dict[str, dict[str, Any]] = {}

    def _walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            flat[item["path"]] = item
            _walk(item.get("children") or [])

    _walk(nodes)
    return flat


# ================================================================== #
# A — file tree preview (happy path)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_file_tree_lists_scripts_and_references(app_server) -> None:
    """GET /pool/{name}/files returns the skill directory tree.

    Test flow:
      1. Create a pool skill with references/ and scripts/ files.
      2. GET .../files -> 200, SKILL.md + scripts/helper.py +
         references/guide.md all present with correct types.
      3. finally: delete the pool skill.

    API endpoints:
      - POST /api/skills/pool/create
      - GET  /api/skills/pool/{skill_name}/files
      - DELETE /api/skills/pool/{skill_name}
    """
    name = "integ-pool-files-tree"
    try:
        _create_pool_skill(app_server, name)
        resp = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}/files",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        flat = _flatten_files(resp.json())
        assert flat["SKILL.md"]["type"] == "file"
        assert flat["scripts"]["type"] == "dir"
        assert flat["scripts/helper.py"]["type"] == "file"
        assert flat["scripts/helper.py"]["size"] > 0
        assert flat["references/guide.md"]["type"] == "file"
    finally:
        _delete_pool_skill_quietly(app_server, name)


# ================================================================== #
# B — single file content preview
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_file_preview_text_content(app_server) -> None:
    """GET /pool/{name}/file returns text content for known text files.

    Test flow:
      1. Create a pool skill with scripts/helper.py.
      2. GET .../file?path=scripts/helper.py -> type=text, language=python,
         content matches what was written.
      3. GET .../file?path=references/guide.md -> type=text, content kept.
      4. finally: delete the pool skill.

    API endpoints:
      - POST /api/skills/pool/create
      - GET  /api/skills/pool/{skill_name}/file
      - DELETE /api/skills/pool/{skill_name}
    """
    name = "integ-pool-files-read"
    try:
        _create_pool_skill(app_server, name)
        py_resp = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}/file",
            params={"path": "scripts/helper.py"},
            timeout=_HTTP_TIMEOUT,
        )
        assert py_resp.status_code == 200, app_server.logs_tail()
        py_body = py_resp.json()
        assert py_body["type"] == "text"
        assert py_body["language"] == "python"
        assert "hello preview" in py_body["content"]

        md_resp = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}/file",
            params={"path": "references/guide.md"},
            timeout=_HTTP_TIMEOUT,
        )
        assert md_resp.status_code == 200, app_server.logs_tail()
        assert md_resp.json()["type"] == "text"
        assert "Step by step." in md_resp.json()["content"]
    finally:
        _delete_pool_skill_quietly(app_server, name)


@pytest.mark.integration
@pytest.mark.p1
def test_pool_file_preview_rejects_traversal(app_server) -> None:
    """GET /pool/{name}/file rejects traversal paths with 400.

    Test flow:
      1. Create a pool skill.
      2. GET .../file?path=../secret.txt -> 400 (never leaks outside root).
      3. GET .../file?path=a/../../secret.txt -> 400.
      4. finally: delete the pool skill.

    API endpoints:
      - POST /api/skills/pool/create
      - GET  /api/skills/pool/{skill_name}/file
      - DELETE /api/skills/pool/{skill_name}
    """
    name = "integ-pool-files-traversal"
    try:
        _create_pool_skill(app_server, name)
        # 真实穿越段（..）必须被 400 拦截
        for unsafe in ("../secret.txt", "a/../../secret.txt", "a/../../../secret.txt"):
            resp = app_server.api_request(
                "GET",
                f"{_POOL_BASE}/{name}/file",
                params={"path": unsafe},
                timeout=_HTTP_TIMEOUT,
            )
            assert resp.status_code == 400, app_server.logs_tail()
        # 编码变体（%2F 双编码后不构成真实 ..段）：只要文件不可达即安全（400/404）
        for encoded in ("..%2Fsecret.txt", "a%2F..%2Fsecret.txt"):
            resp = app_server.api_request(
                "GET",
                f"{_POOL_BASE}/{name}/file",
                params={"path": encoded},
                timeout=_HTTP_TIMEOUT,
            )
            assert resp.status_code != 200, app_server.logs_tail()
    finally:
        _delete_pool_skill_quietly(app_server, name)


@pytest.mark.integration
@pytest.mark.p2
def test_pool_file_preview_not_found(app_server) -> None:
    """GET /pool/{name}/file -> 404 for missing file / missing skill.

    Test flow:
      1. Create a pool skill; GET .../file?path=nope.txt -> 404.
      2. GET .../file on an unknown skill name -> 404.
      3. finally: delete the pool skill.

    API endpoints:
      - POST /api/skills/pool/create
      - GET  /api/skills/pool/{skill_name}/file
      - DELETE /api/skills/pool/{skill_name}
    """
    name = "integ-pool-files-404"
    try:
        _create_pool_skill(app_server, name)
        missing = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}/file",
            params={"path": "nope.txt"},
            timeout=_HTTP_TIMEOUT,
        )
        assert missing.status_code == 404, app_server.logs_tail()
        unknown = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/integ-no-such-skill/file",
            params={"path": "SKILL.md"},
            timeout=_HTTP_TIMEOUT,
        )
        assert unknown.status_code == 404, app_server.logs_tail()
    finally:
        _delete_pool_skill_quietly(app_server, name)


# ================================================================== #
# C — detail response extensions (version / used_by)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_pool_detail_includes_version_and_used_by(app_server) -> None:
    """GET /pool/{name} exposes version (frontmatter) and used_by list.

    Test flow:
      1. Create a pool skill whose SKILL.md frontmatter has version 1.2.3.
      2. GET .../pool/{name} -> version == "1.2.3", used_by is a list.
      3. finally: delete the pool skill.

    API endpoints:
      - POST /api/skills/pool/create
      - GET  /api/skills/pool/{skill_name}
      - DELETE /api/skills/pool/{skill_name}
    """
    name = "integ-pool-detail-version"
    try:
        _create_pool_skill(app_server, name)
        resp = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        body = resp.json()
        assert body["version"] == "1.2.3"
        assert isinstance(body["used_by"], list)
    finally:
        _delete_pool_skill_quietly(app_server, name)
