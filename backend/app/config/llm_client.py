"""LLM 客户端初始化模块。

统一使用 OpenAI 兼容协议（ChatOpenAI），覆盖：
  - OpenAI、DeepSeek、月之暗面、智谱、阿里云百炼 等
"""
from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config.settings import settings


@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    """LLM 客户端单例（OpenAI 兼容协议）。"""
    
    return ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL_NAME,
        temperature=settings.LLM_TEMPERATURE,
    )
