"""
tests/unit/test_task_models.py — Task / Step 模型 + DAG 拓扑 (s07)
"""

from __future__ import annotations

import pytest

from hello_agents.tasks.models import Step, Task
from hello_agents.tasks.graph import TaskGraph


# ---------------------------------------------------------------------------
# Step 模型
# ---------------------------------------------------------------------------

class TestStep:
    def test_defaults(self):
        s = Step(id="1", desc="做点事")
        assert s.tool_hint == ""
        assert s.deps == []
        assert s.status == "PENDING"

    def test_to_dict_roundtrip(self):
        s = Step(id="1", desc="步骤", tool_hint="web_search", deps=["0"], status="DONE")
        d = s.to_dict()
        s2 = Step.from_dict(d)
        assert s2.id == s.id
        assert s2.desc == s.desc
        assert s2.tool_hint == s.tool_hint
        assert s2.deps == s.deps
        assert s2.status == s.status


# ---------------------------------------------------------------------------
# Task 模型
# ---------------------------------------------------------------------------

class TestTask:
    def test_id_auto_generated(self):
        t1 = Task(goal="task1")
        t2 = Task(goal="task2")
        assert t1.id != t2.id

    def test_default_status(self):
        t = Task(goal="test")
        assert t.status == "PENDING"
        assert t.assignee is None
        assert t.worktree is None

    def test_to_dict_roundtrip(self):
        t = Task(goal="写报告", deps=["abc"], assignee="agent-1", result="完成")
        t.status = "DONE"
        d = t.to_dict()
        t2 = Task.from_dict(d)
        assert t2.id == t.id
        assert t2.goal == t.goal
        assert t2.status == "DONE"
        assert t2.assignee == "agent-1"
        assert t2.deps == ["abc"]
        assert t2.result == "完成"

    def test_touch_updates_updated_at(self):
        import time
        t = Task(goal="test")
        before = t.updated_at
        time.sleep(0.01)
        t.touch()
        assert t.updated_at > before

    def test_from_dict_missing_timestamps(self):
        d = {
            "id": "x1",
            "goal": "no timestamps",
            "steps": [],
            "status": "PENDING",
        }
        t = Task.from_dict(d)
        assert t.id == "x1"


# ---------------------------------------------------------------------------
# TaskGraph — DAG 拓扑
# ---------------------------------------------------------------------------

class TestTaskGraph:
    def _make_graph(self):
        g = TaskGraph()
        t1 = Task(goal="task1")
        t1.id = "t1"
        t2 = Task(goal="task2", deps=["t1"])
        t2.id = "t2"
        t3 = Task(goal="task3", deps=["t1", "t2"])
        t3.id = "t3"
        g.add(t1)
        g.add(t2)
        g.add(t3)
        return g, t1, t2, t3

    def test_add_and_get(self):
        g, t1, _, _ = self._make_graph()
        assert g.get("t1") is t1
        assert g.get("missing") is None

    def test_ready_tasks_no_deps(self):
        g, t1, t2, t3 = self._make_graph()
        ready = g.ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == "t1"

    def test_ready_tasks_after_completing_dep(self):
        g, t1, t2, t3 = self._make_graph()
        t1.status = "DONE"
        ready = g.ready_tasks()
        ids = {t.id for t in ready}
        assert "t2" in ids
        assert "t3" not in ids  # t3 still depends on t2

    def test_topological_order(self):
        g, t1, t2, t3 = self._make_graph()
        order = g.topological_order()
        ids = [t.id for t in order]
        assert ids.index("t1") < ids.index("t2")
        assert ids.index("t2") < ids.index("t3")

    def test_cycle_detection(self):
        g = TaskGraph()
        a = Task(goal="a")
        a.id = "a"
        b = Task(goal="b", deps=["a"])
        b.id = "b"
        a.deps = ["b"]  # 制造循环
        g.add(a)
        g.add(b)
        assert g.has_cycle() is True

    def test_no_cycle(self):
        g, *_ = self._make_graph()
        assert g.has_cycle() is False

    def test_topological_raises_on_cycle(self):
        g = TaskGraph()
        a = Task(goal="a")
        a.id = "a"
        a.deps = ["a"]  # 自环
        g.add(a)
        with pytest.raises(ValueError, match="Circular"):
            g.topological_order()

    def test_all_tasks(self):
        g, t1, t2, t3 = self._make_graph()
        assert len(g.all_tasks()) == 3
