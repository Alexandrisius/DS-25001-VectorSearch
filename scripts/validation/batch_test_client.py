#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Клиент для массового тестирования векторного поиска
Запуск: python batch_test_client.py input.xlsx --top_n 5 --column "Текст запроса" --output results.xlsx
"""

import argparse
import pandas as pd
import requests
import time
import json
from tqdm import tqdm
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
import os
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VectorSearchTester:
    def __init__(self, base_url: str = "http://localhost:8000", max_workers: int = 5):
        """
        Инициализация тестера
        
        Args:
            base_url: URL вашего сервера
            max_workers: Максимальное количество параллельных запросов
        """
        self.base_url = base_url.rstrip('/')
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'VectorSearchTester/1.0'
        })
        
        # Проверяем доступность сервера
        self._check_server_availability()
    
    def _check_server_availability(self):
        """Проверяет доступность сервера перед началом тестирования"""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=5)
            response.raise_for_status()
            logger.info(f"✅ Сервер доступен: {response.json().get('status')}")
        except Exception as e:
            logger.error(f"❌ Сервер недоступен: {str(e)}")
            raise ConnectionError(f"Не удалось подключиться к серверу: {self.base_url}")
    
    def search_single_query(self, query_text: str, database: Optional[str] = None, top_n: int = 5) -> Dict[str, Any]:
        """
        Выполняет одиночный поиск по тексту
        
        Args:
            query_text: Текст для поиска
            database: Название базы (опционально)
            top_n: Количество результатов для возврата
        
        Returns:
            Словарь с результатами поиска
        """
        payload = {"text": query_text.strip()}
        if database:
            payload["database"] = database
        
        try:
            response = self.session.post(f"{self.base_url}/match", json=payload, timeout=30)
            response.raise_for_status()
            results = response.json()
            
            # Ограничиваем количество результатов до top_n
            limited_results = results["candidates"][:top_n]
            
            return {
                "success": True,
                "query": query_text,
                "total_candidates": len(results["candidates"]),
                "results": limited_results,
                "processing_time": results["processing_time"]
            }
        except requests.exceptions.RequestException as e:
            error_detail = "Неизвестная ошибка"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json().get("detail", str(e))
                except:
                    error_detail = e.response.text
            
            logger.warning(f"Запрос '{query_text}' завершился с ошибкой: {error_detail}")
            return {
                "success": False,
                "query": query_text,
                "error": str(error_detail),
                "results": []
            }
        except Exception as e:
            logger.warning(f"Неожиданная ошибка для запроса '{query_text}': {str(e)}")
            return {
                "success": False,
                "query": query_text,
                "error": str(e),
                "results": []
            }
    
    def process_batch(self, input_df: pd.DataFrame, query_column: str, top_n: int = 5, 
                     database: Optional[str] = None) -> pd.DataFrame:
        """
        Обрабатывает пакет запросов из DataFrame
        
        Args:
            input_df: DataFrame с исходными данными
            query_column: Название колонки с текстами для поиска
            top_n: Количество результатов для каждого запроса
            database: Название базы (опционально)
        
        Returns:
            DataFrame с добавленными результатами поиска
        """
        logger.info(f"🚀 Начало обработки {len(input_df)} запросов из колонки '{query_column}'")
        logger.info(f"⚙️ Параметры: top_n={top_n}, database={database or 'default'}, workers={self.max_workers}")
        
        # Создаем копию DataFrame для результатов
        results_df = input_df.copy()
        
        # Добавляем колонки для результатов
        for i in range(1, top_n + 1):
            results_df[f'rank_{i}'] = ''
            results_df[f'code_{i}'] = ''
            results_df[f'description_{i}'] = ''
            results_df[f'cosine_{i}'] = 0.0
            results_df[f'rerank_score_{i}'] = 0.0
        
        results_df['search_success'] = False
        results_df['error_message'] = ''
        results_df['total_candidates'] = 0
        results_df['processing_time'] = 0.0
        
        # Обработка в многопоточном режиме с прогресс-баром
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Отправляем все задачи
            future_to_idx = {
                executor.submit(self.search_single_query, row[query_column], database, top_n): idx
                for idx, row in input_df.iterrows()
            }
            
            # Собираем результаты с прогресс-баром
            for future in tqdm(as_completed(future_to_idx), total=len(future_to_idx), desc="🔍 Поиск"):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                    
                    # Обновляем статус
                    results_df.at[idx, 'search_success'] = result['success']
                    results_df.at[idx, 'processing_time'] = result.get('processing_time', 0.0)
                    
                    if result['success']:
                        results_df.at[idx, 'total_candidates'] = result['total_candidates']
                        
                        # Заполняем результаты для каждого ранга
                        for i, candidate in enumerate(result['results'], 1):
                            if i > top_n:
                                break
                            
                            results_df.at[idx, f'rank_{i}'] = candidate['rank']
                            results_df.at[idx, f'code_{i}'] = candidate['code']
                            results_df.at[idx, f'description_{i}'] = candidate['description']
                            results_df.at[idx, f'cosine_{i}'] = candidate['cosine_similarity']
                            results_df.at[idx, f'rerank_score_{i}'] = candidate['reranker_score']
                    else:
                        results_df.at[idx, 'error_message'] = result.get('error', 'Неизвестная ошибка')
                        
                except Exception as e:
                    logger.error(f"Критическая ошибка для строки {idx}: {str(e)}")
                    results_df.at[idx, 'search_success'] = False
                    results_df.at[idx, 'error_message'] = f"Критическая ошибка: {str(e)}"
                
                # Небольшая задержка между запросами для снижения нагрузки на сервер
                time.sleep(0.1)
        
        # Статистика
        success_count = results_df['search_success'].sum()
        logger.info(f"✅ Успешно обработано: {success_count}/{len(input_df)} запросов ({success_count/len(input_df)*100:.1f}%)")
        
        return results_df
    
    def get_available_databases(self) -> List[Dict[str, Any]]:
        """Получает список доступных баз данных с сервера"""
        try:
            response = self.session.get(f"{self.base_url}/databases", timeout=10)
            response.raise_for_status()
            return response.json().get("databases", [])
        except Exception as e:
            logger.error(f"Ошибка получения списка баз: {str(e)}")
            return []

def parse_arguments():
    """Парсит аргументы командной строки"""
    parser = argparse.ArgumentParser(description='Клиент для массового тестирования векторного поиска')
    
    parser.add_argument('input_file', type=str, help='Путь к входному Excel файлу')
    parser.add_argument('--output', type=str, default=None, 
                        help='Путь к выходному Excel файлу (по умолчанию: input_filename_results.xlsx)')
    parser.add_argument('--column', type=str, required=True, 
                        help='Название колонки с текстами для поиска')
    parser.add_argument('--top_n', type=int, default=5, 
                        help='Количество результатов для каждого запроса (по умолчанию: 5)')
    parser.add_argument('--database', type=str, default=None,
                        help='Название базы данных для поиска (по умолчанию: текущая активная база)')
    parser.add_argument('--max_workers', type=int, default=5,
                        help='Максимальное количество параллельных запросов (по умолчанию: 5)')
    parser.add_argument('--list_databases', action='store_true',
                        help='Показать список доступных баз и выйти')
    parser.add_argument('--dry_run', action='store_true',
                        help='Проверить конфигурацию без выполнения поиска')
    
    return parser.parse_args()

def main():
    args = parse_arguments()
    
    # Инициализация тестера
    tester = VectorSearchTester(max_workers=args.max_workers)
    
    # Если нужно просто показать список баз
    if args.list_databases:
        databases = tester.get_available_databases()
        print("\nДоступные векторные базы:")
        print("-" * 50)
        for db in databases:
            status = "✅ АКТИВНАЯ" if db["is_active"] else "⚪"
            print(f"{status} {db['name']}: {db['description']} ({db['record_count']} записей)")
        print("-" * 50)
        return
    
    # Проверка существования входного файла
    if not os.path.exists(args.input_file):
        logger.error(f"❌ Файл не найден: {args.input_file}")
        return
    
    # Чтение Excel файла
    try:
        logger.info(f"📖 Чтение Excel файла: {args.input_file}")
        input_df = pd.read_excel(args.input_file)
        
        logger.info(f"📊 Загружено {len(input_df)} строк, {len(input_df.columns)} колонок")
        logger.info(f"📋 Колонки: {', '.join(input_df.columns.tolist())}")
        
        if args.column not in input_df.columns:
            logger.error(f"❌ Колонка '{args.column}' не найдена в файле")
            logger.info(f"🔍 Доступные колонки: {', '.join(input_df.columns.tolist())}")
            return
        
        logger.info(f"🔎 Проверка уникальных значений в колонке '{args.column}':")
        sample_values = input_df[args.column].dropna().head(3).tolist()
        logger.info(f"   Примеры: {sample_values}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка чтения Excel файла: {str(e)}")
        return
    
    # Dry run - только проверка конфигурации
    if args.dry_run:
        logger.info("🔍 DRY RUN - Проверка конфигурации без выполнения поиска")
        logger.info(f"✅ Конфигурация корректна:")
        logger.info(f"   Входной файл: {args.input_file}")
        logger.info(f"   Колонка для поиска: {args.column}")
        logger.info(f"   Количество результатов: {args.top_n}")
        logger.info(f"   База данных: {args.database or 'текущая активная'}")
        logger.info(f"   Параллельные запросы: {args.max_workers}")
        return
    
    # Определение пути для выходного файла
    if args.output:
        output_file = args.output
    else:
        base_name = os.path.splitext(os.path.basename(args.input_file))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"{base_name}_results_{timestamp}.xlsx"
    
    # Выполнение пакетной обработки
    logger.info(f"🎯 Начало пакетной обработки...")
    results_df = tester.process_batch(
        input_df=input_df,
        query_column=args.column,
        top_n=args.top_n,
        database=args.database
    )
    
    # Сохранение результатов
    try:
        logger.info(f"💾 Сохранение результатов в: {output_file}")
        results_df.to_excel(output_file, index=False)
        logger.info(f"✅ Результаты успешно сохранены!")
        
        # Краткая статистика по результатам
        logger.info("\n📈 Статистика результатов:")
        success_rate = results_df['search_success'].mean() * 100
        avg_processing_time = results_df[results_df['search_success']]['processing_time'].mean()
        
        logger.info(f"   Успешных запросов: {success_rate:.1f}%")
        logger.info(f"   Среднее время обработки: {avg_processing_time:.3f} сек")
        
        # Примеры успешных результатов
        successful = results_df[results_df['search_success']]
        if not successful.empty:
            logger.info("\n📋 Примеры результатов (первые 3 успешных запроса):")
            for idx, row in successful.head(3).iterrows():
                logger.info(f"\nЗапрос: {row[args.column]}")
                logger.info("Результаты:")
                for i in range(1, min(4, args.top_n + 1)):
                    if row[f'code_{i}']:
                        logger.info(f"  {i}. [{row[f'code_{i}']}] {row[f'description_{i}']}")
                        logger.info(f"     cosine: {row[f'cosine_{i}']:.4f}, rerank: {row[f'rerank_score_{i}']:.4f}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения результатов: {str(e)}")

if __name__ == "__main__":
    main()