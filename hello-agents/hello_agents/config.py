"""
config.py — 全局配置（pydantic-settings）

从 .env 文件和环境变量读取配置，提供全局单例 get_settings()。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    llm_api_key: str = ""
    llm_model_id: str = "qwen3-max-2026-01-23"
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Embedding
    embedding_model: str = "text-embedding-v3"
    embedding_dimension: int = 1024

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4jpassword"

    # SQLite
    sqlite_db_path: str = "./data/hello_agents.db"

    # Memory
    working_memory_ttl_seconds: int = 3600
    episodic_collection: str = "episodic_memory"
    perceptual_collection: str = "perceptual_memory"
    reflection_interval_seconds: int = 300

    # Web Search
    tavily_api_key: Optional[str] = None
    serpapi_api_key: Optional[str] = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回全局配置单例。"""
    return Settings()
