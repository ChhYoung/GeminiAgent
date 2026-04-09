"""
skills/loader.py — 技能文件热加载器 (s05)

扫描 ~/.agent/skills/ 目录中的 .py 文件，
每个文件需暴露 SKILL = Skill(...) 变量。
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from hello_agents.skills.registry import Skill, SkillRegistry

logger = logging.getLogger(__name__)

_DEFAULT_SKILLS_DIR = Path.home() / ".agent" / "skills"


def load_builtin_skills(registry: SkillRegistry) -> None:
    """注册内置技能（coding + research）。"""
    from hello_agents.skills.builtin.coding_skill import SKILL as coding
    from hello_agents.skills.builtin.research_skill import SKILL as research

    registry.register(coding)
    registry.register(research)
    logger.info("Built-in skills loaded: coding, research")


def load_from_directory(registry: SkillRegistry, directory: Path | str = _DEFAULT_SKILLS_DIR) -> int:
    """
    从目录热加载自定义技能。

    Returns:
        成功加载的技能数量
    """
    skills_dir = Path(directory)
    if not skills_dir.exists():
        return 0

    count = 0
    for py_file in skills_dir.glob("*.py"):
        try:
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            skill = getattr(module, "SKILL", None)
            if isinstance(skill, Skill):
                registry.register(skill)
                count += 1
                logger.info("Custom skill loaded: %s from %s", skill.name, py_file)
        except Exception as exc:
            logger.warning("Failed to load skill from %s: %s", py_file, exc)

    return count
