"""Checkpoint 层封装。

支持两种模式：
  - MemorySaver：开发/测试用，进程内存储，无需外部依赖
  - RedisSaver：生产用，持久化到 Redis，支持分布式恢复

通过 settings.AGENT_CHECKPOINT_BACKEND 切换，默认 memory。
"""
from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from app.config.settings import settings


def _make_memory_saver() -> MemorySaver:
    """构建 MemorySaver（开发模式）。"""
    return MemorySaver()


def _make_redis_saver() -> BaseCheckpointSaver:
    """构建 RedisSaver（生产模式）。

    依赖 langgraph-checkpoint-redis + Redis Stack（带 RedisJSON/RediSearch）。
    """
    try:
        from langgraph.checkpoint.redis import RedisSaver
        from redis import Redis
    except ImportError as e:  # pragma: no cover - 依赖缺失时友好报错
        raise ImportError(
            "使用 Redis checkpoint 需要 langgraph-checkpoint-redis 和 redis 包"
        ) from e

    redis_client = Redis.from_url(settings.resolved_redis_url, decode_responses=False)
    saver = RedisSaver(redis_client=redis_client)
    saver.setup()  # 初始化 Redis 索引（仅首次需要）
    return saver


@lru_cache(maxsize=1)
def get_checkpointer() -> BaseCheckpointSaver:
    """获取全局 Checkpointer 单例。

    根据配置选择 RedisSaver 或 MemorySaver。
    """
    backend = getattr(settings, "AGENT_CHECKPOINT_BACKEND", "memory")
    if backend == "redis":
        try:
            return _make_redis_saver()
        # 兜底捕获：Redis 不可用时降级到 MemorySaver，保证本地开发无需 Redis Stack
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ Redis checkpointer 初始化失败，降级到 MemorySaver: {e}")
            return _make_memory_saver()
    return _make_memory_saver()
