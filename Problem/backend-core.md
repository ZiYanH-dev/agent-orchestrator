# 后端核心问题（Backend-Core）

> 2026-09-22 审查发现。状态标签：[OPEN] 未修复 / [WIP] 部分修复 / [DONE] 已修复。
> 覆盖测试、配置、仓储、脚本与规范一致性。按原编号顺序排列；编号仅用于跨条目引用。

---

## [DONE] 05. 后端测试覆盖严重不足

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟠 P1 |
| 状态 | 已修复 |
| 影响层 | 测试 |
| 位置 | `backend/tests/` |
| 首次发现 | 2026-09-22 |

### 现象

修复前 `backend/tests/` 只有 2 个文件、6 个用例，要覆盖 57 个后端源文件。

编排、护栏、RAG、仓储四块没有任何单元测试。

### 根因

测试只覆盖了两个最容易写的模块：密码哈希与 JWT 编解码，以及认证服务。

其余模块靠 `backend/scripts/` 下的手工脚本验证，脚本不参与自动化、不进 CI。

护栏缺陷（03 号问题，见 backend-agent.md）正是这层缺口暴露出来的：没有任何自动用例会去构造「模型跳过前置节点」这个输入。

### 证据

修复前的采集结果。

```bash
cd backend && uv run pytest --collect-only -q
# 6 tests collected
```

修复后的采集结果。

```bash
cd backend && uv run pytest -q
# 187 passed, 3 xfailed
```

### 影响

回归只能靠人记得跑脚本，改动编排代码时没有任何自动防线。

手工脚本需要起完整环境（Docker + Ollama + 真实模型），在 CI 里不可用。

### 修复内容

新增 7 个测试文件，合计 184 个新用例。

| 文件 | 覆盖对象 | 要点 |
| --- | --- | --- |
| `conftest.py` | 共享夹具 | 内存 SQLite、pgvector 类型降级、缓存隔离 |
| `fakes.py` | 测试替身 | 内存版 Redis，支持故障注入 |
| `test_agent_dynamic.py` | 编排纯逻辑 | 工具 AST 白名单求值、进展指纹、前置状态校验、规则路由全分支 |
| `test_agent_orchestration.py` | 编排端到端 | 假模型注入 7 种敌意输出，断言收敛性 |
| `test_agent_service_nodes.py` | 节点纯逻辑 | Planner 输出规整的 8 种形态、两条条件路由 |
| `test_repositories.py` | 仓储层 | CRUD、分页、按 user_id 的数据隔离 |
| `test_cache.py` | 缓存层 | key 构造、四个命令的故障降级 |
| `test_utils.py` | 工具与配置 | 时区处理、连接串拼装、维度一致性 |
| `test_known_defects.py` | 已知缺陷 | 用 `xfail(strict=True)` 钉住 01、02 号问题 |

### 设计取舍

| 决策 | 理由 |
| --- | --- |
| 数据库用内存 SQLite | 单元测试不依赖 Docker，可在任意环境秒级跑完 |
| 用 `@compiles(Vector, "sqlite")` 降级类型 | `chunks.embedding` 是 pgvector 类型，SQLite 方言不认识，降级只影响 DDL |
| 假模型按提示词分流 | supervisor 提示词含固定标识，命中即返回预设 payload，其余调用返回普通文本 |
| 未覆盖 `VectorRepository` | 它依赖 pgvector 的 `<=>` 运算符，SQLite 无法执行，需真实 PostgreSQL |
| 未覆盖路由层 HTTP | 路由层端到端由 `scripts/http_e2e.py` 等脚本承担，需要真实模型 |

### 验证方式

```bash
cd backend && uv run pytest -q
cd backend && uv run ruff check . && uv run mypy app
```

### 遗留

`VectorRepository` 的 SQL 仍然只有手工脚本覆盖，若要纳入自动化需要引入 testcontainers 或对 PostgreSQL 的专用测试库。

路由层的每个端点也缺少 401 与越权的自动用例，目前靠 `scripts/verify_hitl_http.py` 与手工 curl。

## [OPEN] 11. 向量维度由两个配置项分别声明

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 未修复 |
| 影响层 | 配置与数据库 |
| 位置 | `backend/app/config/settings.py`（`EMBED_DIMENSION`、`VECTOR_DIMENSION`） |
| 关联位置 | `.env`、`.env.example`、`backend/app/models/chunk.py` |
| 首次发现 | 2026-09-22 |

### 现象

Embedding 的输出维度与数据库向量列的维度由两个独立的配置项表达。

两者当前都是 768，但没有任何机制保证它们一直相等。

### 根因

`EMBED_DIMENSION` 描述的是 Embedding 服务的输出维度，也就是模型属性。

`VECTOR_DIMENSION` 描述的是 `chunks.embedding` 列的维度，也就是数据库 schema。

`chunk.py` 用 `Vector(settings.VECTOR_DIMENSION)` 建列，`documents` 写入路径用 Embedding 服务的实际输出。

这两件事在语义上是同一个值，但在配置里被拆成了两份。

### 证据

```python
# settings.py
EMBED_DIMENSION: int = 768
VECTOR_DIMENSION: int = 768

# app/models/chunk.py
embedding: Mapped[list[float] | None] = mapped_column(
    Vector(settings.VECTOR_DIMENSION), nullable=True
)
```

`.env` 与 `.env.example` 里两个键都存在，各写一次 768。

### 影响

换模型时（例如把 `nomic-embed-text` 换成 1024 维的模型）如果只改了 `EMBED_DIMENSION`，写入路径仍按 768 建列。

表现为 PostgreSQL 拒绝插入，报维度不匹配，报错点在 `document_service.ingest_file` 的 `upsert_embedding` 那一步。

此时上传接口才会失败，而配置看起来是「已改好」的，排查要跨配置、模型、SQL 三层。

改 `VECTOR_DIMENSION` 同样有风险：列定义变了但数据库里已有的向量列不会自动迁移，需要配套写迁移脚本。

### 建议改法

1. 收敛为单一事实来源：保留 `VECTOR_DIMENSION`（它同时决定 schema 与校验），删掉 `EMBED_DIMENSION`，或反过来。
2. 若因兼容原因必须保留两个键，在 `Settings` 上加 `model_validator`，两者不等时直接抛错。
3. 增加启动期自检：对 Embedding 服务发一次探针请求，比对返回向量维度与 `VECTOR_DIMENSION`，不一致时写入日志并在 `/health` 中体现。
4. 换维度时同步产出 Alembic 迁移，重建 `chunks.embedding` 列并全量重算向量。

### 验证方式

已加一条守卫用例，任一维度被单独改动都会失败。

```bash
cd backend && uv run pytest tests/test_utils.py::test_embedding_and_vector_dimensions_agree -q
```

该用例断言 `settings.EMBED_DIMENSION == settings.VECTOR_DIMENSION`，属于临时护栏。

按建议第 1 条收敛成单一配置项后，这条用例应连同被删的配置项一起移除。

## [OPEN] 12. 分页排序缺少稳定次序，翻页可能重复或漏项

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 未修复 |
| 影响层 | Repository 层 |
| 位置 | 见下方受影响清单 |
| 首次发现 | 2026-09-22 |

### 现象

四个分页查询的 `ORDER BY` 只包含一个时间列。

当多行的该时间列取值完全相同时，数据库不保证返回顺序稳定，同一次翻页可能重复拿到某行、也可能漏掉某行。

### 根因

`ORDER BY` 后没有追加唯一列作 tiebreaker，例如主键 `id`。

时间列本身也不具备唯一性保证：多个模型用 `server_default=func.now()` 填充 `created_at`。

PostgreSQL 的 `now()` 返回的是**事务开始时间**，同一事务内插入的多行会拿到完全相同的时间戳。

这意味着重复并不罕见，只要一批写入发生在同一个事务里就会命中。

### 受影响清单

| 位置 | 排序字段 | 是否分页 |
| --- | --- | --- |
| `backend/app/repositories/chat_record_repository.py:59` | `ChatRecord.created_at.desc()` | 是，带 `offset` / `limit` |
| `backend/app/repositories/document_repository.py:61` | `Document.created_at.desc()` | 是，带 `offset` / `limit` |
| `backend/app/repositories/session_repository.py:24` | `Session.updated_at.desc()` | 否，只 `limit` |
| `backend/app/repositories/agent_run_repository.py:80` | `AgentRun.started_at.desc()` | 否，只 `limit` |
| `backend/app/repositories/agent_step_repository.py:64` | `AgentStep.started_at.asc()` | 否，只 `limit` |

前两项有 `offset`，重复与漏项会直接表现为翻页错乱。

后三项只取前 N 条，影响限于「哪几条被选中」不确定，不产生重复。

### 证据

`offset` 分页的确定性依赖「每次查询的全序都不变」，而当前查询只有偏序。

```python
# chat_record_repository.py
.offset(skip).limit(limit)     # 第 59 行只有 created_at.desc() 一个排序键
```

在自动化测试里已经能观察到这个问题：写测试时必须显式给 `created_at` 赋不同的值，否则断言顺序会随机失败。

`backend/tests/test_repositories.py` 里多处 `record.created_at = utc_now() + timedelta(seconds=index)` 就是为此加的。

### 影响

对话历史的翻页可能出现某条记录重复出现或整条看不见。

在数据量小、SQLite 单线程的场景下几乎不出现，换到 PostgreSQL 并发写入后概率上升。

用户侧表现为「刚才那条消息翻不到了」，难以复现、难以归因。

### 建议改法

在每个 `ORDER BY` 后追加唯一列作为 tiebreaker。

```python
.order_by(ChatRecord.created_at.desc(), ChatRecord.id.desc())
.order_by(Document.created_at.desc(), Document.id.desc())
.order_by(Session.updated_at.desc(), Session.id.desc())
.order_by(desc(AgentRun.started_at), desc(AgentRun.id))
.order_by(AgentStep.started_at.asc(), AgentStep.id.asc())
```

方向要与主排序键一致：倒序查询配 `id.desc()`，正序配 `id.asc()`。

`Session.id` 是 UUID 字符串，同样满足唯一性，可直接用作 tiebreaker。

### 验证方式

建议在 `tests/test_repositories.py` 增加一组用例：插入多行且 `created_at` 完全相同，再断言按 `skip`/`limit` 分页拿到的各页集合两两不相交、并集等于全部行。

当前用例刻意让时间错开，因此不覆盖这个场景，需要新增。

### 备注

本问题在 SQLite 上的表现与 PostgreSQL 不同：SQLite 存储时间只有秒级精度，重复概率更高，但并发度低所以更不易被观察到。

## [DONE] 13. 测试隔离未覆盖缓存的全部构造路径

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 已修复 |
| 影响层 | 测试 |
| 位置 | `backend/tests/conftest.py`（`isolated_cache` 夹具） |
| 首次发现 | 2026-09-22 |

### 现象

本轮新增测试的第一次运行中，三个用例断言失败，实际返回值是上一次用例写进去的内容。

排查后发现测试真的读写了开发环境的 Redis，也就是说隔离没有生效。

### 根因

`app/core/cache.py` 里有两个入口指向 Redis 客户端。

| 入口 | 形态 | 谁在用 |
| --- | --- | --- |
| `cache` | 模块级 `RedisCache` 实例 | 业务代码 `from app.core.cache import cache` |
| `redis_client` | 模块级 `Redis` 客户端 | `RedisCache.__init__` 赋值给 `self._client` |

隔离夹具当时只替换了 `cache._client`。

测试里自己 `RedisCache()` 新建实例时，构造函数读的是模块级 `redis_client`，仍然指向真实 Redis。

### 证据

```python
# 修复前的夹具
fake = FakeRedis()
monkeypatch.setattr(cache, "_client", fake)     # 只改单例，不管新建实例
```

```python
# RedisCache.__init__ 读的是模块变量，不是单例的属性
def __init__(self) -> None:
    self._client = redis_client
```

失败断言长这样。

```
E  AssertionError: assert [{'content': '片段', 'score': 0.87}] is None
```

`[{'content': '片段', ...}]` 是上一个用例写进真实 Redis 的值，被这条用例原样读回来了。

### 影响

测试结果依赖上一次运行的残留状态，会随机失败。

测试往开发环境的 Redis 写入了 `k`、`a`、`b` 三个无命名空间的键，并且执行了一次按前缀批量删除。

批量删除的目标是 `agent:retrieval:1:` 前缀，命中的是真实的检索缓存。缓存带 300 秒 TTL 且可重建，因此没有造成数据损失，但这是一次真实的越界写入。

### 修复内容

夹具改为同时替换两个入口。

```python
fake = FakeRedis()
monkeypatch.setattr("app.core.cache.redis_client", fake)   # 覆盖后续新建实例
monkeypatch.setattr(cache, "_client", fake)               # 覆盖已构造的单例
return fake
```

同时在夹具文档字符串里写明「要同时改两处，缺一不可」以及各自的原因。

真实 Redis 里被写入的 `k`、`b` 两个键已用 `redis-cli DEL` 清理。

### 验证方式

```bash
cd backend && uv run pytest tests/test_cache.py -q

# 跑完后真实 Redis 不应出现测试写入的键
docker exec rag-redis redis-cli --scan
```

### 遗留

`FakeRedis` 只实现了 `get`、`set`、`delete`、`scan_iter` 四个命令。

若将来缓存层新增命令（例如 `expire`、`hset`），夹具不会报「未实现」，而是抛 `AttributeError`，需要在新增命令时同步补上。

建议给 `FakeRedis` 加一条测试，断言它与 `RedisCache` 实际调用的方法集一致。

## [OPEN] 15.1 · 仓储层的 barrel 导出不完整

| 项 | 值 |
| --- | --- |
| 严重级别 | ⚪ P3 |
| 状态 | 未修复 |
| 影响层 | 规范一致性 |
| 位置 | `backend/app/repositories/__init__.py` |
| 首次发现 | 2026-09-22 |

### 现象

目录下有 8 个仓储实现，`__init__.py` 只导出了 5 个。

| 已导出 | 未导出 |
| --- | --- |
| `ChatRecordRepository`、`ChunkRepository`、`DocumentRepository`、`UserRepository`、`VectorRepository` | `AgentRunRepository`、`AgentStepRepository`、`SessionRepository` |

### 根因

5 个导出是早期写的，后加的 3 个没有同步补进 `__all__`。

### 影响

同一层的模块出现两种导入写法：一部分从包导入，一部分必须写全路径。

使用方需要先确认某个仓储在不在这 5 个里，多一次查找成本。

### 建议改法

补全 3 个导出，让 `from app.repositories import XxxRepository` 对全部 8 个都成立。

若有意只导出「业务方常用」的子集，应在 `__init__.py` 的文档字符串里写明筛选标准。

## [OPEN] 15.5 · 验证脚本在数据库里留下残留账号

| 项 | 值 |
| --- | --- |
| 严重级别 | ⚪ P3 |
| 状态 | 未修复 |
| 影响层 | 规范一致性 |
| 位置 | `backend/scripts/http_e2e.py`、`backend/scripts/verify_hitl_http.py`、`backend/scripts/test_e2e.py` |
| 首次发现 | 2026-09-22 |

### 现象

开发库的 `users` 表里积压了 14 个由脚本创建的临时账号。

### 证据

```sql
SELECT id, username FROM users ORDER BY id;
-- 1  hzy              <- 真实账号
-- 2  testuser         <- 早期手工创建
-- 6  e2e_af2a037f     <- 以下均为脚本残留
-- 7  e2e_8c48f88b
-- ...
-- 20 hitl_27baa456
```

命名规律是 `e2e_<8位随机>` 与 `hitl_<8位随机>`，与脚本里的用户名生成规则一致。

### 影响

不影响功能，脚本每次都新建账号，不会因为重名失败。

影响的是开发库的可读性：排查数据问题时无法一眼分辨哪些账号是真实的。

如果这些账号下有成对的 `documents` 与 `chunks`，还会一并占用开发库的存储。

### 建议改法

在脚本收尾时按用户名前缀清理自己创建的账号。

由于 `users` 到 `documents`、`agent_runs` 的外键都带 `ondelete="CASCADE"`，删用户会连带清掉关联数据。

另一种做法是给脚本加 `--keep` 开关，默认清理、需要保留现场时才加参数。

### 备注

本轮用到的临时账号 `attacker_probe` 已手动删除。
