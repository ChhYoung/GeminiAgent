"""
multi_agent/worker.py — WorkerAgent (s11)

自主轮询看板，认领可用任务，完成后通知。
无需中心调度器，支持横向扩展（多个 WorkerAgent 实例并发认领）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.tasks.kanban import Kanban
    from hello_agents.subagent.runner import SubAgentRunner

logger = logging.getLogger(__name__)


class WorkerAgent:
    """
    自组织工作 Agent。(s11)

    用法：
        worker = WorkerAgent(agent_id="w1", kanban=kanban, runner=runner)
        task = asyncio.create_task(worker.run_forever())
        # ... 等待 worker 完成任务 ...
        worker.stop()
    """

    def __init__(
        self,
        agent_id: str,
        kanban: "Kanban",
        runner: "SubAgentRunner",
        poll_interval: float = 2.0,
    ) -> None:
        self.agent_id = agent_id
        self._kanban = kanban
        self._runner = runner
        self._poll_interval = poll_interval
        self._running = False

    async def run_forever(self) -> None:
        """
        无限轮询看板：认领 → 执行（SubAgentRunner）→ 完成/失败。

        通过 stop() 优雅退出。
        """
        self._running = True
        logger.info("WorkerAgent %s started", self.agent_id)
        while self._running:
            task = self._kanban.claim(self.agent_id)
            if task:
                logger.info(
                    "WorkerAgent %s claimed task %s", self.agent_id, task.id
                )
                try:
                    result = await self._runner.run(task.goal)
                    self._kanban.complete(task.id, result)
                    logger.info(
                        "WorkerAgent %s completed task %s", self.agent_id, task.id
                    )
                except Exception as exc:
                    logger.exception(
                        "WorkerAgent %s failed task %s: %s",
                        self.agent_id,
                        task.id,
                        exc,
                    )
                    self._kanban.fail(task.id, str(exc))
            else:
                await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        """设置停止标志，run_forever 在下次轮询后退出。"""
        self._running = False
