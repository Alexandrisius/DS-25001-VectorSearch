# ADR-0001 — Fix false-positive diff в "Сравнить с базой"

**Дата:** 2026-06-16
**Статус:** ✅ Принято
**Коммит:** `0e64028`

## Контекст

Пользователь загружал идентичный Excel повторно, нажимал "Сравнить с базой" и видел **255 ложных "изменений"** (а в общей сложности по коллекции `ksr_1` набирается 122+ записей). Красная и зелёная строки в превью при этом выглядели одинаково.

Причина — два независимых бага на стыке клиент↔сервер:

### Bug #1 — `get_all_codes` отдавал лист вместо полного описания

`api/app/api/materials.py:145-149`:

```python
full = payload.get("full_description") or payload.get("description", "")
d = {
    "description": full,         # ← в оба поля пишется одно и то же (лист)
    "full_description": full,
    ...
}
```

Клиент `web/static/js/admin/import/diff/analyze.js:getDescription()` использовал `record.description` для сравнения. Получал лист (`"Материал Z"`) вместо полного текста (`"Раздел → Группа → Материал Z"`). Новая запись (полный) ≠ существующая (лист) → 255 modified.

### Bug #2 — `stripSymmetricQuotes` снимал кавычки только на клиенте

Клиент: `web/static/js/admin/import/mapping.js:67-69` (`cleanValue` → `stripSymmetricQuotes`).
Сервер: `api/app/services/import_service.py:99, 207` — только `.strip()`, без снятия кавычек.

Если в Excel описание содержало «ёлочки» («...»), „..." — клиент при diff снимал их, а сервер при импорте сохранял в Qdrant как есть. Сравнение: «X» ≠ X → modified.

**Подтверждено на живых данных:** в `ksr_1` на выборке 50 000 записей **122 материала** содержат «ёлочки» в `description` (примеры: `«Автоматика отключена»`, `«СПЕЦКАБЛАЙН-КиТ-МРПИ20»`).

### Bug #1 не активен для `ksr_1`

В коллекции `ksr_1` импорт шёл по схеме "Excel-колонка Название → описание, отдельные колонки Раздел/Группа → иерархия". В этом случае `description == full_description` по построению (лист = полное название, иерархия в отдельных `path_level_N`). Поэтому **Bug #1 для `ksr_1` безвреден** — оба поля равны, и diff работает корректно. **Активен только Bug #2**.

## Решение

Три атомарных правки:

1. **`api/app/api/materials.py`** — `get_all_codes`:
   ```python
   desc = payload.get("description", "")
   full = payload.get("full_description") or desc
   d = {"description": desc, "full_description": full, ...}
   ```

2. **`api/app/utils/text.py`** — портировал `strip_symmetric_quotes` (точный порт JS-версии, документирован в docstring с примерами).

3. **`api/app/services/import_service.py`** — сервер вызывает `strip_symmetric_quotes` в трёх местах: `apply_column_mapping.parts` (для каждой ячейки), `import_records` (для description), `path_level_N` (для уровней иерархии).

## Последствия

**Плюсы:**
- Повторный импорт идентичного Excel → diff = 0/0/0.
- Будущие импорты любых Excel не будут страдать от «ёлочек».
- Тесты ловят регрессию (60 тестов, см. ADR-0003).

**Минусы / нюансы:**
- Уже импортированные данные в `ksr_1` содержат «ёлочки» в 122+ записях. До первого re-import diff всё ещё покажет ложные модификации. См. **ADR-0005 — план для существующей коллекции**.
- `description` теперь всегда полный текст (а не лист). Если где-то ещё был код, рассчитывающий на `description == full_description` — может сломаться. Проверено: единственный consumer в `admin_data.py:53` корректно использует `payload.get("description", "")`.

## Файлы

- `api/app/api/materials.py:145-156` — фикс
- `api/app/utils/text.py:11-66` — `strip_symmetric_quotes`
- `api/app/services/import_service.py:24, 96-112, 213-232` — применение
- `api/tests/test_get_all_codes.py` — детектор Bug #1
- `api/tests/test_import_normalization.py` — детектор Bug #2
- `api/tests/test_diff_integration.py` — e2e
