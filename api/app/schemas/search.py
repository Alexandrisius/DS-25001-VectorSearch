"""Схемы поиска — переэкспорт из material.py для удобства."""
from app.schemas.material import (
    CandidateResult,
    FilterPath,
    MatchRequest,
    MatchResponse,
)

# Алиас для обратной совместимости
MatchResponsePublic = MatchResponse

__all__ = [
    "CandidateResult",
    "FilterPath",
    "MatchRequest",
    "MatchResponse",
    "MatchResponsePublic",
]
