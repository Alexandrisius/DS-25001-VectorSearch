
import sys
import os
import json
import asyncio
import logging
import time
import httpx
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

# Запуск из корня проекта:
# python scripts/service/reindex_folders_v2.py

# === НАСТРОЙКА ПУТЕЙ ===
# Добавляем корень проекта в sys.path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))

from src.config import (
    QDRANT_STORAGE_PATH, 
    VECTOR_DATABASES_CONFIG, 
    API_EMBEDDING_BATCH_SIZE, 
    API_MAX_WORKERS
)

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# === КОНСТАНТЫ ===
COLLECTION_NAME = "ksr_main" # Можно поменять или спрашивать аргументом

# === ФУНКЦИИ ИЗ СЕРВЕРА (КОПИЯ) ===

def extract_folders_from_records(records: List[Dict], separator: str = " → ") -> List[Dict]:
    """
    Извлекает уникальные папки из списка записей материалов.
    """
    folders_map = {} # full_path -> {data}

    for record in records:
        path_depth = record.get("path_depth", 0)
        if not path_depth:
            continue
            
        # Собираем путь
        current_parts = []
        for i in range(1, path_depth + 1):
            part = record.get(f"path_level_{i}")
            if not part:
                continue
            
            current_parts.append(part)
            
            # Регистрируем папку для текущего уровня
            full_path = separator.join(current_parts)
            level = len(current_parts)
            
            if full_path not in folders_map:
                # Генерируем path_levels для самой папки
                path_levels = {}
                for k, p in enumerate(current_parts):
                    path_levels[f"path_level_{k+1}"] = p
                
                folders_map[full_path] = {
                    "full_path": full_path,
                    "leaf_name": part,
                    "level": level,
                    "path_depth": level,
                    "path_levels": path_levels,
                    "items_count": 0
                }
            
            # Увеличиваем счетчик элементов в этой папке?
            # В оригинале items_count считается хитрее, но здесь нам важно создать саму запись
            # Для простоты пока оставим 0 или 1, всё равно update_counts потом пересчитает если надо
            folders_map[full_path]["items_count"] += 1

    return list(folders_map.values())

# === OPENROUTER API CLIENT ===

async def get_embeddings_openrouter(texts: List[str], api_key: str, model: str) -> List[List[float]]:
    """
    Генерация эмбеддингов через OpenRouter API.
    """
    if not texts:
        return []
        
    url = "https://openrouter.ai/api/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ksr-matcher.local",
        "X-Title": "KSR Matcher Script"
    }
    
    # Обработка пустых строк
    cleaned_texts = [t.strip() if t.strip() else "пусто" for t in texts]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "input": cleaned_texts
                }
            )
            
            if response.status_code != 200:
                logger.error(f"❌ API Error {response.status_code}: {response.text}")
                return []
                
            data = response.json()
            embeddings = []
            
            # Сортировка по индексу
            sorted_data = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            
            for item in sorted_data:
                emb = item.get("embedding", [])
                # Нормализация
                if emb:
                    v = np.array(emb, dtype=np.float32)
                    norm = np.linalg.norm(v)
                    if norm > 0:
                        v = v / norm
                    embeddings.append(v.tolist())
                else:
                    embeddings.append([])
            
            return embeddings
            
        except Exception as e:
            logger.error(f"❌ Connection Error: {e}")
            return []

# === MAIN LOGIC ===

async def main():
    print("="*60)
    print("🚀 СКРИПТ ПЕРЕИНДЕКСАЦИИ ПАПОК (OPENROUTER)")
    print("="*60)
    
    # 1. Загрузка конфига
    if not os.path.exists(VECTOR_DATABASES_CONFIG):
        logger.error(f"❌ Конфиг не найден: {VECTOR_DATABASES_CONFIG}")
        return

    with open(VECTOR_DATABASES_CONFIG, "r", encoding="utf-8") as f:
        config_data = json.load(f)
        
    settings = config_data.get("_settings", {})
    openrouter = settings.get("openrouter", {})
    
    if not openrouter.get("enabled"):
        logger.warning("⚠️ OpenRouter выключен в настройках! Включите его в админке или отредактируйте vector_databases.json")
        # Но продолжаем, если API ключ есть
        
    api_key = openrouter.get("api_key")
    model = openrouter.get("model", "qwen/qwen3-embedding-4b")
    
    if not api_key:
        logger.error("❌ OpenRouter API Key не найден в конфигурации!")
        return
        
    logger.info(f"🔑 API Key: {api_key[:5]}...***")
    logger.info(f"🧠 Model: {model}")
    
    # 2. Подключение к Qdrant
    logger.info(f"🔌 Подключение к Qdrant: {QDRANT_STORAGE_PATH}")
    logger.warning("⚠️ ВНИМАНИЕ: Если сервер запущен, остановите его, чтобы избежать блокировки БД!")
    try:
        client = QdrantClient(path=str(QDRANT_STORAGE_PATH))
        collections = client.get_collections().collections
        logger.info(f"📚 Найдено коллекций: {len(collections)}")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Qdrant (возможно заблокирован сервером): {e}")
        return

    # Проверяем коллекцию
    exists = any(c.name == COLLECTION_NAME for c in collections)
    if not exists:
        logger.error(f"❌ Коллекция '{COLLECTION_NAME}' не найдена!")
        return
        
    # 3. Загрузка всех материалов
    logger.info("📥 Загрузка всех материалов...")
    
    all_records = []
    offset = None
    
    # Получаем максимальное количество уровней
    # Предполагаем 10
    payload_fields = ["code", "path_depth"] + [f"path_level_{i}" for i in range(1, 11)]
    
    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=1000,
            offset=offset,
            with_payload=payload_fields,
            with_vectors=False,
            scroll_filter=Filter(
                must_not=[FieldCondition(key="is_folder", match=MatchValue(value=True))]
            )
        )
        
        for p in points:
            all_records.append(p.payload)
            
        if next_offset is None:
            break
            
        offset = next_offset
        print(f"   ...загружено {len(all_records)} записей", end="\r")
        
    print(f"\n✅ Всего материалов: {len(all_records)}")
    
    # 4. Извлечение папок
    logger.info("📂 Извлечение уникальных папок...")
    folders = extract_folders_from_records(all_records)
    logger.info(f"✅ Найдено уникальных папок: {len(folders)}")
    
    # 5. Генерация векторов и сохранение
    logger.info(f"🧠 Генерация векторов и запись (Batch size: {API_EMBEDDING_BATCH_SIZE})...")
    
    batch_size = API_EMBEDDING_BATCH_SIZE
    total_folders = len(folders)
    
    for i in range(0, total_folders, batch_size):
        batch = folders[i : i + batch_size]
        
        # Подготовка текстов для эмбеддинга (full_path)
        texts = [f.get("full_path", "") for f in batch]
        
        logger.info(f"   Batch {i // batch_size + 1}: обработка {len(batch)} папок...")
        
        # Получаем вектора
        vectors = await get_embeddings_openrouter(texts, api_key, model)
        
        if not vectors or len(vectors) != len(batch):
            logger.error(f"❌ Ошибка генерации векторов для батча {i}")
            continue
            
        # Подготовка точек для Upsert
        points = []
        import uuid
        import time
        
        for folder_data, vector in zip(batch, vectors):
            if not vector:
                continue
                
            full_path = folder_data["full_path"]
            # ID генерируем детерминировано из пути
            folder_code = f"folder::{full_path.replace(' → ', '::')}"
            folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code))
            
            # Payload
            payload = {
                "code": folder_code,
                "description": full_path, # Legacy
                "full_path": full_path,
                "is_folder": True,
                "items_count": folder_data["items_count"],
                "leaf_name": folder_data["leaf_name"],
                "path_depth": folder_data["path_depth"],
                "timestamp": time.time(),
                "source": "reindex_script",
                **folder_data["path_levels"]
            }
            
            points.append(PointStruct(
                id=folder_id,
                vector=vector,
                payload=payload
            ))
            
        # Запись в базу
        try:
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )
            # Небольшая пауза чтобы не спамить API слишком сильно
            await asyncio.sleep(0.5) 
            
        except Exception as e:
            logger.error(f"❌ Ошибка записи батча: {e}")
            
    logger.info("✅ ГОТОВО! Все папки переиндексированы.")

if __name__ == "__main__":
    asyncio.run(main())
