"""
context/structure.py — Structure 阶段

将多源 RawItem 数据格式化为 XML 标签块，便于 LLM 理解上下文边界。
"""

from __future__ import annotations

from hello_agents.context.gather import RawItem


def structure(items: list[RawItem]) -> str:
    """
    将 RawItem 列表转换为 XML 格式的上下文字符串。

    输出格式示例：
        <memory>
        [1] (score=0.85) 用户喜欢 Python 编程
        [2] (score=0.72) 上次对话讨论了向量数据库
        </memory>
        <knowledge>
        [来源: doc.pdf §3] Qdrant 是一个向量数据库...
        </knowledge>

    Args:
        items: Select 阶段输出的 RawItem 列表

    Returns:
        格式化后的上下文字符串（空列表返回空字符串）
    """
    if not items:
        return ""

    # 按 source 分组
    groups: dict[str, list[RawItem]] = {}
    for item in items:
        groups.setdefault(item.source, []).append(item)

    parts: list[str] = []

    if "memory" in groups:
        lines = []
        for i, item in enumerate(groups["memory"], 1):
            lines.append(f"[{i}] (score={item.score:.2f}) {item.content}")
        parts.append("<memory>\n" + "\n".join(lines) + "\n</memory>")

    if "rag" in groups:
        lines = []
        for item in groups["rag"]:
            src = item.metadata.get("source_file", "unknown")
            sec = item.metadata.get("section", "")
            lines.append(f"[来源: {src} §{sec}] {item.content}")
        parts.append("<knowledge>\n" + "\n\n".join(lines) + "\n</knowledge>")

    if "system_state" in groups:
        lines = [item.content for item in groups["system_state"]]
        parts.append("<system_state>\n" + "\n".join(lines) + "\n</system_state>")

    return "\n\n".join(parts)
