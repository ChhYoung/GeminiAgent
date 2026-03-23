"""
memory/types/semantic.py — 语义记忆

存储从情景记忆中提炼出的实体关系与规则，依赖 Neo4j 图数据库。
支持 GraphRAG 查询：通过图结构扩展相关上下文。
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
from hello_agents.memory.storage.neo4j_store import Neo4jStore
from hello_agents.memory.storage.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


class SemanticMemory:
    """
    语义记忆管理器。

    数据模型：
    - MemoryRecord 节点存于 Neo4j，包含提炼出的事实/规则文本
    - 实体（Entity）与关系（RELATES_TO）构成知识图谱
    - 向量索引存于 Qdrant，支持模糊语义检索
    - 元数据持久化于 SQLite

    典型用途：
    - "用户偏好素食" → Entity(User) -[:PREFERS]-> Entity(Vegetarian)
    - "Python 是一种编程语言" → Entity(Python) -[:IS_A]-> Entity(ProgrammingLanguage)
    """

    def __init__(
        self,
        neo4j: Neo4jStore,
        qdrant: QdrantStore,
        doc_store: DocumentStore,
        embedding: EmbeddingService,
    ) -> None:
        self._neo4j = neo4j
        self._qdrant = qdrant
        self._doc = doc_store
        self._embed = embedding

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def store_fact(
        self,
        content: str,
        entities: list[dict[str, str]] | None = None,
        relations: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        importance: ImportanceLevel = ImportanceLevel.HIGH,
        session_id: str | None = None,
    ) -> MemoryRecord:
        """
        存储一条语义事实。

        Args:
            content:   事实的自然语言描述
            entities:  相关实体列表，格式 [{"name": "...", "type": "..."}]
            relations: 实体关系列表，格式 [{"from": "...", "to": "...", "rel": "...", "weight": 0.9}]
            metadata:  附加元数据
            importance: 重要性等级
            session_id: 来源会话 ID
        """
        record = MemoryRecord(
            memory_type=MemoryType.SEMANTIC,
            content=content,
            metadata={
                **(metadata or {}),
                "entities": entities or [],
                "relations": relations or [],
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            },
            importance=importance,
            importance_score={"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}[
                importance.value
            ],
            source_session_id=session_id,
        )

        # 嵌入向量
        record.embedding = self._embed.embed(content, task_type="RETRIEVAL_DOCUMENT")

        # 写入 Neo4j —— 记忆节点
        self._neo4j.upsert_memory_node(
            record.id,
            {
                "content": content,
                "importance": importance.value,
                "created_at": record.created_at.isoformat(),
            },
        )

        # 写入实体与关系
        ts = datetime.now(timezone.utc).isoformat()
        for ent in entities or []:
            self._neo4j.upsert_entity(ent["name"], ent.get("type", "Unknown"), ts)
            self._neo4j.link_memory_to_entity(record.id, ent["name"])

        for rel in relations or []:
            self._neo4j.upsert_relation(
                from_name=rel["from"],
                to_name=rel["to"],
                relation=rel.get("rel", "RELATES_TO"),
                weight=float(rel.get("weight", 1.0)),
                memory_id=record.id,
            )

        # 写入 Qdrant
        self._qdrant.upsert(record)

        # 写入 SQLite
        self._doc.upsert(record)

        logger.debug("Semantic fact stored: %s", record.id)
        return record

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[MemorySearchResult]:
        """向量语义检索。"""
        query_vec = self._embed.embed(query, task_type="RETRIEVAL_QUERY")
        results = self._qdrant.search(
            query_vector=query_vec,
            memory_type=MemoryType.SEMANTIC,
            top_k=top_k,
            min_score=min_score,
        )
        for r in results:
            r.record.reinforce()
            self._doc.upsert(r.record)
        return results

    def graph_search(
        self,
        entity_name: str,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        """图结构扩展查询（GraphRAG）。"""
        return self._neo4j.get_graph_neighbors(entity_name, limit=depth * 10)

    def search_entities(
        self,
        keyword: str = "",
        entity_type: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self._neo4j.search_entities(keyword, entity_type, limit)

    def run_cypher(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """直接执行 Cypher 语句（高级用途）。"""
        return self._neo4j.run_cypher(cypher, params)

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    def delete(self, memory_id: str) -> None:
        self._neo4j.delete_memory_node(memory_id)
        self._qdrant.delete(memory_id, MemoryType.SEMANTIC)
        self._doc.delete(memory_id)
