"""
prompt/builder.py — System Prompt 分段组装器 (s10)

按优先级拼装各段，超出 token 预算时截断低优先级段。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 粗估：1 token ≈ 4 chars (英) / 2 chars (中)
_CHARS_PER_TOKEN = 3


@dataclass(order=True)
class _Section:
    priority: int           # 优先级，越高越不被截断（降序排列）
    key: str = field(compare=False)
    content: str = field(compare=False)


class PromptBuilder:
    """
    System Prompt 分段组装器。

    用法：
        builder = PromptBuilder()
        builder.add_section("identity", IDENTITY, priority=100)
        builder.add_section("rules", RULES, priority=50)
        builder.add_section("context", ctx_str, priority=10)
        prompt = builder.build(max_tokens=500)
    """

    def __init__(self) -> None:
        self._sections: list[_Section] = []

    def add_section(self, key: str, content: str, priority: int = 0) -> None:
        """添加一个 prompt 段。同一 key 重复添加时覆盖。"""
        # 移除已有同 key 的段
        self._sections = [s for s in self._sections if s.key != key]
        self._sections.append(_Section(priority=-priority, key=key, content=content))
        # 按优先级降序（priority 字段存的是负优先级，所以升序排列即为降序）
        self._sections.sort()

    def remove_section(self, key: str) -> bool:
        before = len(self._sections)
        self._sections = [s for s in self._sections if s.key != key]
        return len(self._sections) < before

    def build(self, max_tokens: int = 500) -> str:
        """
        拼装 prompt，按优先级降序拼接，超出 max_tokens 时截断低优先级段。

        Returns:
            最终 system prompt 字符串
        """
        max_chars = max_tokens * _CHARS_PER_TOKEN
        parts: list[str] = []
        used = 0

        for sec in self._sections:
            content = sec.content.strip()
            if not content:
                continue
            need = len(content) + 2  # +2 for separator
            if used + need > max_chars and parts:
                logger.debug("Prompt section '%s' truncated (budget exceeded)", sec.key)
                break
            parts.append(content)
            used += need

        return "\n\n".join(parts)

    def section_keys(self) -> list[str]:
        """返回已注册段的 key 列表（按优先级降序）。"""
        return [s.key for s in self._sections]

    def __len__(self) -> int:
        return len(self._sections)
