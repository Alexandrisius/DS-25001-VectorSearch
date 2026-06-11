"""Feedback API — /feedback/copy, /feedback/dislike."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.deps import DBSession
from app.schemas.feedback import CopyEventIn, DislikeEventIn, FeedbackOut
from app.services.feedback_service import FeedbackService

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    ua = request.headers.get("User-Agent")
    return ip, ua


@router.post("/copy", response_model=FeedbackOut)
async def feedback_copy(event: CopyEventIn, request: Request, session: DBSession) -> FeedbackOut:
    ip, ua = _client_meta(request)
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
    )
    return FeedbackOut(status="success", message="Событие сохранено")


@router.post("/dislike", response_model=FeedbackOut)
async def feedback_dislike(event: DislikeEventIn, request: Request, session: DBSession) -> FeedbackOut:
    ip, ua = _client_meta(request)
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
    )
    return FeedbackOut(status="success", message="Дизлайк сохранён")
