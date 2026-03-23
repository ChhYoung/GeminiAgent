"""
tools/builtin/memory_tool.py — 记忆工具

允许 Agent 通过 OpenAI Function Calling 主动操作自己的记忆：
- search_memory  : 检索过去的记忆
- store_memory   : 主动标记/存储重要记忆
- forget_memory  : 删除某条记忆

工具定义格式兼容 OpenAI tool dict（{"type": "function", "function": {...}}）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hello_agents.memory.base import ImportanceLevel, MemoryType
from hello_agents.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# OpenAI tool dict 格式
# ------------------------------------------------------------------

MEMORY_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "在 Agent 的记忆系统中检索与查询相关的历史信息。"
                "当需要回忆过去发生的事情、用户偏好或已知事实时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词或自然语言描述",
                    },
                    "memory_types": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["episodic", "semantic", "working", "perceptual"],
                        },
                        "description": "要检索的记忆类型，默认检索 episodic 和 semantic",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最多返回的结果数，默认 5",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_memory",
            "description": (
                "将重要信息主动存入记忆系统。"
                "当获取到需要长期记住的用户偏好、关键事件或事实知识时调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要记忆的内容",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["episodic", "semantic"],
                        "description": "记忆类型：episodic（事件）或 semantic（知识）",
                    },
                    "importance": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "重要性等级，默认 high",
                    },
                    "entities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                            },
                        },
                        "description": "（语义记忆）相关实体列表",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_memory",
            "description": "从记忆系统中删除指定 ID 的记忆条目（谨慎使用）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {
                        "type": "string",
                        "description": "要删除的记忆 ID",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["episodic", "semantic", "perceptual"],
                        "description": "记忆类型",
                    },
                },
                "required": ["memory_id", "memory_type"],
            },
        },
    },
]


# ------------------------------------------------------------------
# 工具处理器
# ------------------------------------------------------------------

class MemoryToolHandler:
    """
    处理 OpenAI tool_call，调用 MemoryManager 完成操作。

    用法：
        handler = MemoryToolHandler(memory_manager, session_id="s1")
        result = handler.dispatch(tool_call)
    """

    # 该 handler 负责的工具名集合
    TOOL_NAMES = {"search_memory", "store_memory", "forget_memory"}

    def __init__(
        self,
        manager: MemoryManager,
        session_id: str | None = None,
    ) -> None:
        self._manager = manager
        self.session_id = session_id

    def dispatch(self, tool_call: Any) -> str:
        """
        分发 OpenAI tool_call 到对应处理器。

        Args:
            tool_call: openai ChatCompletionMessageToolCall 对象

        Returns:
            JSON 字符串，作为 tool message 回传给模型。
        """
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON arguments"})

        try:
            if name == "search_memory":
                return self._search_memory(**args)
            elif name == "store_memory":
                return self._store_memory(**args)
            elif name == "forget_memory":
                return self._forget_memory(**args)
            else:
                return json.dumps({"error": f"Unknown memory tool: {name}"})
        except Exception as exc:
            logger.exception("MemoryTool error in %s: %s", name, exc)
            return json.dumps({"error": str(exc)})

    def _search_memory(
        self,
        query: str,
        memory_types: list[str] | None = None,
        top_k: int = 5,
    ) -> str:
        mt_list = [MemoryType(t) for t in (memory_types or ["episodic", "semantic"])]
        results = self._manager.read(
            query=query,
            memory_types=mt_list,
            top_k=top_k,
            session_id=self.session_id,
        )
        items = [
            {
                "id": r.record.id,
                "type": r.record.memory_type.value,
                "content": r.record.content,
                "score": round(r.final_score, 3),
                "strength": round(r.record.strength, 3),
            }
            for r in results
        ]
        return json.dumps({"results": items, "count": len(items)}, ensure_ascii=False)

    def _store_memory(
        self,
        content: str,
        memory_type: str = "episodic",
        importance: str = "high",
        entities: list[dict] | None = None,
    ) -> str:
        mt = MemoryType(memory_type)
        imp = ImportanceLevel(importance)
        record = self._manager.write(
            content=content,
            memory_type=mt,
            importance=imp,
            session_id=self.session_id,
            entities=entities,
        )
        return json.dumps(
            {"status": "stored", "memory_id": record.id, "type": mt.value},
            ensure_ascii=False,
        )

    def _forget_memory(self, memory_id: str, memory_type: str) -> str:
        mt = MemoryType(memory_type)
        if mt == MemoryType.EPISODIC:
            self._manager._episodic.delete(memory_id)
        elif mt == MemoryType.SEMANTIC:
            self._manager._semantic.delete(memory_id)
        elif mt == MemoryType.PERCEPTUAL:
            self._manager._perceptual.delete(memory_id)
        return json.dumps({"status": "deleted", "memory_id": memory_id})
