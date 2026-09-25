# 基础设施与工程化问题（Infra）

> 2026-09-22 审查发现。状态标签：[OPEN] 未修复 / [WIP] 部分修复 / [DONE] 已修复。
> 按原编号顺序排列；编号仅用于跨条目引用，不代表处理优先级。

---

## [DONE] 06. Makefile 环境检查在失败时仍报成功

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟠 P1 |
| 状态 | 已修复 |
| 影响层 | 工程化 |
| 位置 | `Makefile`（原 `backend-env` 目标） |
| 首次发现 | 2026-09-22 |

### 现象

修复前执行 `make backend-env` 会打印「已创建 backend/.env，请填入真实密钥」，退出码为 0。

检查文件系统，`backend/.env` 根本没有被创建。

### 根因

配方写成 `if [ ! -f ... ]; then cp ...; echo "✅ ..."; else ...; fi`。

`cp` 失败时只把错误写到 stderr，`if` 分支里没有检查它的退出码，紧接着的 `echo` 照常执行。

shell 的 `if` 复合语句整体退出码取决于最后一条命令，也就是那句说谎的 `echo`，因此 make 认为成功。

更根本的问题是 `.env` 的位置：`backend/.env.example` 与 `backend/.env` 从来不存在。

真实配置在仓库根目录 `.env`，`settings.py` 的 `env_file` 与 `docker-compose.yml` 的变量插值都指向它。

`.env.example` 自己的头注释写的也是 `cp .env.example .env`，说明根目录才是设计意图。

### 证据

```bash
# 修复前的行为
make backend-env
# ✅ 已创建 backend/.env，请填入真实密钥 (至少 LLM_API_KEY)   <- 退出码 0
test -f backend/.env && echo 存在 || echo 不存在
# 不存在
```

### 影响

首次按 README 走 setup 流程的人会以为配置就绪，实际缺少全部密钥。

后续 `make start` 仍然能起来（因为后端读的是根目录 `.env`），故障被推迟到第一次调用模型时才暴露。

「打印成功但实际失败」还会掩盖其他真实错误，也搜不到任何报错线索。

### 修复内容

1. 目标改为检查根目录 `.env`，与后端、compose 的读取位置对齐。
2. `cp` 失败时显式 `exit 1`，不再让 `echo` 接管退出码。
3. 追加 `LLM_API_KEY` 空值告警，把最容易被忘记的一项单独提示。
4. 引入 `ROOT_ENV := .env` 变量，避免路径字面量散落多处。
5. `README.md` 的文件树与快速开始段落同步改为根目录 `.env`。

### 验证方式

```bash
# .env 存在时应通过
make backend-env

# 模拟缺失场景
mv .env /tmp/.env.bak && make backend-env; echo "退出码=$?"   # 应为 1
cp .env.example .env && head -6 .env                          # 应生成模板内容
rm -f .env && mv /tmp/.env.bak .env                           # 还原
```

### 遗留

`backend-env` 目前只告警不阻止启动，`LLM_API_KEY` 为空时 `make start` 仍会拉起后端。

建议把它升级为硬校验，或在后端启动时增加一项「模型连通性自检」并把结果写进 `/health`。

## [DONE] 07. Makefile 输出含损坏的替换字符

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 已修复 |
| 影响层 | 工程化 |
| 位置 | `Makefile`（`start` 目标的两行输出） |
| 首次发现 | 2026-09-22 |

### 现象

执行 `make start` 时，结尾的访问入口提示里有两条打印成 `�`。

```
   � 后端接口:  http://127.0.0.1:8765   API 文档: http://127.0.0.1:8765/docs
   � 查看日志:  make logs        🛑 一键停止: make stop
```

同一段输出里的 🎨 与 🛑 显示正常，只有这两行的字符坏掉。

### 根因

用 `hexdump` 查看原始字节，坏掉的位置是 `ef bf bd`。

`ef bf bd` 是 UTF-8 编码的 U+FFFD，也就是 Unicode 的替换字符。

替换字符只能由解码器写出，无法从替换字符反推出原始码点，因此原始 emoji 已经不可还原。

损坏发生在文件写入阶段，推测是某次编辑器或工具的编码转换把非 BMP 字符替换掉了。

### 证据

```bash
sed -n '39,44p' Makefile | hexdump -C | grep -B1 -A1 "ef bf bd"
# 失败行与成功后提示行的 emoji 字节对比，失败行是 ef bf bd
grep -n $'\uFFFD' Makefile
# 命中 2 行
```

### 影响

只影响 `make start` 结尾四行提示的可读性，不影响任何功能。

提示语是使用频率最高的输出，长期显示乱码会让人怀疑项目本身有问题。

### 修复内容

用字节级替换把两处 U+FFFD 换成语义相同的 emoji，后端接口用 🔧，查看日志用 📋。

同步全仓库扫描，确认没有其他残留。

```bash
# 扫描结果
扫描文本文件 116 个
✅ 未发现 U+FFFD 乱码
```

### 验证方式

```bash
make start
# 结尾提示应正常显示 🔧 与 📋，无 � 字符
```

### 遗留

替换是凭语义猜的，原始字符是什么已无法确认。

建议给 Makefile 加一条 100 字符以内的行宽约定，并把 emoji 限制在 BMP 之外风险较高的位置少用，降低再次损坏的概率。

## [OPEN] 08. 后端 Dockerfile 是占位实现且端口不一致

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 未修复 |
| 影响层 | 工程化 |
| 位置 | `backend/Dockerfile` |
| 关联位置 | `docker-compose.yml`、`.env`（`BACKEND_PORT=8765`） |
| 首次发现 | 2026-09-22 |

### 现象

`backend/Dockerfile` 存在且能构建，但构建出的镜像无法完成一次完整启动。

镜像内 `EXPOSE` 与 `CMD` 用的是 8000 端口，开发与文档里的端口是 8765。

镜像内没有 `alembic/`，也没有 `alembic.ini`，容器里跑不了数据库迁移。

### 根因

Dockerfile 是模板阶段留下的骨架，只复制了 `app/` 这一个目录。

`uv sync --frozen --no-install-project` 只装了依赖，业务代码靠 `COPY app ./app` 单独带入。

`docker-compose.yml` 里只定义了 `postgres` 与 `redis` 两个服务，后端与前端都跑在宿主机。

也就是说 Dockerfile 目前没有被任何编排引用，是一条未被验证的路径。

### 证据

```bash
# Dockerfile 关键行
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
COPY app ./app            # 只复制 app/

# compose 服务清单
docker compose config --services
# postgres
# redis
```

`backend/` 下实际存在 `alembic/`（含 `env.py`、`script.py.mako`、`versions/`）与 `alembic.ini`，都没有进镜像。

`backend/data/` 是文档落盘目录，也没有进镜像，且需要以卷方式挂载才能持久化。

### 影响

当前不影响开发流程，因为 compose 不构建后端镜像。

一旦进入容器化上线阶段，会连续撞上三件事：端口映射对不上、容器启动时表不存在、上传的文档在容器重建后全部丢失。

这是一个「看着已经做好了、实际跑不通」的状态，排障成本高于明确的缺失。

### 建议改法

1. 端口统一：把 `EXPOSE` 与 `CMD` 改为 8000，并在 compose 里用 `8765:8000` 做映射；或把容器端口直接对齐 8765。
2. 补 `COPY alembic ./alembic` 与 `COPY alembic.ini ./alembic.ini`。
3. 补 `COPY .env.example ./` 作为配置模板，真实 `.env` 走运行时挂载或环境变量注入。
4. `backend/data/` 声明为 `VOLUME`，在 compose 里挂到宿主机目录。
5. 在 `docker-compose.yml` 增加 `backend` 服务，并把 `depends_on` 与迁移步骤串起来。
6. 容器内的迁移执行顺序需要显式化，建议用入口脚本串联 `alembic upgrade head` 与 `uvicorn`。

### 验证方式

容器化阶段完成后，应能以单条 `docker compose up -d --build` 拉起全部服务。

验收判据是容器内的 `/health` 返回 200，且 `docker exec` 进容器执行 `alembic current` 能看到 `<head>` 版本号。

## [DONE] 14. 缺少统一的测试与自检入口

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟡 P2 |
| 状态 | 已修复 |
| 影响层 | 工程化 |
| 位置 | `Makefile` |
| 首次发现 | 2026-09-22 |

### 现象

修复前 Makefile 有 `backend-lint` 与 `backend-typecheck`，没有测试目标。

按项目约定，终端命令统一由 Makefile 封装，因此跑测试需要另外记住 `uv run pytest` 这条路径。

### 根因

Makefile 的任务清单按「启动流程」组织，`lint` 与 `typecheck` 是作为启动的附属步骤加进来的。

测试当时只有 6 个用例、靠手工脚本验证，没有形成需要固化的入口。

### 证据

```bash
make help | grep -c test
# 0
```

### 影响

提交前自检没有单一命令，容易只跑 `lint` 而漏掉测试。

新人上手时看不出项目的验证方式是什么，只能翻 README 或问人。

### 修复内容

新增两个目标，并纳入 `.PHONY`。

| 目标 | 作用 |
| --- | --- |
| `backend-test` | 执行 `pytest -q` |
| `check` | 顺序执行 `backend-lint`、`backend-typecheck`、`backend-test` |

`check` 的依赖按「快 → 慢」排列，语法与类型问题先暴露，避免等测试跑完才发现低级错误。

### 验证方式

```bash
make check
# 期望输出结尾：✅ 后端自检通过
```

实际执行结果。

```
tests/test_auth_service.py::test_register_and_login
tests/test_security.py::test_access_token_round_trip
  InsecureKeyLengthWarning: The HMAC key is 23 bytes long ...
187 passed, 3 xfailed, 3 warnings in 5.72s
✅ 后端自检通过
```

### 遗留

`check` 只覆盖后端，前端没有对应的 `typecheck` 与 `build` 目标。

端到端脚本（`scripts/http_e2e.py`、`verify_dynamic_agent.py`、`verify_hitl_http.py`、`test_e2e.py`）需要 Docker、Ollama 与真实模型，不适合并入 `check`。

建议后续把它们收进一个独立的 `make verify`，并在 README 里说明它需要完整环境。

`xfailed` 的数量会随 01、02 号问题的修复而减少，不建议在 `check` 里对 3 这个数字做断言。

## [OPEN] 18. `make db-reset` 未清空数据卷，与帮助文案不符

| 项 | 值 |
| --- | --- |
| 严重级别 | 🟠 P1 |
| 状态 | 未修复 |
| 影响层 | Makefile |
| 位置 | `Makefile:192` |
| 首次发现 | 2026-09-22 |

### 现象

`make db-reset` 的帮助文案写的是「清空数据卷后重建」，实际执行时不带 `-v`，数据卷完整保留。

用户想得到干净数据库时跑这条命令，会拿回全部旧数据，且**没有任何提示**。命令退出码为 0，输出看起来正常。

### 根因

目标声明了两个前置依赖，但依赖的目标选错了。

```make
db-reset: infra-down infra-up                    ## ⚠️ 清空数据卷后重建 + 重新迁移到 head
	make db-upgrade
```

| 目标 | 展开 | 是否删卷 |
| --- | --- | --- |
| `infra-down` | `docker compose down` | **否** |
| `infra-reset` | `docker compose down -v` | **是** |

`db-reset` 依赖的是 `infra-down`，不是 `infra-reset`。

Docker 的行为是：`docker compose down` 只删除容器与网络，**具名数据卷默认保留**；只有显式加 `-v` 才删除。所以 `db-reset` 的实际效果是「重启容器 + 重跑迁移」，数据一行不少。

同一文件里已经把这两个目标的差异定义出来了，只是 `db-reset` 引用错了：

```make
infra-down:                           ## 停止 Docker 服务
	$(DOCKER_COMPOSE) down

infra-reset:                          ## ⚠️ 重置 Docker 数据卷 (清空所有数据)
	$(DOCKER_COMPOSE) down -v
```

### 证据

`make -n` 只打印命令不执行，可以安全地看到实际会跑什么。

```bash
cd /Users/jasonhuang/Desktop/trial/ai_trial/projects/agent-orchestrator
make -n db-reset
```

输出：

```
docker compose down            ← 没有 -v
if docker info >/dev/null 2>&1; then ... open -a Docker ... fi
docker compose up -d
make db-upgrade
```

对照 `make -n infra-reset` 的输出：

```
docker compose down -v         ← 有 -v
```

两句唯一的差别就是 `-v`。

数据卷的存在也能佐证：

```bash
docker volume ls | grep agent-orchestrator
# local     agent-orchestrator_pgdata
```

### 影响

| 场景 | 后果 |
| --- | --- |
| 想从干净状态重跑端到端验证 | 拿到旧数据，验证结论不可信 |
| 想清掉测试污染的数据 | 数据还在，返回的错误结论会指向错误的方向 |
| 改了模型想重建表 | 迁移会跑，但只在已有数据上增量执行，不是「重建」 |
| 以为数据已清空而执行危险操作 | 判断前提错误 |

最后一行是最危险的：这条命令的文案带 ⚠️ 符号，给人的印象是「会删数据」，实际不删。**反向的误导比正向的误导更难发现**——用户为了「保险」去跑它，结果什么也没发生，而用户以为发生了。

这与「Makefile 环境检查在失败时仍报成功」（上文）是同一类问题：**目标的声明行为与实际行为不一致，且失败被静默吞掉**。

### 建议改法

把依赖从 `infra-down` 换成 `infra-reset`。

```make
db-reset: infra-reset                    ## ⚠️ 清空数据卷后重建 + 重新迁移到 head
	make db-upgrade
```

`infra-reset` 已经包含 `up` 吗——不包含。它只做 `down -v`。而 `db-upgrade` 的前置里有 `infra-up pg-wait backend-deps`，会自己把容器拉起来并等就绪，所以链路仍然完整：

```
db-reset
  → infra-reset                 docker compose down -v
  → db-upgrade
      → infra-up                docker compose up -d
      → pg-wait                 等 PostgreSQL 就绪
      → backend-deps            确保依赖装好
      → alembic upgrade head    建表
  → db-upgrade（显式那一行，重复执行一次也不会出错）
```

`db-reset` 里那行 `make db-upgrade` 与依赖里的 `db-upgrade` 重复。Make 对同一目标只跑一次，所以实际只有一个 `alembic upgrade head`。可以删掉多余的依赖，写成：

```make
db-reset: infra-reset db-upgrade         ## ⚠️ 清空数据卷后重建 + 重新迁移到 head
```

#### 可选：加一层确认

删数据卷是不可逆操作，可以在配方前加一句交互确认：

```make
db-reset: infra-reset db-upgrade         ## ⚠️ 清空数据卷后重建 + 重新迁移到 head
	@echo "✅ 数据卷已清空并迁移到 head"
```

或者在 `infra-reset` 上要求显式变量：

```make
infra-reset:                          ## ⚠️ 重置 Docker 数据卷 (需 CONFIRM=yes)
	@if [ "$(CONFIRM)" != "yes" ]; then \
		echo "❌ 该操作会删除全部数据，确认请执行: make infra-reset CONFIRM=yes"; \
		exit 1; \
	fi
	$(DOCKER_COMPOSE) down -v
```

这一层是否加取决于使用习惯。不加也能用，因为 `infra-reset` 的帮助文案已经带了 ⚠️。

### 验证方式

1. 记录当前数据量：

   ```bash
   docker exec rag-postgres psql -U postgres -d rag_demo -t -A -c "SELECT count(*) FROM users;"
   ```

2. 执行 `make db-reset`。

3. 再查一次。**修复后的期望值是 0**（表刚建好，没有任何用户）。

修复前该查询返回原值，与未执行任何操作一致。

### 备注

注意与「Makefile 环境检查在失败时仍报成功」一起改，两者都是「Makefile 目标行为与描述不符」。

`Makefile` 里其余目标核对过一遍，没有同类问题：

| 目标 | 声明行为 | 实际命令 | 是否一致 |
| --- | --- | --- | --- |
| `infra-reset` | 重置数据卷 | `down -v` | 一致 |
| `infra-down` | 停止服务 | `down` | 一致 |
| `db-downgrade` | 回滚一个版本 | `alembic downgrade -1` | 一致 |
| `clean` | 停止 Docker + 删 node_modules/uv.lock | 三条命令 | 一致 |
| **`db-reset`** | **清空数据卷后重建** | **`down`（无 `-v`）** | **不一致** |

## [OPEN] 15.4 · `.env` 的头部注释与实际身份矛盾

| 项 | 值 |
| --- | --- |
| 严重级别 | ⚪ P3 |
| 状态 | 未修复 |
| 影响层 | 规范一致性 |
| 位置 | `.env` 前 3 行 |
| 首次发现 | 2026-09-22 |

### 现象

`.env` 的前三行写的是「复制此文件为 .env 并填入真实值」，但这个文件本身就是 `.env`。

```
# ===== 复制此文件为 .env 并填入真实值 =====
#   cp .env.example .env
#   ⚠️ .env 已被 .gitignore 忽略，勿提交真实密钥
```

### 根因

这 3 行注释属于 `.env.example`，是从模板复制过来时一并带过来的，没有删掉。

### 影响

注释描述的是一个已经完成的动作，读起来像是文件被放错了位置。

更实际的风险是这段文字会诱导使用者执行 `cp .env.example .env`，而该命令会覆盖当前已填好真实密钥的文件。

### 建议改法

删掉 `.env` 里这 3 行，换成一行说明当前文件用途的注释。

`.env.example` 保留原注释不动。

### 备注

`.env` 未被 git 跟踪（`.gitignore:18` 命中），也从未进入 git 历史，因此本项只是可读性问题，不涉及泄露。
