"""
tests/integration/test_worktree.py — WorktreeManager 测试 (s12)
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hello_agents.tasks.worktree import WorktreeManager


class TestWorktreeManager:
    def test_create_returns_path(self, tmp_path):
        mgr = WorktreeManager(root=tmp_path / "worktrees")
        path = mgr.create("task-001")
        assert path.exists()
        assert path.name == "task-001"

    def test_create_idempotent(self, tmp_path):
        mgr = WorktreeManager(root=tmp_path / "worktrees")
        p1 = mgr.create("task-001")
        p2 = mgr.create("task-001")  # 再次调用
        assert p1 == p2

    def test_path_for_registered_task(self, tmp_path):
        mgr = WorktreeManager(root=tmp_path / "worktrees")
        path = mgr.create("task-002")
        assert mgr.path_for("task-002") == path

    def test_path_for_unregistered_task(self, tmp_path):
        mgr = WorktreeManager(root=tmp_path / "worktrees")
        # 未创建的任务返回 None
        assert mgr.path_for("no-such-task") is None

    def test_remove_existing(self, tmp_path):
        mgr = WorktreeManager(root=tmp_path / "worktrees")
        path = mgr.create("task-003")
        assert path.exists()
        ok = mgr.remove("task-003")
        assert ok is True
        assert not path.exists()

    def test_remove_nonexistent_returns_false(self, tmp_path):
        mgr = WorktreeManager(root=tmp_path / "worktrees")
        ok = mgr.remove("ghost-task")
        assert ok is False

    def test_path_for_existing_dir_not_in_mapping(self, tmp_path):
        """目录已存在但不在 mapping 中，也能找到。"""
        root = tmp_path / "worktrees"
        (root / "task-005").mkdir(parents=True)
        mgr = WorktreeManager(root=root)
        path = mgr.path_for("task-005")
        assert path is not None
        assert path.name == "task-005"

    def test_multiple_tasks_isolated(self, tmp_path):
        root = tmp_path / "worktrees"
        mgr = WorktreeManager(root=root)
        p1 = mgr.create("task-a")
        p2 = mgr.create("task-b")
        assert p1 != p2
        assert p1.exists()
        assert p2.exists()
