# server.py - ВЕРСИЯ С QDRANT ВЕКТОРНОЙ БД
import asyncio
import json
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import torch
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sentence_transformers import CrossEncoder
from transformers import AutoModel, AutoTokenizer

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Конфигурация ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = (
    "C:/Users/klim9/Yandex.Disk/02_Work/#Projects/04_DataScience/DS-25001-VectorSearch"
)

# Пути к данным
QDRANT_STORAGE_PATH = os.path.join(
    PROJECT_ROOT, "data", "03_processed", "qdrant_storage"
)
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "02_interim")
WEB_DIR = os.path.join(PROJECT_ROOT, "web")

# Настройки моделей
QWEN_MODEL_PATH = r"D:\hf_cache\Qwen3-Embedding-4B"
RERANKER_PATH = r"D:\hf_cache\bge-reranker-v2-m3"


# === ОПТИМИЗАЦИЯ: Кэш для эмбеддингов ===
class EmbeddingCache:
    """
    Кэш для хранения сгенерированных эмбеддингов запросов

    Особенности:
    - Ключи нормализуются (приводятся к lowercase)
    - LRU политика вытеснения при переполнении
    - Потокобезопасность через asyncio.Lock
    """

    def __init__(self, max_size=10000):
        self.cache = {}
        self.max_size = max_size
        self.access_times = {}
        self.lock = asyncio.Lock()

    async def get(self, text: str) -> Optional[np.ndarray]:
        """Получение эмбеддинга из кэша (ключ всегда в нижнем регистре)"""
        async with self.lock:
            key = text.lower().strip()  # Нормализация ключа
            if key in self.cache:
                self.access_times[key] = time.time()
                return self.cache[key]
            return None

    async def set(self, text: str, embedding: np.ndarray):
        """Сохранение эмбеддинга в кэш (ключ всегда в нижнем регистре)"""
        async with self.lock:
            key = text.lower().strip()  # Нормализация ключа
            if len(self.cache) >= self.max_size:
                # Удаляем самый старый элемент (LRU)
                oldest_key = min(self.access_times, key=self.access_times.get)
                del self.cache[oldest_key]
                del self.access_times[oldest_key]
            self.cache[key] = embedding.copy()
            self.access_times[key] = time.time()

    def clear(self):
        """Очистка кэша"""
        self.cache.clear()
        self.access_times.clear()
        logger.info("🧹 Кэш эмбеддингов очищен")


# === МЕНЕДЖЕР ВЕКТОРНЫХ БАЗ НА ОСНОВЕ QDRANT ===
class QdrantVectorDatabaseManager:
    """
    Менеджер для работы с Qdrant векторными базами данных

    Особенности:
    - Поддержка нескольких коллекций одновременно
    - Горячее переключение между коллекциями
    - Горячая перезагрузка конфигурации без перезапуска
    - Асинхронная работа с пулом потоков
    - Кэширование метаданных коллекций
    - Поиск с косинусным сходством
    - Reranking результатов через CrossEncoder
    - Встроенная генерация эмбеддингов (Qwen)
    """

    def __init__(self, storage_path: str):
        """
        Инициализация менеджера Qdrant баз данных

        Args:
            storage_path: Путь к хранилищу Qdrant
        """
        self.storage_path = storage_path
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Определение устройства для вычислений (CPU/CUDA)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"🖥️ Устройство для вычислений: {self.device}")

        # КРИТИЧНО: Сохраняем путь к конфигу для перезагрузки
        self.config_path = os.path.join(BASE_DIR, "vector_databases.json")

        # Инициализация Qdrant клиента
        logger.info(f"🔌 Подключение к Qdrant: {storage_path}")
        self.client = QdrantClient(path=storage_path)

        # Словарь метаданных коллекций {название: метаданные}
        self.collections_metadata = {}

        # Загрузка конфигурации баз из JSON
        self.load_configuration()

        # Текущая активная коллекция
        self.current_collection = (
            next(iter(self.collections_metadata)) if self.collections_metadata else None
        )

        if self.current_collection:
            logger.info(f"🎯 Активная коллекция: {self.current_collection}")
        else:
            logger.warning("⚠️ Нет доступных коллекций в Qdrant")

        # === ИНИЦИАЛИЗАЦИЯ МОДЕЛИ ЭМБЕДДИНГОВ ===
        self._init_embedding_model()
        
        # Инициализация кэша
        self.embedding_cache = EmbeddingCache(max_size=15000)

    def _init_embedding_model(self):
        """Инициализация локальной модели эмбеддингов Qwen3"""
        logger.info(f"📥 Загрузка модели эмбеддингов: {QWEN_MODEL_PATH}")
        
        self.tokenizer = AutoTokenizer.from_pretrained(
            QWEN_MODEL_PATH, padding_side="left", trust_remote_code=True
        )

        self.embedding_model = AutoModel.from_pretrained(
            QWEN_MODEL_PATH,
            trust_remote_code=True,
            device_map=self.device,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
        )
        self.embedding_model.eval()
        if self.device == "cuda":
            torch.cuda.empty_cache()
        logger.info("✅ Модель эмбеддингов загружена")

    def _get_embedding_sync(self, text: str) -> np.ndarray:
        """Синхронное получение эмбеддинга через локальную модель"""
        try:
            # Приводим текст к нижнему регистру
            normalized_text = text.lower().strip()
            
            # Токенизация
            inputs = self.tokenizer(
                [normalized_text],
                max_length=1024,
                padding=True,
                truncation=True,
                return_tensors="pt",
            ).to(self.device)

            # Получение эмбеддингов
            with torch.no_grad():
                outputs = self.embedding_model(**inputs)

            # Last token pooling
            last_hidden_state = outputs.last_hidden_state
            attention_mask = inputs["attention_mask"]

            left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
            if left_padding:
                embeddings = last_hidden_state[:, -1]
            else:
                sequence_lengths = attention_mask.sum(dim=1) - 1
                batch_size = last_hidden_state.shape[0]
                embeddings = last_hidden_state[
                    torch.arange(batch_size, device=last_hidden_state.device),
                    sequence_lengths,
                ]

            # Нормализация
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
            
            # Конвертация в numpy
            return embeddings.cpu().numpy()[0].astype(np.float32)
        except Exception as e:
            logger.error(f"Ошибка генерации эмбеддинга: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка эмбеддинга: {str(e)}")

    async def get_embedding_cached(self, text: str) -> np.ndarray:
        """Получает эмбеддинг с кэшированием (асинхронно)"""
        # Проверяем кэш
        cached_emb = await self.embedding_cache.get(text)
        if cached_emb is not None:
            return cached_emb

        # Если нет в кэше, генерируем
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            self.executor, self._get_embedding_sync, text
        )

        # Сохраняем в кэш
        await self.embedding_cache.set(text, embedding)
        return embedding

    # === МЕТОДЫ СОВМЕСТИМОСТИ (ADAPTERS) ===
    
    def get_thresholds(self):
        """Возвращает пороги для текущей коллекции"""
        meta = self.get_current_database_info()
        thresholds = meta.get("thresholds", {"cosine": 0.45, "rerank": 0.6})
        return thresholds["cosine"], thresholds["rerank"]

    def get_columns(self):
        """Возвращает маппинг колонок для текущей коллекции"""
        meta = self.get_current_database_info()
        return meta.get("columns", {"code": "code", "description": "description"})

    def set_active_collection(self, name: str):
        """Алиас для switch_database с валидацией"""
        if not self.switch_database(name):
             raise ValueError(f"База '{name}' не найдена")

    async def search_similar(self, collection_name, query_embedding, top_k, score_threshold):
        """
        Адаптер для поиска с фильтрацией по score.
        Возвращает список словарей, совместимый с MatchResponse.
        """
        results = await self.search_vectors(
            query_embedding=query_embedding,
            top_k=top_k,
            collection_name=collection_name
        )
        
        # Фильтрация по порогу косинусного сходства
        filtered_results = [r for r in results if r['score'] >= score_threshold]
        return filtered_results
        
    def delete_by_code(self, code: str, collection_name: Optional[str] = None) -> bool:
        """Алиас для delete_record"""
        return self.delete_record(code, collection_name)
    
    def clear_cache(self):
        """Очистка кэша эмбеддингов"""
        self.embedding_cache.clear()

    # === СТАНДАРТНЫЕ МЕТОДЫ QDRANT ===

    def load_configuration(self):
        """
        Загрузка/перезагрузка конфигурации векторных баз из JSON файла

        Может вызываться повторно для обновления списка баз без перезапуска сервера

        Конфигурация содержит:
        - Названия коллекций
        - Описания баз
        - Пороговые значения (cosine, rerank)
        - Маппинг колонок метаданных
        """
        if not os.path.exists(self.config_path):
            logger.warning(f"⚠️ Конфигурационный файл не найден: {self.config_path}")
            self._create_default_config(self.config_path)
            return

        try:
            logger.info(f"📂 Загрузка конфигурации из: {self.config_path}")

            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # Проверяем существование коллекций в Qdrant
            existing_collections = [
                c.name for c in self.client.get_collections().collections
            ]

            # Запоминаем старое состояние для логирования изменений
            old_collections = set(self.collections_metadata.keys())

            # Очищаем старые метаданные перед обновлением
            self.collections_metadata = {}

            for collection_name, db_config in config.items():
                if collection_name in existing_collections:
                    # Получаем информацию о коллекции из Qdrant
                    collection_info = self.client.get_collection(collection_name)

                    # Сохраняем метаданные коллекции
                    self.collections_metadata[collection_name] = {
                        "name": collection_name,
                        "description": db_config.get(
                            "description", f"База {collection_name}"
                        ),
                        "columns": db_config.get(
                            "columns", {"code": "code", "description": "description"}
                        ),
                        "thresholds": db_config.get(
                            "thresholds", {"cosine": 0.45, "rerank": 0.6}
                        ),
                        "record_count": collection_info.points_count,
                        "dimension": collection_info.config.params.vectors.size,
                        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }

                    logger.info(
                        f"✅ Коллекция '{collection_name}' найдена: "
                        f"{collection_info.points_count} записей, "
                        f"размерность {collection_info.config.params.vectors.size}"
                    )
                else:
                    logger.warning(
                        f"⚠️ Коллекция '{collection_name}' указана в конфиге, "
                        f"но не найдена в Qdrant"
                    )

            # Проверка текущей активной коллекции
            if (
                hasattr(self, "current_collection")
                and self.current_collection not in self.collections_metadata
            ):
                if self.collections_metadata:
                    # Устанавливаем первую найденную коллекцию как активную
                    self.current_collection = next(iter(self.collections_metadata))
                    logger.warning(
                        f"⚠️ Предыдущая активная коллекция '{self.current_collection}' недоступна, "
                        f"переключено на: {self.current_collection}"
                    )
                else:
                    self.current_collection = None
                    logger.error("❌ Не найдено ни одной коллекции в Qdrant")

            # Логируем изменения при перезагрузке
            new_collections = set(self.collections_metadata.keys())
            added = new_collections - old_collections
            removed = old_collections - new_collections

            if added:
                logger.info(f"➕ Добавлены коллекции: {', '.join(added)}")
            if removed:
                logger.info(f"➖ Удалены коллекции: {', '.join(removed)}")

            logger.info(
                f"✅ Конфигурация загружена: {len(self.collections_metadata)} коллекций доступно"
            )

        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON конфига: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке конфигурации: {str(e)}")
            raise

    def _create_default_config(self, config_path: str):
        """
        Создание конфигурации по умолчанию если файл не найден

        Args:
            config_path: Путь для сохранения конфига
        """
        logger.info("📝 Создание конфигурации по умолчанию...")

        # Получаем список существующих коллекций в Qdrant
        existing_collections = [
            c.name for c in self.client.get_collections().collections
        ]

        default_config = {}
        for collection_name in existing_collections:
            collection_info = self.client.get_collection(collection_name)

            default_config[collection_name] = {
                "description": f"Векторная база {collection_name}",
                "columns": {"code": "code", "description": "description"},
                "thresholds": {"cosine": 0.45, "rerank": 0.6},
            }

            # Сохраняем метаданные
            self.collections_metadata[collection_name] = {
                "name": collection_name,
                "description": f"Векторная база {collection_name}",
                "columns": {"code": "code", "description": "description"},
                "thresholds": {"cosine": 0.45, "rerank": 0.6},
                "record_count": collection_info.points_count,
                "dimension": collection_info.config.params.vectors.size,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

        # Сохраняем конфиг
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ Создана конфигурация для {len(default_config)} коллекций")

    def get_available_databases(self) -> List[Dict]:
        """
        Получение списка доступных баз данных с метаданными

        Returns:
            List[Dict]: Список баз с метаданными
        """
        return [
            {
                "name": name,
                "description": meta["description"],
                "record_count": meta["record_count"],
                "dimension": meta["dimension"],
                "is_active": name == self.current_collection,
            }
            for name, meta in self.collections_metadata.items()
        ]

    def switch_database(self, database_name: str) -> bool:
        """
        Переключение на другую базу данных

        Args:
            database_name: Название коллекции для переключения

        Returns:
            bool: True если успешно переключено
        """
        if database_name not in self.collections_metadata:
            logger.error(f"❌ База '{database_name}' не найдена")
            return False

        old_db = self.current_collection
        self.current_collection = database_name

        logger.info(f"🔄 Переключение базы: {old_db} → {database_name}")
        return True

    def get_current_database_info(self) -> Dict:
        """
        Получение информации о текущей активной базе

        Returns:
            Dict: Метаданные текущей базы
        """
        if not self.current_collection:
            return {}

        return self.collections_metadata.get(self.current_collection, {})

    async def search_vectors(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        collection_name: Optional[str] = None,
    ) -> List[Dict]:
        """
        Поиск похожих векторов в указанной коллекции

        Args:
            query_embedding: Вектор запроса
            top_k: Количество результатов
            collection_name: Название коллекции (если None - текущая)

        Returns:
            List[Dict]: Список найденных результатов с метаданными
        """
        collection = collection_name or self.current_collection

        if not collection:
            raise ValueError("Не указана коллекция для поиска")

        if collection not in self.collections_metadata:
            raise ValueError(f"Коллекция '{collection}' не найдена")

        # Асинхронный поиск через ThreadPoolExecutor
        loop = asyncio.get_event_loop()

        # Если пришел numpy array, конвертируем в список
        if isinstance(query_embedding, np.ndarray):
            query_embedding = query_embedding.tolist()

        def _search():
            # ИСПРАВЛЕНО: search заменен на query_points в новых версиях qdrant-client
            # logger.info(f"Searching in {collection} with vector dim: {len(query_embedding)}")
            response = self.client.query_points(
                collection_name=collection,
                query=query_embedding,
                limit=top_k,
                with_payload=True,
            )
            return response.points

        search_results = await loop.run_in_executor(self.executor, _search)

        # Получаем маппинг колонок для этой коллекции
        columns = self.collections_metadata[collection]["columns"]

        # Форматирование результатов
        results = []
        for hit in search_results:
            results.append(
                {
                    "id": hit.id,
                    "score": hit.score,
                    "code": hit.payload.get(columns["code"], ""),
                    "description": hit.payload.get(columns["description"], ""),
                    "metadata": hit.payload,
                }
            )

        return results

    def get_record_by_code(
        self, code: str, collection_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Получение записи по коду КСР

        Args:
            code: Код КСР для поиска
            collection_name: Название коллекции (если None - текущая)

        Returns:
            Optional[Dict]: Найденная запись или None
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return None

        columns = self.collections_metadata[collection]["columns"]
        code_field = columns["code"]

        # Поиск по фильтру
        search_result = self.client.scroll(
            collection_name=collection,
            scroll_filter=Filter(
                must=[FieldCondition(key=code_field, match=MatchValue(value=code))]
            ),
            limit=1,
        )

        if search_result[0]:
            point = search_result[0][0]
            return {
                "id": point.id,
                "code": point.payload.get(code_field, ""),
                "description": point.payload.get(columns["description"], ""),
                "metadata": point.payload,
            }

        return None

    def get_all_records(self, collection_name: Optional[str] = None) -> Dict[str, str]:
        """
        Получение всех записей из коллекции

        Args:
            collection_name: Название коллекции (если None - текущая)

        Returns:
            Dict[str, str]: Словарь {код: описание}
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return {}

        columns = self.collections_metadata[collection]["columns"]
        code_field = columns["code"]
        desc_field = columns["description"]

        all_records = {}
        offset = None

        while True:
            # Получаем батч записей
            records, next_offset = self.client.scroll(
                collection_name=collection,
                limit=100,
                offset=offset,
            )

            # Добавляем в словарь
            for point in records:
                code = point.payload.get(code_field, "")
                description = point.payload.get(desc_field, "")
                if code:
                    all_records[code] = description

            # Проверка завершения
            if next_offset is None:
                break

            offset = next_offset

        return all_records

    def update_record(
        self,
        code: str,
        description: str,
        embedding: List[float],
        collection_name: Optional[str] = None,
        point_id: Optional[str] = None,
        new_metadata: Optional[Dict] = None,
    ) -> bool:
        """
        Обновление или создание записи

        Args:
            code: Код КСР
            description: Описание
            embedding: Вектор эмбеддинга
            collection_name: Название коллекции (если None - текущая)
            point_id: ID записи (опционально)
            new_metadata: Полные метаданные (опционально)

        Returns:
            bool: True если успешно
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return False

        columns = self.collections_metadata[collection]["columns"]

        # Если метаданные не переданы, формируем базовые
        is_new_record = False
        
        if new_metadata is None:
            # Ищем существующую запись для проверки
            existing = self.get_record_by_code(code, collection)
            is_new_record = existing is None
            
            payload = {
                columns["code"]: code,
                columns["description"]: description,
                "timestamp": time.time(),
                "source": "update" if existing else "create",
            }
            # Используем существующий ID или генерируем новый UUID на основе кода
            if point_id is None:
                point_id = existing["id"] if existing else str(uuid.uuid5(uuid.NAMESPACE_DNS, code))
        else:
            payload = new_metadata
            if point_id is None:
                 existing = self.get_record_by_code(code, collection)
                 is_new_record = existing is None
                 point_id = existing["id"] if existing else str(uuid.uuid5(uuid.NAMESPACE_DNS, code))

        # Upsert точки
        self.client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )

        # Обновляем счетчик в метаданных, если это новая запись
        if is_new_record:
            self.collections_metadata[collection]["record_count"] += 1

        return True

    def delete_record(self, code: str, collection_name: Optional[str] = None) -> bool:
        """
        Удаление записи по коду

        Args:
            code: Код КСР для удаления
            collection_name: Название коллекции (если None - текущая)

        Returns:
            bool: True если успешно удалено
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return False

        # Находим запись
        record = self.get_record_by_code(code, collection)

        if not record:
            logger.warning(f"⚠️ Запись с кодом '{code}' не найдена")
            return False

        # Удаляем по ID
        self.client.delete(
            collection_name=collection,
            points_selector=[record["id"]],
        )
        
        # Обновляем счетчик в метаданных
        self.collections_metadata[collection]["record_count"] -= 1

        logger.info(f"🗑️ Удалена запись: {code}")
        return True

    def get_collection_stats(self, collection_name: Optional[str] = None) -> Dict:
        """
        Получение статистики коллекции

        Args:
            collection_name: Название коллекции (если None - текущая)

        Returns:
            Dict: Статистика коллекции
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return {}

        collection_info = self.client.get_collection(collection)

        return {
            "name": collection,
            "points_count": collection_info.points_count,
            "dimension": collection_info.config.params.vectors.size,
            "distance": collection_info.config.params.vectors.distance.name,
            "status": collection_info.status.name,
        }


# === ИНИЦИАЛИЗАЦИЯ СИСТЕМЫ ===
logger.info("⚙️ Инициализация системы поиска с Qdrant...")

# Инициализация менеджера векторных баз
db_manager = QdrantVectorDatabaseManager(storage_path=QDRANT_STORAGE_PATH)

# Загрузка reranker модели
logger.info(f"🧠 Загрузка reranker на устройстве: {db_manager.device}")
reranker = CrossEncoder(
    RERANKER_PATH,
    device=db_manager.device,
    model_kwargs={
        "torch_dtype": torch.float16 if db_manager.device == "cuda" else torch.float32
    },
)
logger.info("✅ Reranker загружен")


# === FASTAPI ПРИЛОЖЕНИЕ ===
app = FastAPI(
    title="KSR Matcher API с Qdrant",
    description="Высокопроизводительная система поиска с векторной базой Qdrant",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение статических файлов (CSS, JS, изображения)
STATIC_DIR = os.path.join(WEB_DIR, "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    logger.info(f"✅ Статические файлы подключены из: {STATIC_DIR}")
else:
    logger.warning(f"⚠️ Папка static не найдена: {STATIC_DIR}")


# === PYDANTIC МОДЕЛИ ===
class MatchRequest(BaseModel):
    """Запрос на поиск похожих записей"""

    text: str
    database: Optional[str] = None


class CandidateResult(BaseModel):
    """Результат поиска - один кандидат"""

    rank: int
    code: str
    description: str
    reranker_score: float
    cosine_similarity: float


class DatabaseInfo(BaseModel):
    """Информация о векторной базе/коллекции"""

    name: str
    description: str
    record_count: int
    is_active: bool
    thresholds: dict


class MatchResponse(BaseModel):
    """Ответ на запрос поиска"""

    query: str
    database: str
    candidates: List[CandidateResult]
    processing_time: float
    status: str


class DatabasesResponse(BaseModel):
    """Список доступных баз данных"""

    databases: List[DatabaseInfo]
    current_database: str


class UpdateRequest(BaseModel):
    """Запрос на обновление записи"""

    code: str
    description: str
    database: Optional[str] = None


class CopyEvent(BaseModel):
    """События копирования кода (для аналитики)"""

    query: str
    selected_code: str
    position: int
    description: str
    database: str
    reranker_score: Optional[float] = None
    cosine_similarity: Optional[float] = None


class DislikeEvent(BaseModel):
    """События дизлайка результата (для аналитики)"""

    timestamp: str
    query: str
    selected_code: str
    position: int
    description: str
    database: str
    reranker_score: Optional[float] = None
    cosine_similarity: Optional[float] = None
    action: str = "dislike"


# === MIDDLEWARE ===
@app.middleware("http")
async def log_processing_time(request, call_next):
    """Логирование времени обработки каждого запроса"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - {process_time:.3f}s")
    return response


# === ОСНОВНЫЕ ENDPOINTS ===
@app.get("/", response_class=HTMLResponse)
async def root():
    """Возвращает веб-интерфейс приложения"""
    try:
        index_path = os.path.join(WEB_DIR, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Интерфейс не найден: {index_path}"
        )


@app.get("/databases")
async def get_databases():
    """
    Получение списка доступных баз данных для фронтенда

    Returns:
        {
            "databases": [
                {
                    "name": "ksr_main",
                    "description": "ksr_main",
                    "record_count": 121905,
                    "dimension": 1024,
                    "thresholds": {"cosine": 0.45, "rerank": 0.6}
                }
            ],
            "current_database": "ksr_main"
        }
    """
    try:
        databases_list = []

        # ИСПРАВЛЕНО: используем collections_metadata напрямую
        for name, meta in db_manager.collections_metadata.items():
            databases_list.append(
                {
                    "name": name,
                    "description": meta.get("description", name),
                    "record_count": meta.get("record_count", 0),
                    "dimension": meta.get("dimension", 1024),
                    "thresholds": meta.get(
                        "thresholds", {"cosine": 0.45, "rerank": 0.6}
                    ),
                }
            )

        return {
            "databases": databases_list,
            "current_database": db_manager.current_collection,
        }

    except Exception as e:
        logger.error(f"❌ Ошибка получения списка баз: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка получения баз данных: {str(e)}"
        )


@app.post("/set_database")
async def set_database(database_name: str):
    """Устанавливает активную векторную коллекцию"""
    try:
        db_manager.set_active_collection(database_name)
        return {
            "status": "success",
            "message": f"Активная коллекция установлена: {database_name}",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/clear_cache")
async def clear_cache():
    """Очищает кэш эмбеддингов запросов"""
    db_manager.clear_cache()
    return {"status": "success", "message": "Кэш эмбеддингов очищен"}


@app.post("/match", response_model=MatchResponse)
async def match_ksr(request: MatchRequest):
    """Основной эндпоинт поиска похожих записей"""
    start_time = time.time()
    query_text = request.text.strip()

    if not query_text:
        raise HTTPException(status_code=400, detail="Текст не может быть пустым")

    # Выбор коллекции для поиска
    original_collection = None
    if request.database:
        original_collection = db_manager.current_collection
        try:
            db_manager.set_active_collection(request.database)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    try:
        collection_name = db_manager.current_collection

        # Получение порогов из конфигурации
        COSINE_THRESHOLD, RERANK_THRESHOLD = db_manager.get_thresholds()

        # Получение маппинга колонок
        columns = db_manager.get_columns()

        # Параметры поиска
        TOP_K_QDRANT = 1500
        MAX_FOR_RERANK = 200
        MAX_RESULTS = 100

        # === ШАГ 1: Генерация эмбеддинга запроса (асинхронно с кэшем) ===
        query_emb = await db_manager.get_embedding_cached(query_text)

        # === ШАГ 2: Поиск в Qdrant (теперь асинхронно!) ===
        candidates = await db_manager.search_similar(
            collection_name=collection_name,
            query_embedding=query_emb,
            top_k=TOP_K_QDRANT,
            score_threshold=COSINE_THRESHOLD,
        )

        if not candidates:
            logger.warning(f"⚠️ No candidates found in Qdrant for query: '{query_text}'")
            return MatchResponse(
                query=query_text,
                database=collection_name,
                candidates=[],
                processing_time=time.time() - start_time,
                status="not_found_in_vector_db",
            )

        # === ШАГ 3: Ограничиваем для reranking ===
        candidates_for_rerank = candidates[:MAX_FOR_RERANK]

        # === ШАГ 4: Reranking ===
        normalized_query = query_text.lower().strip()
        candidate_pairs = [
            (normalized_query, c["description"]) for c in candidates_for_rerank
        ]

        loop = asyncio.get_event_loop()
        rerank_scores = await loop.run_in_executor(
            db_manager.executor, lambda: reranker.predict(candidate_pairs)
        )

        # === ШАГ 5: Фильтрация по порогу reranker ===
        valid_results = []
        for idx, (candidate, rerank_score) in enumerate(
            zip(candidates_for_rerank, rerank_scores)
        ):
            if rerank_score >= RERANK_THRESHOLD:
                valid_results.append({**candidate, "rerank_score": float(rerank_score)})

        if not valid_results:
            max_rerank = float(np.max(rerank_scores)) if len(rerank_scores) > 0 else 0.0
            logger.warning(f"⚠️ No results passed reranker threshold. Max score: {max_rerank:.4f} (Threshold: {RERANK_THRESHOLD})")
            
            # FALLBACK: Возвращаем топ результатов несмотря на низкий скор
            logger.info("🔄 Using fallback: returning top results despite low score")
            
            all_scored_results = []
            for idx, (candidate, rerank_score) in enumerate(zip(candidates_for_rerank, rerank_scores)):
                all_scored_results.append({**candidate, "rerank_score": float(rerank_score)})
            
            all_scored_results.sort(key=lambda x: x["rerank_score"], reverse=True)
            valid_results = all_scored_results[:20]  # Возвращаем 20 лучших

        # === ШАГ 6: Сортировка по reranker score ===
        valid_results.sort(key=lambda x: x["rerank_score"], reverse=True)

        # === ШАГ 7: Формирование финального ответа ===
        final_candidates = [
            CandidateResult(
                rank=idx + 1,
                code=r["code"],
                description=r["description"],
                reranker_score=r["rerank_score"],
                cosine_similarity=r["score"],
            )
            for idx, r in enumerate(valid_results[:MAX_RESULTS])
        ]

        processing_time = time.time() - start_time

        logger.info(
            f"✅ Запрос: '{query_text[:50]}...' | "
            f"Найдено в Qdrant: {len(candidates)} | "
            f"Прошло reranker: {len(valid_results)} | "
            f"Возвращено: {len(final_candidates)} | "
            f"Время: {processing_time:.3f}с"
        )

        return MatchResponse(
            query=query_text,
            database=collection_name,
            candidates=final_candidates,
            processing_time=processing_time,
            status="success",
        )

    finally:
        # Восстановление исходной коллекции
        if original_collection and original_collection != db_manager.current_collection:
            db_manager.set_active_collection(original_collection)


@app.get("/health")
async def health_check():
    """
    Health check endpoint - проверка работоспособности сервера

    Returns:
        Статус сервера и основная информация о системе
    """
    return {
        "status": "ok",
        "device": db_manager.device,
        "current_database": db_manager.current_collection,
        "available_databases": len(db_manager.collections_metadata),
        "databases_list": list(db_manager.collections_metadata.keys()),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/stats")
async def get_stats():
    """Детальная статистика производительности"""
    collections_info = []
    for name in db_manager.collections_metadata.keys():
        try:
            info = db_manager.get_collection_info(name)
            collections_info.append(info)
        except Exception as e:
            logger.error(f"Ошибка получения информации о '{name}': {e}")

    return {
        "cache_entries": len(db_manager.embedding_cache.cache),
        "max_cache_size": db_manager.embedding_cache.max_size,
        "collections": collections_info,
        "device": db_manager.device,
        "executor_workers": db_manager.executor._max_workers,
    }


# === ENDPOINTS ДЛЯ ПОЛУЧЕНИЯ ВСЕХ КОДОВ КСР ИЗ БАЗЫ QDRANT ===
@app.get("/get_all_codes")
async def get_all_codes(database: Optional[str] = None):
    """
    Получение списка ВСЕХ кодов и описаний из коллекции (без пагинации)

    Возвращает словарь {код: описание} для сравнения изменений при обновлении базы.

    Маппинг полей:
    - Qdrant поле "code" → ключ словаря
    - Qdrant поле "description" → значение словаря

    Args:
        database: Название коллекции (если не указано - используется текущая активная)

    Returns:
        {
            "status": "success",
            "collection": "ksr_main",
            "records": {"код1": "описание1", "код2": "описание2", ...},
            "total": 121904,
            "elapsed_seconds": 3.24
        }
    """
    try:
        collection_name = database or db_manager.current_collection

        if not collection_name:
            raise HTTPException(status_code=400, detail="Коллекция не указана")

        logger.info(f"📥 Запрос ВСЕХ кодов и описаний из '{collection_name}'...")
        start_time = time.time()

        loop = asyncio.get_event_loop()

        # Собираем все записи в словарь {код: описание}
        all_records = {}
        offset = None
        batch_count = 0

        # Цикл по всей коллекции батчами
        while True:
            batch_count += 1

            # Запрашиваем батч записей из Qdrant
            scroll_result = await loop.run_in_executor(
                db_manager.executor,
                lambda: db_manager.client.scroll(
                    collection_name=collection_name,
                    limit=10000,  # Внутренний батч для производительности
                    offset=offset,
                    with_payload=[
                        "code",
                        "description",
                    ],  # Только нужные поля из Qdrant
                    with_vectors=False,  # Векторы не нужны (экономия памяти)
                ),
            )

            points, offset = scroll_result

            # Извлекаем код и описание из каждой точки
            for point in points:
                code = point.payload.get("code")
                description = point.payload.get("description")

                if code and description:
                    all_records[code] = description

            # Если offset None - достигли конца коллекции
            if offset is None:
                break

        elapsed = time.time() - start_time

        logger.info(
            f"✅ Собрано {len(all_records)} записей за {elapsed:.2f}с "
            f"({batch_count} батчей)"
        )

        return {
            "status": "success",
            "collection": collection_name,
            "records": all_records,  # Словарь {код: описание}
            "total": len(all_records),
            "elapsed_seconds": round(elapsed, 2),
        }

    except Exception as e:
        logger.error(f"❌ Ошибка получения записей: {str(e)}")
        import traceback

        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Ошибка получения записей: {str(e)}"
        )


# === ENDPOINTS ДЛЯ ОБНОВЛЕНИЯ ДАННЫХ ===
@app.post("/update_record")
async def update_ksr_record(request: UpdateRequest):
    """
    Обновление существующей записи в векторной базе

    Автоматически генерирует новый эмбеддинг для описания
    и обновляет запись в Qdrant без перестроения индекса
    """
    try:
        collection_name = request.database or db_manager.current_collection

        # Генерация эмбеддинга для нового описания
        new_embedding = await db_manager.get_embedding_cached(request.description)
        
        # Конвертируем numpy array в список для Qdrant
        if isinstance(new_embedding, np.ndarray):
            new_embedding = new_embedding.tolist()

        # Поиск существующей записи по коду
        search_result = db_manager.client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="code", match=MatchValue(value=request.code))]
            ),
            limit=1,
        )

        # Подготовка метаданных
        new_metadata = {
            "code": request.code,
            "description": request.description,
            "timestamp": time.time(),
            "source": "manual_update",
        }

        # Обновление записи через менеджер
        # (он сам определит, обновление это или создание новой записи)
        db_manager.update_record(
            code=request.code,
            description=request.description,
            embedding=new_embedding,
            collection_name=collection_name,
            new_metadata=new_metadata
        )
        
        message = f"Запись с кодом '{request.code}' успешно сохранена"

        return {"status": "success", "message": message, "database": collection_name}

    except Exception as e:
        logger.error(f"❌ Ошибка обновления записи: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete_record/{code}")
async def delete_ksr_record(code: str, database: Optional[str] = None):
    """Удаление записи из векторной базы по коду КСР"""
    try:
        collection_name = database or db_manager.current_collection

        db_manager.delete_by_code(collection_name=collection_name, code=code)

        return {
            "status": "success",
            "message": f"Записи с кодом '{code}' удалены из '{collection_name}'",
        }

    except Exception as e:
        logger.error(f"❌ Ошибка удаления записи: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# === СБОР АНАЛИТИКИ ===
FEEDBACK_DIR = os.path.join(PROJECT_ROOT, "data", "04_feedback")
FEEDBACK_FILE = os.path.join(FEEDBACK_DIR, "positive.jsonl")
DISLIKE_FILE = os.path.join(FEEDBACK_DIR, "negative.jsonl")

# Создание директории и файлов для фидбека
os.makedirs(FEEDBACK_DIR, exist_ok=True)
for filepath in [FEEDBACK_FILE, DISLIKE_FILE]:
    if not os.path.exists(filepath):
        open(filepath, "w", encoding="utf-8").close()
        logger.info(f"✅ Создан файл для аналитики: {filepath}")


def clean_text_for_json(text):
    """
    Очистка текста для безопасного сохранения в JSON

    Удаляет управляющие символы и нормализует текст
    """
    if not isinstance(text, str):
        return text

    # Удаляем опасные управляющие символы
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", " ", text)

    # Нормализуем стрелки и разделители
    text = re.sub(r"[→⟶➡➤→>]", " → ", text)
    text = re.sub(r"[\/|\\]", "/", text)

    # Сжимаем пробелы
    text = re.sub(r"\s+", " ", text).strip()

    # Убираем опасные символы (оставляем буквы, цифры, пунктуацию)
    text = re.sub(
        r"[^\w\s\d.,;:!?()\"'«»\[\]{}\-_+=*%#@&$€₽¥£¢§°±→/\\u0400-\u04FF\\u00C0-\u017F]",
        "",
        text,
    )

    return text


@app.post("/feedback/copy")
async def record_copy_event(event: CopyEvent):
    """Записывает событие копирования кода в JSONL файл"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cleaned_data = {
            "timestamp": timestamp,
            "query": clean_text_for_json(event.query),
            "selected_code": clean_text_for_json(event.selected_code),
            "position": event.position,
            "description": clean_text_for_json(event.description),
            "database": clean_text_for_json(event.database),
            "reranker_score": event.reranker_score,
            "cosine_similarity": event.cosine_similarity,
        }

        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            json_line = json.dumps(
                cleaned_data, ensure_ascii=False, separators=(",", ":")
            )
            f.write(json_line + "\n")

        logger.info(
            f"📊 Копирование: {cleaned_data['selected_code']} "
            f"(позиция {cleaned_data['position']}, "
            f"rerank: {event.reranker_score:.4f})"
        )

        return {"status": "success", "message": "Событие сохранено"}

    except Exception as e:
        logger.error(f"❌ Ошибка записи события копирования: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка сохранения данных: {str(e)}"
        )


@app.post("/feedback/dislike")
async def record_dislike_event(event: DislikeEvent):
    """Записывает событие дизлайка результата в JSONL файл"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cleaned_data = {
            "timestamp": timestamp,
            "query": clean_text_for_json(event.query),
            "selected_code": clean_text_for_json(event.selected_code),
            "position": event.position,
            "description": clean_text_for_json(event.description),
            "database": clean_text_for_json(event.database),
            "reranker_score": event.reranker_score,
            "cosine_similarity": event.cosine_similarity,
            "action": event.action,
        }

        with open(DISLIKE_FILE, "a", encoding="utf-8") as f:
            json_line = json.dumps(
                cleaned_data, ensure_ascii=False, separators=(",", ":")
            )
            f.write(json_line + "\n")

        logger.info(
            f"👎 Дизлайк: {cleaned_data['selected_code']} "
            f"(позиция {cleaned_data['position']})"
        )

        return {"status": "success", "message": "Дизлайк сохранен"}

    except Exception as e:
        logger.error(f"❌ Ошибка записи дизлайка: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка сохранения дизлайка: {str(e)}"
        )


# === ENDPOINT ДЛЯ ПЕРЕЗАГРУЗКИ КОНФИГУРАЦИИ ===
@app.post("/reload_config")
async def reload_config():
    """
    Перезагрузка конфигурации векторных баз без перезапуска сервера

    Использование:
        curl -X POST http://localhost:8000/reload_config

    Или через браузер/Postman:
        POST http://localhost:8000/reload_config

    Returns:
        {
            "status": "success",
            "message": "Конфигурация перезагружена",
            "available_databases": ["ksr_main", "ksr_test"],
            "current_database": "ksr_main",
            "total_databases": 2,
            "changes": {
                "added": ["ksr_test"],
                "removed": [],
                "old_count": 1,
                "new_count": 2
            }
        }
    """
    try:
        logger.info("🔄 Запрос на перезагрузку конфигурации векторных баз...")

        # Запоминаем старое состояние для логирования
        old_databases = set(db_manager.collections_metadata.keys())
        old_count = len(old_databases)

        # Перезагружаем конфиг
        db_manager.load_configuration()

        # Новое состояние
        new_databases = set(db_manager.collections_metadata.keys())
        new_count = len(new_databases)
        current_db = db_manager.current_collection

        # Анализируем изменения
        added = new_databases - old_databases
        removed = old_databases - new_databases

        logger.info(f"✅ Конфигурация перезагружена")
        logger.info(f"📊 Было баз: {old_count}, стало: {new_count}")

        if added:
            logger.info(f"➕ Добавлено баз: {', '.join(added)}")
        if removed:
            logger.info(f"➖ Удалено баз: {', '.join(removed)}")

        return {
            "status": "success",
            "message": "Конфигурация векторных баз перезагружена",
            "available_databases": list(new_databases),
            "current_database": current_db,
            "total_databases": new_count,
            "changes": {
                "added": list(added),
                "removed": list(removed),
                "old_count": old_count,
                "new_count": new_count,
            },
        }

    except Exception as e:
        logger.error(f"❌ Ошибка перезагрузки конфига: {str(e)}")
        import traceback

        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Ошибка перезагрузки конфигурации: {str(e)}"
        )


from pydantic import BaseModel


class CreateCollectionRequest(BaseModel):
    """Запрос на создание новой коллекции"""

    collection_name: str
    dimension: int
    description: str = ""
    recreate: bool = False


@app.post("/create_collection")
async def create_collection(request: CreateCollectionRequest):
    """
    Создание новой коллекции в Qdrant через API

    Args:
        collection_name: Название новой коллекции
        dimension: Размерность векторов
        description: Описание коллекции
        recreate: Удалить существующую если True

    Returns:
        Статус операции
    """
    try:
        from qdrant_client.models import Distance, VectorParams

        logger.info(f"📝 Запрос на создание коллекции: {request.collection_name}")

        # Проверяем существование
        collections = [c.name for c in db_manager.client.get_collections().collections]

        if request.collection_name in collections:
            if request.recreate:
                logger.warning(
                    f"⚠️ Удаление существующей коллекции: {request.collection_name}"
                )
                db_manager.client.delete_collection(request.collection_name)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Коллекция '{request.collection_name}' уже существует. Используйте recreate=true для перезаписи.",
                )

        # Создаем коллекцию
        db_manager.client.create_collection(
            collection_name=request.collection_name,
            vectors_config=VectorParams(
                size=request.dimension, distance=Distance.COSINE
            ),
        )

        logger.info(f"✅ Коллекция '{request.collection_name}' создана")

        # Обновляем конфигурацию
        config_path = os.path.join(BASE_DIR, "vector_databases.json")

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {}

        # Добавляем новую коллекцию
        config[request.collection_name] = {
            "description": request.description
            or f"Векторная база {request.collection_name}",
            "columns": {"code": "code", "description": "description"},
            "thresholds": {"cosine": 0.45, "rerank": 0.6},
        }

        # Сохраняем конфиг
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Перезагружаем конфигурацию
        db_manager.load_configuration()

        return {
            "status": "success",
            "message": f"Коллекция '{request.collection_name}' успешно создана",
            "collection_name": request.collection_name,
            "dimension": request.dimension,
        }

    except Exception as e:
        logger.error(f"❌ Ошибка создания коллекции: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка создания коллекции: {str(e)}"
        )


@app.post("/upload_batch")
async def upload_batch(collection_name: str, points: List[Dict]):
    """
    Загрузка батча векторов в коллекцию

    Args:
        collection_name: Название коллекции
        points: Список точек с векторами и метаданными
            Формат: [{"id": "uuid", "vector": [...], "payload": {...}}]

    Returns:
        Статус операции
    """
    try:
        from qdrant_client.models import PointStruct

        # Конвертируем в PointStruct
        qdrant_points = [
            PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
            for p in points
        ]

        # Загружаем батч
        db_manager.client.upsert(collection_name=collection_name, points=qdrant_points)

        return {"status": "success", "uploaded": len(points)}

    except Exception as e:
        logger.error(f"❌ Ошибка загрузки батча: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки: {str(e)}")


# === ЗАПУСК СЕРВЕРА ===
if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 80)
    logger.info("🚀 Запуск сервера KSR Matcher с Qdrant")
    logger.info("=" * 80)
    logger.info(f"📍 Адрес: http://localhost:8000")
    logger.info(f"💾 Хранилище Qdrant: {QDRANT_STORAGE_PATH}")
    logger.info(f"🧠 Модель эмбеддингов: {QWEN_MODEL_PATH}")
    logger.info(f"🎯 Reranker: {RERANKER_PATH}")
    logger.info(f"🖥️ Устройство: {db_manager.device}")
    logger.info(
        f"📚 Доступные коллекции: {list(db_manager.collections_metadata.keys())}"
    )
    logger.info(f"✅ Активная коллекция: {db_manager.current_collection}")
    logger.info("=" * 80)
    logger.info("⚡ Оптимизации:")
    logger.info("   🧠 Кэширование эмбеддингов запросов (15000 записей)")
    logger.info("   🔄 Асинхронная обработка запросов")
    logger.info("   📊 ThreadPoolExecutor для CPU операций")
    logger.info("   🎯 Qdrant с косинусной метрикой (аналог FAISS IndexFlatIP)")
    logger.info("   💾 In-memory производительность с персистентным хранилищем")
    logger.info("   🔤 Регистронезависимый поиск (lowercase нормализация)")
    logger.info("   📦 Встроенное хранение метаданных (без Parquet)")
    logger.info("   🔄 Инкрементальные обновления без перестроения индекса")
    logger.info("=" * 80)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        workers=1,
        loop="asyncio",
        http="httptools",
        access_log=False,
        log_level="info",
    )
