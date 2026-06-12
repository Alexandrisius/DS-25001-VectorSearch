"""CleaningRunner — применение regex-правил очистки данных."""
from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cleaning_rule import CleaningRule


class CleaningRunner:
    """Загружает активные cleaning_rules из БД и применяет их к тексту.

    Кэширует загруженные правила в инстансе на 60 секунд. Через class-level
    registry можно сбросить кэш сразу во всех живых экземплярах — это нужно
    при обновлении правил через админку, чтобы следующий импорт подхватил
    свежие данные без ожидания TTL.
    """

    _instances: list["CleaningRunner"] = []

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._rules_cache: list[CleaningRule] | None = None
        self._cache_ts: float = 0.0
        self._cache_ttl = 60.0  # 1 минута
        CleaningRunner._instances.append(self)

    async def load_rules(self) -> list[CleaningRule]:
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

    @classmethod
    def clear_cache(cls) -> None:
        """Сбросить кэш во всех живых экземплярах.

        Вызывается из /admin/cleaning_rules PUT после успешного сохранения,
        чтобы следующий импорт увидел новые правила сразу, а не через TTL.
        """
        for inst in cls._instances:
            inst._rules_cache = None
            inst._cache_ts = 0.0


__all__ = ["CleaningRunner"]
