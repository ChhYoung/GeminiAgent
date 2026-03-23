"""
tools/registry.py — 统一工具注册表

提供：
- ToolRegistry.register(handler)  装饰器，注册工具处理器
- ToolRegistry.get_schemas()       返回 OpenAI tool list（供 chat.completions 使用）
- ToolRegistry.dispatch(tool_call) 按 tool_call.function.name 分发到对应 handler
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class ToolHandler(Protocol):
    """工具处理器协议：handler 需要有 TOOL_NAMES 集合和 dispatch 方法。"""

    TOOL_NAMES: set[str]

    def dispatch(self, tool_call: Any) -> str:
        ...


class ToolRegistry:
    """统一工具注册表，管理所有工具的 schema 和 dispatch 逻辑。"""

    def __init__(self) -> None:
        self._schemas: list[dict] = []
        self._handlers: dict[str, ToolHandler] = {}

    def register_handler(self, handler: ToolHandler, schemas: list[dict]) -> None:
        """
        注册一个工具处理器及其对应的 schema 列表。

        Args:
            handler: 实现了 ToolHandler 协议的对象
            schemas: OpenAI tool dict 列表
        """
        for schema in schemas:
            name = schema["function"]["name"]
            self._handlers[name] = handler
            self._schemas.append(schema)
        logger.debug("Registered tools: %s", [s["function"]["name"] for s in schemas])

    def get_schemas(self) -> list[dict]:
        """返回所有已注册工具的 OpenAI tool list。"""
        return list(self._schemas)

    def dispatch(self, tool_call: Any) -> str:
        """
        按 tool_call.function.name 路由到对应处理器。

        Args:
            tool_call: openai ChatCompletionMessageToolCall 对象

        Returns:
            JSON 字符串结果
        """
        name = tool_call.function.name
        handler = self._handlers.get(name)
        if handler is None:
            logger.warning("No handler registered for tool: %s", name)
            return json.dumps({"error": f"Unknown tool: {name}"})
        return handler.dispatch(tool_call)

    def has_tool(self, name: str) -> bool:
        return name in self._handlers
