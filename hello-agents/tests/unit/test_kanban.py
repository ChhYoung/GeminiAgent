"""
tests/unit/test_kanban.py — Kanban 看板测试 (s11)
"""

from __future__ import annotations

import threading

import pytest

from hello_agents.tasks.kanban import Kanban
from hello_agents.tasks.models import Task


def _task(goal: str = "test") -> Task:
    return Task(goal=goal)


class TestKanban:
    def test_push_and_pending(self):
        k = Kanban()
        t = _task("写报告")
        k.push(t)
        assert len(k.pending()) == 1

    def test_claim_changes_status(self):
        k = Kanban()
        t = _task()
        k.push(t)
        claimed = k.claim("agent-1")
        assert claimed is not None
        assert claimed.status == "IN_PROGRESS"
        assert claimed.assignee == "agent-1"

    def test_claim_returns_none_when_empty(self):
        k = Kanban()
        assert k.claim("agent-1") is None

    def test_claim_skips_in_progress(self):
        k = Kanban()
        t = _task()
        k.push(t)
        k.claim("agent-1")  # 第一个 agent 认领
        assert k.claim("agent-2") is None  # 无剩余

    def test_complete(self):
        k = Kanban()
        t = _task()
        k.push(t)
        k.claim("agent-1")
        ok = k.complete(t.id, "完成了")
        assert ok is True
        assert t.status == "DONE"
        assert t.result == "完成了"

    def test_fail(self):
        k = Kanban()
        t = _task()
        k.push(t)
        k.claim("agent-1")
        ok = k.fail(t.id, "出错了")
        assert ok is True
        assert t.status == "FAILED"

    def test_complete_unknown_task(self):
        k = Kanban()
        assert k.complete("nonexistent", "") is False

    def test_fail_unknown_task(self):
        k = Kanban()
        assert k.fail("nonexistent", "") is False

    def test_concurrent_claim_no_duplicate(self):
        """两个线程并发认领，同一任务只被认领一次。"""
        k = Kanban()
        k.push(_task("task-A"))

        results = []

        def claim():
            results.append(k.claim(f"agent-{threading.get_ident()}"))

        threads = [threading.Thread(target=claim) for _ in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        claimed = [r for r in results if r is not None]
        assert len(claimed) == 1

    def test_all_tasks(self):
        k = Kanban()
        k.push(_task("t1"))
        k.push(_task("t2"))
        assert len(k.all_tasks()) == 2

    def test_done_and_in_progress_lists(self):
        k = Kanban()
        t1 = _task("a")
        t2 = _task("b")
        k.push(t1)
        k.push(t2)
        k.claim("w1")  # t1 -> IN_PROGRESS
        k.complete(t1.id)  # t1 -> DONE
        assert len(k.done()) == 1
        assert len(k.in_progress()) == 0
