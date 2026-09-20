# -*- coding: utf-8 -*-
"""M6-11: 员工面文档 CRUD / 上传 / 预览 / search-test 全链路（T11）。

门控：宿主机 ``QWENPAW_TEST_PG_DSN`` 未设时整文件 skip（PG 门控跑法
同 ``test_kb_pg_plane`` / ``test_kb_bindings_api`` 既有套件）。

子进程供血（collection 阶段自举，先于 ``app_server`` 夹具读 env）：

- ``QWENPAW_TEST_PG_DSN`` → ``QWENPAW_PG_DSN``：conftest
  ``_isolate_pg_database`` 会把库改写到隔离库 ``qwenpaw_integration_test``
  并幂等建库，绝不读写开发者库；**无条件覆盖**——shell 残留 DSN
  （如指向 5432 开发者库）必须被屏蔽，本套件 DSN 唯一权威源是
  ``QWENPAW_TEST_PG_DSN``；
- ``QWENPAW_STORAGE_BACKEND=pg``：默认 dual 会让 KbService 三态门面的
  读（chunks/search）走 json 文件面，与 pg 权威写入面（T6
  ``ingest_space_document``）脱节——T11 文档面端点定位 pg 权威平面，
  同理无条件覆盖。

净注入：测试环境无 embedding 模型配置 → ``embed_texts`` 返回 ``None``
→ 摄入与检索全链 BM25-only，零网络、零模型依赖。

清理：finally 直连隔离库按本用例 kb id 定点删除六表行（可反复跑）。

请求/响应形状以计划文档 T11 章节内嵌测试为基底（L836-884），叠加
search-test 与目录树断言（用户生命周期要求）。

@author qingfeng
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Any, Dict, List

import pytest
from sqlalchemy.engine import make_url

pytestmark = [pytest.mark.integration, pytest.mark.p0]

_TEST_DSN = os.environ.get("QWENPAW_TEST_PG_DSN", "").strip()
if not _TEST_DSN:
    pytest.skip(
        "QWENPAW_TEST_PG_DSN not set (PG-gated kb phase1 api tests)",
        allow_module_level=True,
    )
os.environ["QWENPAW_PG_DSN"] = _TEST_DSN
os.environ["QWENPAW_STORAGE_BACKEND"] = "pg"

#: 隔离库（与 conftest._INTEGRATION_DB_NAME 保持一致）
_INTEGRATION_DB = "qwenpaw_integration_test"

_HTML = "<h1>甲减</h1><p>左甲状腺素</p>".encode("utf-8")
_EDITED_MD = "# 甲减\n\n左甲状腺素剂量增加 20%-30%。"


def _isolation_engine() -> Any:
    """隔离库 async 引擎（NullPool：跨临时循环复用不携带旧连接）。"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    url = make_url(_TEST_DSN).set(database=_INTEGRATION_DB)
    if "+asyncpg" not in url.drivername:
        url = url.set(drivername="postgresql+asyncpg")
    return create_async_engine(
        url.render_as_string(hide_password=False),
        poolclass=NullPool,
    )


async def _cleanup(kb_id: str) -> None:
    """按 kb id 定点清理 KB 六表行（本用例可反复跑的前提）。"""
    from sqlalchemy import text

    engine = _isolation_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM kb_document_versions WHERE document_id IN "
                    "(SELECT id FROM kb_documents WHERE space_id = :kb)",
                ),
                {"kb": kb_id},
            )
            for table in ("kb_chunks", "kb_links", "kb_documents"):
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE space_id = :kb"),
                    {"kb": kb_id},
                )
            await conn.execute(
                text("DELETE FROM agent_kb_bindings WHERE space_id = :kb"),
                {"kb": kb_id},
            )
            await conn.execute(
                text("DELETE FROM kb_spaces WHERE id = :kb"),
                {"kb": kb_id},
            )
    finally:
        await engine.dispose()


def _flatten_tree(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """目录树拉平（含目录节点），供 doc_id 存在性断言。"""
    flat: List[Dict[str, Any]] = []
    for node in nodes:
        flat.append(node)
        flat.extend(_flatten_tree(node.get("children") or []))
    return flat


def test_kb_document_lifecycle(app_server: Any) -> None:
    """建库→上传 html→详情 ready→PUT 编辑→版本+1→chunk 预览→检索命中。"""
    kb_id = ""
    try:
        # 1. 建库（无认证部署 → caller 回退 local，personal 库 owner=local）
        space = app_server.api_request(
            "POST",
            "/api/kb",
            json={"name": "孕产库", "description": "孕产用药问题检索本库"},
        )
        assert space.status_code == 201, app_server.logs_tail()
        kb_id = space.json()["id"]

        # 2. multipart 上传 html → 异步摄入状态机推进到 ready
        up = app_server.api_request(
            "POST",
            f"/api/kb/{kb_id}/documents/upload",
            files={"file": ("guide.html", _HTML, "text/html")},
        )
        assert up.status_code == 201, app_server.logs_tail()
        doc_id = up.json()["doc_id"]
        assert doc_id, app_server.logs_tail()

        # 3. 文档详情：ingest_status==ready（含 content_md 权威全文）
        got = app_server.api_request(
            "GET",
            f"/api/kb/{kb_id}/documents/{doc_id}",
        )
        assert got.status_code == 200, app_server.logs_tail()
        detail = got.json()
        assert detail["ingest_status"] == "ready", app_server.logs_tail()
        assert "甲减" in detail["content_md"], app_server.logs_tail()

        # 4. PUT 编辑 MD：content_md upsert 自动版本+1 + 重切片重索引
        put = app_server.api_request(
            "PUT",
            f"/api/kb/{kb_id}/documents/{doc_id}",
            json={"content_md": _EDITED_MD},
        )
        assert put.status_code == 200, app_server.logs_tail()
        assert put.json()["version"] == 2, app_server.logs_tail()

        # 5. chunk 预览（数据源 svc.document_chunks）：非空
        chunks = app_server.api_request(
            "GET",
            f"/api/kb/{kb_id}/documents/{doc_id}/chunks",
        )
        assert chunks.status_code == 200, app_server.logs_tail()
        assert len(chunks.json()) >= 1, app_server.logs_tail()

        # 6. 员工面混合检索：编辑后的内容应可召回
        hit = app_server.api_request(
            "POST",
            "/api/kb/search",
            json={"query": "左甲状腺素", "kb_id": kb_id},
        )
        assert hit.status_code == 200, app_server.logs_tail()
        assert hit.json()["hits"], "混合检索应命中"

        # 7. search-test（管理面透传引擎 top-k + 得分）
        st = app_server.api_request(
            "POST",
            "/api/admin/kb/search-test",
            json={"query": "左甲状腺素", "kb_id": kb_id, "top_k": 5},
        )
        assert st.status_code == 200, app_server.logs_tail()
        st_hits = st.json()["hits"]
        assert st_hits, "search-test 应命中"
        assert all("score" in item for item in st_hits), app_server.logs_tail()

        # 8. path 聚合目录树：上传文档应出现在树上
        tree = app_server.api_request(
            "GET",
            f"/api/kb/{kb_id}/tree",
        )
        assert tree.status_code == 200, app_server.logs_tail()
        flat = _flatten_tree(tree.json()["nodes"])
        assert any(
            node.get("doc_id") == doc_id for node in flat
        ), app_server.logs_tail()
    finally:
        if kb_id:
            asyncio.run(_cleanup(kb_id))


# ------------------------------------------------------------------
# T11 审查修复轮负例（P3-7）
# ------------------------------------------------------------------


async def _set_space_owner(kb_id: str, owner_id: str) -> None:
    """直改隔离库 space 归属（构造「非 owner」写负例的前提）。"""
    from sqlalchemy import text

    engine = _isolation_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE kb_spaces SET owner_id = :o WHERE id = :kb"),
                {"o": owner_id, "kb": kb_id},
            )
    finally:
        await engine.dispose()


def test_kb_write_requires_owner(app_server: Any) -> None:
    """非 owner 写负例：PUT/upload/delete 全部 403（P3-7-1）。"""
    kb_id = ""
    try:
        space = app_server.api_request(
            "POST", "/api/kb", json={"name": "负例库"}
        )
        assert space.status_code == 201, app_server.logs_tail()
        kb_id = space.json()["id"]
        up = app_server.api_request(
            "POST",
            f"/api/kb/{kb_id}/documents/upload",
            files={"file": ("guide.html", _HTML, "text/html")},
        )
        assert up.status_code == 201, app_server.logs_tail()
        doc_id = up.json()["doc_id"]

        # 归属改走 someone_else 后，local 对 personal 库不可读：
        # _get_accessible_kb 先拒（403 no access），三个写端点全 403
        asyncio.run(_set_space_owner(kb_id, "someone_else"))
        put = app_server.api_request(
            "PUT",
            f"/api/kb/{kb_id}/documents/{doc_id}",
            json={"content_md": _EDITED_MD},
        )
        assert put.status_code == 403, app_server.logs_tail()
        reup = app_server.api_request(
            "POST",
            f"/api/kb/{kb_id}/documents/upload",
            files={"file": ("guide2.html", _HTML, "text/html")},
        )
        assert reup.status_code == 403, app_server.logs_tail()
        dele = app_server.api_request(
            "DELETE",
            f"/api/kb/{kb_id}/documents/{doc_id}",
        )
        assert dele.status_code == 403, app_server.logs_tail()
    finally:
        if kb_id:
            asyncio.run(_cleanup(kb_id))


def test_kb_cross_space_doc_404(app_server: Any) -> None:
    """跨库 doc_id 负例：A 库文档在 B 库路径下 detail/PUT/chunks/delete 全 404。"""
    kb_a = kb_b = ""
    try:
        for name in ("负例A", "负例B"):
            created = app_server.api_request(
                "POST", "/api/kb", json={"name": name}
            )
            assert created.status_code == 201, app_server.logs_tail()
            if not kb_a:
                kb_a = created.json()["id"]
            else:
                kb_b = created.json()["id"]
        up = app_server.api_request(
            "POST",
            f"/api/kb/{kb_a}/documents/upload",
            files={"file": ("guide.html", _HTML, "text/html")},
        )
        assert up.status_code == 201, app_server.logs_tail()
        doc_id = up.json()["doc_id"]

        got = app_server.api_request(
            "GET", f"/api/kb/{kb_b}/documents/{doc_id}"
        )
        assert got.status_code == 404, app_server.logs_tail()
        put = app_server.api_request(
            "PUT",
            f"/api/kb/{kb_b}/documents/{doc_id}",
            json={"content_md": _EDITED_MD},
        )
        assert put.status_code == 404, app_server.logs_tail()
        chunks = app_server.api_request(
            "GET", f"/api/kb/{kb_b}/documents/{doc_id}/chunks"
        )
        assert chunks.status_code == 404, app_server.logs_tail()
        # 跨库删除（P2-N1 归属校验）：A 库管理权在 B 库路径删 → 404 不落删
        dele = app_server.api_request(
            "DELETE", f"/api/kb/{kb_b}/documents/{doc_id}"
        )
        assert dele.status_code == 404, app_server.logs_tail()
        # A 库内文档不受跨库删除尝试影响（仍可读）
        still = app_server.api_request(
            "GET", f"/api/kb/{kb_a}/documents/{doc_id}"
        )
        assert still.status_code == 200, app_server.logs_tail()
    finally:
        for kb_id in (kb_a, kb_b):
            if kb_id:
                asyncio.run(_cleanup(kb_id))


def test_kb_upload_idempotent_version(app_server: Any) -> None:
    """同内容重传幂等负例：doc_id 不变、version 仍为 1（P3-7-4）。"""
    kb_id = ""
    try:
        space = app_server.api_request(
            "POST", "/api/kb", json={"name": "幂等库"}
        )
        assert space.status_code == 201, app_server.logs_tail()
        kb_id = space.json()["id"]
        first = app_server.api_request(
            "POST",
            f"/api/kb/{kb_id}/documents/upload",
            files={"file": ("guide.html", _HTML, "text/html")},
        )
        assert first.status_code == 201, app_server.logs_tail()
        doc_id = first.json()["doc_id"]
        again = app_server.api_request(
            "POST",
            f"/api/kb/{kb_id}/documents/upload",
            files={"file": ("guide.html", _HTML, "text/html")},
        )
        assert again.status_code == 201, app_server.logs_tail()
        assert again.json()["doc_id"] == doc_id, app_server.logs_tail()
        got = app_server.api_request(
            "GET", f"/api/kb/{kb_id}/documents/{doc_id}"
        )
        assert got.status_code == 200, app_server.logs_tail()
        assert got.json()["version"] == 1, app_server.logs_tail()
    finally:
        if kb_id:
            asyncio.run(_cleanup(kb_id))


class _StubKbService:
    """json 后端 503 负例桩：库可读可管理，pg 权威面一律拒绝。"""

    def __init__(self, kb: Any) -> None:
        self._kb = kb
        self.pg_touched = 0

    def get_kb(self, kb_id: str) -> Any:
        return self._kb

    def can_access(self, kb: Any, username: str, **kw: Any) -> bool:
        return True

    def pg_ready(self) -> bool:
        return False

    def pg_list_documents(self, kb_id: str) -> List[Any]:
        self.pg_touched += 1
        return []

    def pg_document_detail(self, kb_id: str, doc_id: str) -> tuple:
        self.pg_touched += 1
        return None, 0

    def pg_ingest_document(self, **kw: Any) -> None:
        self.pg_touched += 1
        return None

    def get_document_meta(self, doc_id: str) -> None:
        return None


def test_json_backend_pg_plane_503(monkeypatch: Any) -> None:
    """json 后端负例（P3-7-3，进程内）：pg 权威面 5 端点 503、门控先行。

    app_server 是 env 固定的子进程，无法在线切 backend；按审查门允许
    的 monkeypatch/env 方案直调路由函数验证门控语义。三段断言：
    1. 真 service 在 json 后端下 pg_ready() is False（P1-1 backend 判定）；
    2. 注入桩后 5 个 pg 权威面端点全部 503 且桩的 pg 取数零调用
       （门控先于数据访问）；
    3. chunks 三态门面不被误伤：json 下 404 而非 503。
    """
    from types import SimpleNamespace

    from fastapi import HTTPException
    from fastapi import UploadFile as FastUploadFile
    from qwenpaw.app.kb.models import SCOPE_PERSONAL, KnowledgeBase
    from qwenpaw.app.kb.service import get_kb_service as real_get_service
    from qwenpaw.app.routers import kb as kb_router
    from qwenpaw.app.routers.admin import kb as admin_kb_router
    from qwenpaw.db import write_gateway

    monkeypatch.setenv("QWENPAW_STORAGE_BACKEND", "json")
    write_gateway.reset_backend_cache()
    try:
        # 1. P1-1 核心语义：json 后端下 pg 权威面不就绪
        assert real_get_service().pg_ready() is False

        stub_kb = KnowledgeBase(
            id="kb_stub",
            name="stub",
            scope=SCOPE_PERSONAL,
            owner_id="local",
        )
        stub = _StubKbService(stub_kb)
        request = SimpleNamespace(state=SimpleNamespace(user="local"))
        monkeypatch.setattr(kb_router, "get_kb_service", lambda: stub)
        monkeypatch.setattr(admin_kb_router, "get_kb_service", lambda: stub)
        monkeypatch.setattr(kb_router, "_access_kwargs", lambda u: {})

        upload = FastUploadFile(file=io.BytesIO(_HTML), filename="guide.html")
        guarded = [
            lambda: kb_router.get_document_tree("kb_stub", request),
            lambda: kb_router.get_document_detail("kb_stub", "doc_x", request),
            lambda: kb_router.update_document(
                "kb_stub",
                "doc_x",
                kb_router.UpdateDocBody(content_md="x"),
                request,
            ),
            lambda: kb_router.upload_document("kb_stub", request, file=upload),
            lambda: admin_kb_router.search_test(
                admin_kb_router.SearchTestBody(query="x", kb_id="kb_stub")
            ),
        ]
        # 2. 五端点全部 503，且 pg 取数零调用（门控先行）
        for call in guarded:
            with pytest.raises(HTTPException) as exc_info:
                call()
            assert exc_info.value.status_code == 503
        assert stub.pg_touched == 0

        # 3. chunks 三态门面不误伤：json 下走 meta 判存 → 404
        with pytest.raises(HTTPException) as exc_info:
            kb_router.get_document_chunks("kb_stub", "doc_x", request)
        assert exc_info.value.status_code == 404
        assert stub.pg_touched == 0
    finally:
        # env 由 monkeypatch 还原，backend 缓存必须显式清
        write_gateway.reset_backend_cache()


class _NoPermRbac:
    """RBAC 桩：任何用户均无任何权限（kb:write 分支负例）。"""

    def user_has_permission(
        self,
        username: str,
        perm: str,
        flat_role: str = "",
    ) -> bool:
        return False


def test_kb_team_write_requires_permission(monkeypatch: Any) -> None:
    """team 库「可读不可写」负例（P3-N1，进程内）：delete/upload 403。

    _ensure_kb_manage 的 kb:write 分支依赖真实 RBAC 用户-权限数据，
    集成子进程内构造成本高；按 json 503 负例同款进程内直调模式，stub
    RBAC 返回无权限，验证 403 在归属校验/取数之前生效。
    """
    from types import SimpleNamespace

    from fastapi import HTTPException
    from fastapi import UploadFile as FastUploadFile
    from qwenpaw.app.kb.models import SCOPE_TEAM, KnowledgeBase
    from qwenpaw.app.rbac import deps as rbac_deps
    from qwenpaw.app.rbac import store as rbac_store_mod
    from qwenpaw.app.routers import kb as kb_router

    team_kb = KnowledgeBase(
        id="kb_team",
        name="team",
        scope=SCOPE_TEAM,
        team_id="team_x",
    )
    stub = _StubKbService(team_kb)  # get_kb/can_access：member1 可读
    request = SimpleNamespace(state=SimpleNamespace(user="member1"))
    monkeypatch.setattr(kb_router, "get_kb_service", lambda: stub)
    monkeypatch.setattr(kb_router, "_access_kwargs", lambda u: {})
    # _ensure_kb_manage 函数内 import：拦截模块属性即可
    monkeypatch.setattr(
        rbac_store_mod, "get_rbac_store", lambda: _NoPermRbac()
    )
    monkeypatch.setattr(rbac_deps, "_resolve_flat_role", lambda u: "")

    upload = FastUploadFile(file=io.BytesIO(_HTML), filename="g.html")
    # delete 端点是 async def：进程内直调需 asyncio.run 驱动
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(kb_router.delete_document("kb_team", "doc_x", request))
    assert exc_info.value.status_code == 403
    assert "kb:write" in str(exc_info.value.detail)
    with pytest.raises(HTTPException) as exc_info:
        kb_router.upload_document("kb_team", request, file=upload)
    assert exc_info.value.status_code == 403
    assert "kb:write" in str(exc_info.value.detail)
    assert stub.pg_touched == 0  # 权限拒绝在归属校验/取数之前
