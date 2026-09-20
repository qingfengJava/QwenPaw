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
    PRINCIPAL_AGENT,
    PRINCIPAL_TEAM,
    SCOPE_ENTERPRISE,
    SCOPE_ORG,
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
    """管理权判定所需的空间投影（grants 两形态归一后的七元组）。"""

    scope: str
    owner_id: str
    team_id: str
    grant_roles: Tuple[str, ...]
    grant_users: Tuple[str, ...]
    grant_teams: Tuple[str, ...]
    org_id: str = "default"


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

    def list_for_agent(
        self,
        agent_id: str,
        *,
        principal_type: str = "",
    ) -> List[KbBinding]:
        """该员工的绑定行（文件序；``principal_type`` 空串=全部）."""
        rows = [b for b in self._load().bindings if b.agent_id == agent_id]
        if principal_type:
            rows = [b for b in rows if b.principal_type == principal_type]
        return rows

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
        principal_type: str = PRINCIPAL_AGENT,
    ) -> bool:
        """插入一行；已存在时零写返回 ``False``（幂等判据）。"""
        if principal_type not in (PRINCIPAL_AGENT, PRINCIPAL_TEAM):
            raise ValueError(
                f"principal_type must be '{PRINCIPAL_AGENT}' or "
                f"'{PRINCIPAL_TEAM}', got {principal_type!r}",
            )
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
                    principal_type=principal_type,
                    granted_by=granted_by,
                    remark=remark,
                ),
            )
            self._save(data)
        return True

    def delete(self, agent_id: str, space_id: str) -> bool:
        """删除一行；不存在返回 ``False``。"""
        return self.delete_typed(agent_id, space_id)

    def delete_typed(
        self,
        agent_id: str,
        space_id: str,
        *,
        principal_type: str = PRINCIPAL_AGENT,
    ) -> bool:
        """删除指定主体类型的一行；不存在返回 ``False``。"""
        with self._lock:
            data = self._load()
            kept = [
                b
                for b in data.bindings
                if not (
                    b.agent_id == agent_id
                    and b.space_id == space_id
                    and b.principal_type == principal_type
                )
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
        org_id=getattr(kb, "org_id", "") or "default",
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
        org_id=getattr(space, "org_id", "") or "default",
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
    user_org: str = "",
) -> Optional[bool]:
    """Whether *username* may grant/revoke bindings on *space_id*.

    Returns ``None`` when the space does not exist（路由层映射 404），
    otherwise the manage verdict. 判定顺序与 ``service.can_access`` 一致：
    admin → grants（users/roles/teams）→ scope 语义。org 库的管理权
    对齐 enterprise 惯例 = 组织成员 + ``kb:write`` 权限（不另立规则）。
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
    if shape.scope == SCOPE_ORG:
        caller_org = user_org or "default"
        if caller_org != (shape.org_id or "default"):
            return False
        return _has_kb_write_perm(username, flat_role)
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
    principal_type: str = PRINCIPAL_AGENT,
) -> Optional[bool]:
    """Bind one principal to a space behind the manage gate.

    Returns ``None``（库不存在，404）/ ``False``（无管理权或写失败，
    403）/ ``True``（绑定关系成立，含幂等重放）。``principal_type``
    为 ``team`` 时 ``agent_id`` 参数存 ``team_{team_id}`` 运行态形态
    （调用方已转换；本函数只透传存储）。
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
            principal_type=principal_type,
        )
    # 已存在时 insert 返回 False，但绑定关系同样成立 → 一律 True
    get_json_binding_store().insert(
        agent_id,
        space_id,
        granted_by=granted_by,
        remark=remark,
        principal_type=principal_type,
    )
    return True


def team_principal_agent_id(team_id: str) -> str:
    """Team principal 的 ``agent_id`` 列存储形态（单一来源桥接）。"""
    from ..experts.models import expert_team_agent_id

    return expert_team_agent_id(team_id)


async def bind_principal(
    *,
    principal_type: str,
    principal_id: str,
    space_id: str,
    granted_by: str,
    remark: str = "",
    flat_role: str = "",
    user_roles: Optional[List[str]] = None,
    user_teams: Optional[List[str]] = None,
) -> Optional[bool]:
    """Bind one principal（``agent`` | ``team``）to a space（T6 入口）。

    ``principal_type='team'`` 时 ``principal_id`` 是 ``expert_teams.id``
    裸 id（非运行态形态），存储行自动转换 ``team_{team_id}``；管理权
    门与 agent 直绑同一 ``can_manage_space``（不另立规则）。
    """
    if principal_type not in (PRINCIPAL_AGENT, PRINCIPAL_TEAM):
        raise ValueError(
            f"principal_type must be '{PRINCIPAL_AGENT}' or "
            f"'{PRINCIPAL_TEAM}', got {principal_type!r}",
        )
    stored_id = (
        team_principal_agent_id(principal_id)
        if principal_type == PRINCIPAL_TEAM
        else principal_id
    )
    return await bind_agent_kb(
        agent_id=stored_id,
        space_id=space_id,
        granted_by=granted_by,
        remark=remark,
        flat_role=flat_role,
        user_roles=user_roles,
        user_teams=user_teams,
        principal_type=principal_type,
    )


async def unbind_agent_kb(
    agent_id: str,
    space_id: str,
    *,
    principal_type: str = PRINCIPAL_AGENT,
) -> bool:
    """Remove one binding; ``False`` when it did not exist.

    仅删除该主体类型的行（supervisor 直绑行与团队行在
    ``team_{tid}`` 同形 id 上共存时互不误伤）。
    """
    if _use_pg():
        return await _pg_store().delete_binding_typed(
            agent_id,
            space_id,
            principal_type=principal_type,
        )
    return get_json_binding_store().delete_typed(
        agent_id,
        space_id,
        principal_type=principal_type,
    )


async def list_bound_space_ids(agent_id: str) -> List[str]:
    """All space ids reachable by one agent（S0 收敛输入，T6 团队扩展）。

    = agent 直绑行（``principal_type='agent'``）∪ 所在团队绑行：

    - supervisor 归属：运行态 id ``team_{tid}`` 命中该团队自己的绑行；
    - 成员归属：expert 成员（``expert_{eid}``）经专家团成员表反查归属
      团队，取各团队 supervisor 形态的绑行。

    团队解析结果进程内 60s TTL 缓存（成员/发布变更由
    :func:`invalidate_principal_cache` 或自然过期收敛）；专家团存储
    不可用（json 部署 / enterprise engine 未就绪）时 fail-soft 只取
    直绑，绝不阻断检索主链。
    """
    agent_rows = await _list_rows(
        agent_id,
        principal_type=PRINCIPAL_AGENT,
    )
    space_ids = {row.space_id for row in agent_rows}
    team_agent_ids = await _team_agent_ids_for_agent(agent_id)
    for stored_id in team_agent_ids:
        if stored_id == agent_id:
            # supervisor 自己：其团队行已在下方按 team 形态读取
            continue
        team_rows = await _list_rows(
            stored_id,
            principal_type=PRINCIPAL_TEAM,
        )
        space_ids.update(row.space_id for row in team_rows)
    if team_agent_ids:
        team_rows = await _list_rows(
            agent_id,
            principal_type=PRINCIPAL_TEAM,
        )
        space_ids.update(row.space_id for row in team_rows)
    return sorted(space_ids)


#: 团队归属解析 TTL（秒）：成员/发布变更走显式失效或自然过期。
_TEAM_TTL_SECONDS = 60

_team_cache: Dict[str, Tuple[float, Tuple[str, ...]]] = {}
_team_cache_lock = threading.Lock()


def invalidate_principal_cache(agent_id: str = "") -> None:
    """团队归属缓存失效（团队发布/成员变更时由管理端点调用）。

    ``agent_id`` 空串 = 全量失效（成员表变更影响面跨团队，全清更安全）。
    """
    with _team_cache_lock:
        if agent_id:
            _team_cache.pop(agent_id, None)
        else:
            _team_cache.clear()


async def _team_agent_ids_for_agent(agent_id: str) -> Tuple[str, ...]:
    """Resolve the team-principal ids one agent belongs to（TTL 缓存）。

    两条归属路径（与 ``expert_team_agent_id`` 惯例对齐）：

    1. supervisor 归属：``agent_id == team_{tid}`` 反解析出该团队；
    2. 成员归属：专家 ``expert_{eid}`` 剥前缀得 ``expert_id``，在
       ``expert_team_members``（``ExpertStore.list_teams`` 一次批量
       带成员）中命中即归属该团队。

    任何异常（json 部署无专家团 / engine 未就绪 / 网络抖动）fail-soft
    返空元组——团队绑行缺席只收敛可见域，不抛错阻断检索。
    """
    now = time.monotonic()
    with _team_cache_lock:
        cached = _team_cache.get(agent_id)
        if cached is not None and now - cached[0] < _TEAM_TTL_SECONDS:
            return cached[1]
    resolved = await _resolve_team_agent_ids(agent_id)
    with _team_cache_lock:
        _team_cache[agent_id] = (now, resolved)
    return resolved


async def _resolve_team_agent_ids(agent_id: str) -> Tuple[str, ...]:
    """Uncached team resolution（supervisor 归属 + 成员归属反查）。"""
    # supervisor 归属：运行态形态 team_{tid} 直接反解析
    team_ids: set = set()
    if agent_id.startswith("team_") and len(agent_id) > len("team_"):
        team_ids.add(agent_id[len("team_"):])
    # 成员归属：expert_{eid} 剥前缀后查专家团成员表
    expert_id = ""
    if agent_id.startswith("expert_") and len(agent_id) > len("expert_"):
        expert_id = agent_id[len("expert_"):]
    if not expert_id:
        return tuple(f"team_{tid}" for tid in sorted(team_ids))
    try:
        from ..experts.store import get_expert_store

        teams = await get_expert_store().list_teams()
    except Exception as exc:  # noqa: BLE001 - fail-soft 见函数 docstring
        logger.debug("kb binding team resolve unavailable: %s", exc)
        return tuple(f"team_{tid}" for tid in sorted(team_ids))
    for team in teams:
        if any(member.expert_id == expert_id for member in team.members):
            team_ids.add(team.id)
    return tuple(f"team_{tid}" for tid in sorted(team_ids))


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
                "principal_type": row.principal_type,
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


async def _list_rows(
    agent_id: str,
    *,
    principal_type: str = "",
) -> List[KbBinding]:
    """绑定行读取的三态分流（json manifest / pg 表）。"""
    if _use_pg():
        return await _pg_store().list_agent_bindings(
            agent_id,
            principal_type=principal_type,
        )
    return get_json_binding_store().list_for_agent(
        agent_id,
        principal_type=principal_type,
    )


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
