"""
tasks/kanban.py — 看板 (s11)

三列看板：PENDING / IN_PROGRESS / DONE
WorkerAgent 通过原子 claim() 操作认领任务，无需中心调度器。
多个 WorkerAgent 并发认领时不会重复。
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.tasks.models import Task

logger = logging.getLogger(__name__)


class Kanban:
    """
    线程安全的三列看板。

    特性：
    - claim() 原子操作：取第一个 PENDING 任务，立即改为 IN_PROGRESS
    - 多个 WorkerAgent 并发认领，不重复
    - complete() / fail() 更新最终状态
    """

    def __init__(self) -> None:
        self._tasks: dict[str, "Task"] = {}
        self._lock = threading.Lock()

    def push(self, task: "Task") -> None:
        """推入新任务（状态应为 PENDING）。"""
        with self._lock:
            self._tasks[task.id] = task
        logger.debug("Kanban: pushed task %s", task.id)

    def claim(self, agent_id: str) -> "Task | None":
        """
        原子认领：取第一个 PENDING 任务，改为 IN_PROGRESS。

        Returns:
            认领到的任务，若无可认领任务则返回 None。
        """
        with self._lock:
            for task in self._tasks.values():
                if task.status == "PENDING":
                    task.status = "IN_PROGRESS"
                    task.assignee = agent_id
                    task.touch()
                    logger.info(
                        "Kanban: agent %s claimed task %s", agent_id, task.id
                    )
                    return task
        return None

    def complete(self, task_id: str, result: str = "") -> bool:
        """标记任务完成。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = "DONE"
            task.result = result
            task.touch()
        return True

    def fail(self, task_id: str, reason: str = "") -> bool:
        """标记任务失败。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            task.status = "FAILED"
            task.result = reason
            task.touch()
        return True

    # ---- 查询 ----

    def pending(self) -> list["Task"]:
        return [t for t in self._tasks.values() if t.status == "PENDING"]

    def in_progress(self) -> list["Task"]:
        return [t for t in self._tasks.values() if t.status == "IN_PROGRESS"]

    def done(self) -> list["Task"]:
        return [t for t in self._tasks.values() if t.status == "DONE"]

    def all_tasks(self) -> list["Task"]:
        return list(self._tasks.values())
