"""
memory/embedding.py — 统一嵌入服务

使用 OpenAI-compatible API（Dashscope text-embedding-v3）将文本转换为高维向量，
支持批量处理、缓存与重试。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from functools import lru_cache
from typing import Sequence

import openai

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 25  # Dashscope 单次批量上限


class EmbeddingService:
    """对 OpenAI-compatible Embedding API 的封装，提供同步 / 异步接口及内存缓存。"""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_size: int = 4096,
    ) -> None:
        cfg = get_settings()
        self.model = model or cfg.embedding_model
        self.dimension = cfg.embedding_dimension
        self._client = openai.OpenAI(
            api_key=api_key or cfg.llm_api_key,
            base_url=base_url or cfg.llm_base_url,
        )
        self._cache: dict[str, list[float]] = {}
        self._cache_size = cache_size

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _get_from_cache(self, key: str) -> list[float] | None:
        return self._cache.get(key)

    def _put_to_cache(self, key: str, vector: list[float]) -> None:
        if len(self._cache) >= self._cache_size:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = vector

    # ------------------------------------------------------------------
    # 同步接口
    # ------------------------------------------------------------------

    def embed(
        self,
        text: str,
        task_type: str = "RETRIEVAL_DOCUMENT",  # 保留参数兼容旧调用方，实际忽略
    ) -> list[float]:
        """将单条文本转换为嵌入向量（带缓存）。"""
        key = self._cache_key(text)
        cached = self._get_from_cache(key)
        if cached is not None:
            return cached

        response = self._client.embeddings.create(
            model=self.model,
            input=text,
        )
        vector: list[float] = response.data[0].embedding
        self._put_to_cache(key, vector)
        return vector

    def embed_batch(
        self,
        texts: Sequence[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        """批量嵌入（自动分批，支持缓存命中跳过）。"""
        results: list[list[float] | None] = [None] * len(texts)
        miss_indices: list[int] = []

        for i, text in enumerate(texts):
            key = self._cache_key(text)
            hit = self._get_from_cache(key)
            if hit is not None:
                results[i] = hit
            else:
                miss_indices.append(i)

        for batch_start in range(0, len(miss_indices), _BATCH_SIZE):
            batch_idx = miss_indices[batch_start : batch_start + _BATCH_SIZE]
            batch_texts = [texts[i] for i in batch_idx]
            response = self._client.embeddings.create(
                model=self.model,
                input=batch_texts,
            )
            vectors = [item.embedding for item in response.data]
            for idx, vec in zip(batch_idx, vectors):
                key = self._cache_key(texts[idx])
                self._put_to_cache(key, vec)
                results[idx] = vec

        return results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 异步接口（在线程池中运行同步调用，避免阻塞事件循环）
    # ------------------------------------------------------------------

    async def aembed(
        self,
        text: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.embed, text, task_type)

    async def aembed_batch(
        self,
        texts: Sequence[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.embed_batch, texts, task_type)

    # ------------------------------------------------------------------
    # 相似度工具
    # ------------------------------------------------------------------

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """全局单例 EmbeddingService（进程级缓存）。"""
    return EmbeddingService()
