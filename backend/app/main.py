"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config.settings import settings
from app.core.exceptions import AppError
from app.core.middleware import ErrorHandlingMiddleware, RequestLoggingMiddleware

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
)

# CORS — 开发模式允许所有 origin（方便 Vite proxy / 随机端口），生产用配置收紧

_cors_origins = ["*"] if settings.DEBUG else settings.cors_origins_list

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """统一处理应用业务异常。"""

    return JSONResponse(
        status_code=exc.code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """统一处理请求参数校验异常。"""

    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": "参数校验失败", "data": None},
    )


# 自定义中间件

app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(RequestLoggingMiddleware)

# 路由

app.include_router(api_router, prefix=settings.API_PREFIX)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """健康检查。"""

    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
