"""
tools/builtin/background_tool.py — 后台执行工具 (s08)

慢操作丢后台，agent 继续想下一步。
run_background 立即返回 job_id；poll_background 查询结果。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from hello_agents.tasks.background import BackgroundExecutor

logger = logging.getLogger(__name__)

BACKGROUND_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "run_background",
            "description": (
                "在后台线程执行耗时的 shell 命令，立即返回 job_id。"
                "使用 poll_background(job_id) 查询执行结果。"
                "适合耗时 > 3 秒的操作，让 agent 继续其他工作。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，默认 60",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "poll_background",
            "description": "查询后台任务的执行状态和结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "run_background 返回的 job_id",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
]


class BackgroundToolHandler:
    """处理后台执行相关的 tool_call。(s02)"""

    TOOL_NAMES = {"run_background", "poll_background"}

    def __init__(self, executor: BackgroundExecutor | None = None) -> None:
        self._executor = executor or BackgroundExecutor()

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON arguments"})

        try:
            if name == "run_background":
                return self._run_background(**args)
            elif name == "poll_background":
                return self._poll_background(**args)
            else:
                return json.dumps({"error": f"Unknown background tool: {name}"})
        except Exception as exc:
            logger.exception("BackgroundTool error in %s: %s", name, exc)
            return json.dumps({"error": str(exc)})

    def _run_background(self, command: str, timeout: int = 60) -> str:
        job_id = self._executor.submit_command(command, timeout=timeout)
        return json.dumps(
            {"job_id": job_id, "status": "submitted"}, ensure_ascii=False
        )

    def _poll_background(self, job_id: str) -> str:
        result = self._executor.poll(job_id)
        return json.dumps(result, ensure_ascii=False)
