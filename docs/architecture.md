# 架构与分层规范

## 1. 分层架构

严格遵循核心五层，**单向调用**：

```
API (路由)  →  Services (业务)  →  Repositories (数据访问)  →  Models (ORM)
                  ↑                                              ↑
              Schemas (出入参)                              Base (声明)
```

- **API（`app/api`）**：路由与 HTTP 协议处理，负责鉴权依赖、请求/响应模型绑定，**不含业务逻辑**。
- **Services（`app/services`）**：业务逻辑层，编排 Repositories 与外部集成，**事务边界所在**（`session.commit()` 在服务层）。
- **Repositories（`app/repositories`）**：封装 SQLAlchemy 数据访问，不掺杂业务规则。
- **Models（`app/models`）**：ORM 实体，继承 `core.database.Base`。
- **Schemas（`app/schemas`）**：Pydantic 请求/响应模型；`response.ApiResponse[T]` 为统一信封。
- **横切模块（非五层）**：
  - `core`：config / database / security / cache / checkpoint / response。
  - `utils`：通用工具（如文件落盘）。
  - `scripts`：验证与端到端脚本（`verify_*.py`、`http_e2e.py`）。

> 已知规范偏差：`models/chunk.py` 与 `repositories/vector_repository.py` 引用 `config.settings`，属轻微向上依赖，见 `Problem/11`（向量维度双份配置）。

## 2. 目录结构

```
backend/app/
├── main.py                 # 应用入口（挂载路由、CORS、生命周期）
├── api/                    # auth / documents / chat / agent
├── services/               # 业务服务（agent_service / agent_dynamic / document_service / rag_service …）
├── repositories/           # 数据访问
├── schemas/                # 入参/出参 + response 信封
├── models/                 # ORM 实体
├── core/                   # config / database / security / cache / checkpoint / response
├── config/                 # settings.py（pydantic-settings，读根目录 .env）
└── utils/                  # 通用工具
```

## 3. Agent 编排设计

### 3.1 四角色闭环

```
planner(问题拆解) → retriever(文档检索) → generator(答案生成) ⇄ reviewer(质量质检)
```

共享状态 `AgentState`（TypedDict，`total=False`）：`question`、`sub_tasks`、`current_task_index`、`context_docs`、`draft_answer`、`final_answer`、`retry_count` 等。

### 3.2 双编排模式（同一批节点，不同连线）

| 模式 | 图结构 | 决策者 |
| --- | --- | --- |
| `deterministic`（默认） | 代码写死边：Planner→Retriever→Generator⇄Reviewer | 无 |
| `dynamic` | 插入 `supervisor` 节点，全部节点回连，模型每步选择下一目标 | LLM |

`supervisor` 输出经 **VALID_TARGETS 白名单** 约束；`dynamic` 模式由六层护栏保证收敛。

### 3.3 六层护栏（`agent_dynamic.py`）

| 层 | 作用 |
| --- | --- |
| 1 | 步数上限（`AGENT_MAX_STEPS`） |
| 2 | 目标名白名单（`VALID_TARGETS`） |
| 3 | 前置状态校验（`_prerequisites_met`，目标节点所需键是否就绪） |
| 4 | 打转检测（进展指纹） |
| 5 | 工具调用上限（`AGENT_MAX_TOOL_CALLS`） |
| 6 | 重试上限 |

不满足时退回 `rule_based_route`（规则路径），保证图一定收敛。

### 3.4 工具（AST 白名单求值）

`TOOL_REGISTRY`：`calculate`（四则运算）、`context_stats`（上下文统计）。工具表达式以 AST 白名单求值，不执行任意代码。

### 3.5 人工介入（HITL）

`AGENT_HITL_ENABLED=true` 时，Reviewer 打回先 `interrupt` 暂停，运行落库 `awaiting_review`。

恢复接口 `POST /agent/runs/resume` 以 `decision` 裁决：`accept`（采纳草稿）/ `rewrite`（按反馈重写）。

### 3.6 Checkpoint

`config/checkpoint.py`：`AGENT_CHECKPOINT_BACKEND`（memory 默认 / redis），`thread_id=run_id`，redis 失败降级 memory。

### 3.7 运行状态机

```
pending → planning → retrieving → generating → reviewing → completed / failed / awaiting_review
```

## 4. 一次 Agent 运行的调用链

```
POST /api/v1/agent/runs
  └─ api/agent.py                    (AgentRunRequest 校验, get_current_user 依赖)
       └─ services/agent_service.run()
            ├─ sessions 校验 / 创建
            ├─ AgentState 初始化
            ├─ LangGraph 编译图执行（deterministic / dynamic）
            │    ├─ planner     → sub_tasks
            │    ├─ retriever   → context_docs（vector_repository 按 user_id 检索）
            │    ├─ generator   → draft_answer
            │    └─ reviewer    → 通过则 final_answer；打回则重试 / interrupt
            ├─ checkpoint 写入（thread_id=run_id）
            ├─ agent_runs / agent_steps 落库
            └─ 返回 run_id + status
```

## 5. 编码规范 Checklist（落地要求）

### 类型注解
- [ ] 函数参数、返回值**必须**标注类型；无返回显式 `-> None`。
- [ ] 简单局部变量若推导清晰可省略；空容器 / 嵌套结构 / 自定义模型实例**必须**显式标注。

### 命名
- [ ] 类 `PascalCase`；函数 / 变量 / 文件 `snake_case`；常量 `UPPER_SNAKE`。
- [ ] 私有成员单下划线 `_xxx`。

### 导入
- [ ] 业务逻辑**优先绝对导入**（`from app.xxx import yyy`）。
- [ ] 顺序：标准库 → 第三方库 → 项目内部；组间空行、组内字母序。

### 响应一致性
- [ ] 所有 JSON 接口经 `ApiResponse[T]` 返回。
- [ ] SSE 流不套信封，按事件类型推送。

### 质量门禁
- [ ] 提交前 `uv run ruff check .` 与 `uv run mypy app`（strict）零告警。
- [ ] 后端自测：`uv run pytest`（190 用例，内存 SQLite + FakeRedis，无外部依赖）。

## 6. 关键技术点

- **向量检索**：pgvector `<=>` 算子（余弦距离），相似度 `score = 1 - distance`；`vector_repository.py` 原生 SQL，`JOIN documents` 后按 `user_id` 过滤，`LIMIT top_k`（默认 3）；`score` 仅作元数据返回，**无阈值过滤**。
- **分块**：`RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)`。
- **检索缓存**：`core/cache.py`，key=`retrieval_key(user_id, question)`，TTL=`RETRIEVAL_TTL_SECONDS`；上传 / 删除文档时清前缀缓存。
- **鉴权**：JWT（HS256，`JWT_EXPIRE_MINUTES=10080`），`HTTPBearer` 解析，`get_current_user` 依赖注入。
- **多提供方（OpenAI 兼容接口）**：通过 `LLM_BASE_URL` / `EMBED_BASE_URL` 切换云端（dashscope 百炼）或本地 Ollama，无需 provider 开关。
