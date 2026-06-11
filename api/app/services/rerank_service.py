"""RerankService — кросс-энкодер реранкер через OpenRouter или OpenAI-совместимый API.

Поддерживает:
- OpenRouter /rerank endpoint (cohere/rerank-4-pro, cohere/rerank-4-fast)
- Любой OpenAI-совместимый endpoint через кастомный base_url
  (LM Studio с rerank-моделями, Cohere напрямую и т.д.)
"""
from __future__ import annotations

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


def _resolve_rerank_url(base_url: str | None) -> str:
    """Преобразует base_url в полный URL для /rerank.

    base_url='http://localhost:1234/v1' -> 'http://localhost:1234/v1/rerank'
    base_url=None -> OPENROUTER_RERANK_URL
    """
    if not base_url:
        return OPENROUTER_RERANK_URL
    base = base_url.rstrip("/")
    if base.endswith("/rerank"):
        return base
    return f"{base}/rerank"


class RerankService:
    """Сервис реранкинга через OpenRouter или OpenAI-совместимый API.

    Поддерживаемые модели (через OpenRouter):
    - cohere/rerank-4-pro (рекомендуется, мультиязычный)
    - cohere/rerank-4-fast (быстрее, чуть хуже качество)

    Использование:
        # OpenRouter
        service = RerankService(
            api_key="sk-or-v1-...",
            model="cohere/rerank-4-pro",
        )

        # LM Studio или другой OpenAI-совместимый
        service = RerankService(
            api_key="lm-studio",
            model="my-rerank-model",
            base_url="http://host.docker.internal:1234/v1",
        )
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 60,
        max_retries: int = 3,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = (base_url or "").strip() or None
        self.endpoint = _resolve_rerank_url(self.base_url)

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
            "User-Agent": "KSR-Matcher/2.0",
        }
        if not self.base_url:
            # OpenRouter требует эти headers для non-localhost ключей
            # (иначе возвращает 403 Forbidden через guardrail)
            # Используем X-Title (старое имя) — X-OpenRouter-Title ломает
            headers["HTTP-Referer"] = "https://ksrmatch.online/"
            headers["X-Title"] = "KSR Matcher"

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
                            self.endpoint, headers=headers, json=payload
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
                    raise ExternalAPIError("Неверный API ключ")
                elif resp.status_code == 404:
                    raise ExternalAPIError(
                        f"Модель '{self.model}' не поддерживает /rerank. "
                        f"Проверьте модель или base_url.",
                    )
                else:
                    raise ExternalAPIError(
                        f"Rerank error {resp.status_code}: {resp.text[:200]}"
                    )
        raise ExternalAPIError("Rerank: исчерпаны попытки")


__all__ = ["RerankService", "OPENROUTER_RERANK_URL"]
