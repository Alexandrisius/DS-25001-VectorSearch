"""HTTP middleware.

RequestContextMiddleware:
- Генерирует/пробрасывает X-Request-ID для корреляции логов
- Извлекает real client IP с правильным приоритетом заголовков
  (Cloudflare → X-Forwarded-For → socket)
- Прокидывает X-Session-ID в request.state
- Логирует request_started / request_completed с user_ip + session_id
"""
from __future__ import annotations

import time
import uuid

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


def resolve_client_ip(request: Request) -> str | None:
    """Real client IP по приоритету Cloudflare → XFF → socket.

    Зачем именно такой порядок:
    - CF-Connecting-IP — Cloudflare docs гарантируют 1 IP, нельзя подделать
      снаружи периметра Cloudflare
    - X-Forwarded-For[0] — стандартный прокси-заголовок (для nginx и т.п.)
    - request.client.host — прямое соединение (localhost для тестов)
    """
    cf = request.headers.get("CF-Connecting-IP", "").strip()
    if cf:
        return cf
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return None


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware: добавляет X-Request-ID, парсит IP/session_id, логирует."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # request_id: из заголовка (distributed tracing) или новый UUID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Атрибуция клиента
        user_ip = resolve_client_ip(request)
        request.state.user_ip = user_ip

        session_id = request.headers.get("X-Session-ID") or None
        request.state.session_id = session_id

        user_agent = request.headers.get("User-Agent")
        request.state.user_agent = user_agent

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Request-ID"] = request_id

        logger.bind(
            event="http_request",
            request_id=request_id,
            session_id=session_id,
            user_ip=user_ip,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(elapsed_ms, 1),
        ).info(
            f"{request.method} {request.url.path} -> {response.status_code} "
            f"({elapsed_ms:.1f}ms) ip={user_ip or '-'} sid={session_id or '-'} "
            f"[{request_id[:8]}]"
        )
        return response


__all__ = ["RequestContextMiddleware", "resolve_client_ip"]
