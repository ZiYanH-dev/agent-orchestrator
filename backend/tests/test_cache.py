"""缓存层的单元测试。

缓存分两部分：key 构造函数（纯函数）与 RedisCache 封装。
封装层的核心契约是「Redis 故障不影响主链路」——读操作返回 None、
写与删除静默跳过。这条契约一旦破了，Redis 抖动就会带崩整个问答链路，
所以这里对四个命令都做了故障注入。
"""
from __future__ import annotations

import hashlib

import pytest

from app.core.cache import (
    RETRIEVAL_TTL_SECONDS,
    SESSION_LIST_TTL_SECONDS,
    RedisCache,
    retrieval_key,
    session_list_key,
    user_retrieval_prefix,
)
from tests.fakes import FakeRedis

# ---------------------------------------------------------------------------
# key 构造
# ---------------------------------------------------------------------------

def test_session_list_key_is_user_scoped() -> None:
    """会话列表 key 按用户隔离，不同用户不会互相命中。"""

    assert session_list_key(1) == "agent:session:list:1"
    assert session_list_key(1) != session_list_key(2)


def test_retrieval_key_is_deterministic() -> None:
    """同一用户同一问句必须命中同一个 key，否则缓存永远不生效。"""

    assert retrieval_key(7, "什么是 RAG") == retrieval_key(7, "什么是 RAG")


def test_retrieval_key_differs_on_user_and_query() -> None:
    """用户或问句任一不同，key 都必须不同。"""

    baseline: str = retrieval_key(7, "什么是 RAG")

    assert baseline != retrieval_key(8, "什么是 RAG")
    assert baseline != retrieval_key(7, "什么是 Agent")


def test_retrieval_key_digests_the_query() -> None:
    """问句用 sha1 摘要，避免长问句把 key 撑爆。"""

    digest: str = hashlib.sha1("什么是 RAG".encode()).hexdigest()
    assert retrieval_key(7, "什么是 RAG") == f"agent:retrieval:7:{digest}"
    assert len(digest) == 40


def test_retrieval_key_prefix_composes_with_key() -> None:
    """批量失效用的前缀必须是检索 key 的前缀，否则清了等于没清。"""

    key: str = retrieval_key(7, "什么是 RAG")
    assert key.startswith(user_retrieval_prefix(7))
    assert not key.startswith(user_retrieval_prefix(8))


def test_retrieval_key_handles_non_ascii_and_long_query() -> None:
    """中文与超长问句都能稳定构造 key。"""

    key: str = retrieval_key(1, "长" * 5000)
    assert key.startswith("agent:retrieval:1:")
    assert len(key) == len("agent:retrieval:1:") + 40


def test_ttl_constants_are_positive() -> None:
    """两次 TTL 都必须是正数，否则 Redis 会把它当成无过期或直接报错。"""

    assert RETRIEVAL_TTL_SECONDS > 0
    assert SESSION_LIST_TTL_SECONDS > 0


# ---------------------------------------------------------------------------
# RedisCache 正常路径
# ---------------------------------------------------------------------------

def test_set_then_get_round_trip(isolated_cache: FakeRedis) -> None:
    """写入后可读回，且保持原始结构。"""

    cache = RedisCache()
    payload = [{"content": "片段", "score": 0.87}]

    cache.set_json("k", payload)

    assert cache.get_json("k") == payload


def test_get_returns_none_for_missing_key() -> None:
    """key 不存在时返回 None。"""

    assert RedisCache().get_json("nope") is None


def test_get_returns_none_for_non_json_value(isolated_cache: FakeRedis) -> None:
    """存量值不是合法 JSON 时返回 None，而不是抛异常。"""

    isolated_cache.store["k"] = "这不是 JSON"
    assert RedisCache().get_json("k") is None


def test_get_returns_none_for_non_str_value(isolated_cache: FakeRedis) -> None:
    """存量值不是字符串或字节时返回 None。"""

    isolated_cache.store["k"] = 123  # type: ignore[assignment]
    assert RedisCache().get_json("k") is None


def test_set_swallows_unserialisable_value(isolated_cache: FakeRedis) -> None:
    """对象无法 JSON 序列化时静默放弃写入，不向上抛异常。"""

    RedisCache().set_json("k", object())

    assert "k" not in isolated_cache.store


def test_delete_without_keys_does_nothing(isolated_cache: FakeRedis) -> None:
    """不传 key 时直接返回，不去打扰 Redis。"""

    isolated_cache.store["keep"] = "1"

    RedisCache().delete()

    assert isolated_cache.store == {"keep": "1"}


def test_delete_removes_specific_keys(isolated_cache: FakeRedis) -> None:
    """删除指定 key。"""

    cache = RedisCache()
    cache.set_json("a", 1)
    cache.set_json("b", 2)

    cache.delete("a")

    assert cache.get_json("a") is None
    assert cache.get_json("b") == 2


def test_delete_prefix_clears_only_matching_keys(isolated_cache: FakeRedis) -> None:
    """按前缀批量删除只命中同前缀的 key。"""

    cache = RedisCache()
    cache.set_json(retrieval_key(1, "q1"), [])
    cache.set_json(retrieval_key(1, "q2"), [])
    cache.set_json(retrieval_key(2, "q1"), [])

    cache.delete_prefix(user_retrieval_prefix(1))

    assert cache.get_json(retrieval_key(1, "q1")) is None
    assert cache.get_json(retrieval_key(1, "q2")) is None
    assert cache.get_json(retrieval_key(2, "q1")) == [], "不得误删其他用户的数据"


# ---------------------------------------------------------------------------
# RedisCache 故障降级
# ---------------------------------------------------------------------------

@pytest.fixture()
def broken_cache(isolated_cache: FakeRedis) -> RedisCache:
    """让底层客户端抛 RedisError，模拟 Redis 不可用。"""

    isolated_cache.fail = True
    return RedisCache()


def test_get_degrades_to_none_on_redis_error(broken_cache: RedisCache) -> None:
    """Redis 读故障时返回 None，让调用方走真实检索而非报错。"""

    assert broken_cache.get_json("k") is None


def test_set_degrades_silently_on_redis_error(broken_cache: RedisCache) -> None:
    """Redis 写故障时静默跳过，主链路照常返回结果。"""

    broken_cache.set_json("k", {"a": 1})


def test_delete_degrades_silently_on_redis_error(broken_cache: RedisCache) -> None:
    """Redis 删除故障时静默跳过。"""

    broken_cache.delete("k")


def test_delete_prefix_degrades_silently_on_redis_error(
    broken_cache: RedisCache,
) -> None:
    """Redis 扫描故障时静默跳过。"""

    broken_cache.delete_prefix(user_retrieval_prefix(1))
