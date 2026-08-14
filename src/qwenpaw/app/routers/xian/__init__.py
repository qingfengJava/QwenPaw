# -*- coding: utf-8 -*-
"""XianWork user-facing API routers (``/api/xian/**``).

Employee-facing counterpart to ``/api/admin/**``: projects, kanban
tasks, feeds, published experts. Identity comes from ``AuthMiddleware``
(``request.state.user``); the anonymous fallback ``local`` keeps local
single-user deployments working exactly like the console plane.
"""
from fastapi import APIRouter

from .automations import router as xian_automations_router
from .bindings import router as xian_bindings_router
from .directory import router as xian_directory_router
from .experts import router as xian_experts_router
from .feed import router as xian_feed_router
from .projects import router as xian_projects_router
from .resources import router as xian_resources_router
from .tasks import router as xian_tasks_router

router = APIRouter(prefix="/xian")
router.include_router(xian_projects_router)
router.include_router(xian_tasks_router)
router.include_router(xian_feed_router)
router.include_router(xian_experts_router)
router.include_router(xian_directory_router)
router.include_router(xian_resources_router)
router.include_router(xian_bindings_router)
router.include_router(xian_automations_router)

__all__ = ["router"]
