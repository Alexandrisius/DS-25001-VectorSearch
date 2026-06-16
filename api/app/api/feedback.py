"""Feedback API — /feedback/copy, /feedback/dislike."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.middleware import resolve_client_ip
from app.deps import DBSession
from app.schemas.feedback import CopyEventIn, DislikeEventIn, FeedbackOut
from app.services.feedback_service import FeedbackService

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _client_meta(request: Request) -> tuple[str | None, str | None, str | None]:
    """Real client IP, UA, session_id из заголовков.

    Использует resolve_client_ip из middleware для правильного приоритета
    (CF-Connecting-IP → X-Forwarded-For → socket). Session_id приходит
    из X-Session-ID (генерируется фронтом, см. shared/session.js).
    """
    ip = resolve_client_ip(request)
    ua = request.headers.get("User-Agent")
    sid = request.headers.get("X-Session-ID") or None
    return ip, ua, sid


@router.post("/copy", response_model=FeedbackOut)
async def feedback_copy(event: CopyEventIn, request: Request, session: DBSession) -> FeedbackOut:
    ip, ua, sid = _client_meta(request)
    svc = FeedbackService(session)
    await svc.record(
        action="copy",
        query=event.query,
        selected_code=event.selected_code,
        position=event.position,
        description=event.description,
        collection=event.database,
        reranker_score=event.reranker_score,
        cosine_similarity=event.cosine_similarity,
        user_ip=ip,
        user_agent=ua,
        session_id=sid,
    )
    return FeedbackOut(status="success", message="Событие сохранено")


@router.post("/dislike", response_model=FeedbackOut)
async def feedback_dislike(event: DislikeEventIn, request: Request, session: DBSession) -> FeedbackOut:
    ip, ua, sid = _client_meta(request)
    svc = FeedbackService(session)
    await svc.record(
        action="dislike",
        query=event.query,
        selected_code=event.selected_code,
        position=event.position,
        description=event.description,
        collection=event.database,
        reranker_score=event.reranker_score,
        cosine_similarity=event.cosine_similarity,
        user_ip=ip,
        user_agent=ua,
        session_id=sid,
    )
    return FeedbackOut(status="success", message="Дизлайк сохранён")
