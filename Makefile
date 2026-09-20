# =============================================================================
# Makefile — 全栈项目一键启动入口
# 底层调用: docker compose / uv / pnpm / ollama
# =============================================================================

.DEFAULT_GOAL := help

# ─── 变量 ────────────────────────────────────────────────────────────────────
BACKEND_DIR   := backend
FRONTEND_DIR  := frontend
UV            := uv
PNPM          := pnpm
DOCKER_COMPOSE:= docker compose
EMBED_MODEL   ?= nomic-embed-text
BACKEND_PORT  ?= 8765
FRONTEND_PORT ?= 5872
LOG_DIR       := .logs
PG_HOST       ?= 127.0.0.1
PG_PORT       ?= 5432
PG_USER       ?= postgres

# 端口：单一事实来源 = 根目录 .env（缺省值兜底）
-include .env

# ─── 帮助 ────────────────────────────────────────────────────────────────────
.PHONY: help
help:                                 ## 显示此帮助
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

# =============================================================================
#  一键入口
# =============================================================================
.PHONY: start dev up all setup backend-run frontend-run stop logs

start: ollama-up docker-check infra-up pg-wait db-upgrade backend-run frontend-run  ## 🔶 【主入口】一键启动: Ollama → Docker → DB → 迁移 → 后端 → 前端
	@echo ""
	@echo "✅ 项目已全部启动，访问入口："
	@echo "   🎨 前端页面:  http://localhost:$(FRONTEND_PORT)"
	@echo "   � 后端接口:  http://127.0.0.1:$(BACKEND_PORT)   API 文档: http://127.0.0.1:$(BACKEND_PORT)/docs"
	@echo "   � 查看日志:  make logs        🛑 一键停止: make stop"
	@echo ""

dev: start                            ## 同 start（别名）

up: dev                               ## 同 start（别名）

setup: start                          ## 首次 setup（同 start，额外确保依赖装好）

all: start                            ## 完整流程

backend-run:                          ## 后台启动后端 (日志: .logs/backend.log)
	@mkdir -p $(LOG_DIR)
	@if lsof -ti :$(BACKEND_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "⏭️  端口 $(BACKEND_PORT) 已被占用，后端已在运行，跳过"; \
	else \
		echo "🚀 后台启动后端 (port $(BACKEND_PORT))..."; \
		cd $(BACKEND_DIR) && nohup $(UV) run uvicorn app.main:app --reload --port $(BACKEND_PORT) > ../$(LOG_DIR)/backend.log 2>&1 & \
	fi

frontend-run:                         ## 后台启动前端 (日志: .logs/frontend.log)
	@mkdir -p $(LOG_DIR)
	@if lsof -ti :$(FRONTEND_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "⏭️  端口 $(FRONTEND_PORT) 已被占用，前端已在运行，跳过"; \
	else \
		echo "🚀 后台启动前端 (port $(FRONTEND_PORT))..."; \
		cd $(FRONTEND_DIR) && nohup $(PNPM) dev > ../$(LOG_DIR)/frontend.log 2>&1 & \
	fi

stop:                                 ## 停止前后端开发服务器
	@if lsof -ti :$(BACKEND_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		lsof -ti :$(BACKEND_PORT) -sTCP:LISTEN | xargs kill; \
		echo "🛑 后端已停止 (port $(BACKEND_PORT))"; \
	else \
		echo "⏭️  后端未在运行"; \
	fi
	@if lsof -ti :$(FRONTEND_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		lsof -ti :$(FRONTEND_PORT) -sTCP:LISTEN | xargs kill; \
		echo "🛑 前端已停止 (port $(FRONTEND_PORT))"; \
	else \
		echo "⏭️  前端未在运行"; \
	fi

logs:                                 ## 实时查看前后端日志 (Ctrl+C 退出)
	@tail -f $(LOG_DIR)/backend.log $(LOG_DIR)/frontend.log

# =============================================================================
#  Ollama（本地 Embedding）
# =============================================================================
.PHONY: ollama-up ollama-list

ollama-up:                            ## 按需检查 Ollama（仅 EMBED_BASE_URL 指向 localhost 时；缺模型只提示、不自动启动）
	@if echo "$(EMBED_BASE_URL)" | grep -qE "localhost|127\.0\.0\.1"; then \
		echo "🦙 Embedding 指向本地 Ollama，检查服务..."; \
		if curl -sf http://127.0.0.1:11434/api/tags -o /tmp/.ollama_tags.json 2>/dev/null; then \
			echo "   ✅ Ollama 服务已就绪 (port 11434)"; \
			if grep -q "$(EMBED_MODEL)" /tmp/.ollama_tags.json 2>/dev/null; then \
				echo "   ✅ 模型 $(EMBED_MODEL) 已就绪"; \
			else \
				echo "   ⚠️  模型 $(EMBED_MODEL) 不存在（不自动 pull，请手动: ollama pull $(EMBED_MODEL)）"; \
			fi; \
		else \
			echo "   ⚠️  Ollama 未运行（Embedding 将连接失败），请先启动: ollama serve"; \
		fi; \
		rm -f /tmp/.ollama_tags.json; \
	else \
		echo "🦙 Embedding 使用云端服务（非 localhost），跳过 Ollama 检查"; \
	fi

ollama-list:                          ## 查看本地 Ollama 模型列表
	ollama list 2>/dev/null || echo "   （Ollama 未运行）"

# =============================================================================
#  基础设施 (Docker)
# =============================================================================
.PHONY: docker-check infra infra-up infra-down infra-reset infra-ps infra-logs pg-wait

docker-check:                         ## 检查 Docker Desktop 是否运行，未运行则自动启动
	@if docker info >/dev/null 2>&1; then \
		echo "✅ Docker Desktop 已运行"; \
	else \
		echo "🚀 启动 Docker Desktop..."; \
		open -a Docker; \
		echo "   ⏳ 等待 Docker 就绪 (首次启动约 30s)..."; \
		until docker info >/dev/null 2>&1; do \
			sleep 2; \
		done; \
		echo "✅ Docker Desktop 已就绪"; \
	fi

infra: infra-up                       ## 启动中间件: PostgreSQL + Redis

infra-up: docker-check                ## 启动 Docker 服务 (后台)
	$(DOCKER_COMPOSE) up -d

infra-down:                           ## 停止 Docker 服务
	$(DOCKER_COMPOSE) down

infra-reset:                          ## ⚠️ 重置 Docker 数据卷 (清空所有数据)
	$(DOCKER_COMPOSE) down -v

infra-ps:                             ## 查看 Docker 容器状态
	$(DOCKER_COMPOSE) ps

infra-logs:                           ## 查看 Docker 容器日志
	$(DOCKER_COMPOSE) logs -f

pg-wait:                              ## 轮询等待 PostgreSQL 就绪 (最多 30s)
	@echo "⏳ 等待 PostgreSQL 就绪..."; \
	deadline=30; \
	while [ $$deadline -gt 0 ]; do \
		if command -v pg_isready >/dev/null 2>&1; then \
			if pg_isready -h $(PG_HOST) -p $(PG_PORT) -U $(PG_USER) >/dev/null 2>&1; then \
				echo "✅ PostgreSQL 已就绪"; \
				exit 0; \
			fi; \
		else \
			if docker exec rag-postgres pg_isready -U $(PG_USER) >/dev/null 2>&1; then \
				echo "✅ PostgreSQL 已就绪"; \
				exit 0; \
			fi; \
		fi; \
		deadline=$$((deadline - 1)); \
		sleep 1; \
	done; \
	echo "❌ PostgreSQL 超时未就绪"; \
	exit 1

# =============================================================================
#  数据库迁移 (Alembic)
# =============================================================================
.PHONY: db-generate db-upgrade db-downgrade db-history db-current db-reset

db-generate: docker-check infra-up backend-deps  ## ➤ 生成新迁移 (改完模型后: make db-generate m="add_user_role")
	@if [ -z "$(m)" ]; then echo "❌ 用法: make db-generate m=\"add_xxx_column\""; exit 1; fi
	cd $(BACKEND_DIR) && $(UV) run alembic revision --autogenerate -m "$(m)"

db-upgrade: infra-up pg-wait backend-deps        ## ➤ 执行迁移到最新版本（首次 setup 也用它建表）
	cd $(BACKEND_DIR) && $(UV) run alembic upgrade head

db-downgrade: infra-up pg-wait                   ## ➤ 回滚一个版本 (或 make db-downgrade v=base 回滚全部)
	cd $(BACKEND_DIR) && $(UV) run alembic downgrade $(if $(v),$(v),-1)

db-history: infra-up pg-wait                     ## 查看迁移历史链
	cd $(BACKEND_DIR) && $(UV) run alembic history --verbose

db-current: infra-up pg-wait                     ## 查看当前数据库的迁移版本
	cd $(BACKEND_DIR) && $(UV) run alembic current

db-reset: infra-down infra-up                    ## ⚠️ 清空数据卷后重建 + 重新迁移到 head
	make db-upgrade

# =============================================================================
#  后端 (Backend / uv)
# =============================================================================
.PHONY: backend-env backend-deps backend backend-lint backend-format backend-typecheck

backend-env:                          ## 创建后端 .env (若不存在)
	@if [ ! -f $(BACKEND_DIR)/.env ]; then \
		cp $(BACKEND_DIR)/.env.example $(BACKEND_DIR)/.env; \
		echo "✅ 已创建 backend/.env，请填入真实密钥 (至少 LLM_API_KEY)"; \
	else \
		echo "✅ backend/.env 已存在"; \
	fi

backend-deps: backend-env             ## 安装后端依赖 (uv sync)
	cd $(BACKEND_DIR) && $(UV) sync

backend:                              ## 前台启动后端开发服务器 (port 8765, hot-reload)
	cd $(BACKEND_DIR) && $(UV) run uvicorn app.main:app --reload --port $(BACKEND_PORT)

backend-lint:                         ## 后端代码检查 (ruff lint)
	cd $(BACKEND_DIR) && $(UV) run ruff check .

backend-format:                       ## 后端格式化 (ruff format)
	cd $(BACKEND_DIR) && $(UV) run ruff format .

backend-typecheck:                    ## 后端类型检查 (mypy)
	cd $(BACKEND_DIR) && $(UV) run mypy app

# =============================================================================
#  前端 (Frontend / pnpm)
# =============================================================================
.PHONY: frontend-deps frontend frontend-build

frontend-deps:                        ## 安装前端依赖 (pnpm install)
	cd $(FRONTEND_DIR) && $(PNPM) install

frontend:                             ## 前台启动前端开发服务器 (port 5872, hot-reload)
	cd $(FRONTEND_DIR) && $(PNPM) dev

frontend-build:                       ## 前端构建生产包
	cd $(FRONTEND_DIR) && $(PNPM) build

# =============================================================================
#  工具
# =============================================================================
.PHONY: clean

clean:                                ## 清理: 停止 Docker + 删除 node_modules/uv.lock
	$(DOCKER_COMPOSE) down 2>/dev/null || true
	rm -rf $(FRONTEND_DIR)/node_modules
	rm -f $(BACKEND_DIR)/uv.lock
	@echo "🧹 清理完成"
