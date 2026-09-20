"""应用配置模块。

集中管理所有环境变量与配置项，通过 pydantic-settings 从 .env 加载。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent  # backend/
REPO_ROOT: Path = PROJECT_ROOT.parent  # 项目根目录（.env 所在）


class Settings(BaseSettings):
    """全局应用配置。

    所有配置项均从环境变量或 .env 文件读取。
    """

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ---- 应用基础 ----
    APP_NAME: str = "RAG Demo"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # ---- 数据库 (PostgreSQL + pgvector) ----
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "rag_demo"
    DATABASE_URL: str = ""

    # ---- Redis ----
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_URL: str = ""

    # ---- Embedding (OpenAI 兼容协议，Ollama / OpenAI / 阿里云 通用) ----
    EMBED_BASE_URL: str = "http://127.0.0.1:11434/v1"
    EMBED_API_KEY: str = "ollama"
    EMBED_MODEL: str = "nomic-embed-text"
    EMBED_DIMENSION: int = 768

    # ---- LLM (OpenAI 兼容协议，如阿里云百炼) ----
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL_NAME: str = "qwen-turbo"
    LLM_TEMPERATURE: float = 0.1

    # ---- RAG 参数 ----
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 80
    RETRIEVE_TOP_K: int = 3
    VECTOR_DIMENSION: int = 768

    # ---- 文档存储 ----
    DATA_DIR: str = "data"

    # ---- 安全 / JWT ----
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080

    # ---- Agent Checkpoint ----
    # memory: 开发/测试用（进程内）
    # redis: 生产用（需 Redis Stack）
    AGENT_CHECKPOINT_BACKEND: str = "memory"

    # ---- CORS ----
    CORS_ORIGINS: str = "http://127.0.0.1:5872,http://localhost:5872"

    @property
    def resolved_database_url(self) -> str:
        """返回可用的数据库连接串。"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def resolved_redis_url(self) -> str:
        """返回可用的 Redis 连接串。"""
        if self.REDIS_URL:
            return self.REDIS_URL
        auth: str = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def data_dir_path(self) -> Path:
        """返回数据目录绝对路径。"""
        return PROJECT_ROOT / self.DATA_DIR

    @property
    def cors_origins_list(self) -> list[str]:
        """解析逗号分隔的跨域白名单。"""
        return [
            origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return Settings()


settings: Settings = get_settings()
