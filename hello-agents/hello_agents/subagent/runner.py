"""
subagent/runner.py — 子 Agent 运行器 (s04)

每个子任务使用独立的 messages[]，不污染主对话上下文。
父 agent 只收到最终文本结果，中间 tool_calls 不暴露。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import openai

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)

_SUB_SYSTEM = (
    "你是一个专注的子任务执行 Agent。"
    "专注完成指定的单一子任务，给出简洁、准确的结果。"
)


class SubAgentRunner:
    """
    隔离上下文的子任务执行器。(s04)

    每次调用 run() 都使用全新的 messages[]，
    完全不依赖主 agent 的对话历史。

    用法：
        runner = SubAgentRunner(registry=tool_registry)
        result = await runner.run("分析 logs/app.log 中的错误模式")
    """

    def __init__(
        self,
        registry: Any | None = None,
        client: openai.OpenAI | None = None,
        model: str | None = None,
        max_tool_rounds: int = 5,
    ) -> None:
        cfg = get_settings()
        self._client = client or openai.OpenAI(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )
        self._model = model or cfg.llm_model_id
        self._registry = registry
        self._max_tool_rounds = max_tool_rounds

    async def run(self, task_desc: str, context_hint: str = "") -> str:
        """
        用全新的 messages[] 执行子任务。

        Args:
            task_desc:    子任务描述
            context_hint: 可选的背景信息（不含主对话历史）

        Returns:
            子任务执行结果文本
        """
        system_content = _SUB_SYSTEM
        if context_hint:
            system_content += f"\n\n背景信息：{context_hint}"

        messages: list[dict] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": task_desc},
        ]

        tool_schemas = self._registry.get_schemas() if self._registry else []

        for _ in range(self._max_tool_rounds):
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=messages,
                tools=tool_schemas if tool_schemas else openai.NOT_GIVEN,
                temperature=0.3,
                max_tokens=2048,
            )
            message = response.choices[0].message

            if message.tool_calls and self._registry:
                messages.append(message.model_dump())
                for tc in message.tool_calls:
                    result = self._registry.dispatch(tc)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        }
                    )
            else:
                return message.content or ""

        return message.content or ""
