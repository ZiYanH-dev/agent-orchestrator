"""Embedding 客户端初始化模块。

统一使用 OpenAI 兼容协议，切换不同后端只需改 .env：
  - Ollama 本地：http://127.0.0.1:11434/v1
  - OpenAI 真云：https://api.openai.com/v1
  - 阿里云百炼：https://dashscope.aliyuncs.com/compatible-mode/v1
"""
from __future__ import annotations

from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.config.settings import settings


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Embedding 客户端单例（OpenAI 兼容协议）。"""
    
    return OpenAIEmbeddings(
        base_url=settings.EMBED_BASE_URL,
        api_key=settings.EMBED_API_KEY,
        model=settings.EMBED_MODEL,
        check_embedding_ctx_length=False,  # 各厂商 ctx 长度差异大，关掉以兼容
    )
