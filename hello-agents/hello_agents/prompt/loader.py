"""
prompt/loader.py — Prompt 段动态加载器 (s10)

支持从文件、环境变量、内存记录加载补充段。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from hello_agents.prompt.builder import PromptBuilder

logger = logging.getLogger(__name__)


def load_from_file(builder: PromptBuilder, path: str | Path, key: str, priority: int = 5) -> bool:
    """
    从文件加载 prompt 段，追加到 builder。

    Returns:
        True if loaded successfully, False otherwise.
    """
    p = Path(path)
    if not p.exists():
        logger.debug("Prompt file not found: %s", p)
        return False
    content = p.read_text(encoding="utf-8").strip()
    if content:
        builder.add_section(key, content, priority=priority)
        logger.info("Loaded prompt section '%s' from %s", key, p)
        return True
    return False


def load_from_env(builder: PromptBuilder, env_var: str, key: str, priority: int = 20) -> bool:
    """
    从环境变量加载 prompt 段。

    Returns:
        True if env var exists and non-empty.
    """
    content = os.environ.get(env_var, "").strip()
    if content:
        builder.add_section(key, content, priority=priority)
        logger.info("Loaded prompt section '%s' from env %s", key, env_var)
        return True
    return False


def load_default_sections(builder: PromptBuilder) -> None:
    """加载内置默认段（identity + capabilities + rules）。"""
    from hello_agents.prompt.sections import CAPABILITIES, IDENTITY, RULES

    builder.add_section("identity", IDENTITY, priority=100)
    builder.add_section("capabilities", CAPABILITIES, priority=80)
    builder.add_section("rules", RULES, priority=60)
