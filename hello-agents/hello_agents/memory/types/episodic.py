"""
memory/types/episodic.py — 情景记忆

记录带时间戳的历史事件（流水账），依赖 Qdrant 进行向量检索，
同时将元数据同步写入 SQLite 持久化。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from hello_agents.memory.base import (
    ImportanceLevel,
    MemoryRecord,
    MemorySearchResult,
    MemoryType,
)
from hello_agents.memory.embedding import EmbeddingService
from hello_agents.memory.storage.document_store import DocumentStore
from hello_agents.memory.storage.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


class EpisodicMemory:
    """
    情景记忆管理器。

    写入流程：
        text -> Embedding -> Qdrant（向量）+ SQLite（元数据）

    检索流程：
        query -> Embedding -> Qdrant ANN -> 按强度过滤 -> 返回结果
    """

    def __init__(
        self,
        qdrant: QdrantStore,
        doc_store: DocumentStore,
        embedding: EmbeddingService,
    ) -> None:
        self._qdrant = qdrant
        self._doc = doc_store
        self._embed = embedding

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def store(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        importance: ImportanceLevel = ImportanceLevel.MEDIUM,
        session_id: str | None = None,
        agent_id: str | None = None,
    ) -> MemoryRecord:
        """将一个情景事件持久化到 Qdrant + SQLite。"""
        importance_score = {
            ImportanceLevel.LOW: 0.25,
            ImportanceLevel.MEDIUM: 0.5,
            ImportanceLevel.HIGH: 0.75,
            ImportanceLevel.CRITICAL: 1.0,
        }[importance]

        record = MemoryRecord(
            memory_type=MemoryType.EPISODIC,
            content=content,
            metadata={
                **(metadata or {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            importance=importance,
            importance_score=importance_score,
            source_session_id=session_id,
            source_agent_id=agent_id,
        )

        # 生成嵌入
        record.embedding = self._embed.embed(content, task_type="RETRIEVAL_DOCUMENT")

        # 写入 Qdrant
        self._qdrant.upsert(record)

        # 写入 SQLite（不含 embedding）
        self._doc.upsert(record)

        logger.debug("Episodic memory stored: %s", record.id)
        return record

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_strength: float = 0.1,
        min_score: float = 0.0,
        session_id: str | None = None,
    ) -> list[MemorySearchResult]:
        """语义检索情景记忆。"""
        query_vec = self._embed.embed(query, task_type="RETRIEVAL_QUERY")
        results = self._qdrant.search(
            query_vector=query_vec,
            memory_type=MemoryType.EPISODIC,
            top_k=top_k * 2,  # 先多取一些，再按强度过滤
            min_score=min_score,
            session_id=session_id,
        )
        # 过滤衰减记忆
        filtered = [r for r in results if r.record.strength >= min_strength]
        # 强化被检索到的记忆
        for r in filtered[:top_k]:
            r.record.reinforce()
            self._doc.upsert(r.record)
        return filtered[:top_k]

    def get_by_id(self, memory_id: str) -> MemoryRecord | None:
        return self._qdrant.get(memory_id, MemoryType.EPISODIC)

    def get_by_session(
        self, session_id: str, limit: int = 50
    ) -> list[MemoryRecord]:
        return self._doc.list_by_session(
            session_id=session_id,
            memory_type=MemoryType.EPISODIC,
            limit=limit,
        )

    def delete(self, memory_id: str) -> None:
        self._qdrant.delete(memory_id, MemoryType.EPISODIC)
        self._doc.delete(memory_id)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def count(self) -> int:
        return self._doc.count(MemoryType.EPISODIC)
