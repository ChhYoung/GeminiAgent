"""
recovery/fallback.py — 工具降级链 (s11)

主工具失败时，自动尝试备用工具，最终返回错误消息。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hello_agents.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class FallbackChain:
    """
    工具降级链。

    用法：
        chain = FallbackChain()
        chain.add("web_search", "search_memory")  # web_search 失败 → 用 search_memory
        result = await chain.call("web_search", args, registry)
    """

    def __init__(self) -> None:
        # primary → list[backup]（有序）
        self._chains: dict[str, list[str]] = {}

    def add(self, primary: str, *backups: str) -> None:
        """注册降级链：primary 失败时依次尝试 backups。"""
        self._chains[primary] = list(backups)

    def call(self, tool_name: str, args: dict, registry: "ToolRegistry") -> str:
        """
        调用工具，失败时按降级链重试。

        Returns:
            JSON 字符串结果（成功或最终失败原因）
        """
        candidates = [tool_name] + self._chains.get(tool_name, [])
        last_err: str = ""

        for name in candidates:
            if not registry.has_tool(name):
                last_err = f"Tool '{name}' not registered."
                logger.warning(last_err)
                continue
            try:
                # 构建最简 mock tool_call
                tc = _MockToolCall(name, args)
                return registry.dispatch(tc)
            except Exception as exc:
                last_err = str(exc)
                logger.warning(
                    "Tool '%s' failed (%s), trying fallback…", name, exc
                )

        return json.dumps({"error": f"All tools in fallback chain failed. Last: {last_err}"})


class _MockToolCall:
    """用于在 fallback 中调用 registry.dispatch 的轻量伪 tool_call。"""

    class _Fn:
        def __init__(self, name: str, args: dict) -> None:
            self.name = name
            import json
            self.arguments = json.dumps(args)

    def __init__(self, name: str, args: dict) -> None:
        self.id = f"fallback-{name}"
        self.function = self._Fn(name, args)
