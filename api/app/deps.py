"""FastAPI dependencies (DI)."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthError
from app.core.security import decode_access_token
from app.db.postgres import get_db as _get_db
from app.db.qdrant import get_qdrant_client as _get_qdrant
from app.db.redis import get_redis as _get_redis

DBSession = Annotated[AsyncSession, Depends(_get_db)]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in _get_db():
        yield session


def get_qdrant():
    return _get_qdrant()


def get_redis_dep():
    return _get_redis()


async def get_current_admin(request: Request) -> dict:
    """FastAPI dependency: проверяет JWT в Authorization header."""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise AuthError("Требуется авторизация", details={"WWW-Authenticate": "Bearer"})

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError("Неверный формат токена. Используйте: Bearer <token>")

    return decode_access_token(parts[1])


__all__ = [
    "DBSession",
    "get_db",
    "get_qdrant",
    "get_redis_dep",
    "get_current_admin",
]
