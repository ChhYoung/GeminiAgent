"""
multi_agent/protocol.py — Agent 间统一消息协议 (s10)

所有跨 agent 通信强制通过 AgentMessage 格式，
correlation_id 将 response 和 request 关联起来。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

MessageType = Literal["request", "response", "event", "broadcast", "vote", "vote_reply", "delegate"]


@dataclass
class AgentMessage:
    """
    Agent 间通信的标准消息格式。

    字段：
        msg_id:         消息唯一 ID
        msg_type:       request / response / event
        from_agent:     发送方 agent_id
        to_agent:       接收方 agent_id
        correlation_id: response 指向对应 request 的 msg_id
        payload:        业务数据 {"content": ..., "task_id": ..., ...}
        created_at:     创建时间
    """

    from_agent: str
    to_agent: str
    payload: dict[str, Any]
    msg_type: MessageType = "request"
    msg_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    correlation_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentMessage":
        return cls(
            msg_id=d["msg_id"],
            msg_type=d["msg_type"],
            from_agent=d["from_agent"],
            to_agent=d["to_agent"],
            correlation_id=d.get("correlation_id"),
            payload=d.get("payload", {}),
            created_at=(
                datetime.fromisoformat(d["created_at"])
                if "created_at" in d
                else datetime.utcnow()
            ),
        )

    def make_response(
        self, from_agent: str, payload: dict[str, Any]
    ) -> "AgentMessage":
        """创建对应的 response 消息（correlation_id 指向本消息）。"""
        return AgentMessage(
            from_agent=from_agent,
            to_agent=self.from_agent,
            msg_type="response",
            correlation_id=self.msg_id,
            payload=payload,
        )
