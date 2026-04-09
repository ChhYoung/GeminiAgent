"""
tests/integration/test_permission_gate.py — 权限门控集成测试 (s07)
"""

from __future__ import annotations

import pytest

from hello_agents.permissions.gate import PermissionGate, PermissionDeniedError
from hello_agents.permissions.policy import PermissionPolicy
from hello_agents.tools.registry import ToolRegistry
from hello_agents.tools.builtin.note_tool import NoteToolHandler, NOTE_TOOLS


def _make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_handler(NoteToolHandler(), NOTE_TOOLS)
    return registry


class TestPermissionGateIntegration:
    def test_bypass_allows_all_safe_tools(self):
        gate = PermissionGate(policy=PermissionPolicy.BYPASS)
        # create_note is not in DANGEROUS_TOOLS, should pass
        gate.check("create_note", {"title": "test"})

    def test_bypass_blocks_rm_rf_command(self):
        gate = PermissionGate(policy=PermissionPolicy.BYPASS)
        with pytest.raises(PermissionDeniedError):
            gate.check("run_terminal", {"command": "rm -rf /tmp"})

    def test_auto_passes_safe_tool_without_asking(self):
        asked = [False]

        def ask(prompt: str) -> bool:
            asked[0] = True
            return True

        gate = PermissionGate(policy=PermissionPolicy.AUTO, ask_fn=ask)
        gate.check("create_note", {"title": "safe"})
        assert not asked[0]  # Did not ask user

    def test_auto_asks_for_run_terminal(self):
        asked = [False]

        def ask(prompt: str) -> bool:
            asked[0] = True
            return True  # User says yes

        gate = PermissionGate(policy=PermissionPolicy.AUTO, ask_fn=ask)
        gate.check("run_terminal", {"command": "ls"})
        assert asked[0]

    def test_default_always_asks_for_dangerous(self):
        ask_count = [0]

        def ask(prompt: str) -> bool:
            ask_count[0] += 1
            return True

        gate = PermissionGate(policy=PermissionPolicy.DEFAULT, ask_fn=ask)
        gate.check("run_terminal", {"command": "ps aux"})
        gate.check("run_background", {"command": "sleep 1"})
        assert ask_count[0] == 2

    def test_denied_by_command_in_args(self):
        gate = PermissionGate(policy=PermissionPolicy.BYPASS)
        with pytest.raises(PermissionDeniedError):
            gate.check("run_terminal", {"command": "dd if=/dev/zero of=/dev/sda"})

    def test_gate_is_agnostic_to_registry(self):
        """Gate works independently of ToolRegistry."""
        registry = _make_registry()
        gate = PermissionGate(policy=PermissionPolicy.BYPASS)
        # Just check that gate and registry can coexist
        gate.check("create_note", {"title": "x"})
        assert registry.has_tool("create_note")
