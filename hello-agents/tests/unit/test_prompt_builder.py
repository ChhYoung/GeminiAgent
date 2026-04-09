"""
tests/unit/test_prompt_builder.py — System Prompt 组装测试 (s10)
"""

from __future__ import annotations

import pytest

from hello_agents.prompt.builder import PromptBuilder
from hello_agents.prompt.sections import IDENTITY, CAPABILITIES, RULES
from hello_agents.prompt.loader import load_default_sections


class TestPromptBuilder:
    def test_add_and_build(self):
        b = PromptBuilder()
        b.add_section("identity", "You are an agent.", priority=100)
        result = b.build()
        assert "You are an agent." in result

    def test_priority_order(self):
        b = PromptBuilder()
        b.add_section("low", "LOW", priority=1)
        b.add_section("high", "HIGH", priority=100)
        result = b.build()
        assert result.index("HIGH") < result.index("LOW")

    def test_budget_truncation(self):
        b = PromptBuilder()
        b.add_section("main", "MAIN", priority=100)
        # 低优先级段很长，超出预算应被截断
        b.add_section("extra", "X" * 100000, priority=1)
        result = b.build(max_tokens=10)
        # 只有高优先级段被保留
        assert "MAIN" in result
        assert "X" * 100000 not in result

    def test_duplicate_key_overwrite(self):
        b = PromptBuilder()
        b.add_section("identity", "v1", priority=10)
        b.add_section("identity", "v2", priority=10)
        result = b.build()
        assert "v2" in result
        assert "v1" not in result

    def test_remove_section(self):
        b = PromptBuilder()
        b.add_section("rules", "RULES", priority=50)
        removed = b.remove_section("rules")
        assert removed is True
        assert "RULES" not in b.build()

    def test_remove_nonexistent_returns_false(self):
        b = PromptBuilder()
        assert b.remove_section("ghost") is False

    def test_section_keys_order(self):
        b = PromptBuilder()
        b.add_section("z", "Z", priority=1)
        b.add_section("a", "A", priority=100)
        keys = b.section_keys()
        assert keys[0] == "a"
        assert keys[-1] == "z"

    def test_len(self):
        b = PromptBuilder()
        assert len(b) == 0
        b.add_section("k", "v", priority=1)
        assert len(b) == 1

    def test_empty_builder(self):
        b = PromptBuilder()
        assert b.build() == ""

    def test_load_default_sections(self):
        b = PromptBuilder()
        load_default_sections(b)
        result = b.build(max_tokens=2000)
        assert len(result) > 0
        # All three default sections present
        assert "identity" in b.section_keys()
        assert "capabilities" in b.section_keys()
        assert "rules" in b.section_keys()
