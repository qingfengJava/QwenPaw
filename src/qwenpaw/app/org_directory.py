# -*- coding: utf-8 -*-
"""Organization directory abstraction (组织架构数据源抽象层).

本期（M3）只有本地数据源；未来接入飞书通讯录时按以下方式扩展：

1. 新建 ``FeishuDirectoryProvider(OrgDirectoryProvider)``：通过飞书
   开放平台通讯录 API 拉取部门/成员（app_token + periodic sync），
   将结果**同步落地**到本地权威存储（``qwenpaw_users.org_id`` /
   ``department_members`` 表）——运行期鉴权始终读本地，外部通讯录
   只作为同步源，避免每次请求外呼；
2. 通过环境变量 ``QWENPAW_ORG_DIRECTORY_PROVIDER=feishu`` 切换工厂
   返回值，调用方零改动。

@author qingfeng
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Protocol

logger = logging.getLogger(__name__)

# 工厂选择键（当前仅支持 local；feishu 为预留扩展位）。
_PROVIDER_ENV = "QWENPAW_ORG_DIRECTORY_PROVIDER"

_PROVIDER_LOCAL = "local"


class OrgMemberView(Protocol):
    """One directory member（成员视图；由具体 provider 定义承载类型）."""


class OrgDirectoryProvider(Protocol):
    """组织架构数据源契约（local / feishu / 未来 LDAP 等）.

    所有方法只读；目录写入（同步/手动管理）由 provider 自行负责。
    """

    #: 数据源标识（"local" / "feishu"），诊断与 UI 标注用。
    source: str

    def resolve_org_for_user(self, username: str) -> str:
        """Return the org id an account belongs to（未知用户返回 default）."""
        ...

    def list_orgs(self) -> List[dict]:
        """List organizations known to this directory."""
        ...

    def list_members(self, org_id: str) -> List[dict]:
        """List accounts within one organization."""
        ...


class LocalDirectoryProvider:
    """本地目录：以账号存储（org_id 字段）为权威数据源."""

    source = _PROVIDER_LOCAL

    def resolve_org_for_user(self, username: str) -> str:
        """Read the account's org from the user store (both backends)."""
        from .users.store import get_user_store

        return get_user_store().org_id_for_user(username)

    def list_orgs(self) -> List[dict]:
        """Distinct org ids across accounts（本地无独立组织表时的投影）."""
        from .users.store import get_user_store

        orgs: dict[str, None] = {}
        for user in get_user_store().list_users():
            orgs.setdefault(user.org_id, None)
        return [{"org_id": org_id} for org_id in orgs]

    def list_members(self, org_id: str) -> List[dict]:
        """List accounts within one organization（display-safe fields）."""
        from .users.store import get_user_store

        return [
            {
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
            }
            for user in get_user_store().list_users()
            if user.org_id == org_id
        ]


def get_org_directory() -> OrgDirectoryProvider:
    """Factory: pick the directory provider from the provider env var.

    未知取值一律回落 local 并告警——目录数据源故障不允许阻塞鉴权主链路
    （AuthMiddleware 的 org 解析走 user store，不依赖本工厂）。
    """
    chosen = os.environ.get(_PROVIDER_ENV, "").strip().lower()
    if not chosen or chosen == _PROVIDER_LOCAL:
        return LocalDirectoryProvider()
    # 预留：feishu provider 落地后在此注册分支；当前回落 local。
    logger.warning(
        "Unknown org directory provider %r; falling back to local",
        chosen,
    )
    return LocalDirectoryProvider()


def current_directory_source() -> str:
    """Effective provider id（doctor/UI 诊断展示用）."""
    provider: Optional[OrgDirectoryProvider] = get_org_directory()
    return provider.source


__all__ = [
    "LocalDirectoryProvider",
    "OrgDirectoryProvider",
    "current_directory_source",
    "get_org_directory",
]
