# server_optimized.py - АДАПТИРОВАННАЯ ВЕРСИЯ ПОД НОВЫЙ PIPELINE
import os
import re
import numpy as np
import pandas as pd
import faiss
import torch
import time
import json
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from sentence_transformers import CrossEncoder
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi import Request
from pydantic import BaseModel
from typing import List, Dict, Optional
from collections import defaultdict
from functools import lru_cache
import weakref
import gc
import xxhash
from datetime import datetime
import csv
import pathlib

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Конфигурация ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = (
    "C:/Users/klim9/Yandex.Disk/02_Work/#Projects/04_DataScience/DS-25001-VectorSearch"
)

# Пути к данным
VECTORS_DIR = os.path.join(PROJECT_ROOT, "data", "03_processed")
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "02_interim")
WEB_DIR = os.path.join(PROJECT_ROOT, "web")

# Настройки моделей
QWEN_MODEL_PATH = r"D:\hf_cache\Qwen3-Embedding-4B"
RERANKER_PATH = r"D:\hf_cache\bge-reranker-v2-m3"


# === ОПТИМИЗАЦИЯ: Кэш для эмбеддингов ===
class EmbeddingCache:
    def __init__(self, max_size=10000):
        self.cache = {}
        self.max_size = max_size
        self.access_times = {}
        self.lock = asyncio.Lock()

    async def get(self, text: str) -> Optional[np.ndarray]:
        async with self.lock:
            key = text.lower().strip()
            if key in self.cache:
                self.access_times[key] = time.time()
                return self.cache[key]
            return None

    async def set(self, text: str, embedding: np.ndarray):
        async with self.lock:
            key = text.lower().strip()
            if len(self.cache) >= self.max_size:
                # Удаляем самый старый элемент
                oldest_key = min(self.access_times, key=self.access_times.get)
                del self.cache[oldest_key]
                del self.access_times[oldest_key]
            self.cache[key] = embedding.copy()
            self.access_times[key] = time.time()

    def clear(self):
        self.cache.clear()
        self.access_times.clear()


# === ОПТИМИЗИРОВАННЫЙ КЛАСС ВЕКТОРНЫХ БАЗ ===
class OptimizedVectorDatabaseManager:
    def __init__(self):
        self.databases = {}  # {name: {index, df, metadata}}
        self.current_db = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"🧠 Устройство для вычислений: {self.device}")

        # === ИНИЦИАЛИЗАЦИЯ МОДЕЛИ ЭМБЕДДИНГОВ ===
        self._init_embedding_model()

        self._load_available_databases()

        # === ОПТИМИЗАЦИЯ: Кэш для эмбеддингов ===
        self.embedding_cache = EmbeddingCache(max_size=15000)

        # === Thread pool для CPU-операций ===
        self.executor = ThreadPoolExecutor(max_workers=4)

    def _init_embedding_model(self):
        """Инициализация локальной модели эмбеддингов Qwen3"""
        print(f"📥 Загрузка модели эмбеддингов: {QWEN_MODEL_PATH}")
        from transformers import AutoTokenizer, AutoModel

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
        torch.cuda.empty_cache()
        print("✅ Модель эмбеддингов загружена")

    def _get_embedding_sync(self, text: str) -> np.ndarray:
        """Синхронное получение эмбеддинга через локальную модель"""
        try:
            # Токенизация
            inputs = self.tokenizer(
                [text],
                max_length=1024,
                padding=True,
                truncation=True,
                return_tensors="pt",
            ).to(self.device)

            # Получение эмбеддингов
            with torch.no_grad():
                outputs = self.embedding_model(**inputs)

            # Last token pooling (как в документации Qwen)
            last_hidden_state = outputs.last_hidden_state
            attention_mask = inputs["attention_mask"]

            # Определяем тип паддинга
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
            emb = embeddings.cpu().numpy()[0].astype(np.float32)

            return emb
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка эмбеддинга: {str(e)}")

    def _load_available_databases(self):
        """Загружает все доступные векторные базы с оптимизацией"""
        config_path = os.path.join(BASE_DIR, "vector_databases.json")
        if not os.path.exists(config_path):
            print(f"⚠️ Конфигурационный файл не найден: {config_path}")
            self._create_default_config(config_path)

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            for db_name, db_config in config.items():
                try:
                    print(f"🔍 Загрузка векторной базы: {db_name}")
                    self._load_database_optimized(db_name, db_config)
                except Exception as e:
                    print(f"❌ Ошибка при загрузке базы '{db_name}': {str(e)}")
                    continue

            if self.databases:
                self.current_db = next(iter(self.databases))
                print(f"✅ Текущая активная база: {self.current_db}")
            else:
                print("❌ Не удалось загрузить ни одну векторную базу")
        except Exception as e:
            print(f"❌ Ошибка при чтении конфигурации: {str(e)}")
            raise

    def _create_default_config(self, config_path: str):
        """Создает базовую конфигурацию"""
        default_config = {
            "ksr_main": {
                "embeddings_path": os.path.join(VECTORS_DIR, "embeddings.npy"),
                "metadata_path": os.path.join(VECTORS_DIR, "metadata.parquet"),
                "description": "Основная база КСР 'Склад реагентов'",
                "columns": {"code": "Код КСР", "description": "full_path"},
                "thresholds": {"cosine": 0.45, "rerank": 0.6},
            }
        }
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        print(f"✅ Создан базовый конфигурационный файл: {config_path}")

    def _load_database_optimized(self, name: str, config: dict):
        """Оптимизированная загрузка базы данных"""
        embeddings_path = os.path.normpath(config["embeddings_path"])
        metadata_path = os.path.normpath(config["metadata_path"])

        if not os.path.exists(embeddings_path):
            raise FileNotFoundError(f"Файл эмбеддингов не найден: {embeddings_path}")
        if not os.path.exists(metadata_path):
            raise FileNotFoundError(f"Файл метаданных не найден: {metadata_path}")

        # === Загрузка метаданных из parquet ===
        print(f"  📊 Загрузка метаданных: {metadata_path}")
        metadata_df = pd.read_parquet(metadata_path)

        # === Загрузка эмбеддингов ===
        print(f"  🧠 Загрузка эмбеддингов: {embeddings_path}")
        embeddings = np.load(embeddings_path).astype(np.float32)

        if len(metadata_df) != len(embeddings):
            raise ValueError(
                f"Несоответствие размеров: {len(metadata_df)} записей в метаданных, {len(embeddings)} эмбеддингов"
            )

        dim = embeddings.shape[1]
        print(
            f"  ✅ Загружено {len(metadata_df)} записей, размерность эмбеддингов: {dim}"
        )

        # === Создание FAISS индекса ===
        print("  🔍 Создание FAISS индекса...")
        index = faiss.IndexFlatIP(dim)
        faiss.normalize_L2(embeddings)
        index.add(embeddings)
        print("  ✅ FAISS индекс создан")

        # === Сохранение базы ===
        self.databases[name] = {
            "index": index,
            "df": metadata_df,
            "embeddings": embeddings.astype(np.float32).copy(),
            "metadata": {
                "name": name,
                "description": config.get("description", f"База {name}"),
                "columns": config["columns"],
                "thresholds": config.get("thresholds", {"cosine": 0.45, "rerank": 0.6}),
                "record_count": len(metadata_df),
                "dimension": dim,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

        # Очистка памяти
        del embeddings
        gc.collect()

    def get_available_databases(self) -> List[dict]:
        """Возвращает список доступных баз с метаданными"""
        return [
            {
                "name": name,
                "description": db["metadata"]["description"],
                "record_count": db["metadata"]["record_count"],
                "is_active": name == self.current_db,
            }
            for name, db in self.databases.items()
        ]

    def set_active_database(self, name: str):
        """Устанавливает активную базу для поиска"""
        if name not in self.databases:
            available = list(self.databases.keys())
            raise ValueError(f"База '{name}' не найдена. Доступные базы: {available}")
        self.current_db = name
        print(f"🔄 Активная база изменена на: {name}")

    def get_active_database(self):
        """Возвращает текущую активную базу"""
        if not self.current_db or self.current_db not in self.databases:
            raise ValueError("Нет активной векторной базы")
        return self.databases[self.current_db]

    def get_thresholds(self):
        """Возвращает пороговые значения для текущей базы"""
        db = self.get_active_database()
        thresholds = db["metadata"]["thresholds"]
        return thresholds["cosine"], thresholds["rerank"]

    def get_columns(self):
        """Возвращает наименования колонок для текущей базы"""
        db = self.get_active_database()
        return db["metadata"]["columns"]

    # === Кэшированный метод получения эмбеддинга ===
    async def get_embedding_cached(self, text: str) -> np.ndarray:
        """Получает эмбеддинг с кэшированием"""
        cached_emb = await self.embedding_cache.get(text)
        if cached_emb is not None:
            return cached_emb

        # Если нет в кэше, запрашиваем у модели
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            self.executor, self._get_embedding_sync, text
        )

        # Сохраняем в кэш
        await self.embedding_cache.set(text, embedding)
        return embedding

    def clear_cache(self):
        """Очищает кэш эмбеддингов"""
        self.embedding_cache.clear()
        print("🧹 Кэш эмбеддингов очищен")


# === ИНИЦИАЛИЗАЦИЯ ===
print("⚙️ Инициализация АДАПТИРОВАННОЙ системы...")
# Менеджер векторных баз
db_manager = OptimizedVectorDatabaseManager()

# === Загрузка reranker ===
print(f"🧠 Загрузка reranker на устройстве: {db_manager.device}")
reranker = CrossEncoder(
    RERANKER_PATH,
    device=db_manager.device,
    model_kwargs={
        "torch_dtype": torch.float16 if db_manager.device == "cuda" else torch.float32
    },
)
print("✅ Reranker загружен.")

# === FastAPI с оптимизациями ===
app = FastAPI(
    title="KSR Matcher API Ultra",
    description="Сверхбыстрая система поиска с кэшированием и оптимизацией",
    docs_url=None,  # Отключаем docs для скорости
    redoc_url=None,
)


# Модели данных
class MatchRequest(BaseModel):
    text: str
    database: Optional[str] = None


class CandidateResult(BaseModel):
    rank: int
    code: str
    description: str
    reranker_score: float
    cosine_similarity: float


class DatabaseInfo(BaseModel):
    name: str
    description: str
    record_count: int
    is_active: bool


class MatchResponse(BaseModel):
    query: str
    database: str
    candidates: List[CandidateResult]
    processing_time: float
    status: str


class DatabasesResponse(BaseModel):
    databases: List[DatabaseInfo]
    current_database: str


# === Middleware для логирования времени обработки ===
@app.middleware("http")
async def log_processing_time(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - {process_time:.3f}s")
    return response


# === API Endpoints ===
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


@app.get("/databases", response_model=DatabasesResponse)
async def get_databases():
    """Возвращает список доступных векторных баз"""
    return DatabasesResponse(
        databases=db_manager.get_available_databases(),
        current_database=db_manager.current_db if db_manager.current_db else "",
    )


@app.post("/set_database")
async def set_database(database_name: str):
    """Устанавливает активную векторную базу"""
    try:
        db_manager.set_active_database(database_name)
        return {
            "status": "success",
            "message": f"Активная база установлена: {database_name}",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/clear_cache")
async def clear_cache():
    """Очищает кэш эмбеддингов"""
    db_manager.clear_cache()
    return {"status": "success", "message": "Кэш очищен"}


@app.post("/match", response_model=MatchResponse)
async def match_ksr(request: MatchRequest):
    """Оптимизированный поиск с фильтрацией по порогам на каждом этапе"""
    start_time = time.time()
    query_text = request.text.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="Текст не может быть пустым")

    # Выбор базы для поиска
    original_db = None
    if request.database:
        original_db = db_manager.current_db
        try:
            db_manager.set_active_database(request.database)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    try:
        # Получение данных активной базы
        db = db_manager.get_active_database()
        index = db["index"]
        df = db["df"]

        # Получение колонок из конфигурации
        columns = db_manager.get_columns()
        code_col = columns["code"]
        desc_col = columns["description"]
        
        # Пороговые значения - устанавливаем "умные" значения по умолчанию
        COSINE_THRESHOLD, RERANK_THRESHOLD = db_manager.get_thresholds()
        
        # Увеличиваем количество для FAISS, чтобы точно захватить все релевантные
        TOP_K_FAISS = 1500
        # Максимальное количество для reranking (ограничение для производительности)
        MAX_FOR_RERANK = 200
        # Максимальное количество результатов для возврата
        MAX_RESULTS = 100
        
        # Получение эмбеддинга запроса с кэшированием
        query_emb = await db_manager.get_embedding_cached(query_text)
        query_emb_reshaped = query_emb.reshape(1, -1)

        # Поиск в FAISS
        loop = asyncio.get_event_loop()
        distances, indices = await loop.run_in_executor(
            db_manager.executor, lambda: index.search(query_emb_reshaped, TOP_K_FAISS)
        )
        
        # === НОВОЕ: Фильтрация по косинусному сходству ===
        cosine_scores = distances[0]  # для IndexFlatIP это косинусное сходство
        # Находим индексы, где косинусное сходство выше порога
        valid_cosine_indices = np.where(cosine_scores >= COSINE_THRESHOLD)[0]
        
        if len(valid_cosine_indices) == 0:
            # Если нет результатов выше основного порога, проверяем топ-3 для информативной ошибки
            top3_scores = cosine_scores[:3]
            max_score = float(np.max(top3_scores))
            raise HTTPException(
                status_code=404,
                detail=f"По вашему запросу не найдено релевантных результатов. Максимальное косинусное сходство: {max_score:.4f} (порог: {COSINE_THRESHOLD:.2f})"
            )
        
        # Берем индексы и соответствующие косинусные сходства только для валидных результатов
        filtered_indices = indices[0][valid_cosine_indices]
        filtered_cosine_scores = cosine_scores[valid_cosine_indices]
        
        # Ограничиваем количество для reranking (для производительности)
        if len(filtered_indices) > MAX_FOR_RERANK:
            # Сортируем по косинусному сходству и берем топ MAX_FOR_RERANK
            top_indices = np.argsort(filtered_cosine_scores)[::-1][:MAX_FOR_RERANK]
            filtered_indices = filtered_indices[top_indices]
            filtered_cosine_scores = filtered_cosine_scores[top_indices]
        
        # === Reranking только отфильтрованных результатов ===
        candidate_pairs = [(query_text, df.iloc[i][desc_col]) for i in filtered_indices]
        
        rerank_scores = await loop.run_in_executor(
            db_manager.executor, lambda: reranker.predict(candidate_pairs)
        )
        
        # === НОВОЕ: Фильтрация по порогу reranker ===
        valid_rerank_indices = np.where(rerank_scores >= RERANK_THRESHOLD)[0]
        
        if len(valid_rerank_indices) == 0:
            # Если нет результатов выше порога reranker, берем топ-3 для информативной ошибки
            top3_indices = np.argsort(rerank_scores)[::-1][:3]
            top3_scores = rerank_scores[top3_indices]
            max_score = float(np.max(top3_scores))
            raise HTTPException(
                status_code=404,
                detail=f"Найдены похожие материалы, но ни один не прошел порог релевантности reranker. Максимальный reranker score: {max_score:.4f} (порог: {RERANK_THRESHOLD:.2f})"
            )
        
        # Берем только валидные результаты после reranking
        final_indices = filtered_indices[valid_rerank_indices]
        final_cosine_scores = filtered_cosine_scores[valid_rerank_indices]
        final_rerank_scores = rerank_scores[valid_rerank_indices]
        
        # Сортировка по reranker score (в порядке убывания)
        sorted_order = np.argsort(final_rerank_scores)[::-1]
        
        # Ограничиваем максимальное количество результатов
        if len(sorted_order) > MAX_RESULTS:
            sorted_order = sorted_order[:MAX_RESULTS]
        
        # === ФОРМИРОВАНИЕ ФИНАЛЬНЫХ РЕЗУЛЬТАТОВ ===
        candidates = []
        
        for rank_idx, sort_idx in enumerate(sorted_order):
            idx = sort_idx
            global_idx = final_indices[idx]
            cosine_val = float(final_cosine_scores[idx])
            rerank_val = float(final_rerank_scores[idx])
            code = str(df.iloc[global_idx][code_col])
            desc = df.iloc[global_idx][desc_col]
            
            candidates.append(CandidateResult(
                rank=rank_idx + 1,
                code=code,
                description=desc,
                reranker_score=rerank_val,
                cosine_similarity=cosine_val
            ))
        
        processing_time = time.time() - start_time
        
        # Статистика для логирования
        logger.info(f"Запрос: '{query_text[:50]}...' | "
                   f"Найдено: {len(cosine_scores)} | "
                   f"Прошло косинусный фильтр: {len(valid_cosine_indices)} | "
                   f"Прошло reranker фильтр: {len(valid_rerank_indices)} | "
                   f"Возвращено результатов: {len(candidates)} | "
                   f"Время: {processing_time:.3f}с")
        
        return MatchResponse(
            query=query_text,
            database=db_manager.current_db,
            candidates=candidates,
            processing_time=processing_time,
            status="success",
        )
    finally:
        # Восстановление исходной базы
        if original_db and original_db != db_manager.current_db:
            db_manager.set_active_database(original_db)


@app.get("/health")
async def health_check():
    """Проверка состояния сервера с метриками"""
    return {
        "status": "ok",
        "embedding_model": QWEN_MODEL_PATH,
        "reranker": RERANKER_PATH,
        "available_databases": list(db_manager.databases.keys()),
        "active_database": db_manager.current_db,
        "cache_size": len(db_manager.embedding_cache.cache),
        "device": db_manager.device,
        "uptime": time.time(),
    }


@app.get("/stats")
async def get_stats():
    """Детальная статистика производительности"""
    return {
        "cache_entries": len(db_manager.embedding_cache.cache),
        "max_cache_size": db_manager.embedding_cache.max_size,
        "databases": db_manager.get_available_databases(),
        "device": db_manager.device,
        "executor_workers": db_manager.executor._max_workers,
    }


# === СБОР АНАЛИТИКИ: Конфигурация ===
FEEDBACK_DIR = os.path.join(PROJECT_ROOT, "data", "04_feedback")
FEEDBACK_FILE = os.path.join(
    FEEDBACK_DIR, "copy_events.jsonl"
)  # Изменено расширение файла
os.makedirs(FEEDBACK_DIR, exist_ok=True)

# Создаем файл с заголовками, если его нет
if not os.path.exists(FEEDBACK_FILE):
    with open(FEEDBACK_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(
            [
                "timestamp",
                "query",
                "selected_code",
                "position",
                "description",
                "database",
            ]
        )


# === СБОР АНАЛИТИКИ: Модель данных ===
class CopyEvent(BaseModel):
    query: str
    selected_code: str
    position: int
    description: str
    database: str


# === СБОР АНАЛИТИКИ: Функция очистки текста ===
def clean_text_for_json(text):
    """Очищает текст от проблемных символов для безопасного хранения в JSON"""
    if not text or not isinstance(text, str):
        return text

    # Удаляем невидимые символы управления (ASCII и Unicode)
    cleaned = re.sub(r"[\x00-\x1F\x7F-\x9F]", " ", text)

    # Заменяем множественные кавычки на одинарные
    cleaned = re.sub(r'""+', '"', cleaned)

    # Удаляем лишние пробелы
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Обработка специальных символов - убираем все, кроме разрешенных
    # Разрешенные символы: буквы, цифры, пробелы, знаки препинания, некоторые специальные символы
    allowed_chars = r"[^\w\s\d.,;:!?()'\"«»\[\]{}\-_+=*%#@&$€₽¥£¢§°±\\/\\u0400-\\u04FF\\u00C0-\\u017F]"
    cleaned = re.sub(allowed_chars, "", cleaned)

    return cleaned


# === СБОР АНАЛИТИКИ: API эндпоинт ===
@app.post("/feedback/copy")
async def record_copy_event(event: CopyEvent):
    """Записывает событие копирования в JSONL файл с очисткой данных"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Очищаем все текстовые поля
        cleaned_data = {
            "timestamp": timestamp,
            "query": clean_text_for_json(event.query),
            "selected_code": clean_text_for_json(event.selected_code),
            "position": event.position,
            "description": clean_text_for_json(event.description),
            "database": clean_text_for_json(event.database),
        }

        # Запись в JSONL файл (каждая запись на новой строке)
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            json_line = json.dumps(
                cleaned_data, ensure_ascii=False, separators=(",", ":")
            )
            f.write(json_line + "\n")

        logger.info(
            f"📊 Событие копирования сохранено: {cleaned_data['selected_code']} (позиция {cleaned_data['position']})"
        )
        return {"status": "success", "message": "Данные сохранены в JSON"}
    except Exception as e:
        logger.error(f"❌ Ошибка записи данных в JSON: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка сохранения данных: {str(e)}"
        )


# === Запуск сервера ===
if __name__ == "__main__":
    import uvicorn

    print("🚀 Запуск АДАПТИРОВАННОГО сервера на http://localhost:8000")
    print("⚡ Оптимизации:")
    print("   🧠 Кэширование эмбеддингов (15000 записей)")
    print("   🔄 Асинхронная обработка запросов")
    print("   📊 ThreadPoolExecutor для CPU операций")
    print("   🎯 FAISS IndexFlatIP (максимальная скорость)")
    print("   💾 Оптимизированные типы данных (float32)")
    print("   🚀 Batched обработка для reranker")
    print("   📦 Локальная модель Qwen3-Embedding-4B вместо LM Studio API")
    print(f"📚 Доступные векторные базы: {list(db_manager.databases.keys())}")

    # Запуск uvicorn
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        workers=1,  # Один воркер для избежания проблем с GPU
        loop="asyncio",
        http="httptools",
        access_log=False,  # Отключаем лишнее логирование
        log_level="info",
    )
