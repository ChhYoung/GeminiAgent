"""
context/compress.py — Compress 阶段 (s06)

三层压缩策略，换来无限会话：

Layer 1 — 滑窗截断（毫秒）
    items 超过 max_items → 丢弃最早的条目
    不调用 LLM，适合高频触发（每轮对话检测）

Layer 2 — LLM 摘要（秒级）
    context 超过 max_chars → 调用轻量模型生成摘要
    保留信息密度，牺牲原文细节

Layer 3 — 卸载到记忆（分钟级，异步）
    context 超过 offload_chars → 把整个上下文快照写入
    外部存储（由调用方异步触发），messages[] 清零

compress() 是 GSSC 流水线使用的主入口，对应 Layer 2。
sliding_window() 和 offload_check() 供 WorkingMemory 调用。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import openai

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)

# 各层默认阈值
_LAYER1_MAX_ITEMS = 20      # 超过此数量触发滑窗截断
_LAYER2_MAX_CHARS = 12000   # 超过此字符数触发 LLM 摘要
_LAYER3_OFFLOAD_CHARS = 40000  # 超过此字符数建议卸载到记忆

_COMPRESS_PROMPT = (
    "请将以下上下文信息压缩为简洁的摘要，保留最关键的事实和细节，"
    "不超过原文的 1/3 长度，使用中文输出：\n\n{context}"
)


# ---------------------------------------------------------------------------
# Layer 1 — 滑窗截断
# ---------------------------------------------------------------------------

def sliding_window(
    items: list[Any],
    max_items: int = _LAYER1_MAX_ITEMS,
    keep_first: int = 1,
) -> list[Any]:
    """
    对列表执行滑动窗口截断，保留最新的 max_items 条。

    Args:
        items:      任意列表（ContextItem、message dict 等）
        max_items:  保留的最大条目数
        keep_first: 始终保留头部的 N 条（如 system message）

    Returns:
        截断后的列表
    """
    if len(items) <= max_items:
        return items

    head = items[:keep_first]
    tail = items[keep_first:]
    keep_tail = max(0, max_items - keep_first)
    truncated = head + tail[-keep_tail:] if keep_tail > 0 else head
    logger.debug(
        "Layer1 sliding_window: %d -> %d items", len(items), len(truncated)
    )
    return truncated


# ---------------------------------------------------------------------------
# Layer 2 — LLM 摘要（原 compress 逻辑，改名保持兼容）
# ---------------------------------------------------------------------------

async def llm_summarize(
    context: str,
    max_chars: int = _LAYER2_MAX_CHARS,
) -> str:
    """
    若 context 超过 max_chars，调用 LLM 做摘要；否则直接返回。(Layer 2)

    Args:
        context:   Structure 阶段输出的上下文字符串
        max_chars: 触发压缩的字符阈值

    Returns:
        压缩后（或原始）的上下文字符串
    """
    if len(context) <= max_chars:
        return context

    logger.info(
        "Layer2 LLM summarize: %d chars > %d, compressing...",
        len(context),
        max_chars,
    )

    cfg = get_settings()
    client = openai.OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)
    prompt = _COMPRESS_PROMPT.format(context=context[: max_chars * 2])

    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=cfg.llm_model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        compressed = response.choices[0].message.content.strip()
        logger.info(
            "Layer2 compressed: %d -> %d chars", len(context), len(compressed)
        )
        return compressed
    except Exception as exc:
        logger.warning("Layer2 LLM summarize failed, using truncation: %s", exc)
        return context[:max_chars]


# ---------------------------------------------------------------------------
# Layer 3 — 卸载检查（由调用方决定是否触发异步卸载）
# ---------------------------------------------------------------------------

def needs_offload(context: str, offload_chars: int = _LAYER3_OFFLOAD_CHARS) -> bool:
    """
    检查 context 是否超过卸载阈值。(Layer 3 触发判断)

    超过阈值时，调用方应将 context 写入 EpisodicMemory，
    然后清空 messages[]，下次对话用 search_memory 按需召回。
    """
    return len(context) > offload_chars


# ---------------------------------------------------------------------------
# 统一入口（向后兼容，供 GSSC 流水线使用）
# ---------------------------------------------------------------------------

async def compress(context: str, max_chars: int = _LAYER2_MAX_CHARS) -> str:
    """
    GSSC 流水线的 Compress 入口。

    - 短于 max_chars：直接返回（Layer 1 已在 select 阶段截断）
    - 超过 max_chars：调用 LLM 摘要（Layer 2）

    Args:
        context:   Structure 阶段输出的字符串
        max_chars: 触发 Layer 2 的字符阈值

    Returns:
        压缩后（或原始）的上下文字符串
    """
    return await llm_summarize(context, max_chars=max_chars)
