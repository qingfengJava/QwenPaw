# -*- coding: utf-8 -*-
"""Shared resource catalog for XianWork (skills / MCP connectors, read-only).

The console plane remains the authoritative editor; this exposes the
default agent workspace's skill list and MCP client registry so project
members can bind them to a project (see bindings router).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resources", tags=["xian-resources"])


async def _default_workspace(request: Request) -> Any:
    """The default agent workspace backing the shared resource catalog."""
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="Agent runtime not ready")
    return await manager.get_agent("default")


@router.get("/skills")
async def list_skills(request: Request) -> List[dict]:
    """Skills installed on the default workspace (name/description)."""
    from ..skills import _build_workspace_skill_specs

    workspace = await _default_workspace(request)
    specs = _build_workspace_skill_specs(Path(workspace.workspace_dir))
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "version": getattr(spec, "version", ""),
            "enabled": getattr(spec, "enabled", True),
        }
        for spec in specs
    ]


@router.get("/connectors")
async def list_connectors(request: Request) -> List[dict]:
    """Configured MCP connectors (console-managed registry, read-only)."""
    from ...mcp.config_service import MCPConfigService  # console-plane svc
    from ...mcp.schemas import MCPClientInfo

    workspace = await _default_workspace(request)
    clients: List[MCPClientInfo] = await MCPConfigService(
        workspace,
    ).list_clients()
    return [
        {
            "client_key": info.client_key,
            "display_name": getattr(info, "display_name", "") or info.client_key,
            "transport": getattr(info, "transport", ""),
            "enabled": getattr(info, "enabled", True),
            "tool_count": len(getattr(info, "tools", []) or []),
        }
        for info in clients
    ]
