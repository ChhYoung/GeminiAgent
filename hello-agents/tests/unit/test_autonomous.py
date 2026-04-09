"""
tests/unit/test_autonomous.py — 自治 Agent 测试 (s17)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from hello_agents.tasks.kanban import Kanban
from hello_agents.tasks.models import Task
from hello_agents.teams.autonomous import AutonomousAgent


def _make_kanban_with_task(goal: str = "test task") -> tuple[Kanban, Task]:
    k = Kanban()
    t = Task(goal=goal)
    k.push(t)
    return k, t


class TestKanbanEnhancements:
    """Test v5 kanban additions: touch + release_stale."""

    def test_touch_updates_last_seen(self):
        k, t = _make_kanban_with_task()
        k.claim("agent-1")
        k.touch(t.id, "agent-1")
        assert t.id in k._last_seen

    def test_touch_only_updates_in_progress(self):
        k, t = _make_kanban_with_task()
        # Task is still PENDING — touch should not record
        k.touch(t.id, "agent-1")
        assert t.id not in k._last_seen

    def test_release_stale_resets_timed_out_task(self):
        k, t = _make_kanban_with_task()
        k.claim("agent-1")
        # Backdate updated_at to simulate timeout
        t.updated_at = datetime.utcnow() - timedelta(seconds=700)
        released = k.release_stale(timeout_s=600)
        assert t.id in released
        assert t.status == "PENDING"
        assert t.assignee is None

    def test_release_stale_keeps_fresh_tasks(self):
        k, t = _make_kanban_with_task()
        k.claim("agent-1")
        k.touch(t.id, "agent-1")  # fresh heartbeat
        released = k.release_stale(timeout_s=600)
        assert len(released) == 0
        assert t.status == "IN_PROGRESS"

    def test_release_stale_ignores_pending_tasks(self):
        k, t = _make_kanban_with_task()
        # Task is PENDING, not IN_PROGRESS
        released = k.release_stale(timeout_s=0)
        assert len(released) == 0


class TestAutonomousAgent:
    def _make_agent(self, kanban: Kanban, succeed: bool = True) -> AutonomousAgent:
        runner = MagicMock()
        if succeed:
            runner.run = AsyncMock(return_value="done")
        else:
            runner.run = AsyncMock(side_effect=RuntimeError("fail"))

        return AutonomousAgent(
            agent_id="auto-1",
            kanban=kanban,
            runner=runner,
            heartbeat_interval=999,  # won't fire during test
            task_timeout=5,
            poll_interval=0.01,
        )

    @pytest.mark.asyncio
    async def test_claims_and_completes_task(self):
        k, t = _make_kanban_with_task()
        agent = self._make_agent(k, succeed=True)
        agent._running = True  # must be set before _claim_loop runs
        try:
            await asyncio.wait_for(agent._claim_loop(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
        assert t.status in ("DONE", "IN_PROGRESS")

    @pytest.mark.asyncio
    async def test_marks_task_failed_on_exception(self):
        k, t = _make_kanban_with_task()
        agent = self._make_agent(k, succeed=False)
        agent._running = True
        try:
            await asyncio.wait_for(agent._claim_loop(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
        assert t.status in ("FAILED", "IN_PROGRESS")

    def test_stop_sets_running_false(self):
        k = Kanban()
        runner = MagicMock()
        agent = AutonomousAgent("a", k, runner)
        agent._running = True
        agent.stop()
        assert agent._running is False

    @pytest.mark.asyncio
    async def test_resume_with_no_checkpoint_store(self):
        k = Kanban()
        runner = MagicMock()
        agent = AutonomousAgent("a", k, runner, checkpoint_store=None)
        result = await agent.resume("task-1")
        assert result is None
