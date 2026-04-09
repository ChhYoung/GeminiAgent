"""
permissions/deny_list.py — 永久拒绝的危险操作 (s07)

即使 policy=bypass 也不放行，须显式用户确认。
"""

from __future__ import annotations

# shell 命令级危险模式（子字符串匹配）
DENY_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "rm -fr",
    "dd if=",
    "> /dev/",
    "mkfs",
    "fdisk",
    "format c:",
    "deltree",
    "shutdown",
    "reboot",
    "halt",
    ":(){ :|:& };:",      # fork bomb
    "chmod -R 777 /",
    "chown -R",
)

# 永久拒绝的工具名（直接 block dispatch）
DENY_TOOLS: frozenset[str] = frozenset()


def is_denied_command(command: str) -> bool:
    """检查 shell 命令是否包含危险模式。"""
    lower = command.lower()
    return any(pat in lower for pat in DENY_PATTERNS)


def is_denied_tool(tool_name: str) -> bool:
    """检查工具名是否在永久拒绝列表。"""
    return tool_name in DENY_TOOLS


# 高风险工具名：policy=default/auto 下需要用户确认
DANGEROUS_TOOLS: frozenset[str] = frozenset({
    "run_terminal",
    "execute_command",
    "run_background",
    "delete_note",
})

DENY_LIST = DENY_PATTERNS  # 向后兼容别名
