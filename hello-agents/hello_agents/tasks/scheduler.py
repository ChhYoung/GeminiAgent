"""
tasks/scheduler.py — 任务调度器 (s07)

TaskGraph + TaskStore 的门面类：接受新任务、查询就绪任务、更新状态、持久化变更。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hello_agents.tasks.graph import TaskGraph
from hello_agents.tasks.store import TaskStore

if TYPE_CHECKING:
    from hello_agents.tasks.models import Task

logger = logging.getLogger(__name__)


class Scheduler:
    """
    任务图 + 持久化存储的门面类。

    职责：
    - 接受新任务（add）
    - 查询就绪任务（next_ready）
    - 更新任务状态（update_status）
    - 持久化所有变更
    """

    def __init__(self, store: TaskStore | None = None) -> None:
        self._store = store or TaskStore()
        self._graph = TaskGraph()
        # 启动时从磁盘恢复
        for task in self._store.load_all():
            self._graph.add(task)

    def add(self, task: "Task") -> None:
        """添加任务并持久化。"""
        self._graph.add(task)
        self._store.save(task)
        logger.info("Scheduled task %s: %s", task.id, task.goal[:60])

    def next_ready(self) -> "Task | None":
        """返回第一个就绪（依赖已全 DONE）的 PENDING 任务。"""
        ready = self._graph.ready_tasks()
        return ready[0] if ready else None

    def all_tasks(self) -> list["Task"]:
        return self._graph.all_tasks()

    def update_status(
        self, task_id: str, status: str, result: str | None = None
    ) -> bool:
        """
        更新任务状态并持久化。

        Returns:
            True 表示成功，False 表示 task_id 不存在。
        """
        task = self._graph.get(task_id)
        if task is None:
            return False
        task.status = status  # type: ignore[assignment]
        if result is not None:
            task.result = result
        task.touch()
        self._store.save(task)
        return True
