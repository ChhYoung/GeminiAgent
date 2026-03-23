"""
context/compress.py — Compress 阶段

当上下文字符数超出阈值时，调用 LLM 进行摘要压缩。
"""

from __future__ import annotations

import asyncio
import logging

import openai

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)

_MAX_CHARS = 12000  # 超过此长度则触发压缩
_COMPRESS_PROMPT = (
    "请将以下上下文信息压缩为简洁的摘要，保留最关键的事实和细节，"
    "不超过原文的 1/3 长度，使用中文输出：\n\n{context}"
)


async def compress(context: str, max_chars: int = _MAX_CHARS) -> str:
    """
    若 context 超过 max_chars，调用 LLM 做摘要；否则直接返回。

    Args:
        context:   Structure 阶段输出的上下文字符串
        max_chars: 触发压缩的字符阈值

    Returns:
        压缩后（或原始）的上下文字符串
    """
    if len(context) <= max_chars:
        return context

    logger.info(
        "Context too long (%d chars > %d), compressing...", len(context), max_chars
    )

    cfg = get_settings()
    client = openai.OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)
    prompt = _COMPRESS_PROMPT.format(context=context[:max_chars * 2])

    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=cfg.llm_model_id,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        compressed = response.choices[0].message.content.strip()
        logger.info(
            "Compressed context: %d -> %d chars", len(context), len(compressed)
        )
        return compressed
    except Exception as exc:
        logger.warning("Context compression failed, using truncation: %s", exc)
        return context[:max_chars]
