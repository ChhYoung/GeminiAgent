"""
tasks/models.py — 任务数据模型 (s07)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

TaskStatus = Literal["PENDING", "IN_PROGRESS", "DONE", "FAILED"]


@dataclass
class Step:
    """任务内的单个执行步骤。"""

    id: str
    desc: str
    tool_hint: str = ""
    deps: list[str] = field(default_factory=list)
    status: TaskStatus = "PENDING"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "desc": self.desc,
            "tool_hint": self.tool_hint,
            "deps": self.deps,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        return cls(
            id=d["id"],
            desc=d["desc"],
            tool_hint=d.get("tool_hint", ""),
            deps=d.get("deps", []),
            status=d.get("status", "PENDING"),
        )


@dataclass
class Task:
    """持久化任务单元。"""

    goal: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    steps: list[Step] = field(default_factory=list)
    status: TaskStatus = "PENDING"
    assignee: str | None = None
    deps: list[str] = field(default_factory=list)
    worktree: str | None = None
    result: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "assignee": self.assignee,
            "deps": self.deps,
            "worktree": self.worktree,
            "result": self.result,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=d["id"],
            goal=d["goal"],
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            status=d.get("status", "PENDING"),
            assignee=d.get("assignee"),
            deps=d.get("deps", []),
            worktree=d.get("worktree"),
            result=d.get("result"),
            created_at=(
                datetime.fromisoformat(d["created_at"])
                if "created_at" in d
                else datetime.utcnow()
            ),
            updated_at=(
                datetime.fromisoformat(d["updated_at"])
                if "updated_at" in d
                else datetime.utcnow()
            ),
        )

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()
