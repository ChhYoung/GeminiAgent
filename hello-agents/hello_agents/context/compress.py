"""
context/compress.py — 上下文压缩（三层优化版）

Layer 1 — 大结果落盘，只留预览
    工具返回的大 result（>L1_RESULT_CHARS）写入临时文件，
    messages[] 中保留一行预览 + 文件路径，不塞满 context。

Layer 2 — 旧结果替换为占位符
    超过 L2_KEEP_RECENT 轮的 tool_result 消息替换成
    "[已折叠: {tool_name} 结果已归档]"，减少重复原文。

Layer 3 — 整体历史过长时，生成连续性摘要
    messages 总字符数超过 L3_SUMMARY_CHARS 时，
    调用 LLM 生成一份连续性摘要，将旧消息替换为单条摘要消息，
    并保留最近 L3_KEEP_RECENT 轮对话原文。

向后兼容入口：
    sliding_window()    Layer 0 滑窗（保留 v4 接口）
    llm_summarize()     对字符串做 LLM 摘要（保留 v4 接口）
    needs_offload()     Layer 3 触发判断（保留 v4 接口）
    compress()          GSSC 流水线入口（Layer 3 字符串版，保留）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import openai

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)

# ── 阈值常量 ────────────────────────────────────────────────────────────────
L1_RESULT_CHARS  = 3000   # Layer 1: 工具结果超过此长度 → 落盘预留预览
L1_PREVIEW_CHARS = 300    # Layer 1: 预览保留字符数
L2_KEEP_RECENT   = 6      # Layer 2: 保留最近 N 轮 tool_result 原文
L3_SUMMARY_CHARS = 20000  # Layer 3: messages 总字符数触发连续性摘要
L3_KEEP_RECENT   = 4      # Layer 3: 摘要后保留最近 N 轮原文对话

# Layer 2/3 之前的旧字符阈值（向后兼容）
_LAYER2_MAX_CHARS   = 12000
_LAYER3_OFFLOAD_CHARS = 40000
_LAYER1_MAX_ITEMS   = 20

_COMPRESS_PROMPT = (
    "请将以下对话历史压缩为简洁的连续性摘要，保留最关键的事实、决策和结论，"
    "不超过原文的 1/4 长度，使用中文输出：\n\n{context}"
)

_SPILL_DIR = Path(tempfile.gettempdir()) / "agent_context_spill"


# ══════════════════════════════════════════════════════════════════════════════
# Layer 1 — 大结果落盘，只留预览
# ══════════════════════════════════════════════════════════════════════════════

def spill_large_results(messages: list[dict]) -> list[dict]:
    """
    Layer 1：遍历 messages，将 role=tool 中过大的 content 写到磁盘，
    原位替换为预览 + 文件路径。

    Args:
        messages: OpenAI messages 列表（原地修改的副本）

    Returns:
        处理后的 messages 列表（新列表，不修改原始）
    """
    _SPILL_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for msg in messages:
        if msg.get("role") != "tool":
            result.append(msg)
            continue
        content = msg.get("content", "")
        if not isinstance(content, str) or len(content) <= L1_RESULT_CHARS:
            result.append(msg)
            continue

        # 写到磁盘
        tool_call_id = msg.get("tool_call_id", "unknown")
        spill_path = _SPILL_DIR / f"{tool_call_id}.txt"
        spill_path.write_text(content, encoding="utf-8")

        # 提取预览（尝试解析 JSON，取关键字段）
        preview = _extract_preview(content)

        new_msg = dict(msg)
        new_msg["content"] = (
            f"[结果已落盘: {spill_path}]\n"
            f"[预览 ({len(content)} chars → {L1_PREVIEW_CHARS} chars)]:\n{preview}"
        )
        result.append(new_msg)
        logger.debug(
            "Layer1: spilled tool result %s (%d chars) to %s",
            tool_call_id, len(content), spill_path,
        )
    return result


def _extract_preview(content: str) -> str:
    """从工具结果中提取有意义的预览。"""
    # 尝试解析 JSON，取关键字段的前几条
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            # 只保留 key 列表 + 每个 value 的前 50 字符
            lines = []
            for k, v in list(data.items())[:8]:
                v_str = str(v)[:60]
                lines.append(f"  {k}: {v_str}")
            return "\n".join(lines)
        if isinstance(data, list):
            preview_items = data[:3]
            return json.dumps(preview_items, ensure_ascii=False)[:L1_PREVIEW_CHARS]
    except (json.JSONDecodeError, TypeError):
        pass
    return content[:L1_PREVIEW_CHARS] + ("…" if len(content) > L1_PREVIEW_CHARS else "")


def load_spilled_result(tool_call_id: str) -> str | None:
    """按 tool_call_id 从磁盘恢复完整结果（供调试/检索用）。"""
    spill_path = _SPILL_DIR / f"{tool_call_id}.txt"
    if spill_path.exists():
        return spill_path.read_text(encoding="utf-8")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Layer 2 — 旧结果替换为占位符
# ══════════════════════════════════════════════════════════════════════════════

def fold_old_results(messages: list[dict], keep_recent: int = L2_KEEP_RECENT) -> list[dict]:
    """
    Layer 2：将超出 keep_recent 轮的 role=tool 消息替换为占位符，
    保留最近 keep_recent 条 tool_result 原文。

    Args:
        messages:    OpenAI messages 列表
        keep_recent: 保留最近几条 tool_result 原文

    Returns:
        处理后的新 messages 列表
    """
    # 找出所有 tool_result 的索引（按出现顺序）
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]

    # 前 N 条之外的都折叠
    fold_indices = set(tool_indices[:-keep_recent]) if len(tool_indices) > keep_recent else set()

    if not fold_indices:
        return messages

    result = []
    for i, msg in enumerate(messages):
        if i not in fold_indices:
            result.append(msg)
            continue

        # 从 assistant 的 tool_call 尝试取 tool_name
        tool_name = _guess_tool_name(messages, i)
        placeholder = dict(msg)
        placeholder["content"] = f"[已折叠: {tool_name} 结果已归档]"
        result.append(placeholder)

    folded = len(fold_indices)
    if folded:
        logger.debug("Layer2: folded %d old tool results (kept %d)", folded, keep_recent)
    return result


def _guess_tool_name(messages: list[dict], tool_result_idx: int) -> str:
    """从 tool_call_id 反查 tool_name（在前一条 assistant 消息中）。"""
    tool_call_id = messages[tool_result_idx].get("tool_call_id", "")
    for msg in reversed(messages[:tool_result_idx]):
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                return tc.get("function", {}).get("name", "tool")
    return "tool"


# ══════════════════════════════════════════════════════════════════════════════
# Layer 3 — 连续性摘要（整体历史太长时）
# ══════════════════════════════════════════════════════════════════════════════

def _total_chars(messages: list[dict]) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages)


async def summarize_history(
    messages: list[dict],
    keep_recent: int = L3_KEEP_RECENT,
    max_total_chars: int = L3_SUMMARY_CHARS,
) -> list[dict]:
    """
    Layer 3：当 messages 总字符数超过 max_total_chars 时，
    将旧部分归纳为一条连续性摘要消息，保留最近 keep_recent 轮对话原文。

    Args:
        messages:        完整 messages 列表（第 0 条通常是 system）
        keep_recent:     保留最近几轮 user/assistant 对话原文
        max_total_chars: 触发摘要的阈值

    Returns:
        压缩后的 messages 列表（system 消息始终保留在头部）
    """
    if _total_chars(messages) <= max_total_chars:
        return messages

    # 分离 system 消息
    if messages and messages[0].get("role") == "system":
        system_msgs = [messages[0]]
        body = messages[1:]
    else:
        system_msgs = []
        body = messages

    # 保留最近 keep_recent * 2 条（每轮 user+assistant）
    tail_count = keep_recent * 2
    to_summarize = body[:-tail_count] if len(body) > tail_count else []
    tail = body[-tail_count:] if len(body) > tail_count else body

    if not to_summarize:
        return messages  # 不够旧，跳过

    # 把旧消息拼成字符串，调用 LLM 摘要
    history_text = "\n".join(
        f"[{m.get('role', '?')}]: {str(m.get('content', ''))[:500]}"
        for m in to_summarize
    )
    summary = await _llm_summarize_text(history_text)
    summary_msg = {
        "role": "system",
        "content": f"[历史对话摘要]\n{summary}",
    }

    compressed = system_msgs + [summary_msg] + tail
    logger.info(
        "Layer3: %d msgs → 1 summary + %d tail (total chars: %d → %d)",
        len(to_summarize), len(tail),
        _total_chars(messages), _total_chars(compressed),
    )
    return compressed


async def apply_all_layers(
    messages: list[dict],
    keep_tool_recent: int = L2_KEEP_RECENT,
    history_threshold: int = L3_SUMMARY_CHARS,
    keep_dialog_recent: int = L3_KEEP_RECENT,
) -> list[dict]:
    """
    依序应用三层压缩到 messages 列表。

    推荐在每轮 LLM 调用前调用此函数。
    """
    # Layer 1: 大结果落盘
    msgs = spill_large_results(messages)
    # Layer 2: 旧结果折叠
    msgs = fold_old_results(msgs, keep_recent=keep_tool_recent)
    # Layer 3: 整体摘要
    msgs = await summarize_history(
        msgs,
        keep_recent=keep_dialog_recent,
        max_total_chars=history_threshold,
    )
    return msgs


# ══════════════════════════════════════════════════════════════════════════════
# 向后兼容 — v4 接口（供 GSSC 流水线和旧测试使用）
# ══════════════════════════════════════════════════════════════════════════════

def sliding_window(
    items: list[Any],
    max_items: int = _LAYER1_MAX_ITEMS,
    keep_first: int = 1,
) -> list[Any]:
    """Layer 0 滑窗截断（v4 接口，保留兼容）。"""
    if len(items) <= max_items:
        return items
    head = items[:keep_first]
    tail = items[keep_first:]
    keep_tail = max(0, max_items - keep_first)
    truncated = head + tail[-keep_tail:] if keep_tail > 0 else head
    logger.debug("sliding_window: %d -> %d items", len(items), len(truncated))
    return truncated


async def llm_summarize(context: str, max_chars: int = _LAYER2_MAX_CHARS) -> str:
    """对字符串做 LLM 摘要（v4 接口，供 GSSC 流水线使用）。"""
    if len(context) <= max_chars:
        return context
    logger.info("llm_summarize: %d chars > %d, compressing…", len(context), max_chars)
    summary = await _llm_summarize_text(context[: max_chars * 2])
    if summary:
        return summary
    return context[:max_chars]


def needs_offload(context: str, offload_chars: int = _LAYER3_OFFLOAD_CHARS) -> bool:
    """Layer 3 触发判断（v4 接口）。"""
    return len(context) > offload_chars


async def compress(context: str, max_chars: int = _LAYER2_MAX_CHARS) -> str:
    """GSSC 流水线入口（v4 接口）。"""
    return await llm_summarize(context, max_chars=max_chars)


# ══════════════════════════════════════════════════════════════════════════════
# 内部 LLM 调用
# ══════════════════════════════════════════════════════════════════════════════

async def _llm_summarize_text(text: str) -> str:
    """调用 LLM 对文本进行摘要，失败时返回空串。"""
    cfg = get_settings()
    client = openai.OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)
    prompt = _COMPRESS_PROMPT.format(context=text)
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=cfg.llm_model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("_llm_summarize_text failed: %s", exc)
        return ""
