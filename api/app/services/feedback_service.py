"""FeedbackService — запись событий обратной связи (лайк/дизлайк) в Postgres."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback_event import FeedbackEvent
from app.utils.text import clean_text_for_json


class FeedbackService:
    """Сервис аналитики: запись feedback_events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        action: str,
        query: str,
        selected_code: str,
        position: int,
        description: str,
        collection: str,
        reranker_score: float | None = None,
        cosine_similarity: float | None = None,
        user_ip: str | None = None,
        user_agent: str | None = None,
        session_id: str | None = None,
    ) -> FeedbackEvent:
        event = FeedbackEvent(
            action=action,
            query=clean_text_for_json(query),
            selected_code=selected_code,
            position=position,
            description=clean_text_for_json(description),
            collection=collection,
            reranker_score=reranker_score,
            cosine_similarity=cosine_similarity,
            user_ip=user_ip,
            user_agent=user_agent,
            session_id=session_id,
        )
        self.session.add(event)
        await self.session.flush()
        return event


__all__ = ["FeedbackService"]
