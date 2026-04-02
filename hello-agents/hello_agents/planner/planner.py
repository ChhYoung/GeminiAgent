"""
planner/planner.py — 计划引擎 (s03)

在执行复杂任务前，先将目标分解为有序 Step 列表，
避免 agent 走哪算哪，完成率翻倍。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import openai

from hello_agents.config import get_settings

logger = logging.getLogger(__name__)

_PLAN_SYSTEM = """你是一个任务分解专家。
将用户的目标分解为清晰的、可执行的步骤序列，以 JSON 数组格式输出。
每个步骤包含：
- id: 步骤编号（字符串，如 "1", "2"）
- desc: 步骤描述（一句话，具体可执行）
- tool_hint: 建议使用的工具（可选，如 "search_memory", "run_command", "web_search"）
- deps: 依赖的步骤 id 列表（如 ["1"] 表示先完成步骤1）

只输出 JSON 数组，不要有其他文字。
"""


@dataclass
class Step:
    """计划中的单个执行步骤。"""
    id: str
    desc: str
    tool_hint: str = ""
    deps: list[str] = field(default_factory=list)


class Planner:
    """
    将用户目标转换为有序 Step 列表。(s03)

    用法：
        planner = Planner()
        steps = await planner.make_plan("帮我整理本周的会议记录")
    """

    def __init__(
        self,
        client: openai.OpenAI | None = None,
        model: str | None = None,
    ) -> None:
        cfg = get_settings()
        self._client = client or openai.OpenAI(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )
        self._model = model or cfg.llm_model_id

    async def make_plan(self, goal: str) -> list[Step]:
        """
        调用 LLM 将目标分解为 Step 列表。
        LLM 调用失败时返回单步兜底计划。
        """
        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=[
                    {"role": "system", "content": _PLAN_SYSTEM},
                    {"role": "user", "content": f"目标：{goal}"},
                ],
                max_tokens=1024,
                temperature=0.2,
            )
            raw = response.choices[0].message.content or ""
            return self._parse_steps(raw.strip())
        except Exception as exc:
            logger.warning("Planner LLM call failed: %s, using fallback", exc)
            return [Step(id="1", desc=goal)]

    def _parse_steps(self, raw: str) -> list[Step]:
        """解析 LLM 返回的 JSON 步骤列表。"""
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return [Step(id="1", desc=raw[:200] or "执行目标")]

        try:
            data: list[dict[str, Any]] = json.loads(raw[start:end])
            steps = []
            for item in data:
                steps.append(
                    Step(
                        id=str(item.get("id", len(steps) + 1)),
                        desc=item.get("desc", ""),
                        tool_hint=item.get("tool_hint", ""),
                        deps=[str(d) for d in item.get("deps", [])],
                    )
                )
            return steps if steps else [Step(id="1", desc="执行目标")]
        except (json.JSONDecodeError, TypeError):
            return [Step(id="1", desc=raw[:200])]

    @staticmethod
    def steps_to_prompt(steps: list[Step]) -> str:
        """将步骤列表转换为可注入 prompt 的文本。"""
        lines = ["## 当前任务计划"]
        for s in steps:
            deps_str = f"（依赖：{', '.join(s.deps)}）" if s.deps else ""
            hint_str = f" [{s.tool_hint}]" if s.tool_hint else ""
            lines.append(f"- [{s.id}] {s.desc}{hint_str}{deps_str}")
        return "\n".join(lines)
