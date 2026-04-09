"""
teams/team.py — 持久化 Agent 团队 (s15)

AgentTeam 封装团队成员、角色和共享规则。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class TeamMember:
    """团队成员描述。"""
    agent_id: str
    role: str                       # 如 "researcher" / "coder" / "reviewer"
    capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"agent_id": self.agent_id, "role": self.role, "capabilities": self.capabilities}

    @classmethod
    def from_dict(cls, d: dict) -> "TeamMember":
        return cls(agent_id=d["agent_id"], role=d["role"], capabilities=d.get("capabilities", []))


@dataclass
class AgentTeam:
    """
    持久化 Agent 团队。

    team_id:          唯一标识
    name:             团队名称
    members:          成员列表
    shared_rules:     所有成员遵守的协调规则（自然语言描述）
    shared_memory_ns: 团队共享记忆命名空间
    created_at:       创建时间
    """
    name: str
    team_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    members: list[TeamMember] = field(default_factory=list)
    shared_rules: list[str] = field(default_factory=list)
    shared_memory_ns: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        if not self.shared_memory_ns:
            self.shared_memory_ns = f"team:{self.team_id}"

    def add_member(self, agent_id: str, role: str, capabilities: list[str] | None = None) -> TeamMember:
        """添加成员（已存在则更新）。"""
        self.remove_member(agent_id)
        m = TeamMember(agent_id=agent_id, role=role, capabilities=capabilities or [])
        self.members.append(m)
        return m

    def remove_member(self, agent_id: str) -> bool:
        before = len(self.members)
        self.members = [m for m in self.members if m.agent_id != agent_id]
        return len(self.members) < before

    def get_member(self, agent_id: str) -> TeamMember | None:
        return next((m for m in self.members if m.agent_id == agent_id), None)

    def members_with_role(self, role: str) -> list[TeamMember]:
        return [m for m in self.members if m.role == role]

    def members_with_capability(self, cap: str) -> list[TeamMember]:
        return [m for m in self.members if cap in m.capabilities]

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "members": [m.to_dict() for m in self.members],
            "shared_rules": self.shared_rules,
            "shared_memory_ns": self.shared_memory_ns,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentTeam":
        t = cls(
            team_id=d["team_id"],
            name=d["name"],
            shared_rules=d.get("shared_rules", []),
            shared_memory_ns=d.get("shared_memory_ns", ""),
            created_at=datetime.fromisoformat(d["created_at"]) if "created_at" in d else datetime.utcnow(),
        )
        t.members = [TeamMember.from_dict(m) for m in d.get("members", [])]
        return t
