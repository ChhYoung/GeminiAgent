"""
tasks/store.py — 任务持久化存储 (s07)

使用 JSON Lines 格式落盘，每行一条 Task 快照（append-only）。
load_all() 重放快照，同 id 取最新状态。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.tasks.models import Task

logger = logging.getLogger(__name__)

_DEFAULT_PATH = os.getenv("TASK_STORE_PATH", "tasks.jsonl")


class TaskStore:
    """
    JSON Lines 文件任务存储。

    格式：每行一个 Task 的 JSON 快照。
    同一 task_id 可出现多次，load_all 以最后一条为准。
    """

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, task: "Task") -> None:
        """追加一条 Task 快照到文件。"""
        line = json.dumps(task.to_dict(), ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_all(self) -> list["Task"]:
        """加载所有任务，同 ID 取最新快照。"""
        from hello_agents.tasks.models import Task

        if not self._path.exists():
            return []

        latest: dict[str, dict] = {}
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    latest[d["id"]] = d
                except (json.JSONDecodeError, KeyError):
                    logger.warning("Skipping malformed task line in %s", self._path)

        return [Task.from_dict(d) for d in latest.values()]

    def compact(self) -> None:
        """压缩存储文件，只保留每个 task 的最新状态。"""
        tasks = self.load_all()
        with self._path.open("w", encoding="utf-8") as f:
            for task in tasks:
                f.write(json.dumps(task.to_dict(), ensure_ascii=False) + "\n")

    def clear(self) -> None:
        """删除存储文件。"""
        if self._path.exists():
            self._path.unlink()
