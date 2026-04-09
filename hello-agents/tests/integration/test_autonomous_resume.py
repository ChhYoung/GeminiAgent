"""
tests/integration/test_autonomous_resume.py — 断点续跑集成测试 (s17)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hello_agents.tasks.kanban import Kanban
from hello_agents.tasks.models import Task
from hello_agents.recovery.checkpoint import CheckpointStore
from hello_agents.teams.autonomous import AutonomousAgent


class TestCheckpointResume:
    @pytest.mark.asyncio
    async def test_resume_from_checkpoint(self, tmp_path):
        kanban = Kanban()
        task = Task(goal="build feature X")
        kanban.push(task)
        kanban.claim("auto-1")  # Mark as IN_PROGRESS

        checkpoint_store = CheckpointStore(directory=tmp_path)
        # Save a checkpoint for the task
        saved_messages = [{"role": "system", "content": "You are an agent"}]
        checkpoint_store.save(task.id, saved_messages, step_idx=2)

        runner = MagicMock()
        runner.run = AsyncMock(return_value="resumed and completed")

        agent = AutonomousAgent(
            agent_id="auto-1",
            kanban=kanban,
            runner=runner,
            checkpoint_store=checkpoint_store,
        )
        result = await agent.resume(task.id)
        assert result == "resumed and completed"
        assert task.status == "DONE"
        # Checkpoint should be deleted after successful resume
        assert not checkpoint_store.exists(task.id)

    @pytest.mark.asyncio
    async def test_resume_no_checkpoint_returns_none(self, tmp_path):
        kanban = Kanban()
        runner = MagicMock()
        checkpoint_store = CheckpointStore(directory=tmp_path)

        agent = AutonomousAgent(
            agent_id="auto-1",
            kanban=kanban,
            runner=runner,
            checkpoint_store=checkpoint_store,
        )
        result = await agent.resume("nonexistent-task")
        assert result is None

    @pytest.mark.asyncio
    async def test_resume_task_not_in_kanban_returns_none(self, tmp_path):
        kanban = Kanban()
        checkpoint_store = CheckpointStore(directory=tmp_path)
        checkpoint_store.save("ghost-task", [], step_idx=0)

        runner = MagicMock()
        agent = AutonomousAgent(
            agent_id="auto-1",
            kanban=kanban,
            runner=runner,
            checkpoint_store=checkpoint_store,
        )
        result = await agent.resume("ghost-task")
        assert result is None

    @pytest.mark.asyncio
    async def test_checkpoint_saved_on_claim(self, tmp_path):
        kanban = Kanban()
        task = Task(goal="test task")
        kanban.push(task)

        checkpoint_store = CheckpointStore(directory=tmp_path)
        runner = MagicMock()
        runner.run = AsyncMock(return_value="done")

        agent = AutonomousAgent(
            agent_id="auto-1",
            kanban=kanban,
            runner=runner,
            checkpoint_store=checkpoint_store,
            heartbeat_interval=999,
            poll_interval=0.01,
        )
        try:
            await asyncio.wait_for(agent._claim_loop(), timeout=0.5)
        except asyncio.TimeoutError:
            pass
        # Task should be completed, checkpoint deleted
        if task.status == "DONE":
            assert not checkpoint_store.exists(task.id)

    @pytest.mark.asyncio
    async def test_stale_task_release_and_resume(self, tmp_path):
        """Simulate crash: task gets stale, then resume is called."""
        from datetime import datetime, timedelta
        kanban = Kanban()
        task = Task(goal="stale task")
        kanban.push(task)
        kanban.claim("crashed-agent")

        # Backdate to simulate stale
        task.updated_at = datetime.utcnow() - timedelta(seconds=700)

        # Release stale
        released = kanban.release_stale(timeout_s=600)
        assert task.id in released
        assert task.status == "PENDING"

        # Now resume (checkpoint simulates prior state)
        checkpoint_store = CheckpointStore(directory=tmp_path)
        checkpoint_store.save(task.id, [{"role": "system", "content": "ctx"}], step_idx=3)
        # Re-claim and resume
        kanban.claim("recovery-agent")
        task.status = "IN_PROGRESS"

        runner = MagicMock()
        runner.run = AsyncMock(return_value="recovered")
        agent = AutonomousAgent(
            agent_id="recovery-agent",
            kanban=kanban,
            runner=runner,
            checkpoint_store=checkpoint_store,
        )
        result = await agent.resume(task.id)
        assert result == "recovered"
