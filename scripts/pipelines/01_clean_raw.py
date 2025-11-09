import pandas as pd
import re
from pathlib import Path

# ─── Конфигурация ───────────────────────────────────────────────
RAW_PATH = Path("data/01_raw/KSR_17.04.2025.xlsx")
INTERIM_PATH = Path("data/02_interim/KSR_clean.csv")

# ─── Функция очистки (ваша, без изменений) ─────────────────────
def clean_ksr_text(text):
    if pd.isna(text) or text == "":
        return ""
    cleaned = re.sub(r'^(Раздел|Группа)\s+[\d\.\s]+', '', str(text))
    return cleaned.strip()

# ─── Основная функция ───────────────────────────────────────────
def prepare_texts(
    raw_excel_path: Path,
    output_csv_path: Path,
    sheet_name=0,
    encoding="utf-8",
    sep=";",
) -> pd.DataFrame:
    print("📥 Загрузка Excel...")
    df = pd.read_excel(
        raw_excel_path,
        sheet_name=sheet_name,
        dtype=str,  # ← критично для сохранения ведущих нулей и избежания интерпретации
        na_values=["", "N/A", "NULL", "—", "–", "-", "отсутствует"],
        keep_default_na=True,
        engine="openpyxl",
    )
    print(f"  → Прочитано {len(df):,} строк, {len(df.columns)} колонок")

    # ── Проверка: есть ли нужные колонки? ──
    required = ["Раздел наименование", "Группа наименование", "Наименование ресурсов ЕХ"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"❌ Отсутствуют колонки: {missing}. "
                       f"Доступные: {list(df.columns)}")

    # ── Очистка текстов ──
    print("🧹 Очистка текстов...")
    df["Раздел наименование"] = df["Раздел наименование"].apply(clean_ksr_text)
    df["Группа наименование"] = df["Группа наименование"].apply(clean_ksr_text)

    # ── Формирование full_path ──
    print("🔗 Формирование full_path...")
    def build_path(row):
        parts = [
            row["Раздел наименование"].strip(),
            row["Группа наименование"].strip(),
            row["Наименование ресурсов ЕХ"].strip()
        ]
        return " → ".join(p for p in parts if p)  # только непустые

    df["full_path"] = df.apply(build_path, axis=1)

    # ── Валидация: критичные пустые full_path ──
    empty_paths = df[df["full_path"] == ""].index.tolist()
    if empty_paths:
        print(f"⚠️  Предупреждение: {len(empty_paths)} строк без full_path (индексы: {empty_paths[:5]}...)")
        # Можно оставить — возможно, это легитимные пустые ресурсы.
        # Или raise — если это ошибка.

    # ── Сохранение ──
    print(f"💾 Сохранение в {output_csv_path}...")
    df.to_csv(output_csv_path, index=False, encoding=encoding, sep=sep)
    print(f"✅ Готово. Размер: {len(df):,} строк. Первые 3 full_path:")
    for i, p in enumerate(df["full_path"].head(3), 1):
        print(f"  {i}. {p}")

    return df

# ─── Запуск при прямом вызове ───────────────────────────────────
if __name__ == "__main__":
    prepare_texts(RAW_PATH, INTERIM_PATH)
