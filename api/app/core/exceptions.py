"""Доменные исключения приложения и FastAPI handlers."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from loguru import logger


class AppError(Exception):
    """Базовое исключение приложения."""

    status_code: int = 500
    error_code: str = "internal_error"
    message: str = "Внутренняя ошибка сервера"

    def __init__(self, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"
    message = "Ресурс не найден"


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "validation_error"
    message = "Ошибка валидации"


class AuthError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"
    message = "Требуется авторизация"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"
    message = "Доступ запрещён"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"
    message = "Конфликт данных"


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "rate_limit"
    message = "Слишком много запросов"


class ExternalAPIError(AppError):
    """Ошибка внешнего API (OpenRouter и др.)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "external_api_error"
    message = "Ошибка внешнего сервиса"


def register_exception_handlers(app: FastAPI) -> None:
    """Регистрация обработчиков исключений в FastAPI приложении."""

    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            f"AppError [{exc.error_code}] on {request.method} {request.url.path}: {exc.message}"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Внутренняя ошибка сервера",
                "details": {},
            },
        )


__all__ = [
    "AppError",
    "NotFoundError",
    "ValidationError",
    "AuthError",
    "ForbiddenError",
    "ConflictError",
    "RateLimitError",
    "ExternalAPIError",
    "register_exception_handlers",
]
