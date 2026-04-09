"""
teams/autonomous.py — 自治 Agent (s17)

自认领 + 心跳检测 + 断点续跑。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.tasks.kanban import Kanban
    from hello_agents.subagent.runner import SubAgentRunner
    from hello_agents.recovery.checkpoint import CheckpointStore

logger = logging.getLogger(__name__)


class AutonomousAgent:
    """
    自治 Agent：事件驱动认领 + 心跳 + 断点续跑。

    用法：
        agent = AutonomousAgent(
            agent_id="alice",
            kanban=kanban,
            runner=runner,
            checkpoint_store=checkpoint_store,
        )
        asyncio.create_task(agent.run())
        agent.stop()
    """

    def __init__(
        self,
        agent_id: str,
        kanban: "Kanban",
        runner: "SubAgentRunner",
        checkpoint_store: "CheckpointStore | None" = None,
        heartbeat_interval: int = 30,
        task_timeout: int = 600,
        poll_interval: float = 2.0,
    ) -> None:
        self.agent_id = agent_id
        self._kanban = kanban
        self._runner = runner
        self._checkpoint = checkpoint_store
        self.heartbeat_interval = heartbeat_interval
        self.task_timeout = task_timeout
        self._poll_interval = poll_interval
        self._running = False
        self._last_heartbeat: datetime | None = None

    async def run(self) -> None:
        """主循环：并发运行任务认领 + 心跳协程。"""
        self._running = True
        logger.info("AutonomousAgent %s started", self.agent_id)
        await asyncio.gather(
            self._claim_loop(),
            self._heartbeat_loop(),
            return_exceptions=True,
        )

    def stop(self) -> None:
        self._running = False

    async def resume(self, task_id: str) -> str | None:
        """从 CheckpointStore 恢复未完成任务并继续执行。"""
        if not self._checkpoint:
            logger.warning("No checkpoint store configured")
            return None
        restored = self._checkpoint.load(task_id)
        if not restored:
            logger.warning("No checkpoint found for task %s", task_id)
            return None
        messages, step_idx = restored
        logger.info(
            "Resuming task %s from step %d (%d messages)",
            task_id, step_idx, len(messages),
        )
        # 找到对应任务并继续执行
        task = next(
            (t for t in self._kanban.all_tasks() if t.id == task_id), None
        )
        if task is None:
            return None
        try:
            result = await self._runner.run(
                task.goal,
                context_hint=f"Resuming from step {step_idx}. Prior messages: {len(messages)}",
            )
            self._kanban.complete(task_id, result)
            if self._checkpoint:
                self._checkpoint.delete(task_id)
            return result
        except Exception as exc:
            logger.exception("Resume failed for %s: %s", task_id, exc)
            self._kanban.fail(task_id, str(exc))
            return None

    async def _claim_loop(self) -> None:
        while self._running:
            task = self._kanban.claim(self.agent_id)
            if task:
                logger.info("AutonomousAgent %s claimed task %s", self.agent_id, task.id)
                try:
                    # 保存检查点（供崩溃续跑）
                    if self._checkpoint:
                        self._checkpoint.save(task.id, [], step_idx=0)
                    result = await asyncio.wait_for(
                        self._runner.run(task.goal),
                        timeout=self.task_timeout,
                    )
                    self._kanban.complete(task.id, result)
                    if self._checkpoint:
                        self._checkpoint.delete(task.id)
                    logger.info("AutonomousAgent %s completed task %s", self.agent_id, task.id)
                except asyncio.TimeoutError:
                    logger.warning("Task %s timed out", task.id)
                    self._kanban.fail(task.id, "timeout")
                except Exception as exc:
                    logger.exception("Task %s failed: %s", task.id, exc)
                    self._kanban.fail(task.id, str(exc))
            else:
                await asyncio.sleep(self._poll_interval)

    async def _heartbeat_loop(self) -> None:
        """每 heartbeat_interval 秒更新 last_seen。"""
        while self._running:
            self._last_heartbeat = datetime.utcnow()
            # 通知 kanban 更新 IN_PROGRESS 任务的 last_seen
            for task in self._kanban.in_progress():
                if task.assignee == self.agent_id:
                    self._kanban.touch(task.id, self.agent_id)
            await asyncio.sleep(self.heartbeat_interval)
