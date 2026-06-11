"""Схемы админ-аутентификации."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AuthRequest(BaseModel):
    password: str = Field(..., min_length=1)


class AuthResponse(BaseModel):
    status: str
    token: str
    expires_in: int
