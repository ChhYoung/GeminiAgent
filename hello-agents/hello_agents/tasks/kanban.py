"""
tasks/kanban.py — 看板 (s12/s17)

三列看板：PENDING / IN_PROGRESS / DONE
WorkerAgent 通过原子 claim() 操作认领任务，无需中心调度器。
多个 WorkerAgent 并发认领时不会重复。

v5 新增：
  - last_seen: 追踪 IN_PROGRESS 任务的心跳时间
  - touch(): AutonomousAgent 心跳更新
  - release_stale(): 超时任务重置为 PENDING（s17）
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
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
        self._last_seen: dict[str, datetime] = {}  # task_id → last heartbeat time
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

    def touch(self, task_id: str, agent_id: str) -> None:
        """更新 IN_PROGRESS 任务的心跳时间（v5 s17）。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status == "IN_PROGRESS" and task.assignee == agent_id:
                self._last_seen[task_id] = datetime.utcnow()

    def release_stale(self, timeout_s: int = 600) -> list[str]:
        """
        释放超时的 IN_PROGRESS 任务，重置为 PENDING（v5 s17）。

        Args:
            timeout_s: 超过此秒数无心跳则认为僵死

        Returns:
            被释放的 task_id 列表
        """
        now = datetime.utcnow()
        released: list[str] = []
        with self._lock:
            for task in self._tasks.values():
                if task.status != "IN_PROGRESS":
                    continue
                last = self._last_seen.get(task.id, task.updated_at)
                elapsed = (now - last).total_seconds()
                if elapsed > timeout_s:
                    task.status = "PENDING"
                    task.assignee = None
                    task.touch()
                    self._last_seen.pop(task.id, None)
                    released.append(task.id)
                    logger.warning(
                        "Released stale task %s (elapsed=%.0fs)", task.id, elapsed
                    )
        return released

    # ---- 查询 ----

    def pending(self) -> list["Task"]:
        return [t for t in self._tasks.values() if t.status == "PENDING"]

    def in_progress(self) -> list["Task"]:
        return [t for t in self._tasks.values() if t.status == "IN_PROGRESS"]

    def done(self) -> list["Task"]:
        return [t for t in self._tasks.values() if t.status == "DONE"]

    def all_tasks(self) -> list["Task"]:
        return list(self._tasks.values())
