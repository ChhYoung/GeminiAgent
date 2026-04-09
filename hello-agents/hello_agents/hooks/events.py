"""
hooks/events.py — Hook 事件枚举 (s08)
"""

from __future__ import annotations

from enum import Enum


class HookEvent(str, Enum):
    PRE_TOOL   = "pre_tool"    # 工具执行前
    POST_TOOL  = "post_tool"   # 工具执行后
    PRE_LLM    = "pre_llm"     # LLM 请求前
    POST_LLM   = "post_llm"    # LLM 响应后
    ON_ERROR   = "on_error"    # 发生异常时
    ON_REPLY   = "on_reply"    # 最终回复生成时
