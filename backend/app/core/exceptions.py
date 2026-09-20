"""全局异常定义。"""
from __future__ import annotations


class AppError(Exception):
    """应用基础异常。"""

    def __init__(self, message: str, code: int = 400) -> None:
        self.message: str = message
        self.code: int = code
        super().__init__(message)


class NotFoundError(AppError):
    """资源不存在异常。"""

    def __init__(self, message: str = "资源不存在") -> None:
        super().__init__(message=message, code=404)


class ValidationError(AppError):
    """参数校验异常。"""

    def __init__(self, message: str = "参数校验失败") -> None:
        super().__init__(message=message, code=422)


class AuthenticationError(AppError):
    """认证失败异常。"""

    def __init__(self, message: str = "认证失败") -> None:
        super().__init__(message=message, code=401)


class AlreadyExistsError(AppError):
    """资源已存在异常。"""

    def __init__(self, message: str = "资源已存在") -> None:
        super().__init__(message=message, code=409)


class ServiceError(AppError):
    """服务内部异常。"""

    def __init__(self, message: str = "服务内部错误") -> None:
        super().__init__(message=message, code=500)
