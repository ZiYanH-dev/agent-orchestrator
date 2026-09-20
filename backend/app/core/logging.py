"""日志配置模块。"""
from __future__ import annotations

import logging
import sys

from app.config.settings import settings

_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def _build_logger() -> logging.Logger:
    """构建全局日志器。"""
    logger = logging.getLogger(settings.APP_NAME)
    logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    return logger


logger: logging.Logger = _build_logger()
