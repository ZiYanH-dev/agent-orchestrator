# 环境准备与启动（开发指南）

> 开发环境快速跑通指南。推荐用 **Makefile 一键命令**，也可手动分步执行。
> 生产部署尚未就绪（Dockerfile 为占位实现），见 `Problem/08`。

## 前置依赖

| 工具 | 用途 |
| --- | --- |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | PostgreSQL 17（pgvector）+ Redis |
| [uv](https://docs.astral.sh/uv/) | Python 包管理 |
| [pnpm](https://pnpm.io/) | 前端包管理 |
| [Ollama](https://ollama.com/) | 本地 Embedding 模型（如用云端则不装） |

## 1. 配置环境变量

`.env` 放在**项目根目录**（不是 `backend/`），从模板复制：

```bash
# 项目根目录
cp .env.example .env
```

> ⚠️ `settings.py` 固定读 `REPO_ROOT/.env`（根目录）。不要 `cd backend` 复制，`backend/.env` 永远不会被加载（此坑曾修过，见 `Problem/06`）。

按需修改，**至少填 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME`**。

### 配置关键项（根目录 `.env`）

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `BACKEND_PORT` | 后端端口 | `8765` |
| `FRONTEND_PORT` | 前端端口 | `5872` |
| `LLM_API_KEY` | 大模型 Key（OpenAI 兼容） | 空 |
| `LLM_BASE_URL` | 大模型基址 | dashscope 百炼 |
| `LLM_MODEL_NAME` | 模型名 | `qwen-turbo` |
| `LLM_TEMPERATURE` | 采样温度 | `0.1` |
| `EMBED_BASE_URL` | 向量基址 | `http://localhost:11434/v1` |
| `EMBED_MODEL` | 向量模型 | `nomic-embed-text` |
| `EMBED_DIMENSION` | 向量维度（须与 DB 一致 768） | `768` |
| `POSTGRES_HOST/PORT/USER/PASSWORD/DB` | 数据库（分字段，URL 由 `settings.py` 拼接） | `127.0.0.1/5432/postgres/postgres/rag_demo` |
| `REDIS_HOST/PORT/DB` | Redis（分字段） | `127.0.0.1/6379/0` |
| `JWT_SECRET_KEY` | JWT 签名密钥，**生产必须改**（≥32 字节） | `change-me-in-production` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 分块参数 | `500` / `80` |
| `RETRIEVE_TOP_K` | 检索条数 | `3` |
| `AGENT_ORCHESTRATION_MODE` | `deterministic` / `dynamic` | `deterministic` |
| `AGENT_HITL_ENABLED` | 人工介入开关 | `false` |
| `AGENT_CHECKPOINT_BACKEND` | checkpoint 后端 | `memory` |
| `AGENT_MAX_STEPS` / `AGENT_MAX_TOOL_CALLS` | 护栏上限 | `12` / `3` |
| `CORS_ORIGINS` | 前端跨域白名单 | `localhost:5872` + `127.0.0.1:5872` |

> ⚠️ `EMBED_DIMENSION` 必须与数据库 `chunks.embedding` 向量维度一致（当前 768），且迁移文件里写死的 768 也要同步，见 `Problem/11`。

## 2. 首个模型（如用本地 Ollama）

若 `EMBED_BASE_URL` 指向 localhost，需先有 Ollama 并拉好嵌入模型：

```bash
ollama pull nomic-embed-text
```

## 3. 一键启动（推荐）

```bash
make start   # ollama → docker → db 迁移 → 后端 → 前端（含 30s pg 就绪轮询）
make status  # 查看全部服务状态
make stop    # 停止前后端（保留 Docker + Ollama）
```

> ⚠️ `make db-reset` 目前不删数据卷，与文案不符，需要干净库时改用 `make infra-reset`，见 `Problem/18`。

启动后访问：

| 服务 | 地址 |
| --- | --- |
| 前端页面 | http://localhost:5872 |
| 后端 API | http://localhost:8765 |
| API 文档 | http://localhost:8765/docs |
| 健康检查 | http://localhost:8765/health |

> ⚠️ 前端开发服务器只监听 IPv6 回环，请用 `localhost` 而非 `127.0.0.1` 访问，见 `Problem/10`。

## 4. 手动分步启动（不依赖 Makefile）

```bash
# 4.1 基础设施（项目根目录）
docker compose up -d

# 4.2 后端
cd backend
uv sync               # 安装依赖
uv run alembic upgrade head   # 建表（0001 → 0003）
uv run uvicorn app.main:app --reload --port 8765

# 4.3 前端（另开终端，项目根目录）
cd frontend
pnpm install
pnpm dev
```

## 5. 完整命令速查

```bash
make check          # 后端自检：ruff + mypy + pytest（190 用例）
make backend-test   # 仅 pytest
make backend-lint   # ruff 检查
make backend-typecheck   # mypy
make be-logs        # 看后端日志
make db-shell       # 进入 psql
make redis-shell    # 进入 redis-cli
make stop-all       # 全部停止（含 Docker + Ollama）
```
