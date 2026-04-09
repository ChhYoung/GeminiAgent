"""
teams/coordinator.py — 团队协调器 (s16)

负责任务分发、广播和简单仲裁投票。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from hello_agents.multi_agent.mailbox import Mailbox
from hello_agents.multi_agent.protocol import AgentMessage

if TYPE_CHECKING:
    from hello_agents.teams.team import AgentTeam

logger = logging.getLogger(__name__)


class TeamCoordinator:
    """
    团队协调器。

    用法：
        coordinator = TeamCoordinator(mailbox=Mailbox())
        await coordinator.broadcast(team, "开始执行任务 X", from_agent="lead")
        result = await coordinator.vote(team, "是否继续？", ["yes", "no"], from_agent="lead")
    """

    def __init__(self, mailbox: Mailbox) -> None:
        self._mailbox = mailbox

    async def broadcast(
        self,
        team: "AgentTeam",
        content: str,
        from_agent: str,
    ) -> None:
        """向团队所有成员发送广播消息。"""
        for member in team.members:
            if member.agent_id == from_agent:
                continue
            msg = AgentMessage(
                from_agent=from_agent,
                to_agent=member.agent_id,
                msg_type="broadcast",
                payload={"content": content, "team_id": team.team_id},
            )
            await asyncio.to_thread(self._mailbox.send_sync, msg.to_agent, msg)
        logger.info("Broadcast sent to %d members of team %s", len(team.members) - 1, team.team_id)

    async def vote(
        self,
        team: "AgentTeam",
        question: str,
        options: list[str],
        from_agent: str,
        timeout: float = 5.0,
    ) -> dict[str, int]:
        """
        发起投票，等待成员回复（简化版：伪收集，实际异步超时）。

        Returns:
            {option: count} 票数统计
        """
        # 发送投票消息
        for member in team.members:
            if member.agent_id == from_agent:
                continue
            msg = AgentMessage(
                from_agent=from_agent,
                to_agent=member.agent_id,
                msg_type="vote",
                payload={"question": question, "options": options, "team_id": team.team_id},
            )
            await asyncio.to_thread(self._mailbox.send_sync, msg.to_agent, msg)

        # 等待 timeout 收集回复（简化：只统计已在收件箱的 vote_reply）
        await asyncio.sleep(min(timeout, 1.0))  # 最多等 1s（测试友好）

        votes: dict[str, int] = {opt: 0 for opt in options}
        replies = await asyncio.to_thread(self._mailbox.read_all, from_agent)  # type: ignore[attr-defined]
        for reply in replies:
            if reply.msg_type == "vote_reply" and "vote" in reply.payload:
                opt = reply.payload["vote"]
                if opt in votes:
                    votes[opt] += 1

        logger.info("Vote result for '%s': %s", question, votes)
        return votes

    async def delegate(
        self,
        to_agent: str,
        task_desc: str,
        from_agent: str,
        expected_format: str = "",
    ) -> str:
        """委托任务给指定成员（发送 DELEGATE 消息），返回 msg_id。"""
        msg = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            msg_type="delegate",
            payload={
                "task_desc": task_desc,
                "expected_format": expected_format,
            },
        )
        await asyncio.to_thread(self._mailbox.send_sync, msg.to_agent, msg)
        logger.info("Delegated task to %s: %s", to_agent, task_desc[:50])
        return msg.msg_id
