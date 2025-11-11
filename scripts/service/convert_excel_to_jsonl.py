import pandas as pd
import json
import re
import os
from datetime import datetime

def clean_text_for_json(text):
    """Очищает текст от проблемных символов для безопасного хранения в JSON"""
    if pd.isna(text) or text is None:
        return ""
    
    if isinstance(text, (int, float)):
        return str(text)
    
    # Преобразуем в строку, если это не строка
    text = str(text)
    
    # Удаляем невидимые символы управления
    cleaned = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', text)
    
    # Заменяем множественные кавычки на одинарные
    cleaned = re.sub(r'""+', '"', cleaned)
    
    # Удаляем лишние пробелы
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # Обработка специальных символов
    allowed_chars = r"[^\w\s\d.,;:!?()'\"«»\[\]{}\-_+=*%#@&$€₽¥£¢§°±\\/\\u0400-\\u04FF\\u00C0-\\u017F]"
    cleaned = re.sub(allowed_chars, "", cleaned)

    return cleaned

def convert_excel_to_jsonl(excel_path, output_jsonl_path):
    """
    Конвертирует Excel файл в JSONL формат с очисткой данных
    
    Args:
        excel_path (str): Путь к Excel файлу
        output_jsonl_path (str): Путь к выходному JSONL файлу
    """
    try:
        # Чтение Excel файла
        print(f"📖 Чтение Excel файла: {excel_path}")
        df = pd.read_excel(excel_path)
        
        print(f"✅ Загружено {len(df)} записей")
        print(f"עמודцы в файле: {', '.join(df.columns.tolist())}")
        
        # Проверка наличия необходимых столбцов
        required_columns = ['timestamp', 'query', 'selected_code', 'position', 'description', 'database']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            print(f"⚠️ Предупреждение: Отсутствуют столбцы: {missing_columns}")
            print("Попытка найти похожие столбцы...")
            
            # Попытка найти похожие столбцы с опечатками
            column_mapping = {}
            for required in required_columns:
                found = False
                for actual in df.columns:
                    if required.lower() in actual.lower() or actual.lower() in required.lower():
                        column_mapping[required] = actual
                        found = True
                        print(f"  ➡️ Найдено соответствие: '{required}' -> '{actual}'")
                        break
                if not found:
                    column_mapping[required] = required  # оставляем как есть
            
            # Переименование столбцов
            df = df.rename(columns=column_mapping)
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                raise ValueError(f"Не удалось найти столбцы: {missing_columns}")
        
        # Очистка данных
        print("🧹 Очистка данных от проблемных символов...")
        total_rows = len(df)
        
        # Обработка timestamp - приведение к стандартному формату
        if 'timestamp' in df.columns:
            def normalize_timestamp(ts):
                try:
                    if pd.isna(ts):
                        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Если это уже строка в правильном формате
                    if isinstance(ts, str) and re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', ts):
                        return ts
                    
                    # Преобразование из Excel timestamp или других форматов
                    ts = pd.to_datetime(ts)
                    return ts.strftime("%Y-%m-%d %H:%M:%S")
                except Exception as e:
                    print(f"  ⚠️ Ошибка преобразования timestamp '{ts}': {str(e)}")
                    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            df['timestamp'] = df['timestamp'].apply(normalize_timestamp)
        
        # Очистка текстовых полей
        text_columns = ['query', 'selected_code', 'description', 'database']
        for col in text_columns:
            if col in df.columns:
                print(f"  🧹 Очистка столбца '{col}'...")
                df[col] = df[col].apply(clean_text_for_json)
        
        # Обработка position - гарантируем, что это целое число
        if 'position' in df.columns:
            print("  🧹 Очистка столбца 'position'...")
            df['position'] = df['position'].apply(lambda x: int(float(x)) if not pd.isna(x) else 1)
        
        # Сохранение в JSONL формат
        print(f"💾 Сохранение данных в JSONL файл: {output_jsonl_path}")
        os.makedirs(os.path.dirname(output_jsonl_path), exist_ok=True)
        
        with open(output_jsonl_path, 'w', encoding='utf-8') as f_out:
            for idx, row in df.iterrows():
                # Создание JSON объекта
                record = {
                    "timestamp": row['timestamp'],
                    "query": row['query'],
                    "selected_code": row['selected_code'],
                    "position": int(row['position']),
                    "description": row['description'],
                    "database": row['database']
                }
                
                # Запись в файл (одна запись на строку)
                f_out.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + "\n")
                
                # Прогресс каждые 100 записей
                if (idx + 1) % 100 == 0:
                    print(f"  ✅ Обработано {idx + 1}/{total_rows} записей")
        
        print(f"✨ Конвертация завершена! Всего обработано: {total_rows} записей")
        print(f"📁 Файл сохранен: {output_jsonl_path}")
        
        # Статистика по базам данных
        if 'database' in df.columns:
            print("\n📊 Статистика по базам данных:")
            db_stats = df['database'].value_counts()
            for db_name, count in db_stats.items():
                print(f"  • {db_name}: {count} записей")
        
        # Пример первой записи
        print("\n🔍 Пример первой записи после конвертации:")
        with open(output_jsonl_path, 'r', encoding='utf-8') as f_in:
            first_line = f_in.readline().strip()
            print(json.dumps(json.loads(first_line), indent=2, ensure_ascii=False))
    
    except Exception as e:
        print(f"❌ Критическая ошибка при конвертации: {str(e)}")
        raise

if __name__ == "__main__":
    # Настройки путей (измените на ваши)
    EXCEL_FILE_PATH = "C:/Users/klim9/Yandex.Disk/02_Work/#Projects/04_DataScience/DS-25001-VectorSearch/data/04_feedback/copy_events.xlsx"
    OUTPUT_JSONL_PATH = "C:/Users/klim9/Yandex.Disk/02_Work/#Projects/04_DataScience/DS-25001-VectorSearch/data/04_feedback/copy_events_2.jsonl"
    
    # Выполнение конвертации
    convert_excel_to_jsonl(EXCEL_FILE_PATH, OUTPUT_JSONL_PATH)
    
    print("\n✅ Скрипт успешно завершен!")