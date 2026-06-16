# ADR-0004 — pytest setup: NullPool + session-scoped event loop

**Дата:** 2026-06-16
**Статус:** ✅ Принято
**Коммит:** `0e64028`

## Контекст

При первой попытке запустить pytest-тесты в `api/tests/` наткнулся на два трудноотлаживаемых asyncpg-эффекта:

1. **"Task got Future attached to a different loop"** — asyncpg pool привязан к event loop, в котором был создан. При function-scoped loop'ах (стандарт pytest-asyncio) connections переиспользуются через loop-переключения → падение.
2. **"Event loop is closed"** при teardown — `pool_pre_ping=True` запускает ping на закрытом loop'е.

Корень: глобальный engine создаётся в `app/db/postgres.py:get_engine()` через `lru_cache`. Создаётся лениво в первом loop'е, в котором его позвали. Никакого reset hook'а нет.

## Решение

**Тест-фикстуры НЕ используют продакшен engine.** Создают свой engine с `NullPool` (без пула — каждое соединение свежее):

```python
def _make_test_session_maker():
    from sqlalchemy.pool import NullPool
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=False,
    )
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
```

**Все async-тесты и фикстуры в ОДНОМ event loop'е** (session-scoped):

```python
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

```python
# В каждом тестовом файле:
pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.integration]
```

Также: `db_session` и `test_collection` фикстуры — function-scoped (каждая сессия БД свежая), но **engine создаётся заново в каждой фикстуре** — потому что у каждого engine свой loop, и переиспользовать engine между разными loop'ами нельзя.

## Последствия

**Плюсы:**
- 60 тестов стабильно проходят за ~6 секунд.
- Полная изоляция тестов: каждый получает свежее соединение, свежую коллекцию.
- Cleanup в `finally` корректно работает — `await db_session.commit()` для удаления, `qdrant.delete_collection()` для Qdrant.
- Тесты скипаются без БД/Qdrant через `pytest_collection_modifyitems` + `_infra_unavailable()`.

**Минусы / нюансы:**
- `NullPool` медленнее реального pool'а (5-10 мс на каждое соединение). На 60 тестах незаметно; на 1000+ будет ощутимо. Альтернатива: переписать продовый engine для поддержки reset hook'а — out of scope.
- Привязка к `loop_scope="session"` означает, что **sync-тесты в одном файле с async-тестами** получают `PytestWarning` о не-async функциях с маркой `@pytest.mark.asyncio`. Подавлено через `pyproject.toml:per-file-ignores` для `tests/*`.
- `event_loop` override — старый API, deprecated в pytest-asyncio 0.24+. Если обновлять — заменить на `asyncio_default_fixture_loop_scope = "session"` в `pyproject.toml`.

**Альтернативы, от которых отказались:**
- **pytest-asyncio session-scope по умолчанию** через `asyncio_default_fixture_loop_scope` — выглядит чище, но в pyproject.toml это сломает другие потенциальные тесты в проекте (которых пока нет, но могут появиться).
- **Docker-контейнер для тестов** (testcontainers-python) — оркестрация Postgres+Qdrant per-test-run. Избыточно, раз в dev-окружении они уже подняты.

## Файлы

- `api/tests/conftest.py` — фикстуры с NullPool + session loop
- `api/tests/test_get_all_codes.py`, `test_import_normalization.py`, `test_diff_integration.py` — `pytestmark` с `loop_scope="session"`
- `api/pyproject.toml:87` — `[tool.ruff.lint.per-file-ignores]` для `tests/*` (N806, SIM103, SIM105, I001, PT014)
