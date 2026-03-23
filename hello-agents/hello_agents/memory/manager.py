"""
memory/manager.py — 记忆调度中枢

对外提供统一的 read / write / delete 接口，
屏蔽四种记忆类型和三种存储后端的细节。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from hello_agents.memory.base import (
    ImportanceLevel,
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    MemoryType,
)
from hello_agents.memory.embedding import EmbeddingService, get_embedding_service
from hello_agents.memory.events import EventBus, EventType, MemoryEvent, get_event_bus
from hello_agents.memory.reflection import ReflectionEngine
from hello_agents.memory.router import MemoryRouter
from hello_agents.memory.storage.document_store import DocumentStore
from hello_agents.memory.storage.neo4j_store import Neo4jStore
from hello_agents.memory.storage.qdrant_store import QdrantStore
from hello_agents.memory.types.episodic import EpisodicMemory
from hello_agents.memory.types.perceptual import PerceptualMemory
from hello_agents.memory.types.semantic import SemanticMemory
from hello_agents.memory.types.working import WorkingMemory, WorkingMemoryStore

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    记忆系统统一入口。

    快速上手：
        manager = MemoryManager.from_env()
        await manager.start()

        # 写入
        manager.write("用户喜欢用 Python 写代码", session_id="s1")

        # 读取
        results = manager.read("Python 编程偏好", session_id="s1")

        # 工作记忆
        wm = manager.get_working_memory("s1")
        wm.add("你好，请帮我写个快速排序", role="user")
    """

    def __init__(
        self,
        embedding: EmbeddingService,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        perceptual: PerceptualMemory,
        working_store: WorkingMemoryStore,
        router: MemoryRouter,
        reflection: ReflectionEngine | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._embed = embedding
        self._episodic = episodic
        self._semantic = semantic
        self._perceptual = perceptual
        self._working_store = working_store
        self._router = router
        self._reflection = reflection
        self._bus = event_bus or get_event_bus()

    # ------------------------------------------------------------------
    # 工厂方法（从环境变量构建）
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        api_key: str | None = None,
        enable_reflection: bool = True,
        enable_graph_rag: bool = True,
    ) -> "MemoryManager":
        """根据 .env 配置一键构建完整的记忆管理器。"""
        from dotenv import load_dotenv
        load_dotenv()

        embedding = EmbeddingService(api_key=api_key)

        qdrant = QdrantStore()
        neo4j = Neo4jStore()
        doc_store = DocumentStore()

        episodic = EpisodicMemory(qdrant, doc_store, embedding)
        semantic = SemanticMemory(neo4j, qdrant, doc_store, embedding)
        perceptual = PerceptualMemory(qdrant, doc_store, embedding)
        working_store = WorkingMemoryStore()

        router = MemoryRouter(
            embedding=embedding,
            episodic=episodic,
            semantic=semantic,
            perceptual=perceptual,
            enable_graph_rag=enable_graph_rag,
        )

        reflection = None
        if enable_reflection:
            reflection = ReflectionEngine(
                episodic=episodic,
                semantic=semantic,
                api_key=api_key,
            )

        bus = get_event_bus()

        return cls(
            embedding=embedding,
            episodic=episodic,
            semantic=semantic,
            perceptual=perceptual,
            working_store=working_store,
            router=router,
            reflection=reflection,
            event_bus=bus,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动异步后台服务（事件总线 + 反思引擎）。"""
        await self._bus.start()
        if self._reflection:
            # 注入 manager 引用，使调度循环可以调用 gc()
            self._reflection._manager = self
            await self._reflection.start()
        logger.info("MemoryManager started.")

    async def stop(self) -> None:
        """优雅关闭所有后台服务。"""
        if self._reflection:
            await self._reflection.stop()
        await self._bus.stop()
        logger.info("MemoryManager stopped.")

    # ------------------------------------------------------------------
    # 工作记忆（Session 级）
    # ------------------------------------------------------------------

    def get_working_memory(self, session_id: str) -> WorkingMemory:
        """获取（或创建）指定会话的工作记忆实例。"""
        wm = self._working_store.get_session(session_id)
        self._router._working = wm
        return wm

    # ------------------------------------------------------------------
    # 统一写入接口
    # ------------------------------------------------------------------

    def write(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.EPISODIC,
        importance: ImportanceLevel = ImportanceLevel.MEDIUM,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        # 语义记忆额外参数
        entities: list[dict[str, str]] | None = None,
        relations: list[dict[str, Any]] | None = None,
    ) -> MemoryRecord:
        """向指定类型的记忆中写入内容。"""
        record: MemoryRecord

        if memory_type == MemoryType.EPISODIC:
            record = self._episodic.store(
                content=content,
                metadata=metadata,
                importance=importance,
                session_id=session_id,
                agent_id=agent_id,
            )
            if self._reflection:
                self._reflection.notify_new_episodic()

        elif memory_type == MemoryType.SEMANTIC:
            record = self._semantic.store_fact(
                content=content,
                entities=entities,
                relations=relations,
                metadata=metadata,
                importance=importance,
                session_id=session_id,
            )

        elif memory_type == MemoryType.PERCEPTUAL:
            record = self._perceptual.store_text(
                description=content,
                metadata=metadata,
                session_id=session_id,
            )

        else:
            raise ValueError(f"Cannot write to {memory_type.value} via manager.write(); use get_working_memory() instead.")

        # 发布事件
        self._bus.publish_sync(
            MemoryEvent(
                type=EventType.MEMORY_CREATED,
                payload={"memory_id": record.id, "memory_type": memory_type.value},
                source="memory_manager",
            )
        )
        return record

    # ------------------------------------------------------------------
    # 统一读取接口
    # ------------------------------------------------------------------

    def read(
        self,
        query: str,
        memory_types: list[MemoryType] | None = None,
        top_k: int = 5,
        session_id: str | None = None,
        min_strength: float = 0.1,
        min_relevance: float = 0.0,
    ) -> list[MemorySearchResult]:
        """多路检索记忆，返回 Re-ranked 候选列表。"""
        if memory_types is None:
            memory_types = [MemoryType.WORKING, MemoryType.EPISODIC, MemoryType.SEMANTIC]

        # 确保工作记忆路由到正确的 session
        if session_id and MemoryType.WORKING in memory_types:
            self._router._working = self._working_store.get_session(session_id)

        mq = MemoryQuery(
            text=query,
            memory_types=memory_types,
            top_k=top_k,
            session_id=session_id,
            min_strength=min_strength,
            min_relevance=min_relevance,
        )
        return self._router.retrieve(mq)

    async def aread(
        self,
        query: str,
        memory_types: list[MemoryType] | None = None,
        top_k: int = 5,
        session_id: str | None = None,
        min_strength: float = 0.1,
        min_relevance: float = 0.0,
    ) -> list[MemorySearchResult]:
        """异步并发多路检索。"""
        if memory_types is None:
            memory_types = [MemoryType.EPISODIC, MemoryType.SEMANTIC]

        if session_id and MemoryType.WORKING in (memory_types or []):
            self._router._working = self._working_store.get_session(session_id)

        mq = MemoryQuery(
            text=query,
            memory_types=memory_types,
            top_k=top_k,
            session_id=session_id,
            min_strength=min_strength,
            min_relevance=min_relevance,
        )
        return await self._router.aretrieve(mq)

    # ------------------------------------------------------------------
    # 上下文构建（供 Prompt 注入使用）
    # ------------------------------------------------------------------

    def build_context(
        self,
        query: str,
        session_id: str | None = None,
        top_k: int = 5,
        max_chars: int = 4000,
    ) -> str:
        """一步完成检索 + 上下文融合，返回可注入 Prompt 的字符串。"""
        results = self.read(query, top_k=top_k, session_id=session_id)
        return self._router.build_context(results, max_chars=max_chars)

    # ------------------------------------------------------------------
    # 手动触发反思
    # ------------------------------------------------------------------

    async def reflect(self, session_id: str | None = None) -> list[str]:
        """手动触发一次反思（将高价值情景记忆提炼为语义记忆）。"""
        if self._reflection is None:
            logger.warning("ReflectionEngine is disabled.")
            return []
        return await self._reflection.reflect(session_id=session_id)

    # ------------------------------------------------------------------
    # 垃圾回收
    # ------------------------------------------------------------------

    def gc(self, forgotten_threshold: float = 0.05) -> int:
        """
        清除已被遗忘的记忆（强度低于 forgotten_threshold）。

        调用 MemoryRecord.is_forgotten() 判断每条记忆是否达到遗忘阈值，
        对判定为"已遗忘"的条目从 Qdrant + SQLite 中删除。

        Returns:
            实际删除的记忆条数。
        """
        candidates = self._episodic._doc.list_weak_memories(
            threshold=forgotten_threshold
        )
        deleted = 0
        for record in candidates:
            if record.is_forgotten(threshold=forgotten_threshold):
                self._episodic.delete(record.id)
                deleted += 1
                logger.debug("GC: forgotten memory deleted %s (strength=%.3f)", record.id, record.strength)
        if deleted:
            logger.info("GC completed: %d forgotten memories deleted.", deleted)
        return deleted

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "episodic_count": self._episodic.count(),
            "active_sessions": self._working_store.active_sessions(),
        }
