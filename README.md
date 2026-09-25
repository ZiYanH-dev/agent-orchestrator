# Agent Orchestrator

基于 **LangGraph** 的多 Agent 编排引擎。四个角色分工完成「问题拆解 → 文档检索 → 答案生成 → 质量质检」的闭环，编排本身才是这套系统的本体，检索只是被编排的一个环节。

支持两种编排模式，由配置切换，复用同一批节点实现：

| 模式 | 路径怎么定 | 适用 |
| --- | --- | --- |
| `deterministic` | 边由代码写死，`Planner → Retriever → Generator ⇄ Reviewer` | 流程稳定的问答 |
| `dynamic` | 中间插入 `supervisor`，每一步由模型读取阶段状态决定下一个执行者 | 路径随任务形状变化 |

动态模式下模型决策不受约束，因此叠加六层护栏：步数上限、目标白名单、前置状态校验、原地打转检测、工具调用上限、重试上限。任一层触发都退回与确定性编排同构的规则路径，保证图一定收敛。

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [编排架构](#编排架构)
- [核心 API](#核心-api)
- [相关文档](#相关文档)

## 功能特性

- **双模式编排**：`AGENT_ORCHESTRATION_MODE` 在 `deterministic` 与 `dynamic` 之间切换，复用同一批节点，只有连线方式不同。
- **六层护栏**：步数上限、目标白名单、前置状态校验、打转检测、工具调用上限、重试上限；模型输出什么都不影响收敛。
- **Human-in-the-loop**：Reviewer 判定不通过先 `interrupt` 暂停，运行落库 `awaiting_review`，恢复时 `accept` 采纳草稿 / `rewrite` 按反馈重写。
- **工具生态**：注册表派发，新增工具只需统一签名登记；算术表达式走 AST 白名单求值，拒绝导入与任意代码执行。
- **Checkpoint 容错**：每个节点执行完自动 checkpoint（开发 memory / 生产 Redis），故障后 `resume` 不重复执行已完成节点。
- **SSE 流式输出**：对话与 Agent 运行均按事件流推送，前端逐 token / 逐节点渲染。
- **用户数据隔离**：`api → service → repository` 全程携带 `user_id`，向量检索也按用户过滤。
- **统一 OpenAI 协议**：LLM 与 Embedding 都走 OpenAI 兼容 `base_url`，切换提供方零代码改动。

## 技术栈

| 端 | 技术 | 包管理 |
| --- | --- | --- |
| 后端 | FastAPI · SQLAlchemy · Pydantic · LangChain · LangGraph · JWT · bcrypt | uv |
| 前端 | Vue 3 · Vite · Pinia · Vue Router · Element Plus · Axios | pnpm |
| 中间件 | PostgreSQL + pgvector · Redis | Docker |
| AI | OpenAI 兼容协议（Ollama / 阿里云百炼 / OpenAI / DeepSeek） | — |

> 统一 OpenAI 兼容协议：切换 LLM / Embedding 提供方只需改 `.env` 里的 `LLM_BASE_URL` / `EMBED_BASE_URL` 与模型名，无需改代码。

## 快速开始

### 前置依赖

| 工具 | 用途 |
| --- | --- |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | PostgreSQL + Redis |
| [uv](https://docs.astral.sh/uv/) | Python 包管理 |
| [pnpm](https://pnpm.io/) | 前端包管理 |
| [Ollama](https://ollama.com/) | 本地 Embedding 模型（用云端则不用装） |

### 配置环境变量

`.env` 放在**项目根目录**，从模板复制：

```bash
cp .env.example .env
```

至少填入真实 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME`。若 Embedding 用本地 Ollama，先拉取模型：

```bash
ollama pull nomic-embed-text
```

### 一键启动

```bash
make start
```

自动完成：检查并启动 Ollama（仅当 `EMBED_BASE_URL` 指向 Ollama）→ 启动 Docker → `docker compose up -d` → 等待 PostgreSQL 就绪 → `alembic upgrade head` 迁移 → 安装前后端依赖 → 后台拉起前后端。启动后访问：

| 服务 | 地址 |
| --- | --- |
| 前端页面 | http://localhost:5872 |
| 后端 API | http://localhost:8765 |
| API 文档 | http://localhost:8765/docs |

### 日常操作

| 命令 | 说明 |
| --- | --- |
| `make stop` | 停止前后端开发服务器 |
| `make logs` | 实时查看前后端日志 (`.logs/`) |
| `make check` | 后端自检：ruff + mypy + pytest |
| `make db-generate m="xxx"` | 改完模型后生成迁移 |
| `make db-upgrade` / `make db-downgrade` | 执行迁移 / 回滚 |
| `make infra-logs` / `make infra-reset` | 中间件日志 / ⚠️ 清空数据卷 |

> ⚠️ 旧数据需重建库时：`make infra-reset` 清空数据卷，再 `make db-upgrade` 重新迁移。

## 项目结构

```
├── backend/            # FastAPI 后端（五层架构）
│   └── app/
│       ├── api/routes/     # 路由层 (chat / agent / auth / documents)
│       ├── services/       # 服务层 (agent_service 编排主图 / agent_dynamic 动态编排 / rag_service / chat_service)
│       ├── repositories/   # 仓储层 (数据访问)
│       ├── schemas/        # 传输模型 (pydantic)
│       ├── models/         # ORM 模型 (含 agent_run / agent_step)
│       ├── config/         # 配置 + 客户端单例 (settings/embeddings/llm/redis/db/checkpoint)
│       ├── core/           # 横切 (exceptions/logging/middleware/response)
│       ├── utils/          # 纯工具函数
│       └── main.py
├── frontend/           # Vue3 前端
│   └── src/{api,views,components,router,stores}
│       └── views/AgentView.vue   # 多 Agent 协作可视化 + 人工裁决面板
├── backend/alembic/    # 数据库迁移 (0001 → 0003)
├── docker-compose.yml  # PostgreSQL + pgvector / Redis
├── Makefile            # 一键启动入口 (make start)
└── .env.example        # 环境变量模板（复制为根目录 .env）
```

**后端单向调用**：`api → service → repository → model`（禁止反向）。

## 编排架构

节点由 LangGraph `StateGraph` 承载，共享状态用 TypedDict 声明：

| 角色 | 节点 | 职责 |
| --- | --- | --- |
| Supervisor | `supervisor` | 仅动态模式存在，读取阶段状态决定下一个执行者，并用 `Command` 接收工人交回的控制权 |
| Planner | `planner` | 把用户问题拆解为可执行的子任务 |
| Retriever | `retriever` | 按子任务从向量库检索相关文档 |
| Generator | `generator` | 基于检索上下文生成回答 |
| Reviewer | `reviewer` | 质检回答质量，不合格则回退 Generator 重新生成，最多 `max_retry` 次 |
| Tool | `tool` | 仅动态模式存在，按注册表派发工具，算术表达式走 AST 白名单求值 |

- **确定性模式的连线**：`START → planner → retriever`，retriever 出条件边回到自身或转 `generator`，generator 转 `reviewer`，reviewer 出条件边回到 `generator` 或转 `END`。
- **动态模式的连线**：所有节点都连回 `supervisor`，下一步去哪由模型决定。
- **Checkpoint 恢复**：每个节点执行完自动 checkpoint，开发用 `memory`，生产用 Redis，故障后可从最近 checkpoint `resume`。
- **运行日志落库**：每一步的执行状态、耗时、错误自动写入 `agent_runs` / `agent_steps` 表，前端 `AgentView` 可视化整个协作过程。

## 核心 API

Base URL：`/api/v1`。除 `/health` 外均需 `Authorization: Bearer <token>`；除 SSE 流外统一返回 `ApiResponse{code, message, data}` 信封。

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/auth/register` | 否 | 注册 |
| POST | `/auth/login` | 否 | 登录，返回 token |
| GET | `/auth/me` | 是 | 当前用户信息 |
| POST | `/chat` | 是 | RAG 问答（同步） |
| POST | `/chat/stream` | 是 | RAG 问答（SSE 流式） |
| GET | `/chat/history` | 是 | 当前用户对话历史 |
| GET/POST | `/chat/sessions` | 是 | 会话列表 / 创建会话 |
| PUT/DELETE | `/chat/sessions/{id}` | 是 | 重命名 / 删除会话 |
| GET | `/documents` | 是 | 当前用户文档列表 |
| POST | `/documents/upload` | 是 | 上传文档（.txt / .md） |
| DELETE | `/documents/{id}` | 是 | 删除文档 |
| POST | `/agent/runs` | 是 | 启动多 Agent 协作（同步） |
| POST | `/agent/runs/stream` | 是 | 启动多 Agent 协作（SSE 流式） |
| POST | `/agent/runs/resume` | 是 | 恢复运行，可带 `decision` 提交人工裁决 |
| POST | `/agent/runs/stream/resume` | 是 | 同上（SSE 流式） |
| GET | `/agent/runs` | 是 | Agent 运行记录列表 |
| GET | `/agent/runs/{run_id}` | 是 | 运行详情（含每个节点执行日志） |

## 相关文档

| 文档 | 说明 |
| --- | --- |
| [docs/](docs/README.md) | 项目设计文档（需求 / 架构 / 数据库 / API / 前端 / 启动指南） |
| [Problem/](Problem/README.md) | 已知问题清单与修复状态 |
| [.Project_Help/](.Project_Help/README.md) | 技术知识库（框架与实现原理） |
