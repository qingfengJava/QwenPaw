# -*- coding: utf-8 -*-
"""Pydantic models for the org/department domain."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class OrgRecord(BaseModel):
    """One enterprise organization (tenant root)."""

    id: str
    name: str
    slug: str
    plan: str = "standard"
    status: str = "active"
    settings: dict = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DepartmentRecord(BaseModel):
    """One department (tree node, materialized id path)."""

    id: str
    parent_id: Optional[str] = None
    name: str
    path: str
    description: str = ""
    member_count: int = 0


class DepartmentTree(BaseModel):
    """A department with its children nested (for tree rendering)."""

    id: str
    parent_id: Optional[str] = None
    name: str
    path: str
    description: str = ""
    children: List["DepartmentTree"] = Field(default_factory=list)


class OrgCreateBody(BaseModel):
    """Payload for creating an organization."""

    name: str
    slug: str
    plan: str = "standard"
    settings: dict = Field(default_factory=dict)


class DepartmentCreateBody(BaseModel):
    """Payload for creating a department."""

    name: str
    parent_id: Optional[str] = None
    description: str = ""


class DepartmentUpdateBody(BaseModel):
    """Payload for renaming / moving is limited to name+description.

    Moving a subtree is intentionally not supported in the first release
    (materialized-path rewrite of descendants is error-prone); create a
    new department instead.
    """

    name: Optional[str] = None
    description: Optional[str] = None


DepartmentTree.model_rebuild()
