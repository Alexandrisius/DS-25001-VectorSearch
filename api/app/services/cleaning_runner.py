"""CleaningRunner — применение regex-правил очистки данных."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cleaning_rule import CleaningRule


class CleaningRunner:
    """Загружает активные cleaning_rules из БД и применяет их к тексту."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._rules_cache: list[CleaningRule] | None = None
        self._cache_ts: float = 0.0
        self._cache_ttl = 60.0  # 1 минута

    async def load_rules(self) -> list[CleaningRule]:
        import time
        if self._rules_cache is not None and (time.time() - self._cache_ts) < self._cache_ttl:
            return self._rules_cache
        result = await self.session.execute(
            select(CleaningRule).order_by(CleaningRule.sort_order)
        )
        self._rules_cache = list(result.scalars().all())
        self._cache_ts = time.time()
        return self._rules_cache

    def apply(
        self, text: str, column_name: str, rules: list[CleaningRule] | None = None
    ) -> str:
        if not text:
            return ""
        result = str(text)
        _rules = rules if rules is not None else (self._rules_cache or [])
        for rule in _rules:
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


__all__ = ["CleaningRunner"]
