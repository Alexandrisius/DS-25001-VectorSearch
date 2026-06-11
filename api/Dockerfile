# =============================================================================
# KSR Vector Search v2 - Backend Dockerfile
# =============================================================================
# Multi-stage build для минимального размера образа
# =============================================================================

FROM python:3.12-slim AS base

# Системные зависимости (минимум)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# uv для быстрой установки зависимостей
RUN pip install --no-cache-dir uv

WORKDIR /app

# Копируем файлы зависимостей (для кэширования слоя)
COPY pyproject.toml ./

# Устанавливаем зависимости
RUN uv pip install --system --no-cache .

# Копируем код
COPY . .

# Непривилегированный пользователь
RUN useradd --create-home --shell /bin/bash ksr && chown -R ksr:ksr /app
USER ksr

# Порт по умолчанию
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
