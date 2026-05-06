"""
teams/analyzer.py — 任务分析器 (TaskAnalyzer)

给定任务描述，调用 LLM 分析需要哪些角色，返回有序 RoleSpec 列表。
这是 pipeline 的第一步，决定了团队组成。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import openai

from hello_agents.config import get_settings
from hello_agents.teams.role_spec import RoleSpec

logger = logging.getLogger(__name__)

_ANALYZER_SYSTEM = """你是一个 Agent 团队设计专家。
给定任务，你需要从零设计一组最合适的 Agent 角色——包括角色名称、职责描述和专属 system prompt。

## 设计原则

1. **角色数量**：2–5 个。太少覆盖不全，太多则冗余
2. **职责单一**：每个角色边界清晰，不与其他角色重叠
3. **信息流转**：角色按执行顺序排列，前置角色的产出会传递给后置角色
4. **贴合任务**：角色名称和 system_prompt 应高度针对该具体任务，
   而不是套用通用模板。例如：
   - 法律合同审查 → 合同分析师 + 法律风险评估师 + 修改建议师
   - 营销方案 → 市场洞察师 + 创意策划师 + 文案撰写师 + 效果评估师
   - Python 工具库 → 接口设计师 + 实现工程师 + 测试工程师

5. **system_prompt 要求**：
   - 明确说明角色的具体职责（结合任务背景，不要泛泛而谈）
   - 指定输出格式（Markdown / 代码块 / JSON 等）
   - 说明需要参考哪些前置角色的输出（如有）

## 输出格式

只输出 JSON，不要有其他文字：
{
  "reason": "一句话说明团队设计思路",
  "roles": [
    {
      "role": "snake_case_identifier",
      "display_name": "中文显示名",
      "system_prompt": "针对本任务的完整 system prompt（100–300 字）",
      "capabilities": ["能力标签1", "能力标签2"]
    }
  ]
}
"""


class TaskAnalyzer:
    """
    任务角色分析器。

    调用 LLM 分析任务描述，返回需要参与的 RoleSpec 列表（保持执行顺序）。

    用法：
        analyzer = TaskAnalyzer()
        specs = await analyzer.analyze("实现一个 JWT 认证中间件，支持 refresh token")
        # → [RoleSpec(architect), RoleSpec(coder), RoleSpec(tester)]
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

    async def analyze(self, task_description: str) -> list[RoleSpec]:
        """
        分析任务，返回有序 RoleSpec 列表。

        失败时返回兜底方案：[architect, coder, tester]。
        """
        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=[
                    {"role": "system", "content": _ANALYZER_SYSTEM},
                    {"role": "user", "content": f"任务描述：\n{task_description}"},
                ],
                max_tokens=512,
                temperature=0.1,
            )
            raw = response.choices[0].message.content or ""
            return self._parse_roles(raw.strip(), task_description)
        except Exception as exc:
            logger.warning("TaskAnalyzer LLM call failed: %s，使用默认角色组合", exc)
            return self._default_specs()

    def _parse_roles(self, raw: str, task_desc: str) -> list[RoleSpec]:
        """从 LLM 输出中解析完整角色定义列表。"""
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            logger.warning("TaskAnalyzer: 无法解析 JSON，raw=%r", raw[:200])
            return self._default_specs()

        try:
            data: dict[str, Any] = json.loads(raw[start:end])
            roles_data: list[dict] = data.get("roles", [])
            reason: str = data.get("reason", "")

            specs: list[RoleSpec] = []
            for item in roles_data:
                role = str(item.get("role", "")).strip()
                system_prompt = str(item.get("system_prompt", "")).strip()
                if not role or not system_prompt:
                    logger.warning("TaskAnalyzer: 角色缺少 role 或 system_prompt，跳过: %r", item)
                    continue
                specs.append(RoleSpec(
                    role=role,
                    display_name=str(item.get("display_name", role)),
                    system_prompt=system_prompt,
                    capabilities=list(item.get("capabilities", [])),
                    reason=reason,
                ))

            if not specs:
                logger.warning("TaskAnalyzer: 解析后角色列表为空，使用默认")
                return self._default_specs()

            logger.info(
                "TaskAnalyzer: task=%r → roles=%s，reason=%s",
                task_desc[:60],
                [(s.role, s.display_name) for s in specs],
                reason,
            )
            return specs
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("TaskAnalyzer: JSON 解析失败 %s，raw=%r", exc, raw[:200])
            return self._default_specs()

    @staticmethod
    def _default_specs() -> list[RoleSpec]:
        # 通用兜底：覆盖大多数非技术任务
        return [
            RoleSpec.from_role("researcher", "默认方案"),
            RoleSpec.from_role("writer", "默认方案"),
            RoleSpec.from_role("reviewer", "默认方案"),
        ]
