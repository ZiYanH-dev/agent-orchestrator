"""测试替身（test doubles）。

单独成一个模块而不是写在 conftest.py 里：conftest 会被 pytest 以顶层模块名
导入，测试文件若再从 `tests.conftest` 导入同一个类，会得到两份不同的类对象。
替身放在这里只被显式导入一次，不存在这个问题。
"""
from __future__ import annotations

from collections.abc import Iterator

from redis.exceptions import RedisError


class FakeRedis:
    """内存版 Redis，只实现缓存层实际用到的四个命令。

    fail 置为真时四个命令都抛 RedisError，用来验证缓存层的故障降级。
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.fail: bool = False

    def get(self, key: str) -> str | None:
        """读取字符串值。"""

        if self.fail:
            raise RedisError("fake redis outage")
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        """写入字符串值，忽略过期参数。"""

        if self.fail:
            raise RedisError("fake redis outage")
        self.store[key] = value

    def delete(self, *keys: str) -> int:
        """删除给定 key，返回实际删除数量。"""

        if self.fail:
            raise RedisError("fake redis outage")
        removed: int = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed

    def scan_iter(self, match: str = "*", count: int = 100) -> Iterator[str]:
        """按前缀匹配返回 key 迭代器，对齐 redis 的 SCAN 游标语义。"""

        if self.fail:
            raise RedisError("fake redis outage")
        prefix: str = match.rstrip("*")
        return iter([key for key in list(self.store) if key.startswith(prefix)])
