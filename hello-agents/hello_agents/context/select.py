"""
context/select.py — Select 阶段

基于 Token 预算和相关度阈值，对 RawItem 列表进行贪心裁切。
"""

from __future__ import annotations

import logging

from hello_agents.context.gather import RawItem

logger = logging.getLogger(__name__)

# 简易 token 估算：4 字符 ≈ 1 token
_CHARS_PER_TOKEN = 4


def select(
    items: list[RawItem],
    token_budget: int = 2000,
    min_score: float = 0.3,
) -> list[RawItem]:
    """
    按 score 降序排列，贪心填充 token 预算，过滤低相关度条目。

    Args:
        items:        原始素材列表
        token_budget: 最大 token 预算
        min_score:    最低相关度阈值

    Returns:
        过滤并截断后的 RawItem 列表
    """
    # 过滤低相关度
    filtered = [item for item in items if item.score >= min_score]

    # 按 score 降序
    filtered.sort(key=lambda x: x.score, reverse=True)

    selected: list[RawItem] = []
    used_chars = 0
    budget_chars = token_budget * _CHARS_PER_TOKEN

    for item in filtered:
        item_chars = len(item.content)
        if used_chars + item_chars > budget_chars:
            # 尝试截断填入剩余空间
            remaining = budget_chars - used_chars
            if remaining > 100:
                truncated = RawItem(
                    source=item.source,
                    content=item.content[:remaining],
                    score=item.score,
                    metadata={**item.metadata, "truncated": True},
                )
                selected.append(truncated)
            break
        selected.append(item)
        used_chars += item_chars

    logger.debug(
        "Select: %d/%d items within %d token budget",
        len(selected),
        len(items),
        token_budget,
    )
    return selected
