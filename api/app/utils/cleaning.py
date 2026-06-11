"""Применение regex-правил очистки к тексту."""
from __future__ import annotations

import re
from typing import Iterable

from app.models.cleaning_rule import CleaningRule


def apply_cleaning_rules(
    text: str,
    column_name: str,
    rules: Iterable[CleaningRule],
) -> str:
    """Применить все активные правила к тексту.

    Args:
        text: Исходный текст.
        column_name: Имя колонки (для фильтрации правил по apply_to_columns).
        rules: Список правил CleaningRule.

    Returns:
        Очищенный текст.
    """
    if not text:
        return ""
    result = str(text)
    for rule in rules:
        if not rule.enabled:
            continue
        apply_to = rule.apply_to_columns or ["*"]
        if "*" not in apply_to and column_name not in apply_to:
            continue
        try:
            result = re.sub(rule.pattern, rule.replacement or "", result)
        except re.error:
            continue
    return result.strip()


__all__ = ["apply_cleaning_rules"]
