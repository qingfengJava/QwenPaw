# -*- coding: utf-8 -*-
"""Agent↔知识库绑定授权（T7，「绑定即授权」spec 决策点 1）。

绑定行的存在即表示该数字员工可在检索时收敛到该库（S0 ACL 交集来源，
Task 9/10 消费）。存储三态：

- ``json``：个人部署唯一存储为 ``SECRET_DIR/kb_bindings.json`` manifest；
- ``dual``/``pg``：``agent_kb_bindings`` 表**同步读写**，不走
  ``submit_shadow_write`` 影子写——授权是交互式强一致数据（PUT 后立即
  GET 必须可见），且 json 平面没有绑定消费点，影子双写只会造出双源
  不一致。json→pg 切换的存量迁移归 Task 8 迁移脚本。

管理权 :func:`can_manage_space` 与读 ACL ``service.can_access`` 同构：
admin 与显式 grants 前置，scope 语义 personal=owner 本人 / team=成员或
grants 命中 / enterprise=``kb:write`` 权限（与员工面非个人库写权限
同一判定，不另立规则）。

@author qingfeng
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from typing_extensions import NamedTuple

from ...constant import SECRET_DIR
from ...db import write_gateway
from .models import (
    SCOPE_ENTERPRISE,
    SCOPE_PERSONAL,
    SCOPE_TEAM,
    KbBinding,
)

logger = logging.getLogger(__name__)

#: json 态 manifest 路径（与 kb_registry.json 同目录同权限惯例）
DEFAULT_MANIFEST_PATH = SECRET_DIR / "kb_bindings.json"

_json_store: Optional["JsonBindingStore"] = None
_json_store_lock = threading.Lock()


def _chmod_best_effort(path: Path, mode: int) -> None:
    """尽力收紧权限（Windows 无 POSIX mode 时静默跳过），对齐 registry。"""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


class SpaceShape(NamedTuple):
    """管理权判定所需的空间投影（grants 两形态归一后的六元组）。"""

    scope: str
    owner_id: str
    team_id: str
    grant_roles: Tuple[str, ...]
    grant_users: Tuple[str, ...]
    grant_teams: Tuple[str, ...]


class _BindingManifest(BaseModel):
    """``kb_bindings.json`` 根文档（行数组 + 版本号）。"""

    version: int = 1
    bindings: List[KbBinding] = Field(default_factory=list)


class JsonBindingStore:
    """``kb_bindings.json`` manifest 存取（0600 + 线程锁 + 整文件覆盖）。

    绑定行量级极小（员工数 × 库数量），整文件读写足够；写路径与
    ``kb_registry.json`` 同惯例（0700 目录 / 0600 文件）。
    """

    def __init__(self, path: Path | str = DEFAULT_MANIFEST_PATH) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> _BindingManifest:
        if not self._path.is_file():
            return _BindingManifest()
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                return _BindingManifest.model_validate(json.load(fh))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.error("Failed to load kb bindings %s: %s", self._path, exc)
            # 损坏现场改名保留再返回空：授权行是仅有的授权凭据，静默归零
            # 会让下一次任意写入把残留行永久覆盖
            self._preserve_corrupt()
            return _BindingManifest()

    def _preserve_corrupt(self) -> None:
        """把损坏 manifest 改名保留现场（``.corrupt.<ts>-<rand>``）。

        后缀带随机位：同秒内二次损坏不会因目标已存在触发 ``FileExistsError``
        被静默吞掉、退化成「原地滞留 + 下次写覆盖销毁现场」（P1-A）；
        极端碰撞则有界重试，跨设备/权限等硬错误放弃（不阻断读空）。
        """
        stem, suffix = self._path.stem, self._path.suffix
        for _attempt in range(8):
            target = self._path.with_name(
                f"{stem}.corrupt.{int(time.time())}"
                f"-{secrets.token_hex(4)}{suffix}",
            )
            try:
                self._path.rename(target)
                return
            except FileExistsError:
                continue
            except OSError:
                return

    def _save(self, data: _BindingManifest) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 授权凭据文件：父目录收紧 0700（对齐 kb_registry.json 惯例，
        # brief R2）。write_json_atomic 只保证「新文件」0600、不收紧已存在
        # 文件的历史 mode，也不管父目录，故写前收父目录、写后强制收文件
        _chmod_best_effort(self._path.parent, 0o700)
        # 原子写（临时文件 + 原子替换）：写中崩溃不产生半截 JSON，授权
        # 数据不允许「截断覆盖后丢失」的窗口
        from ...utils.io_utils import write_json_atomic

        write_json_atomic(
            self._path,
            data.model_dump(mode="json"),
            indent=2,
        )
        _chmod_best_effort(self._path, 0o600)

    def list_for_agent(self, agent_id: str) -> List[KbBinding]:
        """该员工的全部绑定行（文件序）。"""
        return [b for b in self._load().bindings if b.agent_id == agent_id]

    def list_all(self) -> List[KbBinding]:
        """全部绑定行（空间维维护用）。"""
        return list(self._load().bindings)

    def insert(
        self,
        agent_id: str,
        space_id: str,
        *,
        granted_by: str = "",
        remark: str = "",
    ) -> bool:
        """插入一行；已存在时零写返回 ``False``（幂等判据）。"""
        with self._lock:
            data = self._load()
            for binding in data.bindings:
                if (
                    binding.agent_id == agent_id
                    and binding.space_id == space_id
                ):
                    return False
            data.bindings.append(
                KbBinding(
                    agent_id=agent_id,
                    space_id=space_id,
                    granted_by=granted_by,
                    remark=remark,
                ),
            )
            self._save(data)
        return True

    def delete(self, agent_id: str, space_id: str) -> bool:
        """删除一行；不存在返回 ``False``。"""
        with self._lock:
            data = self._load()
            kept = [
                b
                for b in data.bindings
                if not (b.agent_id == agent_id and b.space_id == space_id)
            ]
            if len(kept) == len(data.bindings):
                return False
            data.bindings = kept
            self._save(data)
        return True

    def delete_space(self, space_id: str) -> int:
        """删库回收该库全部绑定行，返回回收条数。"""
        with self._lock:
            data = self._load()
            kept = [b for b in data.bindings if b.space_id != space_id]
            removed = len(data.bindings) - len(kept)
            if removed:
                data.bindings = kept
                self._save(data)
        return removed


def get_json_binding_store() -> JsonBindingStore:
    """json manifest 单例（路径取 :data:`DEFAULT_MANIFEST_PATH`）。"""
    global _json_store  # pylint: disable=global-statement
    if _json_store is None:
        with _json_store_lock:
            if _json_store is None:
                _json_store = JsonBindingStore(DEFAULT_MANIFEST_PATH)
    return _json_store


def reset_json_store_for_tests() -> None:
    """Drop the cached manifest singleton（测试换 tmp 路径后必须调用）."""
    global _json_store  # pylint: disable=global-statement
    with _json_store_lock:
        _json_store = None


def _use_pg() -> bool:
    """绑定落 PG 面的判定（统一收敛写网关，不自行读环境变量）。"""
    return write_gateway.resolve_storage_backend() in ("dual", "pg")


def _pg_store() -> Any:
    """pg 面共享 store（``_use_pg`` 为真时必然可取）。"""
    from .pg_store import get_kb_pg_store

    store = get_kb_pg_store()
    if store is None:
        raise RuntimeError("kb binding: pg backend selected but store is None")
    return store


def _shape_from_json(space_id: str) -> Optional[SpaceShape]:
    """从文件 registry 读空间投影（json 态 / dual 下 PG 未同步的回退）。"""
    from .service import get_kb_service

    kb = get_kb_service().get_kb(space_id)
    if kb is None:
        return None
    return SpaceShape(
        scope=kb.scope,
        owner_id=kb.owner_id,
        team_id=kb.team_id,
        grant_roles=tuple(kb.grants_roles),
        grant_users=tuple(kb.grants_users),
        grant_teams=tuple(kb.grants_teams),
    )


def _shape_from_space_model(space: Any) -> SpaceShape:
    """把 PG 面 ``KbSpace.grants`` dict 归一成六元组。"""
    grants = space.grants or {}
    return SpaceShape(
        scope=space.scope,
        owner_id=space.owner_id,
        team_id=space.team_id,
        grant_roles=tuple(grants.get("roles") or []),
        grant_users=tuple(grants.get("users") or []),
        grant_teams=tuple(grants.get("teams") or []),
    )


async def _load_space_shape(space_id: str) -> Optional[SpaceShape]:
    """空间投影读取：pg 先行，dual 回退文件，json 仅文件。"""
    backend = write_gateway.resolve_storage_backend()
    if backend in ("dual", "pg"):
        store = _pg_store()
        space = await store.get_space(space_id)
        if space is not None:
            return _shape_from_space_model(space)
        if backend == "dual":
            # dual 下文件仍为 primary：PG 未同步到的新库以文件为准
            return _shape_from_json(space_id)
        return None
    return _shape_from_json(space_id)


def _has_kb_write_perm(username: str, flat_role: str) -> bool:
    """enterprise 库的管理权 = ``kb:write`` 权限（对齐员工面写惯例）。"""
    from ..rbac.deps import _resolve_flat_role
    from ..rbac.models import PERM_KB_WRITE
    from ..rbac.store import get_rbac_store

    role = flat_role or (_resolve_flat_role(username) if username else "")
    return get_rbac_store().user_has_permission(
        username,
        PERM_KB_WRITE,
        flat_role=role,
    )


async def can_manage_space(
    space_id: str,
    username: str,
    *,
    flat_role: str = "",
    user_roles: Optional[List[str]] = None,
    user_teams: Optional[List[str]] = None,
) -> Optional[bool]:
    """Whether *username* may grant/revoke bindings on *space_id*.

    Returns ``None`` when the space does not exist（路由层映射 404），
    otherwise the manage verdict. 判定顺序与 ``service.can_access`` 一致：
    admin → grants（users/roles/teams）→ scope 语义。
    """
    shape = await _load_space_shape(space_id)
    if shape is None:
        return None
    if flat_role == "admin":
        return True
    if username and username in shape.grant_users:
        return True
    roles = user_roles or []
    if any(role in shape.grant_roles for role in roles):
        return True
    teams = user_teams or []
    if any(team in shape.grant_teams for team in teams):
        return True
    if shape.scope == SCOPE_PERSONAL:
        return bool(username) and username == shape.owner_id
    if shape.scope == SCOPE_TEAM:
        return bool(shape.team_id) and shape.team_id in teams
    if shape.scope == SCOPE_ENTERPRISE:
        return _has_kb_write_perm(username, flat_role)
    return False


async def bind_agent_kb(
    *,
    agent_id: str,
    space_id: str,
    granted_by: str,
    remark: str = "",
    flat_role: str = "",
    user_roles: Optional[List[str]] = None,
    user_teams: Optional[List[str]] = None,
) -> Optional[bool]:
    """Bind one agent to a space behind the manage gate.

    Returns ``None``（库不存在，404）/ ``False``（无管理权或写失败，
    403）/ ``True``（绑定关系成立，含幂等重放）。
    """
    allowed = await can_manage_space(
        space_id,
        granted_by,
        flat_role=flat_role,
        user_roles=user_roles,
        user_teams=user_teams,
    )
    if allowed is None:
        return None
    if not allowed:
        return False
    if _use_pg():
        return await _pg_store().insert_binding(
            agent_id,
            space_id,
            granted_by=granted_by,
            remark=remark,
        )
    # 已存在时 insert 返回 False，但绑定关系同样成立 → 一律 True
    get_json_binding_store().insert(
        agent_id,
        space_id,
        granted_by=granted_by,
        remark=remark,
    )
    return True


async def unbind_agent_kb(agent_id: str, space_id: str) -> bool:
    """Remove one binding; ``False`` when it did not exist."""
    if _use_pg():
        return await _pg_store().delete_binding(agent_id, space_id)
    return get_json_binding_store().delete(agent_id, space_id)


async def list_bound_space_ids(agent_id: str) -> List[str]:
    """All space ids bound to one agent（Task 9 目录注入的收敛输入）。"""
    rows = await _list_rows(agent_id)
    return [row.space_id for row in rows]


async def list_bindings(agent_id: str) -> List[Dict[str, Any]]:
    """Binding rows enriched with space name/scope（GET 端点组装）。

    名称/scope 经**一次**批量取全部空间后内存组装（禁逐行查询）；
    孤绑定（库已删）照列且名称/scope 置空，便于前端提示解绑。
    """
    rows = await _list_rows(agent_id)
    summaries = await _space_summaries()
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        name, scope = summaries.get(row.space_id, ("", ""))
        enriched.append(
            {
                "agent_id": row.agent_id,
                "space_id": row.space_id,
                "space_name": name,
                "scope": scope,
                "granted_by": row.granted_by,
                "remark": row.remark,
                "created_at": row.created_at.isoformat(),
            },
        )
    return enriched


async def delete_space_bindings(space_id: str) -> int:
    """json manifest 侧的删库回收（pg 态由 ``delete_space`` 同事务回收）。"""
    if _use_pg():
        return 0
    return get_json_binding_store().delete_space(space_id)


async def _list_rows(agent_id: str) -> List[KbBinding]:
    """绑定行读取的三态分流（json manifest / pg 表）。"""
    if _use_pg():
        return await _pg_store().list_agent_bindings(agent_id)
    return get_json_binding_store().list_for_agent(agent_id)


async def _space_summaries() -> Dict[str, Tuple[str, str]]:
    """一次性取全部空间的 ``(id → (name, scope))`` 内存索引。"""
    summaries: Dict[str, Tuple[str, str]] = {}
    if _use_pg():
        for space in await _pg_store().list_spaces():
            summaries[space.id] = (space.name, space.scope)
        return summaries
    from .service import get_kb_service

    for kb in get_kb_service().list_kbs():
        summaries[kb.id] = (kb.name, kb.scope)
    return summaries
