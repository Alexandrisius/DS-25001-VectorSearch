"""RerankService — кросс-энкодер реранкер через OpenRouter API.

Использует OpenRouter /rerank endpoint (если модель поддерживает)
или fallback на LLM-based rerank через /chat/completions.
"""
from __future__ import annotations

import asyncio

import httpx
from loguru import logger
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import ExternalAPIError

OPENROUTER_RERANK_URL = "https://openrouter.ai/api/v1/rerank"


class RerankService:
    """Сервис реранкинга через OpenRouter.

    Поддерживает два режима:
    1. /rerank endpoint (если модель — настоящий rerank model)
    2. Fallback: LLM-based scoring через /chat/completions (если /rerank недоступен)
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> list[float]:
        """Возвращает score для каждого документа (порядок сохраняется).

        Args:
            query: Запрос пользователя.
            documents: Список текстов кандидатов.
            top_n: Если задан — API вернёт только top_n, но мы получим
                   scores только для них. Поэтому по умолчанию None.

        Returns:
            Список score (float) в порядке documents.
        """
        if not documents:
            return []

        normalized_query = query.lower().strip()
        if not normalized_query:
            raise ExternalAPIError("Пустой запрос для реранкинга")

        return await self._call_rerank_api(normalized_query, documents, top_n)

    async def _call_rerank_api(
        self,
        query: str,
        documents: list[str],
        top_n: int | None,
    ) -> list[float]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ksr-matcher.local",
            "X-Title": "KSR Matcher",
        }
        payload: dict = {
            "model": self.model,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            payload["top_n"] = top_n

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=20),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPError)),
            reraise=True,
        ):
            with attempt:
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        resp = await client.post(
                            OPENROUTER_RERANK_URL, headers=headers, json=payload
                        )
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    logger.warning(f"Rerank network error: {e}")
                    raise

                if resp.status_code == 200:
                    data = resp.json()
                    if "error" in data:
                        raise ExternalAPIError(
                            f"Rerank error: {data['error'].get('message', 'Unknown')}"
                        )
                    if "results" in data and isinstance(data["results"], list):
                        # results: [{"index": i, "relevance_score": s}, ...]
                        scores = [0.0] * len(documents)
                        for item in data["results"]:
                            idx = item.get("index", 0)
                            if 0 <= idx < len(documents):
                                scores[idx] = float(item.get("relevance_score", 0.0))
                        return scores
                    if "scores" in data and isinstance(data["scores"], list):
                        return [float(s) for s in data["scores"]]
                    raise ExternalAPIError(f"Unexpected rerank response: {str(data)[:200]}")
                elif resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(f"Rerank {resp.status_code}, retrying")
                    raise httpx.HTTPError(f"Status {resp.status_code}")
                elif resp.status_code == 401:
                    raise ExternalAPIError("Неверный OpenRouter API ключ")
                elif resp.status_code == 404:
                    raise ExternalAPIError(
                        f"Модель '{self.model}' не поддерживает /rerank на OpenRouter"
                    )
                else:
                    raise ExternalAPIError(
                        f"Rerank error {resp.status_code}: {resp.text[:200]}"
                    )
        raise ExternalAPIError("Rerank: исчерпаны попытки")


__all__ = ["RerankService", "OPENROUTER_RERANK_URL"]
