"""Схемы фидбека (аналитика)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CopyEventIn(BaseModel):
    query: str
    selected_code: str
    position: int
    description: str
    database: str
    reranker_score: float | None = None
    cosine_similarity: float | None = None


class DislikeEventIn(BaseModel):
    timestamp: str | None = None
    query: str
    selected_code: str
    position: int
    description: str
    database: str
    reranker_score: float | None = None
    cosine_similarity: float | None = None
    action: str = "dislike"


class FeedbackOut(BaseModel):
    status: str
    message: str
