# Agent 编排与鉴权问题（Backend-Agent）

> 2026-09-22 审查发现。状态标签：[OPEN] 未修复 / [WIP] 部分修复 / [DONE] 已修复。
> 按原编号顺序排列；编号仅用于跨条目引用，不代表处理优先级。

---

## [OPEN] 01. 任意登录用户可读取他人 Agent 运行详情

| 项 | 值 |
| --- | --- |
| 严重级别 | 🔴 P0 |
| 状态 | 未修复 |
| 影响层 | API 层 |
| 位置 | `backend/app/api/routes/agent.py:118` |
| 关联位置 | `backend/app/services/agent_service.py:997`、`backend/app/repositories/agent_run_repository.py:38` |
| 首次发现 | 2026-09-22 |

### 现象

任何已登录用户只要拿到别人的 `run_id`，就能读到那条运行的完整内容。

返回内容包含原始提问与最终回答，也就是别人上传文档后问出的问题与答案全文。

### 根因

路由处理函数把 `current_user` 注入进来，但在调用服务层时没有把它传下去。

`get_run_detail` 的签名是 `get_run_detail(run_id: str)`，本身就没有用户维度。

`AgentRunRepository.get_by_run_id(run_id: str)` 的查询条件只有 `run_id`，没有 `user_id`。

三层一路下来，归属校验在整个调用链上都不存在。

同一文件里的 `list_agent_runs` 反而写对了，它把 `current_user.id` 传给了 `list_by_user`。

### 证据

用两个账号实测，攻击者对自己名下没有任何运行记录。

```bash
# 攻击者自己的记录列表是空的
curl -s "$BASE/agent/runs" -H "Authorization: Bearer $ATTACKER_TOKEN"
# -> {"code":0,"message":"success","data":[]}

# 用同一个 token 读 user_id=1 的运行详情
curl -s "$BASE/agent/runs/1e4cdc3175ef4329" -H "Authorization: Bearer $ATTACKER_TOKEN"
# -> HTTP 200，返回受害者的问题与完整回答
```

对照实验：`DELETE /documents/2` 对他人文档返回 404，说明项目其他路由是有防护的。

### 影响

泄露范围是 `agent_runs.question` 与 `agent_runs.final_answer`，以及 `agent_steps` 里每一步的输入输出摘要。

在多人共用同一套部署的场景下，这等于把所有人的提问内容与回答内容互相公开。

`run_id` 是 16 位十六进制随机串，不可枚举，但会出现在前端 URL 与日志里，属于可获取值。

### 建议改法

给三层都补上归属维度，只改路由层是不够的。

1. `AgentRunRepository` 增加 `get_by_run_id_for_user(run_id: str, user_id: int)`，查询条件同时匹配两个字段。
2. `MultiAgentService.get_run_detail(run_id: str, user_id: int)` 增加参数并转传给仓储层。
3. `agent.py:118` 传入 `current_user.id`，详情为空时返回 404 而不是 `data=None`。
4. 仓储层保留原有的 `get_by_run_id` 供内部使用（如 `resume` 落库），但对外查询一律走带 `user_id` 的版本。

### 验证方式

`backend/tests/test_known_defects.py` 已用 `xfail(strict=True)` 钉住期望行为。

修复后该用例会从 XFAIL 变成 XPASS 并报错，届时删掉 `xfail` 标记即成为正式回归。

```bash
cd backend && uv run pytest tests/test_known_defects.py -q
```

## [OPEN] 02. 任意登录用户可恢复他人 Agent 运行

| 项 | 值 |
| --- | --- |
| 严重级别 | 🔴 P0 |
| 状态 | 未修复 |
| 影响层 | API 层 |
| 位置 | `backend/app/api/routes/agent.py:98`、`backend/app/api/routes/agent.py:54` |
| 关联位置 | `backend/app/services/agent_service.py:611`、`backend/app/services/agent_service.py:861` |
| 首次发现 | 2026-09-22 |

### 现象

任意登录用户可以对他人的 `run_id` 调用恢复接口。

恢复接口是写操作，不只是读：它会把那条运行继续推进，并把状态改成 `completed`。

### 根因

与 01 号问题同源，`current_user` 被注入但从未参与校验。

`MultiAgentService.resume(run_id, decision)` 的查找逻辑是 `AgentRunRepository.get_by_run_id(run_id)`，只按键匹配。

只要 `run_id` 存在，服务层就继续执行，唯一的分支判断是运行状态，而不是调用者身份。

流式版本 `stream_resume` 走同一套逻辑，因此两个端点都有该问题。

### 证据

攻击者用自己 token 对 `user_id=1` 的运行调用恢复接口。

```bash
curl -s -X POST "$BASE/agent/runs/resume" \
  -H "Authorization: Bearer $ATTACKER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id":"1e4cdc3175ef4329"}'
# -> HTTP 200 {"code":0,"message":"success","data":{"run_id":"1e4cdc3175ef4329","status":"completed","interrupt":null}}
```

该运行的 `status` 已是 `completed`，因此这次调用只走到读取分支就返回。

若目标运行停在 `awaiting_review`，攻击者传入 `decision` 即可代替本人作出裁决。

### 影响

读影响同 01 号问题，可以拿到待裁决的草稿与质检反馈。

写影响更严重：攻击者可以把一条暂停中的人工介入运行强行推进到结束，覆盖本人意图。

在 `AGENT_HITL_ENABLED=true` 的部署下，这等于可以越过人工审核环节。

### 建议改法

1. `AgentRunRepository` 增加按 `(run_id, user_id)` 的查询，`resume` 与 `stream_resume` 都改用它。
2. `MultiAgentService.resume` 与 `stream_resume` 增加 `user_id` 参数，找不到归属时直接返回失败结果。
3. `agent.py:54` 与 `agent.py:98` 传入 `current_user.id`。
4. 另外建议校验状态机：`status == "completed"` 的运行不应接受携带 `decision` 的恢复请求。

### 验证方式

`backend/tests/test_known_defects.py::test_resume_hides_other_users_run` 已用 `xfail(strict=True)` 钉住。

该用例把目标运行置为 `awaiting_review` 且不传 `decision`，因此只走读取分支、不触发模型调用。

```bash
cd backend && uv run pytest tests/test_known_defects.py -q
```

## [DONE] 03. 动态编排护栏不校验前置状态，节点抛 KeyError

| 项 | 值 |
| --- | --- |
| 严重级别 | 🔴 P0 |
| 状态 | 已修复 |
| 影响层 | Service 层 |
| 位置 | `backend/app/services/agent_dynamic.py`（`_prerequisites_met`，第 236 行起） |
| 关联位置 | `backend/app/services/agent_dynamic.py`（`supervisor` 内护栏三） |
| 首次发现 | 2026-09-22 |

### 现象

`dynamic` 模式下，模型一旦跳过 `planner` 或 `retriever` 直接点名下游节点，整轮运行以 `failed` 收尾。

失败信息是 `KeyError: 'context_docs'` 或 `KeyError: 'current_task_index'`。

### 根因

`AgentState` 声明为 `TypedDict(total=False)`，所有键都可缺省。

节点本体用下标读取共享状态，例如 `state["context_docs"]`，键不存在时直接抛 `KeyError`。

护栏当时只做一件事：校验模型给出的目标名是否落在 `VALID_TARGETS` 白名单内。

白名单只描述「目标名合不合法」，不描述「这个目标此刻能不能执行」，两者被混为一谈。

因此模型给出合法但时机错误的目标时，护栏判定通过，节点随后崩溃。

这与 README 中「任一层触发都退回规则路径，保证图一定收敛」的承诺直接矛盾。

### 证据

逐个工人节点做前置缺失探针，结果是 4 个工人节点里有 3 个会崩。

| 被派发节点 | 缺失的键 | 修复前结果 |
| --- | --- | --- |
| `retriever` | `current_task_index` | `failed` |
| `generator` | `context_docs` | `failed` |
| `reviewer` | `context_docs`、`draft_answer` | `failed` |
| `tool` | 无 | 侥幸收敛 |

修复后的复测结果。

| 被派发节点 | 修复后结果 | failed step 数 |
| --- | --- | --- |
| `generator` | `completed` | 0 |
| `reviewer` | `completed` | 0 |
| `retriever` | `completed` | 0 |
| 越界目标 `system_admin` | `completed` | 0 |

### 影响

动态编排模式的收敛保证不成立，任何一次模型输出跑偏都会造成整轮问答失败。

因为失败点在落库之后的节点执行阶段，`agent_runs` 会留下 `failed` 记录与 `error_message`，用户侧看到的是「运行失败」而非降级答案。

### 修复内容

新增 `_prerequisites_met(target, state)`，把「前置状态是否具备」纳入护栏。

| 目标节点 | 前置条件 |
| --- | --- |
| `retriever` | `sub_tasks` 非空且 `current_task_index` 小于子任务数 |
| `generator` | `context_docs` 键存在（空列表也算就绪） |
| `reviewer` | `draft_answer` 键存在 |
| `planner`、`tool` | 无要求 |

护栏由五层扩为六层，新的一层插在「目标白名单」之后，不满足时退回 `rule_based_route`。

同时把 `planner` 重复派发的行为写清：只有拆解数量变化时才重置检索进度，避免已检索片段被清空后指纹抖动、打转检测失效。

### 验证方式

| 层级 | 用例 |
| --- | --- |
| 单元 | `backend/tests/test_agent_dynamic.py::test_retriever_prerequisites` 等 4 组参数化用例 |
| 不变量 | `test_fallback_target_always_has_prerequisites_ready` 验证回退后的目标自身也满足前置条件 |
| 端到端 | `backend/tests/test_agent_orchestration.py` 用假模型注入 7 种敌意输出，断言全部 `completed` 且 0 个 failed step |
| 脚本 | `backend/scripts/verify_dynamic_agent.py` 新增第 4 组「前置状态校验」，全量 31 项断言 |

```bash
cd backend && uv run pytest tests/test_agent_dynamic.py tests/test_agent_orchestration.py -q
cd backend && uv run python -m scripts.verify_dynamic_agent
```

## [OPEN] 04. JWT 密钥仍为示例默认值

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟠 P1 |
| 状态 | 未修复 |
| 影响层 | 配置与安全 |
| 位置 | `.env`（`JWT_SECRET_KEY=change-me-in-production`） |
| 关联位置 | `backend/app/config/settings.py`（`JWT_SECRET_KEY` 默认值同值） |
| 首次发现 | 2026-09-22 |

### 现象

当前运行实例的 JWT 签名密钥是示例模板里的占位字符串。

pytest 在签发与解析令牌时都会打印 `InsecureKeyLengthWarning`。

### 根因

`settings.py` 给 `JWT_SECRET_KEY` 配了默认值 `change-me-in-production`，`.env` 与 `.env.example` 里也是同一个值。

默认值的存在让「忘记配置」不会报错，配置缺失于是表现为静默沿用弱密钥。

密钥长度是 23 字节，低于 HS256 建议的下限 32 字节。

### 证据

```bash
cd backend && uv run pytest tests/test_security.py -q
# jwt/api_jwt.py:147: InsecureKeyLengthWarning:
#   The HMAC key is 23 bytes long, which is below the minimum recommended
#   length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
```

### 影响

任何拿到源码或 `.env.example` 的人都能伪造出通过校验的访问令牌，无需知道任何用户密码。

伪造出的令牌可以冒充任意 `user_id`，与 01、02 号问题叠加后影响面进一步扩大。

当前 `.env` 已被 `.gitignore` 忽略且从未进入 git 历史，因此泄露面限于本机与部署环境。

### 建议改法

1. 生成随机密钥并写入 `.env`，例如 `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`。
2. 把 `settings.py` 中 `JWT_SECRET_KEY` 的默认值改成空字符串，让缺配置在启动时直接暴露。
3. 增加启动期校验：`DEBUG=false` 且密钥长度不足 32 字节时拒绝启动。
4. `.env.example` 里保留占位值，但补一句生成命令的注释。

### 验证方式

改用真实密钥后，`uv run pytest tests/test_security.py -q` 不应再出现 `InsecureKeyLengthWarning`。

```bash
cd backend && uv run pytest tests/test_security.py -q -W error::UserWarning
```

## [OPEN] 15.2 · 护栏回退后未复检前置状态

| 项 | 值 |
| --- | --- |
| 严重级别 | ⚪ P3 |
| 状态 | 未修复 |
| 影响层 | 规范一致性 |
| 位置 | `backend/app/services/agent_dynamic.py`（`supervisor` 内护栏三之后） |
| 首次发现 | 2026-09-22 |

### 现象

护栏三在发现目标前置未就绪时会改走 `rule_based_route`，但不会对回退后的目标再校验一次。

### 根因

修复 03 号问题时，校验只加在「模型给出的目标」这一个环节上。

回退目标是 `rule_based_route` 的输出，代码默认它一定可用，没有再次过校验。

### 影响

在当前图结构下不可达，因此是防守纵深缺口而非活跃缺陷。

推理如下：`rule_based_route` 只有在 `current_task_index` 不小于子任务数时才会返回 `generator`，而 `current_task_index` 单调递增且只由 `planner` 与 `retriever` 写入。

| 写入方 | 对 `current_task_index` 的动作 | 是否同时写 `context_docs` |
| --- | --- | --- |
| `planner`（拆解数量变化） | 置 0 | 是，置空列表 |
| `planner`（拆解数量不变） | 不动 | 不动 |
| `retriever` | 加 1 | 是，写入检索结果 |

因此 `current_task_index >= len(sub_tasks)` 成立时，`context_docs` 必然已存在，`generator` 的前置条件必然满足。

### 建议改法

在回退后追加一次 `_prerequisites_met` 校验，不满足则改为收尾。

这样护栏的三条分支（模型目标、回退目标、收尾）构成闭环，将来若有节点改变写入顺序也不会失守。

已在 `backend/tests/test_agent_dynamic.py::test_fallback_target_always_has_prerequisites_ready` 里对 8 个可达状态断言该不变量，新增节点写入时该用例会先失败。
