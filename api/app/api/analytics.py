"""Admin analytics API — /admin/analytics/*.

Дашборд для админа: кто искал, что искал, сколько занял каждый модуль,
что скопировали/дизлайкнули, тренды. Все эндпоинты за JWT-аутентификацией.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import DBSession, get_current_admin
from app.services.search_analytics_service import SearchAnalyticsService

router = APIRouter(
    prefix="/admin/analytics", tags=["admin-analytics"], dependencies=[Depends(get_current_admin)]
)


@router.get("/kpi")
async def kpi(
    hours: int = Query(24, ge=1, le=720),
    session: DBSession = None,
) -> dict:
    """KPI-карточки дашборда: searches, zero_result_pct, p50/p95, unique users."""
    svc = SearchAnalyticsService(session)
    return await svc.kpi(hours=hours)


@router.get("/recent")
async def recent(
    limit: int = Query(50, ge=1, le=500),
    hours: int = Query(168, ge=1, le=720),  # неделя по умолчанию
    session: DBSession = None,
) -> dict:
    """Последние поиски + копирования/дизлайки после каждого."""
    svc = SearchAnalyticsService(session)
    rows = await svc.recent_searches(limit=limit, hours=hours)
    return {"items": rows, "count": len(rows), "window_hours": hours}


@router.get("/top-queries")
async def top_queries(
    limit: int = Query(30, ge=1, le=200),
    days: int = Query(90, ge=1, le=365),
    session: DBSession = None,
) -> dict:
    """Самые частые запросы с avg timings."""
    svc = SearchAnalyticsService(session)
    return {"items": await svc.top_queries(limit=limit, days=days)}


@router.get("/zero-results")
async def zero_results(
    limit: int = Query(30, ge=1, le=200),
    days: int = Query(90, ge=1, le=365),
    session: DBSession = None,
) -> dict:
    """Запросы, не нашедшие ничего — контент-гэпы базы КСР."""
    svc = SearchAnalyticsService(session)
    return {"items": await svc.zero_result_queries(limit=limit, days=days)}


@router.get("/slow")
async def slow(
    limit: int = Query(20, ge=1, le=200),
    hours: int = Query(168, ge=1, le=720),
    threshold_ms: int = Query(3000, ge=500, le=30000),
    session: DBSession = None,
) -> dict:
    """Самые медленные поиски (>threshold_ms) — для отладки реранкера."""
    svc = SearchAnalyticsService(session)
    return {
        "items": await svc.slow_searches(limit=limit, hours=hours, threshold_ms=threshold_ms),
        "threshold_ms": threshold_ms,
        "window_hours": hours,
    }


@router.get("/users/{user_ip}/timeline")
async def user_timeline(
    user_ip: str,
    hours: int = Query(24, ge=1, le=720),
    session: DBSession = None,
) -> dict:
    """Таймлайн одного пользователя: все поиски + копирования/дизлайки."""
    svc = SearchAnalyticsService(session)
    return await svc.user_timeline(user_ip=user_ip, hours=hours)


__all__ = ["router"]
