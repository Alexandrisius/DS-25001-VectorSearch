"""Структурированное логирование (loguru)."""
from __future__ import annotations

import sys

from loguru import logger

from app.config import get_settings


def setup_logging() -> None:
    """Настройка логирования. Вызывается при старте приложения."""
    settings = get_settings()
    logger.remove()

    is_dev = settings.env == "development"

    if is_dev:
        fmt = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )
    else:
        fmt = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"

    logger.add(
        sys.stderr,
        format=fmt,
        level=settings.log_level,
        colorize=is_dev,
        backtrace=is_dev,
        diagnose=is_dev,
    )

    logger.info(f"Logging initialized (level={settings.log_level}, env={settings.env})")


__all__ = ["logger", "setup_logging"]
