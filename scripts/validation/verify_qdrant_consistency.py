import pandas as pd
import requests
import logging
import sys
import re
from pathlib import Path
from typing import Dict, Set
import argparse

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
SERVER_URL = "http://localhost:8000"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV_PATH = PROJECT_ROOT / "data" / "02_interim" / "KSR_clean.csv"

def normalize_text(text: str) -> str:
    """Нормализация для сравнения (как в скрипте обновления)"""
    text = str(text).lower()
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+', ' ', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines).strip()

def get_qdrant_data(collection: str) -> Dict[str, str]:
    """Получение всех данных из Qdrant"""
    logger.info(f"📥 Загрузка данных из Qdrant ({collection})...")
    try:
        resp = requests.get(f"{SERVER_URL}/get_all_codes", params={"database": collection}, timeout=300)
        resp.raise_for_status()
        data = resp.json()
        return data.get("records", {})
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Qdrant: {e}")
        logger.error("Убедитесь, что сервер запущен (python src/server.py)")
        sys.exit(1)

def load_csv_data(path: Path) -> Dict[str, str]:
    """Загрузка данных из CSV"""
    logger.info(f"📂 Чтение CSV файла: {path}...")
    if not path.exists():
        logger.error(f"❌ Файл не найден: {path}")
        sys.exit(1)
        
    df = pd.read_csv(path, sep=';', encoding='utf-8')
    # Преобразуем в словарь {code: full_path}
    # Удаляем дубликаты кодов, оставляя первый (как при импорте)
    df = df.drop_duplicates(subset=['Код КСР'], keep='first')
    return dict(zip(df['Код КСР'].astype(str), df['full_path'].astype(str)))

def compare_data(csv_data: Dict[str, str], qdrant_data: Dict[str, str]):
    """Сравнение данных"""
    csv_codes = set(csv_data.keys())
    qdrant_codes = set(qdrant_data.keys())
    
    logger.info("="*60)
    logger.info("📊 РЕЗУЛЬТАТЫ ПРОВЕРКИ")
    logger.info("="*60)
    logger.info(f"CSV записей:    {len(csv_codes)}")
    logger.info(f"Qdrant записей: {len(qdrant_codes)}")
    
    # 1. Проверка кодов
    missing_in_qdrant = csv_codes - qdrant_codes
    extra_in_qdrant = qdrant_codes - csv_codes
    
    if not missing_in_qdrant and not extra_in_qdrant:
        logger.info("✅ Наборы кодов ПОЛНОСТЬЮ СОВПАДАЮТ")
    else:
        if missing_in_qdrant:
            logger.error(f"❌ Отсутствуют в Qdrant ({len(missing_in_qdrant)}):")
            for c in list(missing_in_qdrant)[:5]: logger.error(f"   - {c}")
            if len(missing_in_qdrant) > 5: logger.error("   ...")
            
        if extra_in_qdrant:
            logger.warning(f"⚠️ Лишние в Qdrant ({len(extra_in_qdrant)}):")
            for c in list(extra_in_qdrant)[:5]: logger.warning(f"   - {c}")
            if len(extra_in_qdrant) > 5: logger.warning("   ...")

    # 2. Проверка контента (только для общих кодов)
    common_codes = csv_codes.intersection(qdrant_codes)
    mismatches = []
    
    logger.info(f"🔍 Сверка описаний для {len(common_codes)} общих записей...")
    
    from tqdm import tqdm
    for code in tqdm(common_codes, desc="Sverka"):
        csv_desc = normalize_text(csv_data[code])
        qdrant_desc = normalize_text(qdrant_data[code])
        
        if csv_desc != qdrant_desc:
            mismatches.append((code, csv_data[code], qdrant_data[code]))
            
    if not mismatches:
        logger.info("✅ Описания ПОЛНОСТЬЮ СОВПАДАЮТ (с учетом нормализации)")
    else:
        logger.error(f"❌ Найдены различия в описаниях: {len(mismatches)} шт.")
        for code, csv_d, qdrant_d in mismatches[:5]:
            logger.error(f"   Код: {code}")
            logger.error(f"   CSV:    {csv_d[:100]}...")
            logger.error(f"   Qdrant: {qdrant_d[:100]}...")
            logger.error("-" * 40)
            
    logger.info("="*60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Сверка данных Qdrant с CSV")
    parser.add_argument("--collection", default="ksr_main", help="Название коллекции в Qdrant")
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH), help="Путь к CSV файлу")
    
    args = parser.parse_args()
    
    logger.info(f"Target collection: {args.collection}")
    logger.info(f"Reference CSV: {args.csv}")
    
    q_data = get_qdrant_data(args.collection)
    c_data = load_csv_data(Path(args.csv))
    compare_data(c_data, q_data)

