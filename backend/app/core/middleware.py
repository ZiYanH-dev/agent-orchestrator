"""全局中间件。"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.core.logging import logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """记录请求耗时与状态码。"""
        
        start_time: float = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms: float = (time.perf_counter() - start_time) * 1000
        
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """全局异常处理中间件。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """捕获未处理异常并返回统一错误响应。"""
        
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unhandled error: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"code": 1, "message": "服务器内部错误", "data": None},
            )
