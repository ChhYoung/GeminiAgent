"""
hooks/registry.py — Hook 注册表 (s08)

在 Agent Loop 各阶段触发已注册的钩子。
钩子异常不中断主循环，只写 warning 日志。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

from hello_agents.hooks.events import HookEvent

logger = logging.getLogger(__name__)

HookFn = Callable[[dict], Any]


class HookRegistry:
    """
    Hook 注册表。

    用法：
        hooks = HookRegistry()
        hooks.on(HookEvent.PRE_TOOL, lambda p: print("before tool", p))
        await hooks.fire(HookEvent.PRE_TOOL, {"tool": "search_memory"})
    """

    def __init__(self) -> None:
        self._handlers: dict[HookEvent, list[HookFn]] = defaultdict(list)

    def on(self, event: HookEvent, fn: HookFn) -> None:
        """注册钩子函数。同一事件可注册多个，按注册顺序调用。"""
        self._handlers[event].append(fn)
        logger.debug("Hook registered for %s: %s", event, fn)

    def off(self, event: HookEvent, fn: HookFn) -> bool:
        """注销钩子函数。返回是否找到并移除。"""
        handlers = self._handlers[event]
        if fn in handlers:
            handlers.remove(fn)
            return True
        return False

    async def fire(self, event: HookEvent, payload: dict) -> None:
        """
        触发指定事件的所有钩子。

        钩子可以是普通函数或协程函数。
        单个钩子抛异常时，记录警告后继续执行后续钩子。
        """
        for fn in list(self._handlers[event]):
            try:
                result = fn(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning(
                    "Hook %s raised %s: %s", fn.__name__ if hasattr(fn, "__name__") else fn, type(exc).__name__, exc
                )

    def listener_count(self, event: HookEvent) -> int:
        """返回指定事件的已注册钩子数量。"""
        return len(self._handlers[event])

    def clear(self, event: HookEvent | None = None) -> None:
        """清空指定事件或所有事件的钩子。"""
        if event is None:
            self._handlers.clear()
        else:
            self._handlers[event].clear()
