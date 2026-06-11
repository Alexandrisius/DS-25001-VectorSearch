# =============================================================================
# KSR Vector Search v2 - Multi-stage Dockerfile
# =============================================================================
# Stage 1: builder — установка зависимостей
# Stage 2: runtime — минимальный образ для запуска
# =============================================================================

# === Stage 1: Builder ===
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

COPY . .

# === Stage 2: Runtime ===
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --from=builder /build/app /app/app
COPY --from=builder /build/alembic /app/alembic
COPY --from=builder /build/alembic.ini /app/alembic.ini
COPY --from=builder /build/pyproject.toml /app/pyproject.toml

# Non-root user
RUN useradd --create-home --shell /bin/bash ksr && chown -R ksr:ksr /app
USER ksr

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
