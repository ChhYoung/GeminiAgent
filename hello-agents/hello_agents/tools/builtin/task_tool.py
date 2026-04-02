"""
tools/builtin/task_tool.py — 任务管理工具 (s07)

让 Agent 自主创建、查询、更新任务图中的任务。
注册到 ToolRegistry 后，通过 Function Calling 触发。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hello_agents.tasks.models import Task
from hello_agents.tasks.scheduler import Scheduler

logger = logging.getLogger(__name__)

TASK_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": (
                "创建一个新任务并加入任务图（持久化到磁盘）。"
                "可以指定依赖其他任务，形成有序执行链。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "任务目标描述",
                    },
                    "deps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "依赖的任务 ID 列表（这些任务完成后才能执行本任务）",
                    },
                },
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "查看任务列表，可按状态过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["PENDING", "IN_PROGRESS", "DONE", "FAILED", "all"],
                        "description": "过滤状态，默认 all",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_status",
            "description": "更新任务状态（如标记为 DONE 或 FAILED）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "任务 ID",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["IN_PROGRESS", "DONE", "FAILED"],
                        "description": "新状态",
                    },
                    "result": {
                        "type": "string",
                        "description": "任务结果或失败原因（可选）",
                    },
                },
                "required": ["task_id", "status"],
            },
        },
    },
]


class TaskToolHandler:
    """处理任务管理相关的 tool_call。(s02)"""

    TOOL_NAMES = {"create_task", "list_tasks", "update_task_status"}

    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON arguments"})

        try:
            if name == "create_task":
                return self._create_task(**args)
            elif name == "list_tasks":
                return self._list_tasks(**args)
            elif name == "update_task_status":
                return self._update_task_status(**args)
            else:
                return json.dumps({"error": f"Unknown task tool: {name}"})
        except Exception as exc:
            logger.exception("TaskTool error in %s: %s", name, exc)
            return json.dumps({"error": str(exc)})

    def _create_task(self, goal: str, deps: list[str] | None = None) -> str:
        task = Task(goal=goal, deps=deps or [])
        self._scheduler.add(task)
        return json.dumps(
            {"status": "created", "task_id": task.id, "goal": goal},
            ensure_ascii=False,
        )

    def _list_tasks(self, status: str = "all") -> str:
        tasks = self._scheduler.all_tasks()
        if status != "all":
            tasks = [t for t in tasks if t.status == status]
        items = [
            {
                "id": t.id,
                "goal": t.goal[:80],
                "status": t.status,
                "assignee": t.assignee,
            }
            for t in tasks
        ]
        return json.dumps({"tasks": items, "count": len(items)}, ensure_ascii=False)

    def _update_task_status(
        self, task_id: str, status: str, result: str | None = None
    ) -> str:
        ok = self._scheduler.update_status(task_id, status, result)
        if ok:
            return json.dumps(
                {"status": "updated", "task_id": task_id, "new_status": status},
                ensure_ascii=False,
            )
        return json.dumps(
            {"error": f"Task {task_id} not found"}, ensure_ascii=False
        )
