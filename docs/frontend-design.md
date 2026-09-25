# 前端 UI 设计 / 原型说明

> 状态：**已实现**（Vue 3 + TypeScript + Vite + pnpm；Pinia 状态管理；Axios；SSE 用 `fetch` + `ReadableStream` 手拆 `\n\n`；UI 库 Element Plus）。

## 1. 页面与路由

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/login` | 登录 | 表单提交至 `/auth/login` |
| `/chat` | 问答 | 同步 / 流式 RAG 问答，历史会话 |
| `/agent` | Agent 编排 | 时间线展示运行轨迹 + 人工裁决（HITL） |
| `/documents` | 知识库 | 上传（.txt/.md）、列表、删除 |
| `/profile` | 个人中心 | 当前用户信息（只读） |
| `*` | 404 | 通配兜底路由 |

路由守卫基于 localStorage 的 `rag_token`：未登录跳转 `/login`。

## 2. 核心交互

### 2.1 Agent 编排页（`/agent`）
- 顶部输入问题，调用 `POST /agent/runs/stream`。
- SSE 事件驱动时间线：`node_start` 添加节点徽标，`node_done` 更新耗时，`final_answer` 渲染回答。
- 运行状态为 `awaiting_review` 时，展示「采纳 / 重写」按钮，调用 `POST /agent/runs/resume`（或 stream/resume）。
- 历史运行按 `session_id` 分组，点击加载详情。

### 2.2 问答页（`/chat`）
- 会话列表（创建 / 重命名 / 删除 / 选中），调用 `/chat/sessions` 系列接口。
- 发送消息：`POST /chat/stream` 以 SSE 逐 `token` 追加渲染；`sources` 事件渲染引用来源卡片。
- 历史回看：`GET /chat/history`。

### 2.3 知识库页（`/documents`）
- 上传区：选择 `.txt` / `.md`，调用 `POST /documents/upload`（multipart）。
- 列表：文件名、分块数、大小、删除按钮（`DELETE /documents/{id}`）。

### 2.4 SSE 消费要点
- 使用 `fetch` + `ReadableStream`，按 `\n\n` 拆帧，解析每帧 `data:` 后的 JSON。
- 按 `type` 分发：`token` → 追加文本；`sources` → 暂存待流结束渲染；`node_start/node_done` → 更新时间线；`done` / `[DONE]` → 结束 loading。
- 维护"回答进行中"状态，禁止在 `done` 前重复发送。

## 3. 页面原型（线框）

```
┌──────────────────────────────────────────────┐
│  Agent 编排         [问答][知识库][用户]       │
├──────────────┬───────────────────────────────┤
│ 会话         │  问题：总结这份资料            │
│ • default    │  ┌─ 运行时间线 ─────────────┐  │
│ [+ 新会话]   │  │ ● planner  0.3s  ✅      │  │
│              │  │ ● retriever 1.1s ✅      │  │
│              │  │ ● generator 2.4s ✅      │  │
│              │  │ ● reviewer 0.8s ✅       │  │
│              │  └──────────────────────────┘  │
│              │  AI：根据资料……（最终回答）    │
│              │  ────────────────────────────  │
│              │  [ 输入框……………… ] [发送]      │
└──────────────┴───────────────────────────────┘
```

## 4. 目录结构

```
frontend/src/
├── api/          # axios 实例 + 各模块请求封装（auth/chat/agent/document）
├── stores/       # Pinia：auth/chat/agent/document
├── views/        # 页面级组件（LoginView/ChatView/AgentView/DocumentView/ProfileView/NotFoundView）
├── components/   # 时间线 / 消息气泡 / 来源卡片 / 上传区
└── router/       # 路由与登录守卫
```

## 5. 与后端对接要点

- 所有请求默认带 `Authorization: Bearer <token>`（Pinia 存储，Axios 拦截器注入）。
- 统一解包 `ApiResponse<T>`：`code===0` 取 `data`，否则 toast 错误。
- SSE 不套信封，单独按 `type` 事件处理。
- 后端端口 `BACKEND_PORT=8765`、前端端口 `FRONTEND_PORT=5872`；开发时前端用 `http://localhost:5872`（Vite 只监听 IPv6，用 localhost 而非 127.0.0.1，见 `Problem/10`）。
