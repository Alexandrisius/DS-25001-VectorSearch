# ADR-0003 — Python-порт JS diff-логики в `app/utils/diff.py`

**Дата:** 2026-06-16
**Статус:** ✅ Принято
**Коммит:** `0e64028`

## Контекст

Diff в админке (`"Сравнить с базой"`) считается **на клиенте** в `web/static/js/admin/import/diff/analyze.js:analyzeChanges` и `csv-parser.js:normalizeText`. Чтобы воспроизводить баги на стыке клиент↔сервер в pytest, нужна идентичная логика на Python.

Два варианта:
- **A. Сделать diff на бэкенде.** Создать новый endpoint `/admin/diff`, портировать логику туда. Большой рефакторинг архитектуры.
- **B. Оставить diff на клиенте, портировать логику в Python для тестов.** Минимальное вмешательство, тесты ловят регрессию в обоих направлениях.

## Решение

Выбрали **B**. Создан `api/app/utils/diff.py` — Python-порт двух JS-функций:

- `normalize_text(text)` — порт `normalizeText` из `csv-parser.js`
- `analyze_changes(new_records, existing_records)` — порт `analyzeChanges` из `analyze.js`

**Контракт:** JS — источник истины. Правило синхронизации записано в шапке модуля `app/utils/diff.py` (docstring "правило обновления").

Зависимости:
- Использует `strip_symmetric_quotes` из `app.utils.text` (уже портирован, см. ADR-0001)
- Не делает HTTP / БД запросов — чистая функция, легко тестируется

## Последствия

**Плюсы:**
- 27 unit-тестов в `test_diff_logic.py` покрывают Python-порт: идентичные записи, added/deleted/modified, case-insensitivity, whitespace normalization, quotes normalization, fallback к `full_description`.
- 2 e2e теста в `test_diff_integration.py` гоняют реальный `ImportService.import_records` + `analyze_changes` — и ловят регрессию по обоим багам.
- При будущих правках JS-функций обновляется и Python-порт, и тесты — два места в одной репе.

**Минусы / нюансы:**
- **Дублирование кода.** Если логика diff поменяется в JS, нужно синхронно менять Python-порт. Риск расхождения.
- Митигация: docstring в начале `app/utils/diff.py` явно требует синхронизации. И в будущем стоит добавить тест, который **читает JS-исходник и сверяет пары кейсов** (например через `pytest` + `subprocess` + `node`).
- Сама логика diff остаётся на клиенте. Бэкенд не имеет своего diff endpoint'а. Если когда-то понадобится — будет несложно вынести `analyze_changes` в новый endpoint (модуль уже изолирован).

**Альтернатива, от которой отказались:**
- A. Создание `/admin/diff` endpoint. Преимущества: single source of truth (только Python), возможность считать diff в фоне. Недостатки: большой рефакторинг UI, переделка WebSocket-обновлений, переделка состояния "сравнение/применение". Не соответствует масштабу текущей задачи (фикс двух багов).

## Файлы

- `api/app/utils/diff.py` — порт (89 строк)
- `api/tests/test_diff_logic.py` — 27 unit-тестов порта
- `api/tests/test_diff_integration.py` — 2 e2e теста
