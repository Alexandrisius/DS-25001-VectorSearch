# 03_update_qdrant_collection.py
"""
Скрипт умного обновления существующей коллекции Qdrant через API с расширенным логированием

Pipeline:
1. Загрузка новых/обновленных данных из CSV
2. Получение текущего состояния коллекции через API
3. Умное определение изменений (с нормализацией переносов строк и пробелов)
4. Отправка обновлений через API эндпоинты на работающий сервер
5. Инкрементальное обновление без остановки сервера (hot update)

Использование (Windows PowerShell):
    # Реальное обновление
    # Важно: Используйте кавычки для путей и URL
    python scripts/pipelines/03_update_qdrant_collection.py --input "data/02_interim/KSR_clean_2.csv" --collection "ksr_main_2" --server "http://localhost:8000"

    # Предпросмотр изменений (без применения)
    python scripts/pipelines/03_update_qdrant_collection.py --input "data/02_interim/KSR_clean.csv" --collection "ksr_main" --dry-run

    # Обновление БЕЗ удаления отсутствующих записей
    python scripts/pipelines/03_update_qdrant_collection.py --input "data/02_interim/KSR_clean.csv" --collection "ksr_main" --no-delete

Автор: Alexandr
Дата: 2025-11-25
"""

import os
import sys
import argparse
import pandas as pd
import requests
import json
from pathlib import Path
from datetime import datetime
from tqdm import tqdm
import time
import logging
from typing import Dict, List, Tuple
import re

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === КОНФИГУРАЦИЯ ПУТЕЙ ===
PROJECT_ROOT = Path("C:/Users/klim9/Yandex.Disk/02_Work/#Projects/04_DataScience/DS-25001-VectorSearch")
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "02_interim" / "KSR_clean_2.csv"
DEFAULT_SERVER_URL = "http://localhost:8000"


class QdrantUpdater:
    """
    Класс для умного обновления коллекции Qdrant через API
    
    Особенности:
    - Работает с запущенным сервером (hot update)
    - Автоматическое определение изменений (умное сравнение)
    - Нормализация текста (переносы строк, пробелы, регистр)
    - Батчевая обработка для производительности
    - Расширенное логирование каждой операции
    """
    
    def __init__(self, server_url: str, collection_name: str):
        """
        Инициализация updater
        
        Args:
            server_url: URL сервера (например, http://localhost:8000)
            collection_name: Название коллекции для обновления
        """
        self.server_url = server_url.rstrip('/')
        self.collection_name = collection_name
        
        # Проверка доступности сервера
        self._check_server_health()
        
        logger.info(f"✅ Подключен к серверу: {self.server_url}")
        logger.info(f"🎯 Целевая коллекция: {self.collection_name}")
    
    def _check_server_health(self):
        """Проверка работоспособности сервера"""
        try:
            response = requests.get(f"{self.server_url}/health", timeout=5)
            response.raise_for_status()
            
            health_data = response.json()
            logger.info(f"🏥 Сервер работает: {health_data.get('status')}")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Сервер недоступен: {str(e)}")
            logger.error(f"💡 Убедитесь что сервер запущен на {self.server_url}")
            sys.exit(1)
    
    def get_existing_records(self) -> Dict[str, str]:
        """
        Получение словаря {код: описание} из текущей коллекции через API
        
        Использует endpoint /get_all_codes который возвращает:
        - Qdrant поле "code" → ключ словаря
        - Qdrant поле "description" → значение словаря
        
        Returns:
            Dict[str, str]: Словарь {код: описание}
        """
        logger.info("📥 Получение существующих записей через API...")
        
        try:
            response = requests.get(
                f"{self.server_url}/get_all_codes",
                params={"database": self.collection_name},
                timeout=300
            )
            response.raise_for_status()
            
            data = response.json()
            existing_records = data.get("records", {})
            elapsed = data.get("elapsed_seconds", 0)
            
            logger.info("=" * 80)
            logger.info(f"✅ Получено {len(existing_records)} записей через API")
            logger.info(f"⏱️ Время запроса: {elapsed}с")
            logger.info("=" * 80)
            
            return existing_records
            
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout при получении записей (превышено 5 минут)")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка получения данных через API: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка обработки ответа: {str(e)}")
            raise
    
    def update_record(self, code: str, description: str) -> bool:
        """
        Обновление одной записи через API
        
        Args:
            code: Код КСР
            description: Описание (full_path)
            
        Returns:
            bool: True если успешно
        """
        try:
            response = requests.post(
                f"{self.server_url}/update_record",
                json={
                    "code": code,
                    "description": description,
                    "database": self.collection_name
                },
                timeout=30
            )
            response.raise_for_status()
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка обновления {code}: {str(e)}")
            return False
    
    def batch_update_api(self, records: List[Tuple[str, str]]) -> bool:
        """
        Отправка пачки записей на сервер через /update_batch_records
        """
        try:
            # Формируем payload
            payload = {
                "database": self.collection_name,
                "records": [
                    {"code": code, "description": desc}
                    for code, desc in records
                ]
            }
            
            response = requests.post(
                f"{self.server_url}/update_batch_records",
                json=payload,
                timeout=300  # Увеличенный таймаут для обработки батча
            )
            response.raise_for_status()
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка отправки батча: {str(e)}")
            return False
            
    def batch_delete_api(self, codes: List[str]) -> bool:
        """
        Отправка пачки кодов на удаление через /delete_batch_records
        """
        try:
            payload = {
                "database": self.collection_name,
                "codes": codes
            }
            
            response = requests.post(
                f"{self.server_url}/delete_batch_records",
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка пакетного удаления: {str(e)}")
            return False
    
    def delete_record(self, code: str) -> bool:
        """
        Удаление записи через API
        
        Args:
            code: Код КСР для удаления
            
        Returns:
            bool: True если успешно
        """
        try:
            response = requests.delete(
                f"{self.server_url}/delete_record/{code}",
                params={"database": self.collection_name},
                timeout=10
            )
            response.raise_for_status()
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка удаления {code}: {str(e)}")
            return False
    
    def batch_update(
        self, 
        records: List[Tuple[str, str]], 
        operation: str = "update",
        existing_records: Dict[str, str] = None,
        batch_size: int = 32
    ) -> Dict:
        """
        Батчевое обновление/удаление записей с детальным логированием
        
        Args:
            records: Список кортежей (code, description) для обновления
                     или список кодов для удаления
            operation: "update" или "delete"
            existing_records: Словарь существующих записей (для логирования)
            batch_size: Размер пачки для отправки на сервер
        """
        stats = {
            "total": len(records),
            "success": 0,
            "failed": 0,
            "failed_codes": []
        }
        
        desc = "🔄 Обновление (Batch)" if operation == "update" else "🗑️ Удаление (Single)"
        
        # Заголовок перед началом операций
        logger.info("\n" + "=" * 80)
        logger.info(f"{desc}: {len(records)} записей, размер батча: {batch_size}")
        logger.info("=" * 80 + "\n")
        
        # Разбиваем на чанки (батчи)
        chunks = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
        
        for chunk in tqdm(chunks, desc=desc):
            if operation == "update":
                # Отправляем весь чанк одним запросом
                if self.batch_update_api(chunk):
                    stats["success"] += len(chunk)
                else:
                    stats["failed"] += len(chunk)
                    stats["failed_codes"].extend([r[0] for r in chunk])
            else:  # delete
                # FIX: Используем пакетное удаление
                if self.batch_delete_api(chunk):
                    stats["success"] += len(chunk)
                else:
                    stats["failed"] += len(chunk)
                    stats["failed_codes"].extend(chunk)
            # Убрали time.sleep(0.01) - он не нужен
        
        # Итоговая статистика операций
        logger.info("=" * 80)
        logger.info(f"✅ ЗАВЕРШЕНО")
        logger.info(f"   Успешно: {stats['success']}")
        logger.info(f"   Ошибок: {stats['failed']}")
        if stats['failed'] > 0:
            logger.warning(f"   Коды с ошибками (первые 10): {stats['failed_codes'][:10]}...")
        logger.info("=" * 80 + "\n")
        
        return stats


def normalize_text(text: str) -> str:
    """
    Полная нормализация текста для сравнения
    
    Убирает все различия которые не влияют на смысл:
    - Разные переносы строк (Windows \\r\\n vs Unix \\n)
    - Множественные пробелы и табуляции
    - Пробелы в начале/конце строк
    - Пустые строки
    - Разный регистр
    """
    text = text.lower()
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[ \t]+', ' ', text)
    lines = text.split('\n')
    lines = [line.strip() for line in lines]
    lines = [line for line in lines if line]
    text = '\n'.join(lines)
    text = text.strip()
    return text


def load_csv_data(csv_path: Path) -> pd.DataFrame:
    """Загрузка данных из CSV файла"""
    logger.info(f"📂 Загрузка данных из: {csv_path}")
    df = pd.read_csv(csv_path, sep=';', encoding='utf-8')
    logger.info(f"✅ Загружено {len(df)} записей")
    
    required_columns = ['Код КСР', 'full_path']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        logger.error(f"❌ Отсутствуют обязательные колонки: {missing_columns}")
        raise ValueError(f"Отсутствуют обязательные колонки: {missing_columns}")
    
    original_len = len(df)
    df = df.drop_duplicates(subset=['Код КСР'], keep='first')
    
    if len(df) < original_len:
        logger.warning(f"⚠️ Удалено {original_len - len(df)} дубликатов")
    
    df = df.dropna(subset=['Код КСР', 'full_path'])
    logger.info(f"✅ После очистки: {len(df)} записей")
    
    return df


def analyze_changes(
    new_df: pd.DataFrame,
    existing_records: Dict[str, str]
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]], List[str]]:
    """Умный анализ изменений с проверкой содержимого"""
    
    required_csv_columns = ['Код КСР', 'full_path']
    missing_columns = [col for col in required_csv_columns if col not in new_df.columns]
    
    if missing_columns:
        logger.error(f"❌ В CSV отсутствуют обязательные колонки: {missing_columns}")
        raise ValueError(f"Отсутствуют колонки: {missing_columns}")
    
    logger.info(f"✅ CSV структура корректна: {required_csv_columns}")
    logger.info(f"📊 Qdrant содержит {len(existing_records)} записей")
    
    if existing_records:
        sample_code = list(existing_records.keys())[0]
        sample_desc = existing_records[sample_code]
        logger.info(f"🔍 Пример из Qdrant: code='{sample_code}', description='{sample_desc[:50]}...'")
    
    if len(new_df) > 0:
        sample_row = new_df.iloc[0]
        logger.info(f"🔍 Пример из CSV: Код КСР='{sample_row['Код КСР']}', full_path='{sample_row['full_path'][:50]}...'")
    
    logger.info("🔍 Умный анализ изменений (с полной нормализацией текста)...")
    
    new_codes = set(str(code) for code in new_df['Код КСР'].values)
    existing_codes = set(str(code) for code in existing_records.keys())
    
    logger.info(f"📊 Уникальных кодов в CSV: {len(new_codes)}")
    logger.info(f"📊 Уникальных кодов в Qdrant: {len(existing_codes)}")
    
    # === 1. НОВЫЕ ЗАПИСИ ===
    new_records_codes = new_codes - existing_codes
    new_records = [
        (str(row['Код КСР']), str(row['full_path']))
        for _, row in new_df.iterrows()
        if str(row['Код КСР']) in new_records_codes
    ]
    
    # === 2. ОБНОВЛЕННЫЕ ЗАПИСИ ===
    updated_records = []
    unchanged_count = 0
    
    for _, row in new_df.iterrows():
        code = str(row['Код КСР'])
        new_desc = str(row['full_path'])
        
        if code in existing_codes:
            old_desc = str(existing_records.get(code, ""))
            old_normalized = normalize_text(old_desc)
            new_normalized = normalize_text(new_desc)
            
            if old_normalized != new_normalized:
                updated_records.append((code, new_desc))
            else:
                unchanged_count += 1
    
    # === 3. УДАЛЕННЫЕ ЗАПИСИ ===
    deleted_codes = list(existing_codes - new_codes)
    
    if deleted_codes:
        logger.info("\n" + "=" * 80)
        logger.info("🗑️ НАЙДЕНЫ ЗАПИСИ ДЛЯ УДАЛЕНИЯ")
        logger.info("=" * 80)
        logger.info(f"Количество: {len(deleted_codes)}")
        logger.info(f"\n📋 Подробная информация о каждой удаляемой записи:\n")
        
        for i, code in enumerate(deleted_codes, 1):
            description = existing_records.get(code, "")
            logger.info(f"{i}. Код: {code}")
            logger.info(f"   Описание: {description[:150]}...")
            logger.info(f"   Полная длина: {len(description)} символов\n")
        
        logger.info("=" * 80)
    
    # === ИТОГОВАЯ СТАТИСТИКА ===
    logger.info("=" * 80)
    logger.info("📊 УМНЫЙ АНАЛИЗ ИЗМЕНЕНИЙ")
    logger.info("=" * 80)
    logger.info(f"➕ Новых записей: {len(new_records)}")
    logger.info(f"🔄 Реально измененных записей: {len(updated_records)}")
    logger.info(f"✅ Без изменений (пропущено): {unchanged_count}")
    logger.info(f"➖ Удаленных записей: {len(deleted_codes)}")
    
    if deleted_codes:
        logger.info(f"\n🗑️ Коды для удаления:")
        for code in deleted_codes:
            logger.info(f"   - {code}")
    
    logger.info(f"\n📊 Итого операций: {len(new_records) + len(updated_records) + len(deleted_codes)}")
    logger.info("=" * 80)
    
    return new_records, updated_records, deleted_codes


def update_config_timestamp(collection_name: str, project_root: Path):
    """Обновление даты в конфигурационном файле"""
    config_path = project_root / "src" / "vector_databases.json"
    
    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if collection_name in config:
                # Формат даты DD.MM.YYYY
                current_date = datetime.now().strftime("%d.%m.%Y")
                config[collection_name]['last_updated'] = current_date
                
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                
                logger.info(f"📅 Дата обновления ({current_date}) записана в конфиг")
                return True
            else:
                logger.warning(f"⚠️ Коллекция {collection_name} не найдена в конфиге для обновления даты")
    except Exception as e:
        logger.error(f"❌ Не удалось обновить дату в конфиге: {e}")
        return False

def reload_server_config(server_url: str):
    """Команда серверу перечитать конфиг"""
    try:
        response = requests.post(f"{server_url}/reload_config", timeout=5)
        if response.status_code == 200:
            logger.info("♻️ Конфигурация сервера успешно перезагружена")
        else:
            logger.warning(f"⚠️ Сервер не перезагрузил конфиг: {response.status_code}")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось перезагрузить конфиг сервера: {e}")


def main():
    """Основная функция скрипта"""
    
    parser = argparse.ArgumentParser(
        description="Умное обновление коллекции Qdrant через API (hot update)"
    )
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT_PATH))
    parser.add_argument("--collection", type=str, required=True, nargs='?', help="Название коллекции")
    parser.add_argument("--server", type=str, default=DEFAULT_SERVER_URL)
    parser.add_argument("--no-delete", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    
    # === АВТОМАТИЧЕСКАЯ НАСТРОЙКА ДЛЯ ЗАПУСКА БЕЗ АРГУМЕНТОВ ===
    if len(sys.argv) == 1:
        print("⚠️  ЗАПУСК БЕЗ АРГУМЕНТОВ (режим Play button)")
        print("ℹ️  Используются настройки по умолчанию для отладки.")
        
        # ЗДЕСЬ МОЖНО НАСТРОИТЬ ПАРАМЕТРЫ ПО УМОЛЧАНИЮ
        default_args = [
            "--input", str(DEFAULT_INPUT_PATH),
            "--collection", "ksr_main_2"
        ]
        print(f"ℹ️  Аргументы: {' '.join(default_args)}")
        args = parser.parse_args(default_args)
    else:
        args = parser.parse_args()
    
    # Проверка обязательного аргумента collection, если он не был передан (для случая когда sys.argv > 1 но collection забыли)
    if not args.collection and len(sys.argv) > 1:
        parser.error("the following arguments are required: --collection")

    
    start_time = time.time()
    logger.info("=" * 80)
    logger.info("🔄 УМНОЕ ОБНОВЛЕНИЕ КОЛЛЕКЦИИ QDRANT (HOT UPDATE)")
    logger.info("=" * 80)
    logger.info(f"📂 Входной файл: {args.input}")
    logger.info(f"📚 Коллекция: {args.collection}")
    logger.info(f"🌐 Сервер: {args.server}")
    logger.info(f"🗑️ Удаление: {'❌ ОТКЛЮЧЕНО' if args.no_delete else '✅ ВКЛЮЧЕНО'}")
    logger.info(f"🔍 Режим: {'DRY RUN' if args.dry_run else 'РЕАЛЬНОЕ ОБНОВЛЕНИЕ'}")
    logger.info("=" * 80)
    
    try:
        csv_path = Path(args.input)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV файл не найден: {csv_path}")
        
        new_df = load_csv_data(csv_path)
        
        updater = QdrantUpdater(
            server_url=args.server,
            collection_name=args.collection
        )
        
        existing_records = updater.get_existing_records()
        
        new_records, updated_records, deleted_codes = analyze_changes(
            new_df=new_df,
            existing_records=existing_records
        )
        
        total_operations = len(new_records) + len(updated_records)
        if not args.no_delete:
            total_operations += len(deleted_codes)
        
        if total_operations == 0:
            logger.info("=" * 80)
            logger.info("✅ ИЗМЕНЕНИЙ НЕ ОБНАРУЖЕНО")
            logger.info("=" * 80)
            logger.info("📊 Коллекция полностью актуальна!")
            logger.info(f"⏱️ Время выполнения: {time.time() - start_time:.2f} сек")
            
            # === ОБНОВЛЕНИЕ ДАТЫ И ПЕРЕЗАГРУЗКА КОНФИГА ===
            if not args.dry_run:
                update_config_timestamp(args.collection, PROJECT_ROOT)
                reload_server_config(args.server)
                
            logger.info("=" * 80)
            return
        
        if args.dry_run:
            logger.info("=" * 80)
            logger.info("🔍 DRY RUN: Изменения НЕ будут применены")
            logger.info("=" * 80)
            
            if new_records:
                logger.info(f"\n➕ НОВЫЕ ЗАПИСИ ({len(new_records)}):")
                for code, desc in new_records[:10]:
                    logger.info(f"   {code}: {desc[:80]}...")
                if len(new_records) > 10:
                    logger.info(f"   ... и еще {len(new_records) - 10} записей")
            
            if updated_records:
                logger.info(f"\n🔄 ОБНОВЛЕННЫЕ ЗАПИСИ ({len(updated_records)}):")
                for code, desc in updated_records[:10]:
                    logger.info(f"   {code}: {desc[:80]}...")
                if len(updated_records) > 10:
                    logger.info(f"   ... и еще {len(updated_records) - 10} записей")
            
            if deleted_codes and not args.no_delete:
                logger.info(f"\n➖ УДАЛЕННЫЕ КОДЫ ({len(deleted_codes)}):")
                for code in deleted_codes[:10]:
                    logger.info(f"   {code}")
                if len(deleted_codes) > 10:
                    logger.info(f"   ... и еще {len(deleted_codes) - 10} кодов")
            
            if deleted_codes and args.no_delete:
                logger.info(f"\n⚠️ НАЙДЕНО {len(deleted_codes)} записей для удаления,")
                logger.info(f"   но удаление ОТКЛЮЧЕНО флагом --no-delete")
            
            logger.info("=" * 80)
            return
        
        # Применение изменений
        logger.info(f"\n🚀 Начало применения {total_operations} операций...\n")
        
        stats_new = stats_updated = stats_deleted = None
        
        if new_records:
            stats_new = updater.batch_update(
                new_records, 
                operation="update",
                existing_records=existing_records
            )
        
        if updated_records:
            # === ДОКУМЕНТАЦИЯ ПРОБЛЕМЫ "ФАНТОМНЫХ ОБНОВЛЕНИЙ" ===
            # Почему мы делаем delete перед update?
            # Проблема: Если ID существующей записи в Qdrant (например, исторической)
            # отличается от того, который генерирует скрипт (uuid5 от кода),
            # то обычный upsert создаст дубликат, а старая запись останется.
            # Скрипт будет видеть старую запись вечно и пытаться её обновить.
            # Решение: Принудительное удаление по коду (delete_batch) гарантирует,
            # что мы убираем старую версию с любым ID перед записью новой.
            # ======================================================
            logger.info(f"🧹 Предварительная очистка {len(updated_records)} записей для корректного обновления ID...")
            codes_to_refresh = [r[0] for r in updated_records]
            updater.batch_update(
                codes_to_refresh, 
                operation="delete",
                existing_records=existing_records,
                batch_size=50 # Можно чуть быстрее удалять
            )

            stats_updated = updater.batch_update(
                updated_records, 
                operation="update",
                existing_records=existing_records
            )
        
        if deleted_codes and not args.no_delete:
            stats_deleted = updater.batch_update(
                deleted_codes, 
                operation="delete",
                existing_records=existing_records
            )
        elif deleted_codes and args.no_delete:
            logger.warning("=" * 80)
            logger.warning(f"⚠️ ПРОПУЩЕНО: {len(deleted_codes)} записей для удаления")
            logger.warning("   Удаление ОТКЛЮЧЕНО флагом --no-delete")
            for code in deleted_codes:
                logger.warning(f"   - {code}")
            logger.warning("=" * 80 + "\n")
        
        # Итоговая статистика
        logger.info("=" * 80)
        logger.info("✅ ОБНОВЛЕНИЕ ЗАВЕРШЕНО")
        logger.info("=" * 80)
        
        total_success = 0
        total_failed = 0
        
        if stats_new:
            total_success += stats_new['success']
            total_failed += stats_new['failed']
            logger.info(f"➕ Добавлено: {stats_new['success']}")
        
        if stats_updated:
            total_success += stats_updated['success']
            total_failed += stats_updated['failed']
            logger.info(f"🔄 Обновлено: {stats_updated['success']}")
        
        if stats_deleted:
            total_success += stats_deleted['success']
            total_failed += stats_deleted['failed']
            logger.info(f"🗑️ Удалено: {stats_deleted['success']}")
        
        if deleted_codes and args.no_delete:
            logger.info(f"⚠️ Пропущено удаление: {len(deleted_codes)} записей")
        
        logger.info(f"\n📊 Итого успешных операций: {total_success}")
        if total_failed > 0:
            logger.warning(f"❌ Итого ошибок: {total_failed}")
        
        logger.info(f"⏱️ Время: {time.time() - start_time:.2f} сек")
        logger.info(f"📚 Коллекция '{args.collection}' обновлена")
        
        # === ОБНОВЛЕНИЕ ДАТЫ И ПЕРЕЗАГРУЗКА КОНФИГА ===
        if not args.dry_run:
            update_config_timestamp(args.collection, PROJECT_ROOT)
            reload_server_config(args.server)
            
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
