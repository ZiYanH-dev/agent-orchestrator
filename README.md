# Agent Orchestrator

基于 **LangGraph** 的多 Agent 编排引擎。四个角色分工完成「问题拆解 → 文档检索 → 答案生成 → 质量质检」的闭环，编排本身才是这套系统的本体，检索只是被编排的一个环节。

支持两种编排模式，由配置切换，复用同一批节点实现：

| 模式 | 路径怎么定 | 适用 |
| --- | --- | --- |
| `deterministic` | 边由代码写死，`Planner → Retriever → Generator ⇄ Reviewer` | 流程稳定的问答 |
| `dynamic` | 中间插入 `supervisor`，每一步由模型读取阶段状态决定下一个执行者 | 路径随任务形状变化 |

动态模式下模型决策不受约束，因此叠加五层护栏：步数上限、目标白名单、原地打转检测、工具调用上限、重试上限。任一层触发都退回与确定性编排同构的规则路径，保证图一定收敛。

## 技术栈

| 端 | 技术 | 包管理 | 缓存/复用 |
| --- | --- | --- | --- |
| 后端 | FastAPI · SQLAlchemy · pydantic · LangChain · LangGraph · JWT · bcrypt | **uv** | `~/.cache/uv` |
| 前端 | Vue3 · Vite · Pinia · Vue Router · Element Plus · Axios | **pnpm** | pnpm store 硬链接 |
| 中间件 | PostgreSQL + pgvector · Redis | Docker | 优先复用本地镜像 |
| AI | OpenAI 兼容协议 (Ollama / 阿里云百炼 / OpenAI / DeepSeek) | — | Embedding 与 LLM 共用一套 base_url 切换 |

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

## 目录结构

```
├── backend/            # FastAPI 后端(五层架构)
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
│   └── src/{api,views,components,router,stores,utils,assets}
│       └── views/AgentView.vue   # 多 Agent 协作可视化 + 人工裁决面板
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

- **双模式编排**：`AGENT_ORCHESTRATION_MODE` 在 `deterministic` 与 `dynamic` 之间切换，两者复用同一批节点实现，只有连线方式不同。
- **模型决策路由**：动态模式下 `supervisor` 每一步读取阶段状态清单决定下一个执行者，工人节点执行完用 `Command(goto=...)` 把控制权交回。
- **五层护栏**：步数上限、目标白名单、原地打转检测、工具调用上限、重试上限，任一层触发都退回规则路径，模型输出什么都不影响收敛。
- **Human-in-the-loop**：开启后 Reviewer 判定不通过先 `interrupt` 暂停，运行落库 `awaiting_review`，调用方带裁决值从 checkpoint 续跑，`accept` 采纳草稿、`rewrite` 按反馈重写。
- **工具生态**：工具以注册表承载，新增工具只需实现统一签名并登记进表即可被派发；算术表达式走 AST 白名单求值，只放行数字常量与四则运算，拒绝导入、属性访问与推导式。
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
| POST | `/api/v1/agent/runs/resume` | 是 | 从 checkpoint 恢复，可带 `decision` 提交人工裁决(同步) |
| POST | `/api/v1/agent/runs/stream` | 是 | 启动多 Agent 协作(SSE 流式) |
| POST | `/api/v1/agent/runs/stream/resume` | 是 | 从 checkpoint 恢复，可带 `decision` 提交人工裁决(SSE 流式) |
| GET | `/api/v1/agent/runs` | 是 | Agent 运行记录列表 |
| GET | `/api/v1/agent/runs/{run_id}` | 是 | 运行详情(含每个节点执行日志) |
