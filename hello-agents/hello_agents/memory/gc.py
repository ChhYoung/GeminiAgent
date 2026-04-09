"""
memory/gc.py — 记忆垃圾回收器 (s09)

按遗忘曲线定时扫描 EpisodicMemory，删除 strength 低于阈值的条目。
以后台协程形式运行，不阻塞主循环。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class MemoryGarbageCollector:
    """
    记忆垃圾回收器。

    用法：
        gc = MemoryGarbageCollector(manager, min_strength=0.1)
        deleted = await gc.run_once()
        await gc.start_background(interval_s=3600)
    """

    def __init__(
        self,
        manager: "MemoryManager",
        min_strength: float = 0.1,
    ) -> None:
        self._manager = manager
        self._min_strength = min_strength
        self._task: asyncio.Task | None = None
        self._running = False

    async def run_once(self) -> int:
        """
        执行一次 GC 扫描。

        Returns:
            删除的记忆条目数
        """
        deleted = 0
        try:
            working = self._manager.get_working_memory("__gc__")
            records = list(working._store._records.values()) if hasattr(working, "_store") else []
            for record in records:
                # 按遗忘曲线更新 strength（如果 record 有此属性）
                if hasattr(record, "strength"):
                    record.decay()  # type: ignore[attr-defined]
                    if record.strength < self._min_strength:
                        working._store.delete(record.id)  # type: ignore[attr-defined]
                        deleted += 1
        except Exception as exc:
            logger.warning("MemoryGC run_once error: %s", exc)

        logger.info("MemoryGC: deleted %d weak records", deleted)
        return deleted

    async def start_background(self, interval_s: int = 3600) -> None:
        """启动后台 GC 循环（每 interval_s 秒运行一次）。"""
        self._running = True
        self._task = asyncio.ensure_future(self._loop(interval_s))
        logger.info("MemoryGC background loop started (interval=%ds)", interval_s)

    async def stop(self) -> None:
        """停止后台 GC 循环。"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self, interval_s: int) -> None:
        while self._running:
            await asyncio.sleep(interval_s)
            if self._running:
                await self.run_once()

    @property
    def is_running(self) -> bool:
        return self._running and (self._task is not None) and not self._task.done()
