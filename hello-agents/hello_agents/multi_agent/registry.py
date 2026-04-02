"""
multi_agent/registry.py — PeerAgent 全局注册表
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.multi_agent.peer import PeerAgent


class AgentRegistry:
    """已知 PeerAgent 的全局注册表。"""

    def __init__(self) -> None:
        self._agents: dict[str, "PeerAgent"] = {}

    def register(self, agent: "PeerAgent") -> None:
        self._agents[agent.agent_id] = agent

    def get(self, agent_id: str) -> "PeerAgent | None":
        return self._agents.get(agent_id)

    def list_agents(self) -> list["PeerAgent"]:
        return list(self._agents.values())

    def unregister(self, agent_id: str) -> bool:
        return self._agents.pop(agent_id, None) is not None


# 进程级单例
_registry = AgentRegistry()


def get_registry() -> AgentRegistry:
    return _registry
