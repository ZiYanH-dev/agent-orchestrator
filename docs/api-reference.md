# 接口一览（总表）

> 所有业务接口 Base URL 前缀均为 `/api/v1`。
> 鉴权：除 `/health` 外均需 `Authorization: Bearer <token>`。
> 响应：除 SSE 流（`/chat/stream`、`/agent/runs/stream*`）外，统一返回 `ApiResponse[T]` 信封（`{code, message, data}`）。
> 字段级定义见 [`api-spec.md`](./api-spec.md)。

## 系统

| 方法 | 路径 | 鉴权 | 请求 | 响应 data | 说明 |
| --- | --- | --- | --- | --- | --- |
| GET | `/health` | 否 | — | 健康状态 | 健康检查 |

## 认证 `/auth`

| 方法 | 路径 | 鉴权 | 请求 | 响应 data | 说明 |
| --- | --- | --- | --- | --- | --- |
| POST | `/auth/register` | 否 | `UserRegister` | `UserOut` | 注册 |
| POST | `/auth/login` | 否 | `UserLogin` | `TokenResponse` | 登录，返回 JWT |
| GET | `/auth/me` | 是 | — | `UserOut` | 当前用户信息 |

## 文档 `/documents`

| 方法 | 路径 | 鉴权 | 请求 | 响应 data | 说明 |
| --- | --- | --- | --- | --- | --- |
| POST | `/documents/upload` | 是 | form `file` | `DocumentOut` | 上传并解析+向量化（.txt/.md） |
| GET | `/documents` | 是 | query `skip`,`limit` | `DocumentListOut` | 文档列表（分页） |
| DELETE | `/documents/{document_id}` | 是 | — | `DeleteOut` | 删除文档（含分块与向量） |

## 会话 `/chat/sessions`

| 方法 | 路径 | 鉴权 | 请求 | 响应 data | 说明 |
| --- | --- | --- | --- | --- | --- |
| GET | `/chat/sessions` | 是 | — | `list[SessionOut]` | 会话列表 |
| POST | `/chat/sessions` | 是 | `SessionCreate` | `SessionOut` | 创建会话 |
| PUT | `/chat/sessions/{session_id}` | 是 | `SessionUpdate` | `SessionOut` | 重命名会话 |
| DELETE | `/chat/sessions/{session_id}` | 是 | — | `DeleteOut` | 删除会话 |

## 问答 `/chat`

| 方法 | 路径 | 鉴权 | 请求 | 响应 data | 说明 |
| --- | --- | --- | --- | --- | --- |
| POST | `/chat` | 是 | `ChatRequest` | `ChatResponse` | 同步 RAG 问答 |
| POST | `/chat/stream` | 是 | `ChatRequest` | SSE 流 | 流式问答，事件：`sources → token → done` |
| GET | `/chat/history` | 是 | query `session_id`,`skip`,`limit` | `list[ChatRecordOut]` | 会话历史消息 |

## Agent 编排 `/agent/runs`

| 方法 | 路径 | 鉴权 | 请求 | 响应 data | 说明 |
| --- | --- | --- | --- | --- | --- |
| POST | `/agent/runs` | 是 | `AgentRunRequest` | `AgentRunOut` | 启动 Agent 运行（deterministic 默认） |
| POST | `/agent/runs/stream` | 是 | `AgentRunRequest` | SSE 流 | 流式运行，事件含节点轨迹 |
| POST | `/agent/runs/resume` | 是 | `AgentRunResumeRequest` | `AgentRunOut` | 恢复 HITL 暂停的运行 |
| POST | `/agent/runs/stream/resume` | 是 | `AgentRunResumeRequest` | SSE 流 | 流式恢复运行 |
| GET | `/agent/runs` | 是 | query `session_id`(默认 "default"),`limit`(≤100) | `list[AgentRunOut]` | 运行列表 |
| GET | `/agent/runs/{run_id}` | 是 | — | `AgentRunDetail` | 运行详情（含步骤） |

> ⚠️ 已知缺陷：`GET /agent/runs/{run_id}` 与 `POST /agent/runs/resume` **缺少归属校验**，任何登录用户可读/改他人运行，见 `Problem/01`、`Problem/02`。

## 统计

| 模块 | 接口数 |
| --- | --- |
| 系统 | 1 |
| 认证 | 3 |
| 文档 | 3 |
| 会话 | 4 |
| 问答 | 3 |
| Agent 编排 | 6 |
| **合计** | **20** |

## 状态码速查

| HTTP | 含义 |
| --- | --- |
| 200 | 成功（含 DELETE） |
| 400 | 参数错误 |
| 401 | 未认证 / 令牌无效 |
| 404 | 资源不存在 |
| 422 | 校验失败（不支持的文件类型 / 编码错误） |
| 500 | 服务器内部错误 |
