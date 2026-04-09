"""
tasks/worktree.py — Git Worktree 隔离 (s18)

每个任务分配一个独立的 git worktree，
WorkerAgent 的文件操作限定在该目录内，互不干扰。

v5 新增：
  - create_named(lane, task_id): 命名通道支持
  - list_lanes(): 列出所有通道
  - gc(ttl_hours): 定时清理过期 worktree
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import time
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

    # ------------------------------------------------------------------ v5 s18

    def create_named(self, lane: str, task_id: str, branch: str | None = None) -> Path:
        """
        创建命名通道 worktree：root/{lane}/{task_id}（v5 s18）。

        命名通道：
            main/       主 Agent 默认通道
            agent-alice/ Alice 专属通道
            review/     代码审查通道
        """
        dest = self._root / lane / task_id
        key = f"{lane}/{task_id}"
        if key in self._mapping or dest.exists():
            self._mapping[key] = dest
            return dest

        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "worktree", "add", str(dest)]
        if branch:
            cmd += ["-b", branch]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info("Named worktree created: %s/%s at %s", lane, task_id, dest)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.warning("git worktree add failed (%s); using plain mkdir", exc)
            dest.mkdir(parents=True, exist_ok=True)

        self._mapping[key] = dest
        return dest

    def list_lanes(self) -> list[str]:
        """列出 root 下所有命名通道目录名。"""
        if not self._root.exists():
            return []
        return [
            d.name
            for d in self._root.iterdir()
            if d.is_dir()
        ]

    async def gc(self, ttl_hours: float = 24.0) -> int:
        """
        清理超过 TTL 的 worktree 目录（v5 s18）。

        Returns:
            删除的目录数量
        """
        if not self._root.exists():
            return 0
        cutoff = time.time() - ttl_hours * 3600
        removed = 0
        for path in list(self._root.rglob("*")):
            if not path.is_dir():
                continue
            # 只处理叶节点（实际 worktree 目录）
            if any(path.iterdir()):
                # 非空目录：检查 mtime
                if path.stat().st_mtime < cutoff and path.parent != path:
                    try:
                        subprocess.run(
                            ["git", "worktree", "remove", str(path), "--force"],
                            capture_output=True, text=True,
                        )
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        pass
                    shutil.rmtree(path, ignore_errors=True)
                    # 从 mapping 中移除
                    self._mapping = {k: v for k, v in self._mapping.items() if v != path}
                    removed += 1
                    logger.info("GC removed stale worktree: %s", path)
        return removed

    async def start_gc_loop(self, interval_hours: float = 6.0, ttl_hours: float = 24.0) -> None:
        """后台定时 GC 循环。"""
        while True:
            await asyncio.sleep(interval_hours * 3600)
            await self.gc(ttl_hours)
