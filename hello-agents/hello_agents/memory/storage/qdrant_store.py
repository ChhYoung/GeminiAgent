"""
memory/storage/qdrant_store.py — Qdrant 向量存储引擎

提供高维嵌入向量的 CRUD 与 ANN（近似最近邻）检索能力。
支持 Qdrant Cloud 和本地 Docker 部署。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from qdrant_client import AsyncQdrantClient, QdrantClient, models
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from hello_agents.memory.base import MemoryRecord, MemorySearchResult, MemoryType

logger = logging.getLogger(__name__)

_QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
_QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
_EMBED_DIM = int(os.getenv("EMBEDDING_DIMENSION", "768"))


def _collection_name(memory_type: MemoryType) -> str:
    return f"{memory_type.value}_memory"


class QdrantStore:
    """同步 Qdrant 存储封装。"""

    def __init__(
        self,
        url: str = _QDRANT_URL,
        api_key: str | None = _QDRANT_API_KEY,
        dimension: int = _EMBED_DIM,
    ) -> None:
        self.client = QdrantClient(url=url, api_key=api_key)
        self.dimension = dimension
        self._ensure_collections()

    def _ensure_collections(self) -> None:
        existing = {c.name for c in self.client.get_collections().collections}
        for mt in MemoryType:
            name = _collection_name(mt)
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=self.dimension,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", name)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def upsert(self, record: MemoryRecord) -> None:
        if record.embedding is None:
            raise ValueError(f"Record {record.id} has no embedding vector.")
        collection = _collection_name(record.memory_type)
        payload = record.to_storage_dict()
        self.client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=record.id,
                    vector=record.embedding,
                    payload=payload,
                )
            ],
        )

    def delete(self, memory_id: str, memory_type: MemoryType) -> None:
        collection = _collection_name(memory_type)
        self.client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=[memory_id]),
        )

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        memory_type: MemoryType,
        top_k: int = 10,
        min_score: float = 0.0,
        session_id: str | None = None,
    ) -> list[MemorySearchResult]:
        collection = _collection_name(memory_type)
        query_filter: Filter | None = None
        if session_id:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="source_session_id",
                        match=MatchValue(value=session_id),
                    )
                ]
            )

        results = self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=min_score,
            query_filter=query_filter,
            with_payload=True,
        )

        out: list[MemorySearchResult] = []
        for hit in results:
            try:
                record = MemoryRecord.from_storage_dict(dict(hit.payload))
                record.embedding = None  # 不回传大向量
                relevance = float(hit.score)
                final = relevance * record.strength * record.importance_score
                out.append(
                    MemorySearchResult(
                        record=record,
                        relevance_score=relevance,
                        final_score=final,
                        source=f"qdrant:{collection}",
                    )
                )
            except Exception as exc:
                logger.warning("Failed to deserialize qdrant hit %s: %s", hit.id, exc)
        return out

    def get(self, memory_id: str, memory_type: MemoryType) -> MemoryRecord | None:
        collection = _collection_name(memory_type)
        results = self.client.retrieve(
            collection_name=collection,
            ids=[memory_id],
            with_payload=True,
            with_vectors=True,
        )
        if not results:
            return None
        hit = results[0]
        record = MemoryRecord.from_storage_dict(dict(hit.payload))
        record.embedding = hit.vector  # type: ignore[assignment]
        return record


class AsyncQdrantStore:
    """异步 Qdrant 存储封装。"""

    def __init__(
        self,
        url: str = _QDRANT_URL,
        api_key: str | None = _QDRANT_API_KEY,
        dimension: int = _EMBED_DIM,
    ) -> None:
        self.client = AsyncQdrantClient(url=url, api_key=api_key)
        self.dimension = dimension

    async def ensure_collections(self) -> None:
        existing_resp = await self.client.get_collections()
        existing = {c.name for c in existing_resp.collections}
        for mt in MemoryType:
            name = _collection_name(mt)
            if name not in existing:
                await self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=self.dimension,
                        distance=Distance.COSINE,
                    ),
                )

    async def upsert(self, record: MemoryRecord) -> None:
        if record.embedding is None:
            raise ValueError(f"Record {record.id} has no embedding vector.")
        collection = _collection_name(record.memory_type)
        await self.client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=record.id,
                    vector=record.embedding,
                    payload=record.to_storage_dict(),
                )
            ],
        )

    async def search(
        self,
        query_vector: list[float],
        memory_type: MemoryType,
        top_k: int = 10,
        min_score: float = 0.0,
        session_id: str | None = None,
    ) -> list[MemorySearchResult]:
        collection = _collection_name(memory_type)
        query_filter: Filter | None = None
        if session_id:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="source_session_id",
                        match=MatchValue(value=session_id),
                    )
                ]
            )
        results = await self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=min_score,
            query_filter=query_filter,
            with_payload=True,
        )
        out: list[MemorySearchResult] = []
        for hit in results:
            try:
                record = MemoryRecord.from_storage_dict(dict(hit.payload))
                record.embedding = None
                relevance = float(hit.score)
                final = relevance * record.strength * record.importance_score
                out.append(
                    MemorySearchResult(
                        record=record,
                        relevance_score=relevance,
                        final_score=final,
                        source=f"qdrant:{collection}",
                    )
                )
            except Exception as exc:
                logger.warning("Failed to deserialize async qdrant hit %s: %s", hit.id, exc)
        return out
