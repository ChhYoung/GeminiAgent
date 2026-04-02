"""
tasks/worktree.py — Git Worktree 隔离 (s12)

每个任务分配一个独立的 git worktree，
WorkerAgent 的文件操作限定在该目录内，互不干扰。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_WORKTREES_ROOT = Path(".worktrees")


class WorktreeManager:
    """
    Git Worktree 生命周期管理。

    用法：
        mgr = WorktreeManager()
        path = mgr.create("task-001")
        # WorkerAgent 在此路径工作...
        mgr.remove("task-001")
    """

    def __init__(self, root: Path | str = _WORKTREES_ROOT) -> None:
        self._root = Path(root)
        self._mapping: dict[str, Path] = {}

    def create(self, task_id: str, branch: str | None = None) -> Path:
        """
        为 task_id 创建独立 worktree。

        Git worktree 失败时降级为普通目录（mkdir），
        保证测试环境（非 git repo）下也能正常运行。

        Args:
            task_id: 任务 ID，用于目录命名
            branch:  可选分支名

        Returns:
            worktree 目录路径
        """
        dest = self._root / task_id
        if task_id in self._mapping or dest.exists():
            self._mapping[task_id] = dest
            return dest

        cmd = ["git", "worktree", "add", str(dest)]
        if branch:
            cmd += ["-b", branch]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info("Created git worktree for task %s at %s", task_id, dest)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.warning(
                "git worktree add failed (%s); using plain mkdir", exc
            )
            dest.mkdir(parents=True, exist_ok=True)

        self._mapping[task_id] = dest
        return dest

    def remove(self, task_id: str) -> bool:
        """移除 worktree（任务完成后调用）。"""
        dest = self._mapping.pop(task_id, self._root / task_id)
        if not dest.exists():
            return False

        try:
            subprocess.run(
                ["git", "worktree", "remove", str(dest), "--force"],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Removed git worktree for task %s", task_id)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            # 降级：直接删除目录
            shutil.rmtree(dest, ignore_errors=True)
            return True

    def path_for(self, task_id: str) -> Path | None:
        """按 task_id 查 worktree 路径，供 TerminalToolHandler.cwd 使用。"""
        if task_id in self._mapping:
            return self._mapping[task_id]
        candidate = self._root / task_id
        if candidate.exists():
            self._mapping[task_id] = candidate
            return candidate
        return None
