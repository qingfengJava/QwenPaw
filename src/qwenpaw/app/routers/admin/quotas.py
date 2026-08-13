# -*- coding: utf-8 -*-
"""Admin quota management API (M4-4/M4-6)."""
from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...quotas.models import (
    VALID_SUBJECT_TYPES,
    VALID_WINDOWS,
    WINDOW_DAY,
    QuotaRule,
)
from ...quotas.store import get_quota_store
from ...rbac import PERM_ADMIN_QUOTAS, require_perm

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/quotas",
    tags=["admin-quotas"],
    dependencies=[Depends(require_perm(PERM_ADMIN_QUOTAS))],
)


class QuotaRuleBody(BaseModel):
    subject_type: str
    subject: str
    model: str = "*"
    window: str = WINDOW_DAY
    limit: int
    description: str = ""


@router.get("", response_model=List[QuotaRule])
async def list_quotas() -> List[QuotaRule]:
    """List all quota rules."""
    return get_quota_store().list_rules()


@router.put("", response_model=QuotaRule)
async def upsert_quota(body: QuotaRuleBody) -> QuotaRule:
    """Create or replace one quota rule."""
    rule = QuotaRule(**body.model_dump())
    saved = get_quota_store().upsert_rule(rule)
    if saved is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid rule: subject_type must be one of "
                f"{sorted(VALID_SUBJECT_TYPES)}, window one of "
                f"{sorted(VALID_WINDOWS)}, subject non-empty, limit > 0"
            ),
        )
    return saved


@router.delete("", status_code=204)
async def delete_quota(
    subject_type: str,
    subject: str,
    model: str = "*",
    window: str = WINDOW_DAY,
) -> None:
    """Delete one quota rule by its key parts."""
    if not get_quota_store().delete_rule(
        subject_type,
        subject,
        model,
        window,
    ):
        raise HTTPException(status_code=404, detail="rule not found")
