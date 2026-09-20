"""安全工具单元测试。"""
from __future__ import annotations

import pytest

from app.core.exceptions import AuthenticationError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    """哈希后的密码能通过校验，错误密码被拒绝。"""

    hashed: str = hash_password("secret-123")
    assert hashed != "secret-123"
    assert verify_password("secret-123", hashed) is True
    assert verify_password("wrong-pass", hashed) is False


def test_access_token_round_trip() -> None:
    """签发的令牌能还原出用户 ID。"""

    user_id: int = 42
    token: str = create_access_token(user_id=user_id)
    assert decode_access_token(token=token) == user_id


def test_invalid_token_raises() -> None:
    """非法令牌抛出认证异常。"""

    with pytest.raises(AuthenticationError):
        decode_access_token(token="not-a-valid-token")