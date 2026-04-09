"""
tests/unit/test_permissions.py — 权限系统测试 (s07)
"""

from __future__ import annotations

import pytest

from hello_agents.permissions.deny_list import is_denied_command, is_denied_tool, DANGEROUS_TOOLS
from hello_agents.permissions.gate import PermissionGate, PermissionDeniedError
from hello_agents.permissions.policy import PermissionPolicy


class TestDenyList:
    def test_rm_rf_denied(self):
        assert is_denied_command("rm -rf /") is True

    def test_normal_command_allowed(self):
        assert is_denied_command("ls -la") is False

    def test_fork_bomb_denied(self):
        assert is_denied_command(":(){ :|:& };:") is True

    def test_echo_allowed(self):
        assert is_denied_command("echo hello world") is False

    def test_dd_denied(self):
        assert is_denied_command("dd if=/dev/zero of=/dev/sda") is True

    def test_tool_deny_list_empty_by_default(self):
        assert is_denied_tool("some_tool") is False

    def test_dangerous_tools_set(self):
        assert "run_terminal" in DANGEROUS_TOOLS

    def test_case_insensitive(self):
        assert is_denied_command("RM -RF /") is True


class TestPermissionPolicy:
    def test_from_str_default(self):
        p = PermissionPolicy.from_str("default")
        assert p == PermissionPolicy.DEFAULT

    def test_from_str_unknown_falls_back(self):
        p = PermissionPolicy.from_str("unknown")
        assert p == PermissionPolicy.DEFAULT

    def test_from_str_bypass(self):
        p = PermissionPolicy.from_str("bypass")
        assert p == PermissionPolicy.BYPASS


class TestPermissionGate:
    def _gate(self, policy: PermissionPolicy, allow: bool = True) -> PermissionGate:
        return PermissionGate(policy=policy, ask_fn=lambda _: allow)

    def test_bypass_allows_dangerous_tool(self):
        gate = self._gate(PermissionPolicy.BYPASS)
        # Should not raise
        gate.check("run_terminal", {"command": "ls"})

    def test_denied_command_always_blocked(self):
        gate = self._gate(PermissionPolicy.BYPASS)
        with pytest.raises(PermissionDeniedError):
            gate.check("run_terminal", {"command": "rm -rf /"})

    def test_auto_allows_safe_tool(self):
        gate = self._gate(PermissionPolicy.AUTO)
        gate.check("search_memory", {})  # not in DANGEROUS_TOOLS

    def test_auto_asks_for_dangerous_tool_and_allows(self):
        gate = self._gate(PermissionPolicy.AUTO, allow=True)
        gate.check("run_terminal", {"command": "ls"})  # allowed by user

    def test_auto_asks_for_dangerous_tool_and_denies(self):
        gate = self._gate(PermissionPolicy.AUTO, allow=False)
        with pytest.raises(PermissionDeniedError):
            gate.check("run_terminal", {"command": "ls"})

    def test_default_allows_safe_tool(self):
        gate = self._gate(PermissionPolicy.DEFAULT)
        gate.check("search_memory", {})

    def test_default_asks_for_dangerous_tool(self):
        gate = self._gate(PermissionPolicy.DEFAULT, allow=False)
        with pytest.raises(PermissionDeniedError):
            gate.check("run_terminal", {"command": "ls"})

    def test_policy_property(self):
        gate = PermissionGate(policy=PermissionPolicy.AUTO)
        assert gate.policy == PermissionPolicy.AUTO
