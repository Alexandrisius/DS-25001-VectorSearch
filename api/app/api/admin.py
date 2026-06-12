"""Admin auth API — /admin/auth."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.rate_limit import get_login_rate_limiter
from app.core.security import create_access_token, verify_password
from app.deps import DBSession
from app.schemas.admin import AuthRequest, AuthResponse

router = APIRouter(prefix="/admin", tags=["admin-auth"])


@router.post("/auth", response_model=AuthResponse)
async def admin_auth(
    req: AuthRequest, request: Request, session: DBSession
) -> AuthResponse:
    settings = get_settings()
    limiter = get_login_rate_limiter()

    ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )

    if await limiter.is_blocked(ip):
        remaining = limiter.get_remaining_time(ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Слишком много попыток. Повторите через {remaining} секунд.",
        )

    if not settings.admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_PASSWORD_HASH не настроен",
        )

    if not verify_password(req.password, settings.admin_password_hash):
        await limiter.record_attempt(ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный пароль"
        )

    await limiter.clear(ip)

    expires = timedelta(hours=settings.jwt_expire_hours)
    token = create_access_token("admin", extra={"ip": ip}, expires_delta=expires)
    return AuthResponse(
        status="ok", token=token, expires_in=int(expires.total_seconds())
    )
