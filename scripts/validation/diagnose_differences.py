# scripts/utils/diagnose_differences.py
"""
Диагностический скрипт для поиска причин ложных изменений
"""

import pandas as pd
import requests
from pathlib import Path
import json

PROJECT_ROOT = Path("C:/Users/klim9/Yandex.Disk/02_Work/#Projects/04_DataScience/DS-25001-VectorSearch")
CSV_PATH = PROJECT_ROOT / "data" / "02_interim" / "KSR_clean.csv"
SERVER_URL = "http://localhost:8000"
COLLECTION = "ksr_main"

def load_csv():
    """Загрузка CSV"""
    print("📂 Загрузка CSV...")
    df = pd.read_csv(CSV_PATH, sep=';', encoding='utf-8')
    df = df.drop_duplicates(subset=['Код КСР'], keep='first')
    df = df.dropna(subset=['Код КСР', 'full_path'])
    print(f"✅ Загружено {len(df)} записей из CSV")
    return df

def get_qdrant_records():
    """Получение записей из Qdrant"""
    print("📥 Получение записей из Qdrant...")
    response = requests.get(
        f"{SERVER_URL}/get_all_codes",
        params={"database": COLLECTION},
        timeout=300
    )
    response.raise_for_status()
    data = response.json()
    records = data.get("records", {})
    print(f"✅ Получено {len(records)} записей из Qdrant")
    return records

def find_differences(csv_df, qdrant_records):
    """Поиск различий"""
    print("\n🔍 Анализ различий...")
    
    differences = []
    
    for idx, row in csv_df.iterrows():
        code = row['Код КСР']
        csv_desc = row['full_path']
        
        # Проверяем тип кода
        code_str = str(code)
        
        if code_str in qdrant_records:
            qdrant_desc = qdrant_records[code_str]
            
            # Нормализация как в скрипте
            csv_normalized = str(csv_desc).strip().lower()
            qdrant_normalized = str(qdrant_desc).strip().lower()
            
            if csv_normalized != qdrant_normalized:
                differences.append({
                    'code': code_str,
                    'csv_type': type(code).__name__,
                    'csv_desc': csv_desc,
                    'qdrant_desc': qdrant_desc,
                    'csv_len': len(str(csv_desc)),
                    'qdrant_len': len(str(qdrant_desc)),
                    'csv_normalized': csv_normalized[:100],
                    'qdrant_normalized': qdrant_normalized[:100]
                })
    
    return differences

def main():
    print("=" * 80)
    print("🔬 ДИАГНОСТИКА РАЗЛИЧИЙ")
    print("=" * 80)
    
    # Загрузка данных
    csv_df = load_csv()
    qdrant_records = get_qdrant_records()
    
    # Поиск различий
    differences = find_differences(csv_df, qdrant_records)
    
    print("\n" + "=" * 80)
    print(f"📊 НАЙДЕНО РАЗЛИЧИЙ: {len(differences)}")
    print("=" * 80)
    
    if differences:
        print(f"\n🔍 Показываю первые 5 различий:\n")
        
        for i, diff in enumerate(differences[:5], 1):
            print(f"{i}. Код: {diff['code']} (тип в CSV: {diff['csv_type']})")
            print(f"   📏 Длина: CSV={diff['csv_len']}, Qdrant={diff['qdrant_len']}")
            print(f"   📝 CSV:     {diff['csv_normalized'][:80]}...")
            print(f"   📝 Qdrant:  {diff['qdrant_normalized'][:80]}...")
            
            # Побайтовое сравнение первых символов
            csv_bytes = diff['csv_desc'][:50].encode('utf-8')
            qdrant_bytes = diff['qdrant_desc'][:50].encode('utf-8')
            
            if csv_bytes != qdrant_bytes:
                print(f"   🔍 Байты различаются:")
                print(f"      CSV:    {csv_bytes}")
                print(f"      Qdrant: {qdrant_bytes}")
            
            print()
        
        # Сохраняем все различия в файл
        output_file = PROJECT_ROOT / "data" / "04_feedback" / "differences_debug.json"
        output_file.parent.mkdir(exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(differences, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Все различия сохранены в: {output_file}")
    else:
        print("\n✅ Различий не найдено! Данные идентичны.")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
