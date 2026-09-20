# ---- 构建阶段:安装依赖 (uv) ----
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

# 先拷贝依赖清单,利用 Docker 层缓存(改代码不重装依赖)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- 运行时阶段(镜像更小) ----
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app/.venv /app/.venv
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]