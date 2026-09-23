# -*- coding: utf-8 -*-
"""Unit tests for ``_resolve_stats_scope``（agent-stats token 口径解析）。

覆盖四条分支：
- 认证关闭（无 viewer）→ ``("agent", None)``；
- RBAC 未强制 → ``("agent", None)``（与闸门直通一致，不收敛）；
- 管理授权者（admin / team_lead / grant / owner）→ claimed_scope，默认
  ``agent``，显式 ``mine`` 时带 viewer 收敛；
- 普通 employee（无管理授权）→ 强制 ``("mine", viewer)``，忽略 claimed。

@author qingfeng
"""
# pylint: disable=protected-access
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.app.routers.agent_stats import _resolve_stats_scope


def _request(user: str | None) -> SimpleNamespace:
    """构造仅带 ``state.user`` 的假 Request（解析器只读该属性）。"""
    return SimpleNamespace(state=SimpleNamespace(user=user))


@pytest.mark.asyncio
async def test_no_viewer_returns_agent_scope() -> None:
    """认证关闭：无 viewer，单用户部署按 agent 全量（scope 无意义）。"""
    scope, viewer = await _resolve_stats_scope(_request(None), "agent-a", None)
    assert (scope, viewer) == ("agent", None)


@pytest.mark.asyncio
async def test_rbac_disabled_returns_agent_scope() -> None:
    """有 viewer 但 RBAC 未强制：不收敛，保留全量口径，不触碰 grant 判定。"""
    with patch(
        "qwenpaw.app.routers.agent_stats.rbac_enforcement_enabled",
        return_value=False,
    ):
        scope, viewer = await _resolve_stats_scope(
            _request("alice"), "agent-a", "mine"
        )
    assert (scope, viewer) == ("agent", None)


@pytest.mark.asyncio
async def test_manager_can_choose_scope() -> None:
    """管理授权者：默认 agent 全量；显式 mine 时按本人 viewer 收敛。"""
    with (
        patch(
            "qwenpaw.app.routers.agent_stats.rbac_enforcement_enabled",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.routers.agent_stats.manage_allowed",
            new=AsyncMock(return_value=True),
        ),
    ):
        default_scope, default_viewer = await _resolve_stats_scope(
            _request("root"), "agent-a", None
        )
        mine_scope, mine_viewer = await _resolve_stats_scope(
            _request("root"), "agent-a", "mine"
        )
    assert (default_scope, default_viewer) == ("agent", None)
    assert (mine_scope, mine_viewer) == ("mine", "root")


@pytest.mark.asyncio
async def test_non_manager_forced_to_mine() -> None:
    """普通 employee（无管理授权）：强制个人口径，忽略 claimed_scope。"""
    with (
        patch(
            "qwenpaw.app.routers.agent_stats.rbac_enforcement_enabled",
            return_value=True,
        ),
        patch(
            "qwenpaw.app.routers.agent_stats.manage_allowed",
            new=AsyncMock(return_value=False),
        ),
    ):
        scope, viewer = await _resolve_stats_scope(
            _request("eve"), "agent-a", "agent"
        )
    assert (scope, viewer) == ("mine", "eve")
