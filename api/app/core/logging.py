"""Структурированное логирование (loguru).

Два режима:
- text:  человекочитаемый, цвета в dev
- json:  одна JSON-строка на событие, идеален для Docker / jq / Loki

Переключение: LOG_FORMAT=json|text (по умолчанию text в dev, json в production).

Все дополнительные поля (event, request_id, user_ip, stages_ms и т.п.)
попадают в JSON через logger.bind(...) — без ручной интерполяции.
"""
from __future__ import annotations

import sys

from loguru import logger

from app.config import get_settings


def setup_logging() -> None:
    """Настройка логирования. Вызывается при старте приложения."""
    settings = get_settings()
    logger.remove()

    is_dev = settings.env == "development"
    as_json = (settings.log_format or "").lower() == "json"

    if as_json:
        # JSON-режим: одна строка = один объект, без backtrace/diagnose (PII)
        logger.add(
            sys.stderr,
            level=settings.log_level,
            serialize=True,
            backtrace=False,
            diagnose=False,
            enqueue=True,  # не блокировать event loop (async FastAPI)
        )
        msg = f"Logging initialized (json mode, level={settings.log_level}, env={settings.env})"
    elif is_dev:
        fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
        logger.add(
            sys.stderr,
            format=fmt,
            level=settings.log_level,
            colorize=True,
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )
        msg = f"Logging initialized (dev/text mode, level={settings.log_level})"
    else:
        fmt = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
        logger.add(
            sys.stderr,
            format=fmt,
            level=settings.log_level,
            colorize=False,
            backtrace=False,
            diagnose=False,
            enqueue=True,
        )
        msg = f"Logging initialized (text mode, level={settings.log_level}, env={settings.env})"

    logger.info(msg)


__all__ = ["logger", "setup_logging"]
