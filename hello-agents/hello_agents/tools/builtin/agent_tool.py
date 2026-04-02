"""
tools/builtin/agent_tool.py — Agent 间通信工具 (s09/s10)

send_to_agent  : 向另一个 Agent 发送请求
read_mailbox   : 读取自己邮箱中的消息
list_agents    : 列出所有已注册的协作 Agent
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hello_agents.multi_agent.mailbox import Mailbox
from hello_agents.multi_agent.protocol import AgentMessage
from hello_agents.multi_agent.registry import get_registry

logger = logging.getLogger(__name__)

AGENT_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "send_to_agent",
            "description": "向另一个 Agent 发送请求消息，请求其执行某个任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_agent": {
                        "type": "string",
                        "description": "目标 Agent 的 agent_id",
                    },
                    "content": {
                        "type": "string",
                        "description": "请求内容",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "关联的任务 ID（可选）",
                    },
                },
                "required": ["to_agent", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_mailbox",
            "description": "读取当前 Agent 邮箱中的下一条消息（来自其他 Agent 的回复或通知）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "当前 Agent 的 ID",
                    },
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": "列出当前已注册的所有协作 Agent 及其专长。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


class AgentToolHandler:
    """
    处理 Agent 间通信相关的 tool_call。(s02)

    dispatch 是同步的（符合 ToolRegistry 约定），
    内部通过 Mailbox 的 sync API 操作 SQLite。
    """

    TOOL_NAMES = {"send_to_agent", "read_mailbox", "list_agents"}

    def __init__(
        self,
        from_agent_id: str,
        mailbox: Mailbox | None = None,
    ) -> None:
        self._from_agent = from_agent_id
        self._mailbox = mailbox or Mailbox()

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON arguments"})

        try:
            if name == "send_to_agent":
                return self._send_to_agent(**args)
            elif name == "read_mailbox":
                return self._read_mailbox(**args)
            elif name == "list_agents":
                return self._list_agents()
            else:
                return json.dumps({"error": f"Unknown agent tool: {name}"})
        except Exception as exc:
            logger.exception("AgentTool error in %s: %s", name, exc)
            return json.dumps({"error": str(exc)})

    def _send_to_agent(
        self, to_agent: str, content: str, task_id: str | None = None
    ) -> str:
        payload: dict[str, Any] = {"content": content}
        if task_id:
            payload["task_id"] = task_id

        msg = AgentMessage(
            from_agent=self._from_agent,
            to_agent=to_agent,
            msg_type="request",
            payload=payload,
        )
        self._mailbox.send_sync(to_agent, msg)
        return json.dumps(
            {"status": "sent", "msg_id": msg.msg_id, "to": to_agent},
            ensure_ascii=False,
        )

    def _read_mailbox(self, agent_id: str) -> str:
        count = self._mailbox.pending_count(agent_id)
        if count == 0:
            return json.dumps({"status": "empty", "message": None}, ensure_ascii=False)

        msg = self._mailbox.recv_sync(agent_id)
        if msg is None:
            return json.dumps({"status": "empty", "message": None}, ensure_ascii=False)

        return json.dumps(
            {
                "status": "received",
                "message": {
                    "msg_id": msg.msg_id,
                    "from": msg.from_agent,
                    "type": msg.msg_type,
                    "payload": msg.payload,
                },
            },
            ensure_ascii=False,
        )

    def _list_agents(self) -> str:
        agents = get_registry().list_agents()
        items = [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "speciality": a.speciality,
            }
            for a in agents
        ]
        return json.dumps({"agents": items, "count": len(items)}, ensure_ascii=False)
