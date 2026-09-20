# Multi-Agent RAG 问答应用

基于 **LangGraph** 编排的多 Agent 协作 RAG 问答系统，四个 Agent 分工完成「问题拆解 → 文档检索 → 答案生成 → 质量质检」的闭环。

> 架构：`Planner → Retriever → Generator ⇄ Reviewer`

## 技术栈

| 端 | 技术 | 包管理 | 缓存/复用 |
| --- | --- | --- | --- |
| 后端 | FastAPI · SQLAlchemy · pydantic · LangChain · LangGraph · JWT · bcrypt | **uv** | `~/.cache/uv` |
| 前端 | Vue3 · Vite · Pinia · Vue Router · Element Plus · Axios | **pnpm** | pnpm store 硬链接 |
| 中间件 | PostgreSQL + pgvector · Redis | Docker | 优先复用本地镜像 |
| AI | OpenAI 兼容协议 (Ollama / 阿里云百炼 / OpenAI / DeepSeek) | — | Embedding 与 LLM 共用一套 base_url 切换 |

## Multi-Agent 架构

四个 Agent 由 LangGraph `StateGraph` 编排，单向流转 + Reviewer 回环：

| Agent | 节点 | 职责 |
| --- | --- | --- |
| Planner | `planner` | 把用户问题拆解为可执行的子任务 |
| Retriever | `retriever` | 按子任务从向量库检索相关文档 |
| Generator | `generator` | 基于检索上下文生成回答 |
| Reviewer | `reviewer` | 质检回答质量，不合格则回退 Generator 重新生成（最多 `max_retry` 次） |

- **Checkpoint 恢复**：每个节点执行完自动 checkpoint（开发用 `memory`、生产用 Redis），故障后可从最近 checkpoint `resume`。
- **运行日志落库**：每一步的执行状态、耗时、错误自动写入 `agent_runs` / `agent_steps` 表，前端 `AgentView` 可视化整个协作过程。

## 目录结构

```
├── backend/            # FastAPI 后端(五层架构)
│   └── app/
│       ├── api/routes/     # 路由层 (chat / agent / auth / documents)
│       ├── services/       # 服务层 (chat_service / agent_service / rag_service / ...)
│       ├── repositories/   # 仓储层 (数据访问)
│       ├── schemas/        # 传输模型 (pydantic)
│       ├── models/         # ORM 模型 (含 agent_run / agent_step)
│       ├── config/         # 配置 + 客户端单例 (settings/embeddings/llm/redis/db/checkpoint)
│       ├── core/           # 横切 (exceptions/logging/middleware/response)
│       ├── utils/          # 纯工具函数
│       └── main.py
├── frontend/           # Vue3 前端
│   └── src/{api,views,components,router,stores,utils,assets}
│       └── views/AgentView.vue   # 多 Agent 协作可视化
├── backend/alembic/    # 数据库迁移 (0002 引入 agent_runs / agent_steps)
├── docker-compose.yml  # PostgreSQL+pgvector / Redis
├── Makefile            # 一键启动入口 (make start)
└── backend/.env.example  # 环境变量模板(复制为 .env)
```

**后端单向调用**：`api → service → repository → model`（禁止反向）。

## 快速开始

### 前置准备（一次性）

```bash
cp backend/.env.example backend/.env   # 填入真实 LLM_API_KEY
```

### 一键启动

```bash
make start
```

自动完成：检查并启动 Ollama(仅当 EMBED_BASE_URL 指向 Ollama 时) → 启动 Docker Desktop → `docker compose up -d` → 等待 PostgreSQL 就绪 → `alembic upgrade head` 迁移 → 安装前后端依赖 → 后台拉起后端与前端，结束时在底部打印访问入口：

```
✅ 项目已全部启动，访问入口：
   🎨 前端页面:  http://localhost:5872
   🔧 后端接口:  http://127.0.0.1:8765   API 文档: http://127.0.0.1:8765/docs
```

### 日常操作

| 命令 | 说明 |
| --- | --- |
| `make stop` | 停止前后端开发服务器 |
| `make logs` | 实时查看前后端日志 (.logs/) |
| `make db-generate m="xxx"` | 改完模型后生成迁移 |
| `make db-upgrade` / `make db-downgrade` | 执行迁移 / 回滚 |
| `make infra-logs` / `make infra-reset` | 中间件日志 / ⚠️ 清空数据卷 |

> ⚠️ 旧数据需重建库时：`make infra-reset` 清空数据卷，再 `make db-upgrade` 重新迁移。

## 关键设计

- **Multi-Agent 协作**：LangGraph `StateGraph` 编排 Planner / Retriever / Generator / Reviewer 四个节点，Reviewer 不合格自动回环重生成。
- **Checkpoint 容错**：每个节点执行完自动 checkpoint，故障后 `resume` 从最近 checkpoint 续跑，不重复执行已完成节点。
- **统一 OpenAI 协议**：Embedding 与 LLM 都走 OpenAI 兼容 `base_url`，切换后端只需改 `.env` 三字段，零代码改动。
- **SSE 流式输出**：`/chat/stream` 与 `/agent/runs/stream` 均按事件流推送，前端 `fetch + ReadableStream` 逐 token / 逐节点渲染。
- **多会话管理**：会话 CRUD 持久化到 `sessions` 表，历史按会话隔离，删除会话级联清理对话记录。
- **客户端单例**：`config/embeddings_client.py`、`llm_client.py` 用 `@lru_cache` 复用，避免每次请求重建。
- **层层用户数据隔离**：`api → service → repository` 全程携带 `user_id`，连向量检索也按 user 过滤，不同用户互不可见。
- **JWT 认证**：注册/登录签发无状态 `Bearer` token，`api/dependencies.get_current_user` 统一鉴权；密码用 bcrypt 哈希。
- **分层规范**：强制五层 + 单向依赖，`core/` 放横切关注点。
- **环境变量安全**：`.env` 不入库，提供 `.env.example` 模板(含 JWT / CORS)。

## 核心 API

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/register` | 否 | 注册 |
| POST | `/api/v1/auth/login` | 否 | 登录，返回 token |
| GET | `/api/v1/auth/me` | 是 | 当前用户信息 |
| POST | `/api/v1/chat` | 是 | RAG 问答(同步) |
| POST | `/api/v1/chat/stream` | 是 | RAG 问答(SSE 流式) |
| GET | `/api/v1/chat/history` | 是 | 当前用户对话历史 |
| GET/POST | `/api/v1/chat/sessions` | 是 | 会话列表 / 创建会话 |
| PUT/DELETE | `/api/v1/chat/sessions/{id}` | 是 | 重命名 / 删除会话 |
| GET | `/api/v1/documents` | 是 | 当前用户文档列表 |
| POST | `/api/v1/documents/upload` | 是 | 上传文档 |
| DELETE | `/api/v1/documents/{id}` | 是 | 删除文档 |
| POST | `/api/v1/agent/runs` | 是 | 启动多 Agent 协作(同步阻塞) |
| POST | `/api/v1/agent/runs/resume` | 是 | 从 checkpoint 恢复(同步) |
| POST | `/api/v1/agent/runs/stream` | 是 | 启动多 Agent 协作(SSE 流式) |
| POST | `/api/v1/agent/runs/stream/resume` | 是 | 从 checkpoint 恢复(SSE 流式) |
| GET | `/api/v1/agent/runs` | 是 | Agent 运行记录列表 |
| GET | `/api/v1/agent/runs/{run_id}` | 是 | 运行详情(含每个节点执行日志) |
