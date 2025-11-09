# -*- coding: utf-8 -*-
import pandas as pd
import torch
from transformers import AutoTokenizer
from pathlib import Path

# === Настройки ===
CSV_PATH = "data/02_interim/KSR_clean.csv"
MODEL_PATH = r"D:\hf_cache\Qwen3-Embedding-4B"  # ваш путь к модели
SEPARATOR = ";"
ENCODING = "utf-8"
MAX_LENGTH = 8192  # лимит модели

print("🔍 Анализ длины текстов в символах и токенах...")

# === 1. Читаем ТОЛЬКО колонку full_path (экономим память) ===
df = pd.read_csv(
    CSV_PATH,
    sep=SEPARATOR,
    encoding=ENCODING,
    usecols=["full_path"],
    dtype={"full_path": "string"}
)

texts = df["full_path"].dropna().str.strip()
texts = texts[texts != ""]
print(f"✅ Всего непустых записей: {len(texts)}")

# === 2. Находим самую длинную строку по символам ===
lengths_chars = texts.str.len()
max_len_chars = lengths_chars.max()
idx_max = lengths_chars.idxmax()
longest_text = texts.loc[idx_max]

print(f"📏 Макс. длина (символы): {max_len_chars}")
print(f"📌 Пример (индекс {idx_max}):")
print("-" * 80)
print(longest_text[:200] + "..." if len(longest_text) > 200 else longest_text)  # укорачиваем для вывода
print("-" * 80)

# === 3. Загружаем ТОЛЬКО токенизатор (без модели!) ===
print("\n⚙️  Загружаю токенизатор Qwen3-Embedding-4B...")
tokenizer = AutoTokenizer.from_pretrained(
    MODEL_PATH,
    trust_remote_code=True,
    padding_side="left"
)

# Токенизируем самую длинную строку
encoded = tokenizer(
    longest_text,
    max_length=MAX_LENGTH,
    truncation=True,  # обрежет, если >8192
    return_tensors="pt",
    add_special_tokens=True  # учитываем BOS/EOS
)

num_tokens = encoded["input_ids"].shape[1]
print(f"\n🧮 Длина самой длинной строки в токенах: {num_tokens}")

# Статистика по всему датасету (выборка для скорости)
print("\n📊 Анализ по выборке (первые 1000 строк):")
sample_texts = texts.head(1000).tolist()
batch_encoded = tokenizer(
    sample_texts,
    padding=False,
    truncation=True,
    max_length=MAX_LENGTH,
    return_length=True,
    add_special_tokens=True
)
sample_lengths = batch_encoded["length"]
avg_tokens_per_char = sum(sample_lengths) / sum(len(t) for t in sample_texts)
print(f"   • Среднее соотношение: 1 символ ≈ {avg_tokens_per_char:.3f} токенов")
print(f"   • Средняя длина в токенах: {sum(sample_lengths) / len(sample_lengths):.1f}")

# === 4. Критическая проверка лимита ===
exceeds_limit = num_tokens > MAX_LENGTH
if exceeds_limit:
    print(f"\n⚠️  КРИТИЧНО: строка превышает лимит модели (8192 токенов) на {num_tokens - MAX_LENGTH} токенов!")
    print("💡 Рекомендация: разбить на подзаписи по разделителям '→' или усечь до 8000 токенов.")
else:
    print(f"\n✅ Все строки укладываются в лимит модели (макс. {MAX_LENGTH} токенов).")
    # Оценка запаса
    margin = MAX_LENGTH - num_tokens
    print(f"   • Запас: {margin} токенов ({margin / MAX_LENGTH:.1%} от лимита)")

# === 5. Дополнительно: сколько строк близко к лимиту ===
if not exceeds_limit:
    near_limit = sum(1 for l in sample_lengths if l > MAX_LENGTH * 0.9)
    if near_limit > 0:
        print(f"   • {near_limit} строк из выборки (>90% от лимита) — проверьте их отдельно.")