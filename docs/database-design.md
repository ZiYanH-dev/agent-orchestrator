# 数据库表设计

> 数据库：PostgreSQL 17 + pgvector 扩展（`pgvector/pgvector:pg17`）
> 迁移文件：`backend/alembic/versions/0001_init.py` → `0002_agent_runs.py` → `0003_sessions.py`

## 1. 实体关系（ER）

```
users (1) ───< (N) documents (1) ───< (N) chunks
  │
  ├──────────< (N) chat_records
  ├──────────< (N) sessions
  └──────────< (N) agent_runs (1) ───< (N) agent_steps
```

- 一个用户拥有多份文档、多条聊天记录、多个会话、多次 Agent 运行。
- 一份文档拆分为多个分块（`chunks`），分块携带向量 `embedding`。
- 一次 Agent 运行包含多个步骤（`agent_steps`），记录每个节点的执行与重试。

## 2. 表结构

### 2.1 users（用户）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK, 自增 | 用户 ID |
| username | VARCHAR(64) | NOT NULL, UNIQUE, INDEX | 用户名 |
| email | VARCHAR(255) | UNIQUE, INDEX, NULL | 邮箱（可选） |
| hashed_password | VARCHAR(128) | NOT NULL | 哈希密码 |
| created_at | TIMESTAMPTZ | NOT NULL, 默认 now() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL, 默认 now() | 更新时间 |

### 2.2 documents（文档）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK, 自增 | 文档 ID |
| user_id | BIGINT | FK→users.id ON DELETE CASCADE, NOT NULL, INDEX | 归属用户 |
| filename | VARCHAR(255) | NOT NULL | 原始文件名 |
| file_path | VARCHAR(1024) | NOT NULL | 服务器落盘路径 |
| chunk_count | INTEGER | 默认 0 | 分块数 |
| created_at | TIMESTAMPTZ | NOT NULL, 默认 now() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL, 默认 now() | 更新时间 |

### 2.3 chunks（文档分块 / 向量）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK, 自增 | 分块 ID |
| document_id | BIGINT | FK→documents.id ON DELETE CASCADE, NOT NULL, INDEX | 所属文档 |
| chunk_index | INTEGER | NOT NULL | 分块序号 |
| content | TEXT | NOT NULL | 分块文本 |
| embedding | VECTOR(768) | NULL | 文本向量（维度与 `EMBED_DIMENSION` 一致） |
| created_at | TIMESTAMPTZ | NOT NULL, 默认 now() | 创建时间 |

> ⚠️ 向量维度双份配置：迁移文件写死 `768`，模型层取 `settings.VECTOR_DIMENSION`（同为 768）。换 embedding 模型需同步改两处并重建向量，见 `Problem/11`。

### 2.4 chat_records（聊天记录）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK, 自增 | 记录 ID |
| user_id | BIGINT | FK→users.id ON DELETE CASCADE, NOT NULL, INDEX | 归属用户 |
| session_id | VARCHAR(64) | NOT NULL, INDEX | 所属会话 |
| question | TEXT | NOT NULL | 用户问题 |
| answer | TEXT | NOT NULL | 回答 |
| sources | TEXT | NULL | 引用来源（序列化文本） |
| created_at | TIMESTAMPTZ | NOT NULL, 默认 now() | 创建时间 |

### 2.5 sessions（会话）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | VARCHAR(36) | PK | 会话 ID（UUID 字符串） |
| user_id | BIGINT | FK→users.id ON DELETE CASCADE, NOT NULL, INDEX | 归属用户 |
| name | VARCHAR(128) | NOT NULL | 会话名 |
| created_at | TIMESTAMPTZ | NOT NULL, 默认 now() | 创建时间 |
| updated_at | TIMESTAMPTZ | NOT NULL, 默认 now(), 更新时刷新 | 更新时间 |

### 2.6 agent_runs（Agent 运行）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK, 自增 | 行 ID |
| run_id | VARCHAR(64) | NOT NULL, UNIQUE, INDEX | 运行 ID（外部引用键） |
| user_id | BIGINT | FK→users.id, NOT NULL | 归属用户 |
| session_id | VARCHAR(64) | NOT NULL, INDEX | 所属会话 |
| status | VARCHAR(32) | NOT NULL, 默认 `pending` | 运行状态 |
| checkpoint_id | VARCHAR(255) | NULL | checkpoint 标识 |
| retry_count | INTEGER | 默认 0 | 重试次数 |
| started_at | TIMESTAMPTZ | NOT NULL | 开始时间 |

> `status` 取值：`pending / planning / retrieving / generating / reviewing / completed / failed / awaiting_review`。

### 2.7 agent_steps（Agent 步骤）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGINT | PK, 自增 | 步骤 ID |
| run_id | VARCHAR(64) | FK→agent_runs.run_id ON DELETE CASCADE, NOT NULL, INDEX | 所属运行 |
| node_name | VARCHAR(32) | NOT NULL, INDEX | 节点名 |
| attempt | INTEGER | 默认 1 | 尝试次数 |
| status | VARCHAR(16) | NOT NULL, 默认 `running` | 步骤状态 |
| duration_ms | INTEGER | NULL | 耗时（毫秒） |

## 3. 向量检索说明

- 使用 pgvector `<=>` 算子计算**余弦距离**，相似度 `score = 1 - distance`。
- 检索 SQL（`vector_repository.py`）：`JOIN documents` 后 `WHERE d.user_id = :user_id` 保证**仅检索当前用户文档**，按距离升序取 `LIMIT top_k`（默认 3）。
- `score` 仅作为元数据返回给调用方，**无业务阈值过滤**。
- 向量维度必须与 `EMBED_DIMENSION`（768）一致，否则插入报错。

## 4. 级联删除一览

| 父表 | 子表 | 行为 |
| --- | --- | --- |
| users | documents / chat_records / sessions | CASCADE |
| documents | chunks | CASCADE |
| agent_runs | agent_steps | CASCADE |

> ⚠️ 落盘文件不走数据库级联：删文档只删行不删磁盘文件，见 `Problem/17`。

## 5. 迁移链

| 迁移 | 内容 |
| --- | --- |
| `0001_init.py` | `CREATE EXTENSION vector`；users / documents / chunks / chat_records 四表 |
| `0002_agent_runs.py` | agent_runs / agent_steps 两表 |
| `0003_sessions.py` | sessions 表 |
