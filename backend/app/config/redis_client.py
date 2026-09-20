"""Redis 客户端初始化模块。"""
from __future__ import annotations

from redis import Redis

from app.config.settings import settings

redis_client: Redis = Redis.from_url(
    settings.resolved_redis_url,
    decode_responses=True,
    encoding="utf-8",
)
