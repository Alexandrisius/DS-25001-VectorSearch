import argparse
import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from torch import Tensor
from pathlib import Path
from tqdm import tqdm
import gc
import xxhash

# === Конфигурация ===
MODEL_PATH = r"D:\hf_cache\Qwen3-Embedding-4B"
CSV_PATH = "data/02_interim/KSR_clean.csv"
OUTPUT_DIR = Path("data/03_processed")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EMBEDDINGS_PATH = OUTPUT_DIR / "embeddings.npy"
METADATA_PATH = OUTPUT_DIR / "metadata.parquet"
HASH_PATH = OUTPUT_DIR / "dataset_hash.txt"  # хранит xxh64(csv_path)

BATCH_SIZE = 32
MAX_LENGTH = 1024
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

REQUIRED_COLS = [
    "id",
    "Код КСР",
    "Раздел наименование",
    "Группа наименование",
    "Наименование ресурсов ЕХ",
    "full_path"
]

# === Функция: быстрый хеш файла (xxh64) ===
def file_xxh64(filepath: Path) -> str:
    """Быстрый хеш файла с помощью xxHash (xxh64) — идеален для больших CSV."""
    h = xxhash.xxh64()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

# === Функция: last_token_pool (как в Qwen) ===
def last_token_pool(last_hidden_states: Tensor, attention_mask: Tensor) -> Tensor:
    left_padding = (attention_mask[:, -1].sum() == attention_mask.shape[0])
    if left_padding:
        return last_hidden_states[:, -1]
    else:
        sequence_lengths = attention_mask.sum(dim=1) - 1
        batch_size = last_hidden_states.shape[0]
        return last_hidden_states[
            torch.arange(batch_size, device=last_hidden_states.device),
            sequence_lengths
        ]

# === Основная функция генерации ===
def compute_embeddings(df: pd.DataFrame, model, tokenizer) -> np.ndarray:
    all_embeddings = []
    for i in tqdm(range(0, len(df), BATCH_SIZE), desc="🧠 Эмбеддинги"):
        batch_texts = df["full_path"].iloc[i:i+BATCH_SIZE].tolist()
        batch_dict = tokenizer(
            batch_texts,
            max_length=MAX_LENGTH,
            padding=True,
            truncation=True,
            return_tensors="pt"
        ).to(DEVICE)
        
        with torch.no_grad():
            outputs = model(**batch_dict)
        embeddings = last_token_pool(outputs.last_hidden_state, batch_dict["attention_mask"])
        embeddings = F.normalize(embeddings, p=2, dim=1)
        all_embeddings.append(embeddings.cpu().numpy().astype(np.float32))
        
        if DEVICE == "cuda":
            torch.cuda.empty_cache()
            gc.collect()
    
    return np.vstack(all_embeddings)

# === Точка входа ===
def main(force_recompute: bool = False, debug: bool = False):
    csv_path = Path(CSV_PATH)
    if not csv_path.exists():
        raise FileNotFoundError(f"❌ Не найден CSV: {csv_path}")
    
    # 1. Считаем хеш CSV
    csv_hash = file_xxh64(csv_path)
    print(f"🔍 Хеш CSV: {csv_hash[:8]}... (xxh64)")

    # 2. Проверяем, есть ли сохранённые артефакты с тем же хешем
    embeddings_exist = EMBEDDINGS_PATH.exists()
    metadata_exist = METADATA_PATH.exists()
    hash_match = HASH_PATH.exists() and HASH_PATH.read_text().strip() == csv_hash

    if not force_recompute and embeddings_exist and metadata_exist and hash_match:
        print("✅ Эмбеддинги и метаданные актуальны — загружаем из кэша.")
        embeddings = np.load(EMBEDDINGS_PATH)
        metadata = pd.read_parquet(METADATA_PATH)
        
        if debug:
            print(f"   → размер эмбеддингов: {embeddings.shape}")
            print(f"   → метаданные: {len(metadata)} записей")
            print(f"   → пример id=0:\n{metadata.iloc[0].to_dict()}")
        return embeddings, metadata

    print("🔄 Требуется перегенерация эмбеддингов.")
    # 3. Загружаем и подготавливаем данные
    df = pd.read_csv(csv_path, sep=";", encoding="utf-8")

    # Добавляем id, если отсутствует
    if "id" not in df.columns:
        df["id"] = range(len(df))
        print("🆔 Сгенерированы id (ранее отсутствовали)")

    # Проверяем обязательные колонки
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"❌ Отсутствуют колонки: {missing}\nДоступны: {list(df.columns)}")

    # Оставляем только нужные поля + гарантируем порядок
    metadata_df = df[REQUIRED_COLS].copy()
    metadata_df["embedding_index"] = range(len(metadata_df))  # явное соответствие строке в embeddings.npy

    # 4. Загружаем модель (только если генерируем!)
    print("📥 Загружаем модель...")
    from transformers import AutoTokenizer, AutoModel
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_PATH, padding_side="left", trust_remote_code=True
    )
    model = AutoModel.from_pretrained(
        MODEL_PATH,
        trust_remote_code=True,
        device_map=DEVICE,
        torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32
    )
    model.eval()

    # 5. Генерация
    embeddings = compute_embeddings(df, model, tokenizer)

    # 6. Сохранение
    np.save(EMBEDDINGS_PATH, embeddings)
    metadata_df.to_parquet(METADATA_PATH, index=False)
    HASH_PATH.write_text(csv_hash)
    print(f"💾 Сохранено:\n   → {EMBEDDINGS_PATH}\n   → {METADATA_PATH}\n   → {HASH_PATH}")

    print(f"✅ Готово: {len(embeddings)} эмбеддингов, размерность {embeddings.shape[1]}")
    return embeddings, metadata_df

# === CLI ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Генерация эмбеддингов с кэшированием")
    parser.add_argument("--force", action="store_true", help="Игнорировать кэш, пересчитать")
    parser.add_argument("--debug", action="store_true", help="Вывести отладочную информацию")
    args = parser.parse_args()

    embeddings, metadata = main(force_recompute=args.force, debug=args.debug)

   