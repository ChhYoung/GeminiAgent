"""
context/builder.py — ContextBuilder

GSSC 流水线调度入口：Gather → Select → Structure → Compress。
对外暴露 build(query, session_id) 方法。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hello_agents.context.compress import compress
from hello_agents.context.gather import gather
from hello_agents.context.select import select
from hello_agents.context.structure import structure

if TYPE_CHECKING:
    from hello_agents.memory.manager import MemoryManager
    from hello_agents.rag.knowledge_base import KnowledgeBaseManager

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    串联 Gather→Select→Structure→Compress，为每轮对话组装上下文。

    用法：
        builder = ContextBuilder(memory_manager=mm, kb_manager=kb)
        ctx = await builder.build(query="用户问题", session_id="s1")
        # ctx 是可直接注入 system/user prompt 的字符串
    """

    def __init__(
        self,
        memory_manager: "MemoryManager | None" = None,
        kb_manager: "KnowledgeBaseManager | None" = None,
        token_budget: int = 2000,
        min_score: float = 0.3,
        max_chars: int = 12000,
    ) -> None:
        self._memory = memory_manager
        self._kb = kb_manager
        self._token_budget = token_budget
        self._min_score = min_score
        self._max_chars = max_chars

    async def build(self, query: str, session_id: str) -> str:
        """
        执行完整 GSSC 流水线并返回格式化上下文字符串。

        Args:
            query:      用户当前查询
            session_id: 会话 ID

        Returns:
            可注入 prompt 的上下文字符串（可能为空字符串）
        """
        # 1. Gather
        raw_items = await gather(
            query=query,
            session_id=session_id,
            memory_manager=self._memory,
            kb_manager=self._kb,
        )

        if not raw_items:
            return ""

        # 2. Select
        selected = select(
            items=raw_items,
            token_budget=self._token_budget,
            min_score=self._min_score,
        )

        if not selected:
            return ""

        # 3. Structure
        structured = structure(selected)

        # 4. Compress（如需要）
        final = await compress(structured, max_chars=self._max_chars)

        logger.debug("ContextBuilder: built %d chars of context", len(final))
        return final
