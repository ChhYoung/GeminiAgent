"""
memory/events.py — 异步事件总线

解耦耗时的 DB 读写与 Embedding 计算，使主调用链路保持低延迟。
订阅者在后台协程中异步处理事件。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

HandlerType = Callable[["MemoryEvent"], Coroutine[Any, Any, None]]


class EventType(str, Enum):
    # 记忆写入
    MEMORY_CREATED = "memory.created"
    MEMORY_UPDATED = "memory.updated"
    MEMORY_DELETED = "memory.deleted"
    MEMORY_ACCESSED = "memory.accessed"

    # 反思与提炼
    REFLECTION_TRIGGERED = "reflection.triggered"
    REFLECTION_COMPLETED = "reflection.completed"

    # 会话生命周期
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"

    # 嵌入计算
    EMBEDDING_REQUESTED = "embedding.requested"
    EMBEDDING_COMPLETED = "embedding.completed"


@dataclass
class MemoryEvent:
    """事件载体。"""

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"

    def __repr__(self) -> str:
        return f"<MemoryEvent type={self.type.value} source={self.source}>"


class EventBus:
    """轻量级内存异步事件总线。

    使用方式：
        bus = EventBus()

        @bus.subscribe(EventType.MEMORY_CREATED)
        async def on_create(event: MemoryEvent):
            ...

        await bus.publish(MemoryEvent(type=EventType.MEMORY_CREATED, payload={...}))
    """

    def __init__(self, max_queue_size: int = 1024) -> None:
        self._handlers: dict[EventType, list[HandlerType]] = {}
        self._queue: asyncio.Queue[MemoryEvent] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._worker_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # 订阅
    # ------------------------------------------------------------------

    def subscribe(self, *event_types: EventType):
        """装饰器：将异步函数注册为指定事件类型的处理器。"""

        def decorator(handler: HandlerType) -> HandlerType:
            for et in event_types:
                self._handlers.setdefault(et, []).append(handler)
            return handler

        return decorator

    def register(self, event_type: EventType, handler: HandlerType) -> None:
        """编程式注册处理器。"""
        self._handlers.setdefault(event_type, []).append(handler)

    def unregister(self, event_type: EventType, handler: HandlerType) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    # ------------------------------------------------------------------
    # 发布
    # ------------------------------------------------------------------

    async def publish(self, event: MemoryEvent) -> None:
        """将事件放入队列（非阻塞，若队列满则丢弃并警告）。"""
        try:
            self._queue.put_nowait(event)
            logger.debug("Event published: %s", event)
        except asyncio.QueueFull:
            logger.warning("EventBus queue is full, dropping event: %s", event)

    def publish_sync(self, event: MemoryEvent) -> None:
        """从同步上下文发布事件（线程安全）。"""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(self.publish(event))
        else:
            loop.run_until_complete(self.publish(event))

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动后台消费者协程。"""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._consume(), name="event-bus-worker")
        logger.info("EventBus started.")

    async def stop(self) -> None:
        """优雅关闭：等待队列清空后停止。"""
        self._running = False
        if self._worker_task:
            await self._queue.join()
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("EventBus stopped.")

    # ------------------------------------------------------------------
    # 内部消费循环
    # ------------------------------------------------------------------

    async def _consume(self) -> None:
        while self._running or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            handlers = self._handlers.get(event.type, [])
            for handler in handlers:
                try:
                    await handler(event)
                except Exception as exc:
                    logger.exception(
                        "Handler %s raised an error for event %s: %s",
                        handler.__name__,
                        event,
                        exc,
                    )
            self._queue.task_done()


# 全局单例
_default_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus
