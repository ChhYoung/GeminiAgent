"""
multi_agent/peer.py — 持久化 PeerAgent 配置 (s09)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PeerAgent:
    """
    协作 Agent 的配置描述。

    speciality 告诉主 agent 这个队友擅长什么（用于路由决策），
    tool_names 限制该 agent 可使用的工具集合。
    """

    agent_id: str
    name: str
    speciality: str
    system_prompt: str
    tool_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "speciality": self.speciality,
            "system_prompt": self.system_prompt,
            "tool_names": self.tool_names,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PeerAgent":
        return cls(
            agent_id=d["agent_id"],
            name=d["name"],
            speciality=d["speciality"],
            system_prompt=d["system_prompt"],
            tool_names=d.get("tool_names", []),
        )
