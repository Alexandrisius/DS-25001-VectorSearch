# 02_create_qdrant_collection.py
"""
Скрипт создания новой коллекции Qdrant через API сервера

Pipeline:
1. Загрузка очищенных данных из CSV (разделитель: точка с запятой)
2. Генерация эмбеддингов для всех записей
3. Создание новой коллекции через API сервера
4. Загрузка векторов и метаданных батчами через API
5. Автоматическое обновление vector_databases.json
6. Автоматическая перезагрузка конфигурации на сервере

Использование:
    # Создание продакшн базы (добавляется в конфиг)
    python 02_create_qdrant_collection.py \
        --input data/02_interim/KSR_clean.csv \
        --collection ksr_main \
        --recreate

    # Создание тестовой базы (БЕЗ добавления в конфиг)
    python 02_create_qdrant_collection.py \
        --input data/02_interim/KSR_clean_2.csv \
        --collection ksr_test \
        --recreate \
        --no-config

Автор: Alexandr
Дата: 2025-11-25
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
import torch
import json
import requests
from pathlib import Path
from tqdm import tqdm
import time
import logging
import uuid
from typing import List, Dict

# Трансформеры для генерации эмбеддингов
from transformers import AutoTokenizer, AutoModel

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ПУТЕЙ ===
PROJECT_ROOT = Path("C:/Users/klim9/Yandex.Disk/02_Work/#Projects/04_DataScience/DS-25001-VectorSearch")
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "02_interim" / "cleaned_data.csv"
CONFIG_PATH = PROJECT_ROOT / "src" / "vector_databases.json"
DEFAULT_SERVER_URL = "http://localhost:8000"

# Пути к моделям
QWEN_MODEL_PATH = r"D:\hf_cache\Qwen3-Embedding-4B"

# === ПАРАМЕТРЫ ===
BATCH_SIZE = 32  # Размер батча для генерации эмбеддингов
UPLOAD_BATCH_SIZE = 100  # Размер батча для загрузки через API
MAX_LENGTH = 1024  # Максимальная длина токенизированного текста


class EmbeddingGenerator:
    """
    Генератор эмбеддингов с использованием модели Qwen3-4B
    
    Особенности:
    - Батчевая обработка для ускорения
    - Нормализация текста (lowercase)
    - L2 нормализация векторов для косинусного сходства
    - Поддержка CUDA
    """
    
    def __init__(self, model_path: str):
        """
        Инициализация генератора эмбеддингов
        
        Args:
            model_path: Путь к модели Qwen3-Embedding-4B
        """
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"🧠 Устройство для вычислений: {self.device}")
        
        # Загрузка токенизатора
        logger.info(f"📥 Загрузка токенизатора из: {model_path}")
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            padding_side="left",
            trust_remote_code=True
        )
        
        # Загрузка модели эмбеддингов
        logger.info(f"📥 Загрузка модели эмбеддингов из: {model_path}")
        self.model = AutoModel.from_pretrained(
            model_path,
            trust_remote_code=True,
            device_map=self.device,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
        )
        self.model.eval()
        
        if self.device == "cuda":
            torch.cuda.empty_cache()
        
        logger.info("✅ Модель эмбеддингов загружена и готова к работе")
    
    def generate_batch(self, texts: List[str]) -> np.ndarray:
        """
        Генерация эмбеддингов для батча текстов
        
        Args:
            texts: Список текстов для обработки
            
        Returns:
            np.ndarray: Массив эмбеддингов (N x dimension)
        """
        # Нормализация текстов (приводим к lowercase)
        normalized_texts = [text.lower().strip() for text in texts]
        
        # Токенизация
        inputs = self.tokenizer(
            normalized_texts,
            max_length=MAX_LENGTH,
            padding=True,
            truncation=True,
            return_tensors="pt",
        ).to(self.device)
        
        # Генерация эмбеддингов без градиентов
        with torch.no_grad():
            outputs = self.model(**inputs)
        
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
        
        # L2 нормализация для косинусного сходства
        embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
        
        # Конвертация в numpy float32
        return embeddings.cpu().numpy().astype(np.float32)
    
    def generate_all(self, texts: List[str], batch_size: int = BATCH_SIZE) -> np.ndarray:
        """
        Генерация эмбеддингов для всех текстов с прогресс-баром
        
        Args:
            texts: Список текстов
            batch_size: Размер батча для обработки
            
        Returns:
            np.ndarray: Массив всех эмбеддингов
        """
        all_embeddings = []
        
        # Обработка батчами с прогресс-баром
        for i in tqdm(range(0, len(texts), batch_size), desc="🔄 Генерация эмбеддингов"):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = self.generate_batch(batch_texts)
            all_embeddings.append(batch_embeddings)
            
            # Очистка памяти GPU каждые 10 батчей
            if self.device == "cuda" and (i // batch_size) % 10 == 0:
                torch.cuda.empty_cache()
        
        # Объединение всех батчей
        return np.vstack(all_embeddings)


def load_csv_data(csv_path: Path) -> pd.DataFrame:
    """
    Загрузка данных из CSV файла
    
    Args:
        csv_path: Путь к CSV файлу
        
    Returns:
        pd.DataFrame: Загруженные данные
    """
    logger.info(f"📂 Загрузка данных из: {csv_path}")
    
    # Загрузка CSV с разделителем "точка с запятой"
    df = pd.read_csv(csv_path, sep=';', encoding='utf-8')
    
    logger.info(f"✅ Загружено {len(df)} записей")
    logger.info(f"📊 Колонки: {list(df.columns)}")
    
    # Проверка обязательных колонок
    required_columns = ['Код КСР', 'full_path']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        raise ValueError(f"Отсутствуют обязательные колонки: {missing_columns}")
    
    # Удаление дубликатов по коду КСР
    original_len = len(df)
    df = df.drop_duplicates(subset=['Код КСР'], keep='first')
    
    if len(df) < original_len:
        logger.warning(f"⚠️ Удалено {original_len - len(df)} дубликатов по 'Код КСР'")
    
    # Удаление записей с пустыми значениями
    df = df.dropna(subset=['Код КСР', 'full_path'])
    logger.info(f"✅ После очистки: {len(df)} записей")
    
    return df


def check_server_connection(server_url: str) -> bool:
    """
    Проверка подключения к серверу
    
    Args:
        server_url: URL сервера
        
    Returns:
        bool: True если сервер доступен
    """
    try:
        logger.info(f"🔍 Проверка подключения к серверу: {server_url}")
        response = requests.get(f"{server_url}/health", timeout=5)
        
        if response.status_code == 200:
            logger.info(f"✅ Сервер доступен: {response.json()}")
            return True
        else:
            logger.error(f"❌ Сервер ответил с кодом: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        logger.error(f"❌ Сервер недоступен на {server_url}")
        logger.error("💡 Убедитесь что сервер запущен: python src/server.py")
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка подключения: {str(e)}")
        return False


def create_collection_via_api(
    collection_name: str,
    dimension: int,
    description: str,
    recreate: bool,
    server_url: str
) -> bool:
    """
    Создание коллекции через API сервера
    
    Args:
        collection_name: Название коллекции
        dimension: Размерность векторов
        description: Описание коллекции
        recreate: Перезаписать существующую
        server_url: URL сервера
        
    Returns:
        bool: True если успешно
    """
    try:
        logger.info(f"🔨 Создание коллекции '{collection_name}' через API...")
        
        response = requests.post(
            f"{server_url}/create_collection",
            json={
                "collection_name": collection_name,
                "dimension": dimension,
                "description": description,
                "recreate": recreate
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ {data['message']}")
            return True
        else:
            error_data = response.json()
            logger.error(f"❌ Ошибка API: {error_data.get('detail', 'Unknown error')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка создания через API: {str(e)}")
        return False


def upload_batch_via_api(
    collection_name: str,
    embeddings: np.ndarray,
    metadata_df: pd.DataFrame,
    server_url: str,
    batch_size: int = UPLOAD_BATCH_SIZE
):
    """
    Загрузка векторов через API сервера батчами
    
    Args:
        collection_name: Название коллекции
        embeddings: Массив эмбеддингов
        metadata_df: DataFrame с метаданными
        server_url: URL сервера
        batch_size: Размер батча для загрузки
    """
    total_records = len(embeddings)
    logger.info(f"📤 Загрузка {total_records} записей через API (батчи по {batch_size})...")
    
    uploaded_count = 0
    
    for i in tqdm(range(0, total_records, batch_size), desc="📦 Загрузка батчами"):
        batch_end = min(i + batch_size, total_records)
        
        # Формируем батч точек
        points = []
        for idx in range(i, batch_end):
            # Генерируем уникальный ID
            point_id = str(uuid.uuid4())
            
            # Формируем payload
            payload = {
                "code": str(metadata_df.iloc[idx]["Код КСР"]),
                "description": str(metadata_df.iloc[idx]["full_path"]),
                "timestamp": time.time(),
                "source": "initial_load"
            }
            
            # Добавляем дополнительные поля если есть
            for col in metadata_df.columns:
                if col not in ["Код КСР", "full_path"]:
                    payload[col] = str(metadata_df.iloc[idx][col])
            
            points.append({
                "id": point_id,
                "vector": embeddings[idx].tolist(),
                "payload": payload
            })
        
        # Отправляем батч через API
        try:
            response = requests.post(
                f"{server_url}/upload_batch",
                params={"collection_name": collection_name},
                json=points,
                timeout=60
            )
            
            if response.status_code == 200:
                uploaded_count += len(points)
            else:
                logger.error(f"❌ Ошибка загрузки батча {i}-{batch_end}: {response.text}")
                raise Exception(f"Ошибка загрузки батча: {response.status_code}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки батча: {str(e)}")
            raise
    
    logger.info(f"✅ Загружено {uploaded_count} записей через API")


def update_vector_databases_config(
    collection_name: str,
    points_count: int,
    dimension: int,
    add_to_config: bool = True
):
    """
    Обновление файла конфигурации векторных баз
    
    Args:
        collection_name: Название коллекции
        points_count: Количество записей
        dimension: Размерность векторов
        add_to_config: Добавить в конфиг (можно отключить для тестовых баз)
    """
    if not add_to_config:
        logger.info("⏭️ Пропуск обновления конфига (флаг --no-config)")
        return
    
    logger.info(f"📝 Обновление конфигурации: {CONFIG_PATH}")
    
    # Загрузка существующего конфига
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
    else:
        logger.warning("⚠️ Конфиг не найден, создаем новый")
        config = {}
    
    # Проверяем существование базы в конфиге
    if collection_name in config:
        logger.info(f"🔄 Обновление существующей записи для '{collection_name}'")
        config[collection_name]["record_count"] = points_count
        config[collection_name]["dimension"] = dimension
    else:
        logger.info(f"➕ Добавление новой записи для '{collection_name}'")
        
        # Определяем параметры новой базы
        config[collection_name] = {
            "description": f"Векторная база {collection_name} ({points_count} записей)",
            "columns": {
                "code": "code",
                "description": "description"
            },
            "thresholds": {
                "cosine": 0.45,
                "rerank": 0.6
            }
        }
    
    # Сохранение обновленного конфига
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    logger.info(f"✅ Конфигурация обновлена: {CONFIG_PATH}")


def notify_server_about_new_db(
    collection_name: str, 
    server_url: str = DEFAULT_SERVER_URL
):
    """
    Уведомление сервера о новой базе для автоматической перезагрузки конфига
    
    Args:
        collection_name: Название новой коллекции
        server_url: URL сервера
    """
    try:
        logger.info(f"📡 Уведомление сервера о новой базе '{collection_name}'...")
        
        response = requests.post(
            f"{server_url}/reload_config",
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ Конфигурация сервера перезагружена")
            logger.info(f"   Доступно баз: {data['total_databases']}")
            logger.info(f"   Текущая база: {data['current_database']}")
            
            if data['changes']['added']:
                logger.info(f"   ➕ Добавлено: {', '.join(data['changes']['added'])}")
        else:
            logger.warning(f"⚠️ Сервер ответил с кодом {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        logger.warning("⚠️ Сервер недоступен для перезагрузки конфига")
        logger.info("💡 Конфиг обновлен локально, перезапустите сервер или вызовите:")
        logger.info(f"   curl -X POST {server_url}/reload_config")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось уведомить сервер: {str(e)}")


def main():
    """Основная функция скрипта"""
    
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(
        description="Создание новой коллекции Qdrant через API сервера"
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(DEFAULT_INPUT_PATH),
        help="Путь к CSV файлу с данными"
    )
    parser.add_argument(
        "--collection",
        type=str,
        required=True,
        help="Название коллекции Qdrant"
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Удалить существующую коллекцию если существует"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help="Размер батча для генерации эмбеддингов"
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help="НЕ добавлять базу в vector_databases.json (для тестовых баз)"
    )
    parser.add_argument(
        "--server-url",
        type=str,
        default=DEFAULT_SERVER_URL,
        help="URL сервера API"
    )
    
    args = parser.parse_args()
    
    # Начало работы
    start_time = time.time()
    logger.info("=" * 80)
    logger.info("🚀 СОЗДАНИЕ НОВОЙ КОЛЛЕКЦИИ QDRANT ЧЕРЕЗ API")
    logger.info("=" * 80)
    logger.info(f"📂 Входной файл: {args.input}")
    logger.info(f"📚 Коллекция: {args.collection}")
    logger.info(f"🔄 Пересоздание: {'Да' if args.recreate else 'Нет'}")
    logger.info(f"📝 Обновление конфига: {'Нет (--no-config)' if args.no_config else 'Да'}")
    logger.info(f"🌐 Сервер: {args.server_url}")
    logger.info("=" * 80)
    
    try:
        # Шаг 1: Проверка подключения к серверу
        if not check_server_connection(args.server_url):
            logger.error("❌ Сервер недоступен. Запустите сервер и повторите.")
            sys.exit(1)
        
        # Шаг 2: Загрузка данных из CSV
        csv_path = Path(args.input)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV файл не найден: {csv_path}")
        
        df = load_csv_data(csv_path)
        
        # Шаг 3: Инициализация генератора эмбеддингов
        generator = EmbeddingGenerator(model_path=QWEN_MODEL_PATH)
        
        # Шаг 4: Генерация эмбеддингов
        logger.info("🔄 Начало генерации эмбеддингов...")
        texts = df['full_path'].tolist()
        embeddings = generator.generate_all(texts, batch_size=args.batch_size)
        
        dimension = embeddings.shape[1]
        logger.info(f"✅ Сгенерировано {len(embeddings)} эмбеддингов, размерность: {dimension}")
        
        # Шаг 5: Создание коллекции через API
        if not create_collection_via_api(
            collection_name=args.collection,
            dimension=dimension,
            description=f"Векторная база {args.collection}",
            recreate=args.recreate,
            server_url=args.server_url
        ):
            logger.error("❌ Не удалось создать коллекцию через API")
            sys.exit(1)
        
        # Шаг 6: Загрузка данных через API
        upload_batch_via_api(
            collection_name=args.collection,
            embeddings=embeddings,
            metadata_df=df,
            server_url=args.server_url
        )
        
        # Шаг 7: Обновление конфигурации
        update_vector_databases_config(
            collection_name=args.collection,
            points_count=len(embeddings),
            dimension=dimension,
            add_to_config=not args.no_config
        )
        
        # Шаг 8: Уведомление сервера о новой базе
        if not args.no_config:
            notify_server_about_new_db(args.collection, args.server_url)
        
        # Итоговая статистика
        logger.info("=" * 80)
        logger.info("✅ УСПЕШНОЕ ЗАВЕРШЕНИЕ")
        logger.info("=" * 80)
        logger.info(f"📊 Коллекция: {args.collection}")
        logger.info(f"📈 Количество записей: {len(embeddings)}")
        logger.info(f"📐 Размерность: {dimension}")
        logger.info(f"⏱️ Время выполнения: {time.time() - start_time:.2f} секунд")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error("=" * 80)
        logger.error("❌ ОШИБКА ВЫПОЛНЕНИЯ")
        logger.error("=" * 80)
        logger.error(f"Ошибка: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        logger.error("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
