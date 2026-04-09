"""
tests/unit/test_skills.py — 技能系统测试 (s05)
"""

from __future__ import annotations

import pytest

from hello_agents.skills.registry import Skill, SkillRegistry
from hello_agents.skills.loader import load_builtin_skills


def _make_skill(name: str = "test_skill") -> Skill:
    return Skill(
        name=name,
        description="A test skill",
        prompt_snippet="## Test\nDo test things.",
        tools=["web_search"],
    )


class TestSkillRegistry:
    def test_register_and_activate(self):
        reg = SkillRegistry()
        skill = _make_skill("coding")
        reg.register(skill)
        activated = reg.activate("coding")
        assert activated is not None
        assert activated.name == "coding"

    def test_activate_nonexistent_returns_none(self):
        reg = SkillRegistry()
        assert reg.activate("ghost") is None

    def test_list_available(self):
        reg = SkillRegistry()
        reg.register(_make_skill("a"))
        reg.register(_make_skill("b"))
        names = reg.list_available()
        assert set(names) == {"a", "b"}

    def test_register_lazy(self):
        reg = SkillRegistry()
        loaded = [False]

        def loader():
            loaded[0] = True
            return _make_skill("lazy_skill")

        reg.register_lazy("lazy_skill", loader)
        assert not loaded[0]  # Not loaded yet
        names = reg.list_available()
        assert "lazy_skill" in names
        skill = reg.activate("lazy_skill")
        assert loaded[0]  # Now loaded
        assert skill is not None
        assert skill.name == "lazy_skill"

    def test_lazy_loaded_then_cached(self):
        reg = SkillRegistry()
        call_count = [0]

        def loader():
            call_count[0] += 1
            return _make_skill("cached_skill")

        reg.register_lazy("cached_skill", loader)
        reg.activate("cached_skill")
        reg.activate("cached_skill")  # second call
        assert call_count[0] == 1  # loader called once

    def test_is_registered(self):
        reg = SkillRegistry()
        reg.register(_make_skill("foo"))
        assert reg.is_registered("foo")
        assert not reg.is_registered("bar")

    def test_lazy_loader_failure_returns_none(self):
        reg = SkillRegistry()
        reg.register_lazy("bad_skill", lambda: (_ for _ in ()).throw(ImportError("missing")))
        result = reg.activate("bad_skill")
        assert result is None


class TestBuiltinSkills:
    def test_load_builtin_skills(self):
        reg = SkillRegistry()
        load_builtin_skills(reg)
        assert reg.is_registered("coding")
        assert reg.is_registered("research")

    def test_coding_skill_content(self):
        reg = SkillRegistry()
        load_builtin_skills(reg)
        skill = reg.activate("coding")
        assert skill is not None
        assert len(skill.prompt_snippet) > 0
        assert "run_terminal" in skill.tools

    def test_research_skill_content(self):
        reg = SkillRegistry()
        load_builtin_skills(reg)
        skill = reg.activate("research")
        assert skill is not None
        assert "web_search" in skill.tools

    def test_skill_to_dict(self):
        skill = _make_skill("x")
        d = skill.to_dict()
        assert d["name"] == "x"
        assert "prompt_snippet" in d
