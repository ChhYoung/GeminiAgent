"""
permissions/gate.py — 权限门控 (s07)

工具执行前调用 gate.check()，决定是否允许执行。
不可绕过的危险操作通过 deny_list 强制拦截。
"""

from __future__ import annotations

import logging
from typing import Callable

from hello_agents.permissions.deny_list import (
    DANGEROUS_TOOLS,
    is_denied_command,
    is_denied_tool,
)
from hello_agents.permissions.policy import PermissionPolicy

logger = logging.getLogger(__name__)


class PermissionDeniedError(Exception):
    """工具被权限门控拒绝时抛出。"""


class PermissionGate:
    """
    权限门控。在工具执行前 check()，决定允许/拒绝/询问。

    用法：
        gate = PermissionGate(policy=PermissionPolicy.AUTO)
        gate.check("run_terminal", {"command": "ls -la"})  # ok
        gate.check("run_terminal", {"command": "rm -rf /"})  # raises
    """

    def __init__(
        self,
        policy: PermissionPolicy = PermissionPolicy.DEFAULT,
        ask_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._policy = policy
        # ask_fn(prompt) -> True = allowed, False = denied
        self._ask = ask_fn or self._default_ask

    # ------------------------------------------------------------------

    def check(self, tool_name: str, args: dict) -> None:
        """
        检查工具是否允许执行。

        Raises:
            PermissionDeniedError: 工具被拒绝时
        """
        # 永不放行的工具
        if is_denied_tool(tool_name):
            raise PermissionDeniedError(f"Tool '{tool_name}' is permanently denied.")

        # 检查命令内容中的危险模式
        command = args.get("command", "")
        if command and is_denied_command(command):
            raise PermissionDeniedError(
                f"Command contains a denied pattern: {command!r}"
            )

        if self._policy == PermissionPolicy.BYPASS:
            return  # 全部放行

        if self._policy == PermissionPolicy.AUTO:
            if tool_name not in DANGEROUS_TOOLS:
                return  # 非高风险工具直通
            # 高风险工具询问
            allowed = self._ask(
                f"[Permission] Allow dangerous tool '{tool_name}' with args {args}? [y/N]: "
            )
            if not allowed:
                raise PermissionDeniedError(f"User denied tool '{tool_name}'.")
            return

        # DEFAULT: 危险工具必须询问
        if tool_name in DANGEROUS_TOOLS:
            allowed = self._ask(
                f"[Permission] Allow '{tool_name}' with args {args}? [y/N]: "
            )
            if not allowed:
                raise PermissionDeniedError(f"User denied tool '{tool_name}'.")

    # ------------------------------------------------------------------

    @staticmethod
    def _default_ask(prompt: str) -> bool:
        """终端询问用户（非交互式环境返回 False）。"""
        try:
            ans = input(prompt).strip().lower()
            return ans in ("y", "yes")
        except (EOFError, OSError):
            return False

    @property
    def policy(self) -> PermissionPolicy:
        return self._policy
