# ADR-0002 — Side-fix: убрать `else: raise` после успешного commit в import pipeline

**Дата:** 2026-06-16
**Статус:** ✅ Принято
**Коммит:** `0e64028`

## Контекст

В `api/app/services/import_service.py:297-307` (до фикса) была сломана логика обработки commit:

```python
# Commit транзакцию (если упадём — этот чанк уже в БД)
try:
    await self.session.commit()
except Exception as e:
    logger.error(f"[import] chunk {chunk_idx+1} commit failed: {e}")
else:
    # Invalidate BM25 — следующий /match пересоберёт индекс
    from app.services.cache_manager import CacheManager
    CacheManager.invalidate_bm25(collection.name)
    await self.session.rollback()  # ← BUG: rollback ПОСЛЕ успешного commit
    raise                          # ← BUG: raise без активного исключения
```

`else` блок выполняется при УСПЕШНОМ `commit()`. После этого код вызывал:
1. `CacheManager.invalidate_bm25` — **ок, валидно**
2. `session.rollback()` — **бессмысленно, данные уже закоммичены**
3. `raise` — **RuntimeError: No active exception to reraise**

Результат: `import_records` падал с `RuntimeError` при первой же удачной транзакции (а не при падении, как ожидал автор). То есть **импорт мог падать на первом chunk'е даже без сетевых ошибок**.

Баг введён в коммите `da26254` (perf refactor: BM25 singleton) — там логика была неправильно рефакторена.

Оригинальный код (до рефакторинга, из `6904f0c`):

```python
try:
    await self.session.commit()
except Exception as e:
    logger.error(f"[import] chunk {chunk_idx+1} commit failed: {e}")
    await self.session.rollback()
    raise
```

То есть **при исключении** — лог + rollback + reraise. **При успехе** — ничего. Просто и правильно.

## Решение

Вернул исходную логику `try/except` + вынес `CacheManager.invalidate_bm25` в обычный код (выполняется при успехе):

```python
# Commit транзакцию (если упадём — этот чанк уже в БД)
try:
    await self.session.commit()
except Exception as e:
    logger.error(f"[import] chunk {chunk_idx+1} commit failed: {e}")
    await self.session.rollback()
    raise
# Commit OK — invalidate BM25 чтобы следующий /match пересобрал индекс
from app.services.cache_manager import CacheManager
CacheManager.invalidate_bm25(collection.name)
```

## Последствия

**Плюсы:**
- `import_records` больше не падает с `RuntimeError` на ровном месте.
- Логика rollback строго привязана к неуспешному commit (как и должно быть).
- `test_import_records_strips_quotes_before_saving_to_qdrant` (Bug #2 detector) проходит — раньше падал именно на этом `RuntimeError`.

**Минор:**
- Side-fix попутно с основной задачей. Можно было выделить в отдельный коммит, но фикс тривиален (4 строки) и связан с тестированием импорт-пайплайна.

## Файлы

- `api/app/services/import_service.py:297-307` — фикс
- `api/tests/test_import_normalization.py:107-120` — регрессионный тест (падал до фикса)
