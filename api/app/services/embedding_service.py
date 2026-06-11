"""EmbeddingService — генерация эмбеддингов через OpenRouter или OpenAI-совместимый API.

Поддерживает:
- OpenRouter (по умолчанию, https://openrouter.ai/api/v1)
- Любой OpenAI-совместимый endpoint через кастомный base_url
  (LM Studio, Ollama, vLLM, etc.)

Кеш: in-memory LRU (для prod можно заменить на Redis).
Retry: экспоненциальная задержка при 429/5xx.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import httpx
from loguru import logger
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings
from app.core.exceptions import ExternalAPIError

OPENROUTER_EMBED_URL = "https://openrouter.ai/api/v1/embeddings"
OPENROUTER_RERANK_URL = "https://openrouter.ai/api/v1/rerank"

# Известные размерности эмбеддингов
KNOWN_EMBED_DIMS: dict[str, int] = {
    "qwen/qwen3-embedding-4b": 2560,
    "qwen/qwen3-embedding-8b": 4096,
    "qwen/qwen3-embedding-0.6b": 1024,
    "openai/text-embedding-3-small": 1536,
    "openai/text-embedding-3-large": 3072,
    "openai/text-embedding-ada-002": 1536,
    "baai/bge-m3": 1024,
    "google/gemini-embedding-001": 3072,
    "intfloat/multilingual-e5-large": 1024,
    "mistralai/mistral-embed-2312": 1024,
    "voyage-large-2": 1536,
    "voyage-code-2": 1536,
    "text-embedding-nomic-embed-text-v1.5": 768,
    "nomic-embed-text-v1.5": 768,
}


def _resolve_embed_url(base_url: str | None) -> str:
    """Преобразует кастомный base_url в полный URL для эмбеддингов.

    base_url='http://localhost:1234/v1' -> 'http://localhost:1234/v1/embeddings'
    base_url='http://localhost:1234/v1/' -> 'http://localhost:1234/v1/embeddings'
    base_url=None -> OPENROUTER_EMBED_URL
    """
    if not base_url:
        return OPENROUTER_EMBED_URL
    base = base_url.rstrip("/")
    if base.endswith("/embeddings"):
        return base
    return f"{base}/embeddings"


class EmbeddingService:
    """Сервис генерации эмбеддингов через OpenRouter или OpenAI-совместимый API.

    Использование:
        # OpenRouter (по умолчанию)
        service = EmbeddingService(api_key="sk-or-v1-...", model="qwen/qwen3-embedding-4b")

        # LM Studio (OpenAI-совместимый)
        service = EmbeddingService(
            api_key="lm-studio",  # любой, LM Studio игнорирует
            model="text-embedding-nomic-embed-text-v1.5",
            base_url="http://localhost:1234/v1",
        )
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        batch_size: int = 10,
        max_workers: int = 3,
        timeout: int = 60,
        max_retries: int = 3,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = (base_url or "").strip() or None
        self.endpoint = _resolve_embed_url(self.base_url)
        self._cache: dict[str, list[float]] = {}
        self._cache_max = get_settings().embedding_cache_size

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    async def embed_one(self, text: str, *, use_cache: bool = True) -> list[float]:
        """Один эмбеддинг (lowercase + strip нормализация)."""
        normalized = text.lower().strip()
        if not normalized:
            raise ExternalAPIError("Пустой текст для эмбеддинга")

        if use_cache:
            cache_key = self._cache_key(normalized)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        vectors = await self._call_api([normalized])
        if not vectors:
            raise ExternalAPIError("Пустой ответ от OpenRouter")
        vector = vectors[0]

        if use_cache:
            self._cache_put(normalized, vector)
        return vector

    async def embed_batch(
        self,
        texts: list[str],
        *,
        progress_cb=None,
    ) -> list[list[float]]:
        """Батч эмбеддингов с параллелизмом через Semaphore.

        Разбивает на чанки по self.batch_size, обрабатывает параллельно
        с ограничением self.max_workers.
        """
        if not texts:
            return []

        # Нормализация
        normalized: list[str] = []
        cache_keys: list[str | None] = []
        for t in texts:
            t = (t or "").lower().strip()
            if not t:
                t = "пусто"
            normalized.append(t)
            cache_keys.append(self._cache_key(t))

        # Cache lookup
        results: list[list[float] | None] = [self._cache.get(k) if k else None for k in cache_keys]
        missing_idx = [i for i, v in enumerate(results) if v is None]
        logger.info(
            f"Embedding batch: {len(texts)} texts, {len(missing_idx)} need compute, "
            f"batch_size={self.batch_size}, workers={self.max_workers}"
        )

        if missing_idx:
            # Бьём на чанки
            chunks: list[tuple[int, list[str]]] = []
            for start in range(0, len(missing_idx), self.batch_size):
                chunk_indices = missing_idx[start : start + self.batch_size]
                chunk_texts = [normalized[i] for i in chunk_indices]
                chunks.append((start // self.batch_size, chunk_texts))

            sem = asyncio.Semaphore(self.max_workers)
            completed = 0

            async def _process_chunk(chunk_idx: int, chunk_texts: list[str]) -> tuple[int, list[list[float]]]:
                async with sem:
                    vectors = await self._call_api(chunk_texts)
                    if progress_cb is not None:
                        nonlocal completed
                        completed += len(chunk_texts)
                        progress_cb(completed, len(missing_idx))
                    return chunk_idx, vectors

            tasks = [_process_chunk(idx, texts_) for idx, texts_ in chunks]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for resp in responses:
                if isinstance(resp, Exception):
                    raise resp
                _, vectors = resp  # type: ignore[misc]
                for offset, vec_idx in enumerate(
                    range(
                        (resp[0]) * self.batch_size,  # type: ignore[has-type]
                        (resp[0]) * self.batch_size + len(vectors),  # type: ignore[has-type]
                    )
                ):
                    if vec_idx < len(missing_idx):
                        real_idx = missing_idx[vec_idx]
                        results[real_idx] = vectors[offset]
                        # cache
                        if use_cache := True:
                            ck = cache_keys[real_idx]
                            if ck:
                                self._cache_put(ck, vectors[offset])

        # Проверка что все заполнены
        if any(r is None for r in results):
            raise ExternalAPIError("Не все эмбеддинги были получены")

        return [r for r in results]  # type: ignore[list-item]

    def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("Embedding cache cleared")

    @staticmethod
    def known_dimension(model: str) -> int | None:
        """Возвращает известную размерность для модели (или None)."""
        model_l = (model or "").lower()
        for known, dim in KNOWN_EMBED_DIMS.items():
            if known in model_l or known.split("/")[-1] in model_l:
                return dim
        return None

    # ---------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------
    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Один HTTP запрос к /embeddings.

        Для OpenRouter добавляются заголовки HTTP-Referer/X-Title
        (требование API — без них возможен 403 Forbidden).
        Используем X-Title (старое имя) — X-OpenRouter-Title ломает.
        Для кастомного base_url — отправляется минимальный набор заголовков.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if not self.base_url:
            headers["HTTP-Referer"] = "https://ksr-matcher.local"
            headers["X-Title"] = "KSR Matcher"

        payload = {"model": self.model, "input": texts}
        # encoding_format поддерживается OpenRouter и OpenAI, но не LM Studio
        if not self.base_url or "openrouter.ai" in self.base_url:
            payload["encoding_format"] = "float"

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=20),
            retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPError)),
            reraise=True,
        ):
            with attempt:
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        resp = await client.post(self.endpoint, headers=headers, json=payload)
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    logger.warning(f"Embeddings endpoint network error: {e}")
                    raise

                if resp.status_code == 200:
                    data = resp.json()
                    if "error" in data:
                        msg = data["error"].get("message", "Unknown")
                        code = data["error"].get("code", "")
                        if code == 404 or "No successful provider" in msg:
                            raise ExternalAPIError(
                                f"Модель '{self.model}' недоступна: {msg}"
                            )
                        raise ExternalAPIError(f"API error: {msg}")
                    if "data" in data and isinstance(data["data"], list):
                        sorted_data = sorted(data["data"], key=lambda x: x.get("index", 0))
                        return [
                            self._normalize([float(x) for x in item["embedding"]])
                            for item in sorted_data
                            if item.get("embedding")
                        ]
                    raise ExternalAPIError(f"Unexpected response: {str(data)[:200]}")
                elif resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        f"Embeddings {resp.status_code}, retrying "
                        f"(attempt {attempt.retry_state.attempt_number})"
                    )
                    raise httpx.HTTPError(f"Status {resp.status_code}")
                elif resp.status_code == 401:
                    raise ExternalAPIError("Неверный API ключ", details={"status": 401})
                elif resp.status_code == 404:
                    raise ExternalAPIError(
                        f"Endpoint не найден: {self.endpoint}. "
                        f"Проверьте base_url.",
                        details={"status": 404},
                    )
                else:
                    raise ExternalAPIError(
                        f"API error {resp.status_code}: {resp.text[:200]}"
                    )

        raise ExternalAPIError("Embeddings: исчерпаны попытки")

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        """L2-нормализация вектора (для косинусного сходства)."""
        norm = sum(v * v for v in vec) ** 0.5
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(f"{self.endpoint}|{self.model}|{text}".encode()).hexdigest()[:32]

    def _cache_put(self, text: str, vector: list[float]) -> None:
        if len(self._cache) >= self._cache_max:
            # LRU eviction (простая версия)
            first_key = next(iter(self._cache))
            del self._cache[first_key]
        self._cache[self._cache_key(text)] = vector


__all__ = ["EmbeddingService", "KNOWN_EMBED_DIMS", "OPENROUTER_EMBED_URL", "OPENROUTER_RERANK_URL"]
