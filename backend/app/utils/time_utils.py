"""时间工具模块。

数据库中的时间列均为 DateTime(timezone=True)，读写两侧必须统一使用时区感知时间，
否则 naive datetime 与 aware datetime 相减会直接抛 TypeError。
"""
from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """返回当前 UTC 时间（时区感知）。"""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """把可能缺失时区的时间补成 UTC，用于兼容历史数据。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
