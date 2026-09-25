# API 接口规范

> Base URL：`/api/v1`
> 交互式文档：启动后访问 `/docs`（Swagger）

## 1. 通用约定

### 1.1 鉴权
除 `/health` 外，所有接口需在请求头携带 JWT：

```
Authorization: Bearer <access_token>
```

令牌由 `POST /auth/login` 返回。未携带或过期返回 `401`。

### 1.2 统一响应信封
除 SSE 流接口外，所有 JSON 接口均返回 `ApiResponse[T]`：

```json
{
  "code": 0,
  "message": "success",
  "data": { }
}
```

- `code`：业务状态码，`0` 成功，非 `0` 业务异常。
- `message`：提示文案。
- `data`：业务负载，类型随接口而定；无负载为 `null`。

> DELETE 接口统一返回 `200` + `ApiResponse[DeleteOut]`（`data.id` 为被删资源 ID），不使用 `204`。

### 1.3 错误响应
业务异常以 HTTP 状态码体现，错误体形如：

```json
{ "detail": "文档不存在" }
```

## 2. 接口清单

### 2.1 认证 `auth`

#### POST `/auth/register`
请求体 `UserRegister`：`username`(必填)、`email`(可选)、`password`(必填)。
响应 `ApiResponse[UserOut]`（data = 新建用户，不含密码）。

#### POST `/auth/login`
请求体 `UserLogin`：`username`、`password`。
响应 `ApiResponse[TokenResponse]`：

```json
{ "code": 0, "message": "success",
  "data": { "access_token": "<jwt>", "token_type": "bearer" } }
```

#### GET `/auth/me`
需鉴权。响应 `ApiResponse[UserOut]`（当前用户）。

### 2.2 文档 `documents`

#### POST `/documents/upload`
需鉴权。表单字段 `file`（multipart）。支持 `.txt` / `.md`（UTF-8 文本）。
处理流程（同步）：落盘 → 解析 → 分块 → 向量化入库。
响应 `ApiResponse[DocumentOut]`（data = 文档元信息，含 `chunk_count`）。

> ⚠️ 非 UTF-8 / PDF / Word 会触发 500，类型与编码未校验，见 `Problem/16`。

#### GET `/documents`
需鉴权。Query：`skip`(默认0)、`limit`(默认20)。
响应 `ApiResponse[DocumentListOut]`：`{ total, items: [DocumentOut] }`。

#### DELETE `/documents/{document_id}`
需鉴权。响应 `200` + `ApiResponse[DeleteOut]`：`{ "data": { "id": 1 } }`；不存在返回 `404`。
删除含分块与向量；磁盘文件不删，见 `Problem/17`。

### 2.3 会话 `chat/sessions`

#### GET `/chat/sessions`
需鉴权。响应 `ApiResponse[list[SessionOut]]`。

#### POST `/chat/sessions`
需鉴权。请求体 `SessionCreate`：`name`。
响应 `ApiResponse[SessionOut]`：`id, name, created_at, updated_at`。

#### PUT `/chat/sessions/{session_id}`
需鉴权。请求体 `SessionUpdate`：`name`。
响应 `ApiResponse[SessionOut]`。

#### DELETE `/chat/sessions/{session_id}`
需鉴权。响应 `200` + `ApiResponse[DeleteOut]`。

### 2.4 问答 `chat`

#### POST `/chat`（同步）
需鉴权。请求体 `ChatRequest`：`question`、`session_id`（可选，留空自动建会话）。
响应 `ApiResponse[ChatResponse]`：`answer` + `sources`（引用来源列表）。

#### POST `/chat/stream`（SSE）
需鉴权。请求体同上。响应 `Content-Type: text/event-stream`，**不使用 JSON 信封**。

事件格式（每行一个 SSE `data` 帧，JSON 含 `type` 与 `content`）：

```
data: {"type": "sources", "content": [{"document_id": 1, "chunk_index": 0, "snippet": "...", "score": 0.82}]}

data: {"type": "token", "content": "根据"}

data: {"type": "token", "content": "文档..."}

data: {"type": "done"}

data: [DONE]
```

事件类型：
- `sources`：引用来源数组（首帧）。
- `token`：回答增量文本，前端拼接为完整回答。
- `done`：流结束标记；随后以 `data: [DONE]` 收尾。

#### GET `/chat/history`
需鉴权。Query：`session_id`、`skip`、`limit`。
响应 `ApiResponse[list[ChatRecordOut]]`：`id, question, answer, sources, created_at`。

### 2.5 Agent 编排 `agent/runs`

#### POST `/agent/runs`
需鉴权。请求体 `AgentRunRequest`：`question`、`session_id`（可选，默认 "default"）。
响应 `ApiResponse[AgentRunOut]`：`run_id, session_id, status, checkpoint_id, retry_count, started_at`。

#### POST `/agent/runs/stream`（SSE）
需鉴权。请求体同上。事件类型：

```
data: {"type": "node_start", "content": {"node": "planner", "run_id": "..."}}

data: {"type": "node_done", "content": {"node": "retriever", "run_id": "..."}}

data: {"type": "final_answer", "content": "..."}

data: {"type": "interrupt", "content": {"run_id": "..."}}     # HITL 暂停

data: {"type": "done"}
```

- `node_start` / `node_done`：节点轨迹（前端渲染时间线）。
- `final_answer`：最终回答。
- `interrupt`：HITL 暂停，运行落 `awaiting_review`。
- `done` / `error`：结束或失败。

#### POST `/agent/runs/resume`
需鉴权。请求体 `AgentRunResumeRequest`：`run_id`、`decision`（`accept` 采纳草稿 / `rewrite` 按反馈重写）。
响应 `ApiResponse[AgentRunOut]`（新状态）。

> ⚠️ 已知缺陷：该端点缺少归属校验，见 `Problem/02`。

#### POST `/agent/runs/stream/resume`（SSE）
需鉴权。请求体同上。事件在流式事件基础上额外含 `resumed`（`retry_count`）。

#### GET `/agent/runs`
需鉴权。Query：`session_id`（默认 "default"）、`limit`（≤100）。
响应 `ApiResponse[list[AgentRunOut]]`。

#### GET `/agent/runs/{run_id}`
需鉴权。响应 `ApiResponse[AgentRunDetail]`（运行信息 + 步骤列表）。

> ⚠️ 已知缺陷：该端点缺少归属校验，见 `Problem/01`。

### 2.6 系统

#### GET `/health`
无需鉴权。响应健康状态体。

## 3. 状态码速查

| HTTP | 含义 |
| --- | --- |
| 200 | 成功（含 DELETE） |
| 400 | 参数错误 |
| 401 | 未认证 / 令牌无效 |
| 404 | 资源不存在 |
| 422 | 校验失败（不支持的文件类型 / 编码错误） |
| 500 | 服务器内部错误 |
