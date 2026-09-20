# -*- coding: utf-8 -*-
"""M6-7: 绑定授权单测——管理权矩阵 / 幂等 / 三态 / manifest 持久化。

默认在 json 后端下运行（个人部署默认态），manifest 落 tmp_path；
pg/dual 分支由用例显式改写后端并用 FakeStore 断言委托，不连真库。
真库与 HTTP 往返由 ``tests/integration/test_kb_bindings_api.py`` 门控覆盖。

@author qingfeng
"""

# pylint: disable=protected-access
from __future__ import annotations

from typing import Any, List, Optional

import pytest

from qwenpaw.app.kb import bindings
from qwenpaw.app.kb.models import KbBinding, KbSpace

pytestmark = pytest.mark.unit

_STAMP = "2026-09-18T00:00:00+00:00"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _json_backend(monkeypatch: pytest.MonkeyPatch) -> Any:
    """默认 json 后端 + 每例重置 json manifest 单例（测试卫生）。"""
    monkeypatch.setattr(
        bindings.write_gateway,
        "resolve_storage_backend",
        lambda: "json",
    )
    bindings.reset_json_store_for_tests()
    yield
    bindings.reset_json_store_for_tests()


@pytest.fixture()
def manifest_path(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """把 json manifest 指到临时目录，返回文件路径。"""
    path = tmp_path / "kb_bindings.json"
    monkeypatch.setattr(
        bindings,
        "DEFAULT_MANIFEST_PATH",
        path,
    )
    return path


def _shape(
    scope: str = "personal",
    owner_id: str = "alice",
    team_id: str = "",
    roles: tuple = (),
    users: tuple = (),
    teams: tuple = (),
) -> Any:
    """构造一条空间形态（can_manage_space 的判定输入）。"""
    return bindings.SpaceShape(
        scope=scope,
        owner_id=owner_id,
        team_id=team_id,
        grant_roles=roles,
        grant_users=users,
        grant_teams=teams,
    )


def _patch_shape(
    monkeypatch: pytest.MonkeyPatch,
    shape: Optional[Any],
) -> None:
    """把空间读取打桩为固定返回值（None = 库不存在）。"""

    async def _load(space_id: str) -> Optional[Any]:
        del space_id
        return shape

    monkeypatch.setattr(bindings, "_load_space_shape", _load)


class _FakePgStore:
    """pg 态委托断言桩：记录调用并回放固定结果。"""

    def __init__(
        self,
        *,
        rows: Optional[List[KbBinding]] = None,
        exists: bool = False,
    ) -> None:
        self.insert_calls: List[dict] = []
        self.deleted: List[str] = []
        self._rows = rows or []
        self._exists = exists

    async def get_space(self, space_id: str) -> KbSpace:
        # 管理权判定的空间来源桩：personal + owner=alice（ granted_by 即 owner）
        del space_id
        return KbSpace(
            id="kb_a",
            name="n",
            scope="personal",
            owner_id="alice",
        )

    async def insert_binding(
        self,
        agent_id: str,
        space_id: str,
        *,
        granted_by: str = "",
        remark: str = "",
        principal_type: str = "agent",
    ) -> bool:
        # True = 绑定关系成立（新插入或已存在幂等），False = 平面不可用
        self.insert_calls.append(
            {
                "agent_id": agent_id,
                "space_id": space_id,
                "granted_by": granted_by,
                "remark": remark,
                "principal_type": principal_type,
            },
        )
        return True

    async def delete_binding_typed(
        self,
        agent_id: str,
        space_id: str,
        *,
        principal_type: str = "agent",
    ) -> bool:
        self.deleted.append((agent_id, space_id))
        return not self._exists

    async def list_agent_bindings(
        self,
        agent_id: str,
        *,
        principal_type: str = "",
    ) -> List[KbBinding]:
        del agent_id, principal_type
        return list(self._rows)


# ---------------------------------------------------------------------------
# can_manage_space 管理权矩阵
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "scope",
        "owner_id",
        "team_id",
        "grants",
        "username",
        "flat_role",
        "user_roles",
        "user_teams",
        "expected",
    ),
    [
        # admin 对任何 scope 全量可管理
        ("personal", "alice", "", (), "bob", "admin", (), (), True),
        # personal：仅 owner 本人
        ("personal", "alice", "", (), "alice", "", (), (), True),
        ("personal", "alice", "", (), "bob", "", (), (), False),
        # team：成员或显式 grants（users/roles/teams）命中
        ("team", "", "t1", (), "bob", "", (), ("t1",), True),
        ("team", "", "t1", (("users", "bob"),), "bob", "", (), (), True),
        (
            "team",
            "",
            "t1",
            (("roles", "kb_admin"),),
            "carol",
            "",
            ("kb_admin",),
            (),
            True,
        ),
        ("team", "", "t1", (), "bob", "", (), (), False),
        # enterprise：对齐 kb.py 非个人库写权限（kb:write）
        ("enterprise", "", "", (), "bob", "", (), (), "perm"),
        ("enterprise", "", "", (), "bob", "", (), (), False),
        # 显式 grants 对 personal 同样生效（与 can_access 顺序一致）
        (
            "personal",
            "alice",
            "",
            (("users", "bob"),),
            "bob",
            "",
            (),
            (),
            True,
        ),
    ],
)
async def test_manage_space_matrix(
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    owner_id: str,
    team_id: str,
    grants: tuple,
    username: str,
    flat_role: str,
    user_roles: tuple,
    user_teams: tuple,
    expected: Any,
) -> None:
    """管理权判定矩阵：admin/owner/成员/grants/enterprise 写权限。"""
    shape = _shape(
        scope=scope,
        owner_id=owner_id,
        team_id=team_id,
        roles=tuple(v for kind, v in grants if kind == "roles"),
        users=tuple(v for kind, v in grants if kind == "users"),
        teams=tuple(v for kind, v in grants if kind == "teams"),
    )
    _patch_shape(monkeypatch, shape)
    monkeypatch.setattr(
        bindings,
        "_has_kb_write_perm",
        lambda _username, _flat_role: expected == "perm",
    )
    allowed = await bindings.can_manage_space(
        "kb_a",
        username,
        flat_role=flat_role,
        user_roles=list(user_roles),
        user_teams=list(user_teams),
    )
    assert allowed is True if expected == "perm" else allowed is expected


async def test_manage_missing_space_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """库不存在返回 None 哨兵（路由层区分 404 与 403）。"""
    _patch_shape(monkeypatch, None)
    assert await bindings.can_manage_space("kb_x", "alice") is None


# ---------------------------------------------------------------------------
# bind / unbind（json 态）
# ---------------------------------------------------------------------------


async def test_bind_without_right_false_and_not_persisted(
    monkeypatch: pytest.MonkeyPatch,
    manifest_path: Any,
) -> None:
    """无管理权绑定 → False，且 manifest 不落任何行。"""
    _patch_shape(monkeypatch, _shape(owner_id="alice"))
    ok = await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="bob",
    )
    assert ok is False
    assert not manifest_path.exists()


async def test_bind_ok_persists_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    manifest_path: Any,
) -> None:
    """owner 绑定成功落盘；重复绑定幂等成立且不产生重复行。"""
    _patch_shape(monkeypatch, _shape(owner_id="alice"))
    first = await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="alice",
        remark="孕产问答",
    )
    second = await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="alice",
    )
    assert first is True
    assert second is True
    rows = bindings.get_json_binding_store().list_for_agent("analyst")
    assert [r.space_id for r in rows] == ["kb_a"]
    assert rows[0].remark == "孕产问答"
    assert manifest_path.exists()


async def test_bind_missing_space_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """库不存在绑定 → None（路由层转 404）。"""
    _patch_shape(monkeypatch, None)
    assert (
        await bindings.bind_agent_kb(
            agent_id="analyst",
            space_id="kb_x",
            granted_by="alice",
        )
        is None
    )


async def test_unbind_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    manifest_path: Any,
) -> None:
    """解绑存在行 True；再次解绑 False。"""
    _patch_shape(monkeypatch, _shape(owner_id="alice"))
    await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="alice",
    )
    assert await bindings.unbind_agent_kb("analyst", "kb_a") is True
    assert await bindings.unbind_agent_kb("analyst", "kb_a") is False


async def test_list_bound_space_ids_persist_across_instances(
    monkeypatch: pytest.MonkeyPatch,
    manifest_path: Any,
) -> None:
    """绑定清单跨实例（新进程语义）读回一致，且按 agent 过滤。"""
    _patch_shape(monkeypatch, _shape(owner_id="alice"))
    await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="alice",
    )
    await bindings.bind_agent_kb(
        agent_id="writer",
        space_id="kb_a",
        granted_by="alice",
    )
    # 模拟重启：重置单例后重新读取（文件仍在中）
    bindings.reset_json_store_for_tests()
    assert await bindings.list_bound_space_ids("analyst") == ["kb_a"]
    assert await bindings.list_bound_space_ids("writer") == ["kb_a"]
    assert await bindings.list_bound_space_ids("nobody") == []


# ---------------------------------------------------------------------------
# list_bindings（GET 端点组装：名称/scope/孤绑定）
# ---------------------------------------------------------------------------


async def test_list_bindings_shapes_with_orphan(
    monkeypatch: pytest.MonkeyPatch,
    manifest_path: Any,
) -> None:
    """列表返回名称/scope；孤绑定（库已删）照列且名称为空。"""

    async def _load(space_id: str) -> Optional[Any]:
        # 绑定期两库都可管理；kb_b 的孤儿态由 _summaries 桩表达
        # （绑定后库被删的真实时序：行还在、空间索引查无）
        del space_id
        return _shape(owner_id="alice")

    async def _summaries() -> dict:
        # 空间名称批量索引桩：只含 kb_a → kb_b 呈孤儿形态
        return {"kb_a": ("孕产知识库", "personal")}

    monkeypatch.setattr(bindings, "_load_space_shape", _load)
    monkeypatch.setattr(bindings, "_space_summaries", _summaries)
    await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="alice",
    )
    await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_b",
        granted_by="alice",
    )
    listed = await bindings.list_bindings("analyst")
    by_space = {row["space_id"]: row for row in listed}
    assert by_space["kb_a"]["space_name"] == "孕产知识库"
    assert by_space["kb_a"]["scope"] == "personal"
    assert by_space["kb_b"]["space_name"] == ""
    assert by_space["kb_b"]["scope"] == ""
    assert by_space["kb_a"]["granted_by"] == "alice"


# ---------------------------------------------------------------------------
# json manifest 维护
# ---------------------------------------------------------------------------


async def test_delete_space_bindings_json(
    monkeypatch: pytest.MonkeyPatch,
    manifest_path: Any,
) -> None:
    """删库回收该库全部绑定行（json 态），返回回收条数。"""
    _patch_shape(monkeypatch, _shape(owner_id="alice"))
    await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="alice",
    )
    await bindings.bind_agent_kb(
        agent_id="writer",
        space_id="kb_a",
        granted_by="alice",
    )
    removed = await bindings.delete_space_bindings("kb_a")
    assert removed == 2
    assert await bindings.list_bound_space_ids("analyst") == []


async def test_manifest_corruption_preserved(
    manifest_path: Any,
) -> None:
    """manifest 损坏：现场改名保留 + 返回空，写入不再静默覆盖残留。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{ half-written json", encoding="utf-8")

    store = bindings.JsonBindingStore(manifest_path)
    assert store.list_for_agent("analyst") == []

    # 原文件已改名保留，且新写入从空 manifest 起步，不吞残留
    corrupt = list(manifest_path.parent.glob("*.corrupt.*.json"))
    assert len(corrupt) == 1
    assert "half-written" in corrupt[0].read_text(encoding="utf-8")
    store.insert("analyst", "kb_a", granted_by="alice")
    rows = store.list_for_agent("analyst")
    assert [r.space_id for r in rows] == ["kb_a"]


async def test_save_uses_atomic_write(
    monkeypatch: pytest.MonkeyPatch,
    manifest_path: Any,
) -> None:
    """_save 必须走原子写（防回归成 open+json.dump 的半截 JSON）。"""
    from qwenpaw.utils import io_utils

    calls: List[str] = []
    real_atomic = io_utils.write_json_atomic

    def _spy(path: Any, payload: Any, **kwargs: Any) -> None:
        # 记录调用并委派真实实现（变异回直写时 calls 为空 → 本例变红）
        calls.append(str(path))
        real_atomic(path, payload, **kwargs)

    monkeypatch.setattr(io_utils, "write_json_atomic", _spy)
    _patch_shape(monkeypatch, _shape(owner_id="alice"))
    await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="alice",
    )
    assert calls == [str(manifest_path)]
    assert manifest_path.exists()


def test_manifest_corruption_same_second_preserved_twice(
    manifest_path: Any,
) -> None:
    """同秒内二次损坏：两份现场都保留（随机位后缀不碰撞、不退化）。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    store = bindings.JsonBindingStore(manifest_path)

    # 第一次损坏 → 改名保留
    manifest_path.write_text("{ bad json 1", encoding="utf-8")
    assert store.list_for_agent("analyst") == []
    # 紧接第二次损坏（同一秒内，时间戳部分相同）→ 随机位区分仍保留
    manifest_path.write_text("{ bad json 2", encoding="utf-8")
    assert store.list_for_agent("analyst") == []

    corrupt = list(manifest_path.parent.glob("*.corrupt.*.json"))
    # 两份现场都在（旧实现同秒会因 FileExistsError 被吞只剩一份 +
    # 原文件滞留，下次 _save 直接覆盖销毁现场）
    assert len(corrupt) == 2
    # 损坏文件已移走，不滞留原位
    assert not manifest_path.exists()


# ---------------------------------------------------------------------------
# pg/dual 态委托
# ---------------------------------------------------------------------------


async def test_pg_backend_routes_to_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg 后端：绑定三操作全部委托 pg store，不触碰 json manifest。"""
    monkeypatch.setattr(
        bindings.write_gateway,
        "resolve_storage_backend",
        lambda: "pg",
    )
    fake = _FakePgStore()
    monkeypatch.setattr(bindings, "_pg_store", lambda: fake)

    ok = await bindings.bind_agent_kb(
        agent_id="analyst",
        space_id="kb_a",
        granted_by="alice",
        remark="r",
    )
    assert ok is True
    assert fake.insert_calls == [
        {
            "agent_id": "analyst",
            "space_id": "kb_a",
            "granted_by": "alice",
            "remark": "r",
            "principal_type": "agent",
        },
    ]
    assert await bindings.unbind_agent_kb("analyst", "kb_a") is True
    assert fake.deleted == [("analyst", "kb_a")]


async def test_list_bound_space_ids_pg_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pg 后端 list_bound_space_ids 委托 store 行转 id 列表。"""
    monkeypatch.setattr(
        bindings.write_gateway,
        "resolve_storage_backend",
        lambda: "dual",
    )
    fake = _FakePgStore(
        rows=[
            KbBinding(
                agent_id="analyst",
                space_id="kb_a",
                granted_by="alice",
                created_at=_STAMP,
            ),
            KbBinding(
                agent_id="analyst",
                space_id="kb_b",
                granted_by="alice",
                created_at=_STAMP,
            ),
        ],
    )
    monkeypatch.setattr(bindings, "_pg_store", lambda: fake)
    assert await bindings.list_bound_space_ids("analyst") == [
        "kb_a",
        "kb_b",
    ]
