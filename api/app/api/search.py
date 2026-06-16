"""Search API — /match (публичный, главный endpoint поиска)."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from app.deps import DBSession
from app.schemas.material import (
    CandidateResult,
    MatchRequest,
    MatchResponse,
)
from app.services.collection_service import CollectionService
from app.services.search_analytics_service import SearchAnalyticsService
from app.services.search_service import SearchService
from app.di import get_search_service

router = APIRouter(tags=["search"])


def _client_meta(request: Request) -> tuple[str | None, str | None, str | None]:
    """Client IP (CF → XFF → socket), UA, session_id из заголовков.

    Приоритет для IP (best practice Cloudflare):
      1. CF-Connecting-IP — гарантированно 1 IP, не подделывается
      2. X-Forwarded-For[0] — стандартный прокси-заголовок
      3. request.client.host — прямое соединение
    """
    cf = request.headers.get("CF-Connecting-IP", "").strip()
    if cf:
        ip = cf
    else:
        xff = request.headers.get("X-Forwarded-For", "")
        ip = xff.split(",")[0].strip() if xff else ""
        if not ip and request.client:
            ip = request.client.host or ""
    ip = ip or None

    ua = request.headers.get("User-Agent")
    sid = request.headers.get("X-Session-ID") or None
    return ip, ua, sid


def _stages_from_trace(trace: dict[str, Any], total_ms: int) -> dict[str, int]:
    """Конвертирует trace['stages'] (имя+elapsed сек) в {stage: ms_int}."""
    out: dict[str, int] = {}
    for st in trace.get("stages", []):
        name = st.get("name")
        elapsed = st.get("elapsed")
        if name and elapsed is not None:
            out[name] = int(round(float(elapsed) * 1000))
    out["total"] = int(total_ms)
    return out


@router.post("/match", response_model=MatchResponse)
async def match(
    request: MatchRequest,
    req: Request,
    session: DBSession,
    search: SearchService = Depends(get_search_service),
) -> MatchResponse:
    """2-stage retrieval: Qdrant (vector) + OpenRouter (rerank)."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Текст не может быть пустым")

    coll_svc = CollectionService(session)
    coll = await coll_svc.get_current_active(request.database)
    if not coll:
        raise HTTPException(
            status_code=404,
            detail=f"Коллекция '{request.database or 'default'}' не найдена",
        )

    # Преобразование filter_paths (если есть)
    filter_paths = None
    if request.filter_paths:
        filter_paths = [{"path": fp.path, "level": fp.level} for fp in request.filter_paths]
    elif request.filter_path:
        filter_paths = [{"path": request.filter_path, "level": request.filter_level}]

    user_ip, user_agent, session_id = _client_meta(req)
    request_id = getattr(req.state, "request_id", None)
    models = _models_for_log()

    t0 = time.perf_counter()
    error_msg: str | None = None
    result: dict[str, Any] = {}
    try:
        result = await search.search(
            collection=coll,
            query=request.text,
            filter_paths=filter_paths,
            max_results=request.max_results,
        )
        return MatchResponse(**result)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        raise
    finally:
        total_ms = int((time.perf_counter() - t0) * 1000)
        # Один структурированный лог + одна запись в search_events
        try:
            trace = result.get("search_trace", {}) if result else {}
            stages_ms = _stages_from_trace(trace, total_ms)
            branch = trace.get("adaptive_branch")
            top = result.get("candidates", []) if result else []
            candidates_count = len(top)

            # 1) Структурированный JSON-лог
            logger.bind(
                event="search_completed",
                request_id=request_id,
                session_id=session_id,
                user_ip=user_ip,
                collection=coll.name,
                query=request.text[:200],
                candidates=candidates_count,
                branch=branch,
                stages_ms=stages_ms,
                total_ms=total_ms,
                status="error" if error_msg else "success",
            ).info(
                f"{request.text[:50]} | branch={branch} | total={total_ms}ms "
                f"| ip={user_ip or '-'}"
            )

            # 2) Запись в Postgres
            analytics = SearchAnalyticsService(session)
            await analytics.record(
                query=request.text,
                stages_ms=stages_ms,
                candidates_count=candidates_count,
                branch=branch,
                top_results=top,
                collection=coll.name,
                filter_paths=filter_paths,
                request_id=request_id,
                session_id=session_id,
                user_ip=user_ip,
                user_agent=user_agent,
                model_embed=models[0],
                model_rerank=models[1],
                status="error" if error_msg else "success",
                error=error_msg,
            )
            await session.commit()
        except Exception as log_exc:
            # Не даём аналитике сломать основной запрос
            logger.warning(f"[search-analytics] record failed: {log_exc}")
            try:
                await session.rollback()
            except Exception:
                pass


def _models_for_log() -> tuple[str | None, str | None]:
    """Текущие модели эмбеддинга/реранкера (для отладки смены)."""
    try:
        from app.config import get_settings
        s = get_settings()
        return s.openrouter_model_embed, s.openrouter_model_rerank
    except Exception:
        return None, None


@router.post("/set_database")
async def set_database(database_name: str, session: DBSession) -> dict:
    """Установить активную коллекцию (для совместимости с UI)."""
    from sqlalchemy import update
    from app.models.collection import Collection
    # В v2 — нет понятия current, UI сам выбирает.
    coll = await CollectionService(session).get_by_name(database_name)
    if not coll:
        raise HTTPException(status_code=404, detail=f"Коллекция '{database_name}' не найдена")
    return {"status": "success", "message": f"Активная коллекция: {database_name}"}


@router.get("/databases")
async def list_databases(session: DBSession) -> dict:
    """Список visible коллекций (публичный, для UI поиска).

    Использует list_visible_fast() (без selectinload) + stored counter
    Collection.materials_count — иначе SELECT COUNT для 142k записей
    даёт 6+ сек лаг при каждом открытии главной страницы.
    """
    svc = CollectionService(session)
    visible = await svc.list_visible_fast()
    current = await svc.get_current_active(None)
    return {
        "databases": [
            {
                "name": c.name,
                "description": c.description or c.name,
                "record_count": c.materials_count or 0,
                "dimension": c.dimension,
                "thresholds": {
                    "cosine": c.cosine_threshold,
                    "rerank": c.rerank_threshold,
                },
                "phase4": {
                    "rrf_k": c.rrf_k,
                    "rrf_dense_weight": c.rrf_dense_weight,
                    "rrf_bm25_weight": c.rrf_bm25_weight,
                    "mmr_lambda": c.mmr_lambda,
                    "mmr_pool_size": c.mmr_pool_size,
                    "adaptive_confident_min": c.adaptive_confident_min,
                    "adaptive_uncertain_min": c.adaptive_uncertain_min,
                    "fallback_cosine_min": c.fallback_cosine_min,
                },
                "last_updated": c.last_updated.isoformat() if c.last_updated else "",
            }
            for c in visible
        ],
        "current_database": current.name if current else None,
    }
