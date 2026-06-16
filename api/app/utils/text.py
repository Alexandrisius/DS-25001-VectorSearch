"""Текстовые утилиты: очистка, нормализация."""
from __future__ import annotations

import re

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")
_DANGEROUS_CHARS = re.compile(
    r"[^\w\s\d.,;:!?()\"'«»\[\]{}\-_+=*%#@&$€₽¥£¢§°±→/\\u0400-\u04FF\\u00C0-\u017F]"
)
_ARROW_LIKE = re.compile(r"[→⟶➡➤→>→]")


# Симметричные пары кавычек для снятия "обёрток" с краёв строки.
# Точный порт web/static/js/admin/import/csv-parser.js:stripSymmetricQuotes.
# Клиент (diff) и сервер (import) должны давать идентичный результат,
# иначе при повторной загрузке того же файла diff показывает ложные изменения.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("'", "'"),
    ('«', '»'),
    ('„', '"'),
    ('"', '"'),
    ('`', '`'),
)


def strip_symmetric_quotes(text: str | None) -> str:
    """Снять парные симметричные кавычки с обоих концов строки (повторно).

    Точный порт web/static/js/admin/import/csv-parser.js:stripSymmetricQuotes.
    Используется при импорте, чтобы клиент (diff) и сервер (сохранение)
    давали идентичный результат.

    >>> strip_symmetric_quotes('«Material»')
    'Material'
    >>> strip_symmetric_quotes('"\\"вложенные\\""')
    'вложенные'
    >>> strip_symmetric_quotes('text')
    'text'
    >>> strip_symmetric_quotes('')
    ''
    """
    if not text or len(text) < 2:
        return text or ""
    result = text.strip()
    changed = True
    while changed and len(result) >= 2:
        changed = False
        for open_q, close_q in _QUOTE_PAIRS:
            if result.startswith(open_q) and result.endswith(close_q):
                result = result[len(open_q):-len(close_q)].strip()
                changed = True
                break
    return result


def clean_text_for_json(text: str | None) -> str:
    """Очистить текст для безопасного сохранения в JSON."""
    if not isinstance(text, str):
        return ""
    text = _CONTROL_CHARS.sub(" ", text)
    text = _ARROW_LIKE.sub(" → ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _DANGEROUS_CHARS.sub("", text)
    return text


def normalize_query(text: str) -> str:
    """Нормализация пользовательского запроса (lowercase + strip)."""
    return text.lower().strip()


__all__ = [
    "_QUOTE_PAIRS",
    "clean_text_for_json",
    "normalize_query",
    "strip_symmetric_quotes",
]
