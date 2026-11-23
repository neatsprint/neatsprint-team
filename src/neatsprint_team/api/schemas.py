from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    lead_id: UUID | None = None


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    lead_id: UUID | None = None
    is_archived: bool | None = None


class MemberAdd(BaseModel):
    user_id: UUID
    role_in_team: Literal["LEAD", "MEMBER"] = "MEMBER"
