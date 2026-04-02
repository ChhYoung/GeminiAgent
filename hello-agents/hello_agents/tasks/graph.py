"""
tasks/graph.py — DAG 任务图 (s07)

管理任务之间的依赖关系，支持拓扑排序和就绪任务查询。
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.tasks.models import Task

logger = logging.getLogger(__name__)


class TaskGraph:
    """
    有向无环图（DAG）任务依赖管理。

    特性：
    - 检测循环依赖（has_cycle）
    - 计算拓扑排序（topological_order）
    - 找出当前可执行的任务（ready_tasks）
    """

    def __init__(self) -> None:
        self._tasks: dict[str, "Task"] = {}

    def add(self, task: "Task") -> None:
        """添加任务到图中。"""
        self._tasks[task.id] = task

    def get(self, task_id: str) -> "Task | None":
        return self._tasks.get(task_id)

    def all_tasks(self) -> list["Task"]:
        return list(self._tasks.values())

    def ready_tasks(self) -> list["Task"]:
        """返回依赖全部已 DONE 且状态为 PENDING 的任务。"""
        result = []
        for task in self._tasks.values():
            if task.status != "PENDING":
                continue
            deps_ok = all(
                self._tasks.get(dep_id) is not None
                and self._tasks[dep_id].status == "DONE"
                for dep_id in task.deps
            )
            if deps_ok:
                result.append(task)
        return result

    def topological_order(self) -> list["Task"]:
        """
        返回拓扑排序后的任务列表（Kahn 算法）。

        Raises:
            ValueError: 存在循环依赖时抛出。
        """
        # 计算每个节点的入度
        in_degree: dict[str, int] = {tid: 0 for tid in self._tasks}
        for task in self._tasks.values():
            for dep in task.deps:
                if dep in in_degree:
                    in_degree[task.id] = in_degree.get(task.id, 0) + 1

        queue: deque[str] = deque(
            tid for tid, deg in in_degree.items() if deg == 0
        )
        order: list["Task"] = []

        while queue:
            tid = queue.popleft()
            order.append(self._tasks[tid])
            for other in self._tasks.values():
                if tid in other.deps:
                    in_degree[other.id] -= 1
                    if in_degree[other.id] == 0:
                        queue.append(other.id)

        if len(order) != len(self._tasks):
            raise ValueError("Circular dependency detected in TaskGraph")

        return order

    def has_cycle(self) -> bool:
        """检测是否存在循环依赖。"""
        try:
            self.topological_order()
            return False
        except ValueError:
            return True
