"""
tools/builtin/team_tool.py — 团队管理工具 (s15/s16)
"""

from __future__ import annotations

import json
from typing import Any

from hello_agents.teams.roster import TeamRoster

TEAM_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "form_team",
            "description": "创建一支 Agent 团队",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "团队名称"},
                    "members": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent_id": {"type": "string"},
                                "role": {"type": "string"},
                            },
                        },
                        "description": "成员列表",
                    },
                    "shared_rules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "团队协调规则",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_teams",
            "description": "列出所有团队",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dissolve_team",
            "description": "解散团队",
            "parameters": {
                "type": "object",
                "properties": {"team_id": {"type": "string"}},
                "required": ["team_id"],
            },
        },
    },
]


class TeamToolHandler:
    TOOL_NAMES = {"form_team", "list_teams", "dissolve_team"}

    def __init__(self, roster: TeamRoster) -> None:
        self._roster = roster

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        args: dict = json.loads(tool_call.function.arguments or "{}")
        if name == "form_team":
            return self._form(args)
        if name == "list_teams":
            return self._list()
        if name == "dissolve_team":
            return self._dissolve(args)
        return json.dumps({"error": f"Unknown team tool: {name}"})

    def _form(self, args: dict) -> str:
        team = self._roster.create(
            name=args["name"],
            members=args.get("members", []),
            shared_rules=args.get("shared_rules", []),
        )
        return json.dumps({"team_id": team.team_id, "name": team.name, "status": "created"})

    def _list(self) -> str:
        teams = [{"team_id": t.team_id, "name": t.name, "members": len(t.members)}
                 for t in self._roster.list_teams()]
        return json.dumps({"teams": teams})

    def _dissolve(self, args: dict) -> str:
        ok = self._roster.dissolve(args["team_id"])
        return json.dumps({"dissolved": ok})
