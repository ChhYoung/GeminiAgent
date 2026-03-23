"""
context/gather.py — Gather 阶段

并发从 memory router、RAG 和 terminal last_output 收集原始素材。
返回统一格式的 RawItem 列表。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hello_agents.memory.manager import MemoryManager
    from hello_agents.rag.knowledge_base import KnowledgeBaseManager

logger = logging.getLogger(__name__)


@dataclass
class RawItem:
    """单条原始素材。"""
    source: str          # "memory" | "rag" | "system_state"
    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


async def gather(
    query: str,
    session_id: str,
    memory_manager: "MemoryManager | None" = None,
    kb_manager: "KnowledgeBaseManager | None" = None,
    top_k: int = 5,
) -> list[RawItem]:
    """
    并发收集所有来源的原始素材。

    Args:
        query:          用户当前查询
        session_id:     会话 ID
        memory_manager: 记忆系统（可选）
        kb_manager:     知识库（可选）
        top_k:          每个来源最多返回条数

    Returns:
        RawItem 列表
    """
    tasks: list[asyncio.Task] = []

    if memory_manager is not None:
        tasks.append(asyncio.create_task(
            _fetch_memory(query, session_id, memory_manager, top_k),
            name="gather-memory",
        ))

    if kb_manager is not None:
        tasks.append(asyncio.create_task(
            _fetch_rag(query, kb_manager, top_k),
            name="gather-rag",
        ))

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    items: list[RawItem] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Gather task failed: %s", result)
        else:
            items.extend(result)

    return items


async def _fetch_memory(
    query: str,
    session_id: str,
    manager: "MemoryManager",
    top_k: int,
) -> list[RawItem]:
    from hello_agents.memory.base import MemoryType

    try:
        results = await asyncio.to_thread(
            manager.read,
            query=query,
            memory_types=[MemoryType.EPISODIC, MemoryType.SEMANTIC],
            top_k=top_k,
            session_id=session_id,
        )
        return [
            RawItem(
                source="memory",
                content=r.record.content,
                score=r.final_score,
                metadata={
                    "id": r.record.id,
                    "type": r.record.memory_type.value,
                    "strength": r.record.strength,
                },
            )
            for r in results
        ]
    except Exception as exc:
        logger.warning("Memory gather failed: %s", exc)
        return []


async def _fetch_rag(
    query: str,
    kb_manager: "KnowledgeBaseManager",
    top_k: int,
) -> list[RawItem]:
    try:
        all_kbs = await asyncio.to_thread(kb_manager.list_all)
        items: list[RawItem] = []
        for kb_meta in all_kbs:
            kb = await asyncio.to_thread(kb_manager.get, kb_meta["name"])
            if kb is None:
                continue
            results = await asyncio.to_thread(kb.search, query, top_k=top_k, min_score=0.4)
            for r in results:
                items.append(
                    RawItem(
                        source="rag",
                        content=r.chunk.text[:600],
                        score=r.score,
                        metadata={
                            "source_file": r.chunk.source,
                            "section": str(r.chunk.page_or_section),
                            "kb_name": kb_meta["name"],
                        },
                    )
                )
        return items
    except Exception as exc:
        logger.warning("RAG gather failed: %s", exc)
        return []
