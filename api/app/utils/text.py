"""Текстовые утилиты: очистка, нормализация."""
from __future__ import annotations

import re

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]")
_DANGEROUS_CHARS = re.compile(
    r"[^\w\s\d.,;:!?()\"'«»\[\]{}\-_+=*%#@&$€₽¥£¢§°±→/\\u0400-\u04FF\\u00C0-\u017F]"
)
_ARROW_LIKE = re.compile(r"[→⟶➡➤→>→]")


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


__all__ = ["clean_text_for_json", "normalize_query"]
