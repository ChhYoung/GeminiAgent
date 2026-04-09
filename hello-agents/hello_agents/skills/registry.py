"""
skills/registry.py — 技能注册表 (s05 独立化)

惰性加载：技能只在首次激活时才真正导入，
保持 system prompt 精简（技能内容按需注入）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """技能描述。"""
    name: str
    description: str
    prompt_snippet: str             # 激活时注入的 prompt 段
    tools: list[str] = field(default_factory=list)   # 该技能关联的工具名
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "prompt_snippet": self.prompt_snippet,
            "tools": self.tools,
        }


class SkillRegistry:
    """
    技能注册表。

    用法：
        registry = SkillRegistry()
        registry.register(Skill(name="coding", description="...", prompt_snippet="..."))
        skill = registry.activate("coding")
        print(skill.prompt_snippet)
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._loaders: dict[str, Callable[[], Skill]] = {}

    def register(self, skill: Skill) -> None:
        """立即注册技能。"""
        self._skills[skill.name] = skill
        logger.debug("Skill registered: %s", skill.name)

    def register_lazy(self, name: str, loader: Callable[[], Skill]) -> None:
        """注册惰性加载技能（首次 activate 时才调用 loader）。"""
        self._loaders[name] = loader
        logger.debug("Lazy skill registered: %s", name)

    def activate(self, name: str) -> Skill | None:
        """
        激活技能（惰性加载后缓存）。

        Returns:
            Skill 对象，不存在时返回 None
        """
        if name in self._skills:
            return self._skills[name]
        if name in self._loaders:
            try:
                skill = self._loaders[name]()
                self._skills[name] = skill
                del self._loaders[name]
                logger.info("Skill '%s' lazy-loaded", name)
                return skill
            except Exception as exc:
                logger.warning("Failed to load skill '%s': %s", name, exc)
                return None
        logger.warning("Skill '%s' not found", name)
        return None

    def list_available(self) -> list[str]:
        """返回所有可用技能名称（已注册 + 待惰性加载）。"""
        return sorted(set(self._skills) | set(self._loaders))

    def is_registered(self, name: str) -> bool:
        return name in self._skills or name in self._loaders
