"""Python-порт JS-логики diff для админки импорта.

Источник истины — JS:
  - web/static/js/admin/import/csv-parser.js:normalizeText
  - web/static/js/admin/import/diff/analyze.js:analyzeChanges

Используется в:
  - api/tests/test_diff_logic.py       (юнит-тесты самого порта)
  - api/tests/test_diff_integration.py (интеграционный: импорт → diff)

Зачем нужен порт:
  Diff в UI считается на клиенте, а баги (#1 get_all_codes, #2 quotes)
  возникают на стыке клиент↔сервер. Чтобы воспроизвести их в pytest,
  нужна та же логика сравнения на Python.

Правило обновления: при любом изменении JS-функций ниже — синхронизировать
порт и эталонные кейсы в test_diff_logic.py.
"""
from __future__ import annotations

import re
from typing import Any

from app.utils.text import strip_symmetric_quotes

# Симметрично web/static/js/admin/import/csv-parser.js:normalizeText.
_WHITESPACE_RUN = re.compile(r"[ \t]+")
_LINE_ENDINGS = (("\r\n", "\n"), ("\r", "\n"))


def normalize_text(text: str | None) -> str:
    """Нормализовать текст для сравнения в diff.

    Шаги (в этом порядке):
      1. strip_symmetric_quotes (снять «ёлочки», кавычки и т.п. с краёв)
      2. lowercase
      3. \\r\\n / \\r → \\n
      4. схлопнуть пробелы и табы
      5. trim каждую строку, выкинуть пустые
      6. trim всего

    >>> normalize_text('«Material»')
    'material'
    >>> normalize_text('  TEXT  \\n\\n  ')
    'text'
    >>> normalize_text('A\\r\\nB')
    'a\\nb'
    """
    if not text:
        return ""
    out = strip_symmetric_quotes(text).lower()
    for src, dst in _LINE_ENDINGS:
        out = out.replace(src, dst)
    out = _WHITESPACE_RUN.sub(" ", out)
    lines = [ln.strip() for ln in out.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


def _get_description(record: Any) -> str:
    """Симметрично web/static/js/admin/import/diff/analyze.js:getDescription."""
    if isinstance(record, str):
        return record
    if not isinstance(record, dict):
        return ""
    return (
        record.get("description")
        or record.get("full_description")
        or ""
    )


def analyze_changes(
    new_records: list[dict[str, Any]],
    existing_records: dict[str, Any],
) -> dict[str, Any]:
    """Сравнить новые записи (из Excel) с существующими (из БД).

    Args:
        new_records: [{code, description, hierarchy?, meta?}, ...] — то, что
            собирает web/static/js/admin/import/mapping.js:buildRecordsFromMapping.
        existing_records: {code: {description, full_description, ...}} — то, что
            отдаёт api/app/api/materials.py:get_all_codes (после фикса #1).

    Returns:
        {added: [...], modified: [...], deleted: [...], unchanged: int}

    Симметрично web/static/js/admin/import/diff/analyze.js:analyzeChanges.
    """
    added: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    unchanged = 0

    new_codes = {r["code"] for r in new_records}
    existing_codes = set(existing_records.keys())

    for r in new_records:
        code = r["code"]
        if code not in existing_codes:
            added.append(r)
            continue
        old_desc = _get_description(existing_records[code])
        new_desc = r.get("description") or ""
        if normalize_text(old_desc) != normalize_text(new_desc):
            modified.append({
                "code": code,
                "oldDescription": old_desc,
                "newDescription": new_desc,
                "hierarchy": r.get("hierarchy"),
            })
        else:
            unchanged += 1

    for code in existing_codes:
        if code not in new_codes:
            deleted.append({
                "code": code,
                "description": _get_description(existing_records[code]),
            })

    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "unchanged": unchanged,
    }


__all__ = ["analyze_changes", "normalize_text"]
