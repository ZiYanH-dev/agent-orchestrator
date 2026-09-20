"""Redis 缓存封装模块。

统一负责 key 命名、JSON 序列化与故障降级。
Redis 不可用时读操作返回 None、写与删除操作直接跳过，缓存层故障不影响主链路。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from redis.exceptions import RedisError

from app.config.redis_client import redis_client
from app.core.logging import logger

# ---- key 命名空间 ----
SESSION_LIST_PREFIX: str = "agent:session:list"
RETRIEVAL_PREFIX: str = "agent:retrieval"

# ---- 过期时间（秒）----
SESSION_LIST_TTL_SECONDS: int = 300
RETRIEVAL_TTL_SECONDS: int = 300


class RedisCache:
    """Redis 读写封装。"""

    def __init__(self) -> None:
        self._client = redis_client

    def get_json(self, key: str) -> Any | None:
        """读取并反序列化 JSON 值，key 不存在或 Redis 异常时返回 None。"""
        try:
            raw = self._client.get(key)
        except RedisError as exc:
            logger.warning("cache get failed, key=%s err=%s", key, exc)
            return None

        if raw is None:
            return None

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            logger.warning("cache value not str, key=%s", key)
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("cache value not json, key=%s", key)
            return None

    def set_json(self, key: str, value: Any, ttl: int = RETRIEVAL_TTL_SECONDS) -> None:
        """序列化为 JSON 写入并设置过期时间。"""
        try:
            self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except (RedisError, TypeError) as exc:
            logger.warning("cache set failed, key=%s err=%s", key, exc)

    def delete(self, *keys: str) -> None:
        """删除指定 key，未传 key 时直接返回。"""
        if not keys:
            return

        try:
            self._client.delete(*keys)
        except RedisError as exc:
            logger.warning("cache delete failed, keys=%s err=%s", keys, exc)

    def delete_prefix(self, prefix: str) -> None:
        """按前缀批量删除，用 SCAN 游标遍历避免 KEYS 阻塞 Redis。"""
        try:
            for key in self._client.scan_iter(match=f"{prefix}*", count=100):
                self._client.delete(key)
        except RedisError as exc:
            logger.warning("cache delete_prefix failed, prefix=%s err=%s", prefix, exc)


cache: RedisCache = RedisCache()


def session_list_key(user_id: int) -> str:
    """会话列表缓存 key。"""
    return f"{SESSION_LIST_PREFIX}:{user_id}"


def retrieval_key(user_id: int, query: str) -> str:
    """检索结果缓存 key，查询语句取 sha1 摘要避免 key 过长。"""
    digest: str = hashlib.sha1(query.encode("utf-8")).hexdigest()
    return f"{RETRIEVAL_PREFIX}:{user_id}:{digest}"


def user_retrieval_prefix(user_id: int) -> str:
    """某用户全部检索结果缓存的前缀，用于批量失效。"""
    return f"{RETRIEVAL_PREFIX}:{user_id}:"
