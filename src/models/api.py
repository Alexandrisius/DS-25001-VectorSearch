from typing import List, Optional, Dict
from pydantic import BaseModel

class MatchRequest(BaseModel):
    """
    Запрос на поиск похожих записей.
    
    Attributes:
        text: Текст запроса для поиска.
        database: Имя базы данных (коллекции).
        filter_path: (Опционально) Фильтр по пути категории (строка).
        filter_level: (Опционально) Уровень вложенности для filter_path.
        filter_paths: (Опционально) Список путей для фильтрации (OR логика).
                      Формат: [{"path": "...", "level": N}, ...]
    """
    text: str
    database: Optional[str] = None
    filter_path: Optional[str] = None
    filter_level: Optional[int] = None
    filter_paths: Optional[List[dict]] = None


class CandidateResult(BaseModel):
    """
    Результат поиска - один кандидат.
    
    Attributes:
        rank: Позиция в выдаче (1 = лучший)
        code: Код материала (КСР)
        description: Описание материала
        reranker_score: Оценка реранкером (если применимо)
        cosine_similarity: Косинусное сходство (Qdrant)
    """
    rank: int
    code: str
    description: str
    material_name: Optional[str] = None
    category_path: Optional[str] = None
    reranker_score: float
    cosine_similarity: float


class MatchResponse(BaseModel):
    query: str
    database: str
    candidates: List[CandidateResult]
    processing_time: float
    status: str


class AuthRequest(BaseModel):
    password: str


class AuthResponse(BaseModel):
    status: str
    token: str
    expires_in: int


class UpdateRequest(BaseModel):
    code: str
    description: str
    database: Optional[str] = None


class BatchUpdateRequest(BaseModel):
    records: List[UpdateRequest]
    database: Optional[str] = None


class BatchDeleteRequest(BaseModel):
    codes: List[str]
    database: Optional[str] = None


class UpdatePointRequest(BaseModel):
    """
    Запрос на обновление одной ячейки.
    
    Поддерживаемые поля:
    - code: код записи
    - description: полное описание (legacy)
    - full_description: описание материала
    - path_level_N: уровни категорий
    - status: статус записи (active, draft, deprecated и др.)
    """
    code: str = None
    field: str
    value: str
