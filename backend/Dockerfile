# ===== Python 运行镜像 =====
# 多阶段构建: base(装 uv) → dependencies(装依赖) → runner(运行)
# 参照 study_helper 的后端 Dockerfile 结构, 优化镜像体积与构建缓存。

FROM python:3.11-slim AS base
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# 安装 uv(pip 安装体积远小于专用 uv 镜像)
RUN pip install --no-cache-dir uv

# ===== 依赖缓存层(依赖不变则此层缓存复用, 改代码不清依赖) =====
FROM base AS dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ===== 运行镜像(镜像更小) =====
FROM base AS runner
COPY --from=dependencies /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

# 只拷贝运行所需: app 包 + alembic(启动时自动迁移)
COPY app/ app/
COPY alembic.ini ./
COPY alembic/ alembic/

EXPOSE 8000
# 启动前先自动执行数据库迁移, 再启动 uvicorn
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]