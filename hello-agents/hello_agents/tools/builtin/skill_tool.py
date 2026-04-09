"""
tools/builtin/skill_tool.py — 技能激活工具 (s05)
"""

from __future__ import annotations

import json
from typing import Any

from hello_agents.skills.registry import SkillRegistry

SKILL_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "activate_skill",
            "description": "激活指定专项技能，获取专项 prompt 和相关工具列表",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "技能名称，如 coding / research"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "列出所有可用技能",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class SkillToolHandler:
    TOOL_NAMES = {"activate_skill", "list_skills"}

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        args: dict = json.loads(tool_call.function.arguments or "{}")
        if name == "activate_skill":
            return self._activate(args)
        if name == "list_skills":
            return self._list()
        return json.dumps({"error": f"Unknown skill tool: {name}"})

    def _activate(self, args: dict) -> str:
        skill = self._registry.activate(args["name"])
        if skill is None:
            return json.dumps({"error": f"Skill '{args['name']}' not found"})
        return json.dumps({
            "name": skill.name,
            "prompt_snippet": skill.prompt_snippet,
            "tools": skill.tools,
        })

    def _list(self) -> str:
        names = self._registry.list_available()
        return json.dumps({"skills": names})
