"""
tools/builtin/cron_tool.py — Cron 管理工具 (s14)
"""

from __future__ import annotations

import json
from typing import Any

from hello_agents.tasks.cron import CronScheduler

CRON_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "add_cron",
            "description": "添加一条定时任务（标准 5 字段 cron 表达式：分 时 日 月 周）",
            "parameters": {
                "type": "object",
                "properties": {
                    "cron_expr": {"type": "string", "description": "Cron 表达式，如 '0 9 * * 1-5'"},
                    "tool_name": {"type": "string", "description": "定时触发的工具名"},
                    "args": {"type": "object", "description": "工具参数"},
                },
                "required": ["cron_expr", "tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_crons",
            "description": "列出所有已注册的 Cron 任务",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_cron",
            "description": "删除指定 Cron 任务",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
            },
        },
    },
]


class CronToolHandler:
    TOOL_NAMES = {"add_cron", "list_crons", "remove_cron"}

    def __init__(self, scheduler: CronScheduler) -> None:
        self._scheduler = scheduler

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        args: dict = json.loads(tool_call.function.arguments or "{}")
        if name == "add_cron":
            return self._add(args)
        if name == "list_crons":
            return self._list()
        if name == "remove_cron":
            return self._remove(args)
        return json.dumps({"error": f"Unknown cron tool: {name}"})

    def _add(self, args: dict) -> str:
        job_id = self._scheduler.add_job(
            cron_expr=args["cron_expr"],
            tool_name=args["tool_name"],
            args=args.get("args", {}),
        )
        return json.dumps({"job_id": job_id, "status": "registered"})

    def _list(self) -> str:
        jobs = [j.to_dict() for j in self._scheduler.list_jobs()]
        return json.dumps({"jobs": jobs, "count": len(jobs)})

    def _remove(self, args: dict) -> str:
        ok = self._scheduler.remove_job(args["job_id"])
        return json.dumps({"removed": ok})
