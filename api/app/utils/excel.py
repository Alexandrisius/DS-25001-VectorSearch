"""Парсинг Excel-файлов."""
from __future__ import annotations

import io
from typing import Any

import pandas as pd
from fastapi import HTTPException, UploadFile, status


async def parse_excel(
    file: UploadFile,
    sheet: str | None = None,
    preview_rows: int = 100,
) -> dict[str, Any]:
    """Парсинг Excel-файла.

    Returns:
        dict с полями: sheets, selected_sheet, headers, preview, total_rows.
    """
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поддерживаются только Excel-файлы (.xlsx, .xls)",
        )

    content = await file.read()
    try:
        xlsx = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка чтения Excel: {e}",
        ) from e

    sheet_names = xlsx.sheet_names
    selected = sheet if sheet and sheet in sheet_names else sheet_names[0]

    try:
        df = pd.read_excel(
            xlsx,
            sheet_name=selected,
            dtype=str,
            na_values=["", "N/A", "NULL", "—", "–", "-"],
            keep_default_na=True,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка парсинга листа '{selected}': {e}",
        ) from e

    df = df.fillna("")
    all_records = df.to_dict(orient="records")
    preview = df.head(preview_rows).to_dict(orient="records")

    return {
        "filename": filename,
        "sheets": sheet_names,
        "selected_sheet": selected,
        "headers": df.columns.tolist(),
        "preview": preview,
        "data": all_records,
        "total_rows": len(df),
    }


__all__ = ["parse_excel"]
