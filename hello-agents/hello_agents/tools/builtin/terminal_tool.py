"""
tools/builtin/terminal_tool.py — 终端/文件系统工具

赋予 Agent 刺探系统状态和读取本地文件的能力：
- run_command    : 执行白名单命令（ls/cat/pwd/find/grep/head/tail/echo/python3 -c）
- read_file      : 读取文件内容
- list_directory : 列出目录内容

安全措施：
- 命令白名单（拦截 rm/sudo/curl/wget/chmod 等危险命令）
- 超时 10 秒
- 输出截断 8000 字符
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import shlex
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_MAX_OUTPUT = 8000

# 允许的命令前缀（小写）
_ALLOWED_COMMANDS = {
    "ls", "cat", "pwd", "find", "grep", "head", "tail", "echo",
    "python3", "python", "wc", "sort", "uniq", "cut", "awk", "sed",
    "date", "whoami", "env", "printenv", "which", "type",
}

# 无论如何都拒绝的关键词
_BLOCKED_PATTERNS = {
    "rm", "rmdir", "sudo", "su", "curl", "wget", "chmod", "chown",
    "kill", "pkill", "killall", "reboot", "shutdown", "poweroff",
    "mkfs", "dd", "fdisk", "mount", "umount", "nc", "ncat", "netcat",
    "ssh", "scp", "sftp", "rsync", "git push", "git commit",
    ">", ">>",  # 重定向写入
    "|&",  # 管道重定向
}


# ------------------------------------------------------------------
# OpenAI tool dict 格式
# ------------------------------------------------------------------

TERMINAL_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "在本地终端执行安全的只读命令（ls/cat/pwd/find/grep/head/tail 等）。"
                "禁止使用 rm/sudo/curl/wget 等危险命令。超时 10 秒，输出截断 8000 字符。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令（仅限白名单命令）",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "工作目录（可选，默认当前目录）",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取本地文件内容（文本文件），超过 8000 字符时自动截断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径（绝对或相对路径）",
                    },
                    "encoding": {
                        "type": "string",
                        "description": "文件编码，默认 utf-8",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出目录内容，返回文件名、大小、修改时间等信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录路径，默认为当前工作目录",
                    },
                    "show_hidden": {
                        "type": "boolean",
                        "description": "是否显示隐藏文件（以.开头），默认 false",
                    },
                },
                "required": [],
            },
        },
    },
]


# ------------------------------------------------------------------
# 工具处理器
# ------------------------------------------------------------------

class TerminalToolHandler:
    """处理终端/文件系统相关 tool_call。"""

    TOOL_NAMES = {"run_command", "read_file", "list_directory"}

    def dispatch(self, tool_call: Any) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON arguments"})

        try:
            if name == "run_command":
                return self._run_command(**args)
            elif name == "read_file":
                return self._read_file(**args)
            elif name == "list_directory":
                return self._list_directory(**args)
            else:
                return json.dumps({"error": f"Unknown terminal tool: {name}"})
        except Exception as exc:
            logger.exception("TerminalTool error in %s: %s", name, exc)
            return json.dumps({"error": str(exc)})

    def _is_safe_command(self, command: str) -> tuple[bool, str]:
        """检查命令是否安全，返回 (is_safe, reason)。"""
        cmd_lower = command.lower().strip()

        # 拦截危险关键词
        for blocked in _BLOCKED_PATTERNS:
            if blocked in cmd_lower:
                return False, f"命令包含被禁止的操作: '{blocked}'"

        # 检查命令是否在白名单中
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return False, f"命令解析失败: {e}"

        if not parts:
            return False, "空命令"

        base_cmd = os.path.basename(parts[0]).lower()
        if base_cmd not in _ALLOWED_COMMANDS:
            return False, f"命令 '{base_cmd}' 不在白名单中"

        return True, ""

    def _run_command(self, command: str, cwd: str | None = None) -> str:
        is_safe, reason = self._is_safe_command(command)
        if not is_safe:
            return json.dumps({"error": f"命令被拦截: {reason}"}, ensure_ascii=False)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                cwd=cwd,
            )
            stdout = result.stdout[:_MAX_OUTPUT]
            stderr = result.stderr[:1000] if result.stderr else ""
            return json.dumps(
                {
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result.returncode,
                    "truncated": len(result.stdout) > _MAX_OUTPUT,
                },
                ensure_ascii=False,
            )
        except subprocess.TimeoutExpired:
            return json.dumps({"error": f"命令超时（{_TIMEOUT}s）"}, ensure_ascii=False)

    def _read_file(self, file_path: str, encoding: str = "utf-8") -> str:
        path = Path(file_path)
        if not path.exists():
            return json.dumps({"error": f"文件不存在: {file_path}"}, ensure_ascii=False)
        if not path.is_file():
            return json.dumps({"error": f"路径不是文件: {file_path}"}, ensure_ascii=False)

        try:
            content = path.read_text(encoding=encoding)
            truncated = len(content) > _MAX_OUTPUT
            return json.dumps(
                {
                    "content": content[:_MAX_OUTPUT],
                    "size": path.stat().st_size,
                    "truncated": truncated,
                },
                ensure_ascii=False,
            )
        except UnicodeDecodeError:
            return json.dumps({"error": "文件非文本格式或编码错误"}, ensure_ascii=False)

    def _list_directory(
        self, path: str | None = None, show_hidden: bool = False
    ) -> str:
        dir_path = Path(path) if path else Path.cwd()
        if not dir_path.exists():
            return json.dumps({"error": f"目录不存在: {path}"}, ensure_ascii=False)
        if not dir_path.is_dir():
            return json.dumps({"error": f"路径不是目录: {path}"}, ensure_ascii=False)

        entries = []
        for entry in sorted(dir_path.iterdir()):
            if not show_hidden and entry.name.startswith("."):
                continue
            stat = entry.stat()
            entries.append(
                {
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": stat.st_size if entry.is_file() else None,
                }
            )
        return json.dumps(
            {"path": str(dir_path), "entries": entries, "count": len(entries)},
            ensure_ascii=False,
        )
