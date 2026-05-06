"""
teams/pipeline.py — 动态 Agent 团队流水线

完整流程：
  任务描述
    │
    ▼  TaskAnalyzer.analyze()
  RoleSpec 列表（有序）
    │
    ▼  TaskPipeline.run()
  逐角色执行 SubAgentRunner：
    每个角色获得「原始任务 + 所有前置角色的输出」作为 context
    │
    ▼
  TaskResult（design_doc / code / test_cases / review / ...）

对外唯一入口：TaskPipeline.solve(task_description)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import openai

from hello_agents.config import get_settings
from hello_agents.teams.analyzer import TaskAnalyzer
from hello_agents.teams.role_spec import RoleSpec
from hello_agents.teams.team import AgentTeam, TeamMember
from hello_agents.teams.roster import TeamRoster

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# 产出物容器
# -----------------------------------------------------------------------

@dataclass
class RoleOutput:
    """单个角色的执行结果。"""
    role: str
    content: str
    elapsed_seconds: float = 0.0
    display_name: str = ""  # LLM 生成的中文显示名


@dataclass
class TaskResult:
    """
    团队协作的最终产出。

    按角色分别存储，同时提供常用快捷字段：
      design_doc   → architect 输出
      code         → coder 输出
      test_cases   → tester 输出
      review       → reviewer 输出
    """
    task_description: str
    roles_used: list[str] = field(default_factory=list)
    outputs: dict[str, RoleOutput] = field(default_factory=dict)
    team_id: str = ""
    total_elapsed_seconds: float = 0.0

    # 快捷字段
    @property
    def design_doc(self) -> str:
        return self._get("architect")

    @property
    def code(self) -> str:
        return self._get("coder")

    @property
    def test_cases(self) -> str:
        return self._get("tester")

    @property
    def review(self) -> str:
        return self._get("reviewer")

    @property
    def research(self) -> str:
        return self._get("researcher")

    @property
    def analysis(self) -> str:
        return self._get("analyst")

    @property
    def strategy(self) -> str:
        return self._get("strategist")

    @property
    def writing(self) -> str:
        return self._get("writer")

    @property
    def critique(self) -> str:
        return self._get("critic")

    @property
    def edited(self) -> str:
        return self._get("editor")

    @property
    def documentation(self) -> str:
        return self._get("documenter")

    def _get(self, role: str) -> str:
        return self.outputs[role].content if role in self.outputs else ""

    def to_markdown(self) -> str:
        """将所有产出格式化为 Markdown 报告。"""
        from hello_agents.teams.role_spec import ROLE_DISPLAY_NAMES

        # 角色显示名：优先 RoleOutput.display_name，其次预设表，最后 role 本身
        def _title(out: RoleOutput) -> str:
            return out.display_name or ROLE_DISPLAY_NAMES.get(out.role, out.role)

        role_team_str = " → ".join(
            (self.outputs[r].display_name or r) if r in self.outputs else r
            for r in self.roles_used
        )
        lines = [
            "# 任务产出报告",
            "",
            f"**任务**：{self.task_description}",
            f"**参与角色**：{role_team_str}",
            f"**总耗时**：{self.total_elapsed_seconds:.1f}s",
            "",
        ]
        for role in self.roles_used:
            if role in self.outputs:
                out = self.outputs[role]
                lines += [
                    "---",
                    "",
                    f"## {_title(out)}",
                    "",
                    out.content,
                    "",
                    f"*（耗时 {out.elapsed_seconds:.1f}s）*",
                    "",
                ]
        return "\n".join(lines)

    def save_report(self, path: str | None = None) -> str:
        """
        将报告写入 Markdown 文件，返回实际写入路径。

        若 path 为 None，自动在 reports/ 目录下按时间戳生成文件名。
        """
        import re
        from datetime import datetime
        from pathlib import Path

        if path is None:
            reports_dir = Path(__file__).parent.parent.parent.parent / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^\w一-鿿]+", "_", self.task_description[:30]).strip("_")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(reports_dir / f"{ts}_{slug}.md")

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_markdown(), encoding="utf-8")
        logger.info("TaskResult: 报告已保存到 %s", path)
        return path


# -----------------------------------------------------------------------
# 角色 SubAgent 执行器
# -----------------------------------------------------------------------

class _RoleRunner:
    """
    单角色 LLM 执行器。

    每个角色都有：
      - 独立的 system prompt（来自 RoleSpec）
      - 全新的 messages[]，不共享主对话上下文
      - 完整的任务描述 + 所有前置角色的输出作为 context
    """

    _MAX_ROUNDS = 3  # 角色 Agent 不需要工具调用，轮数少即可

    def __init__(
        self,
        spec: RoleSpec,
        client: openai.OpenAI,
        model: str,
        max_tokens: int = 4096,
    ) -> None:
        self._spec = spec
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    async def run(
        self,
        task_description: str,
        prior_outputs: list[tuple[RoleSpec, str]],
    ) -> str:
        """
        执行角色任务。

        Args:
            task_description: 原始任务描述
            prior_outputs: 前置角色的 (spec, output) 列表

        Returns:
            角色产出的文本内容
        """
        user_content = self._build_user_content(task_description, prior_outputs)
        messages: list[dict] = [
            {"role": "system", "content": self._spec.system_prompt},
            {"role": "user", "content": user_content},
        ]

        for _ in range(self._MAX_ROUNDS):
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self._model,
                messages=messages,
                temperature=0.3,
                max_tokens=self._max_tokens,
            )
            message = response.choices[0].message
            # 角色 agent 不使用工具，直接返回文本
            if message.content:
                return message.content.strip()
            messages.append({"role": "assistant", "content": message.content or ""})
            messages.append({"role": "user", "content": "请继续完成任务。"})

        return ""

    def _build_user_content(
        self,
        task_description: str,
        prior_outputs: list[tuple[RoleSpec, str]],
    ) -> str:
        parts = [f"## 任务描述\n\n{task_description}"]

        if prior_outputs:
            parts.append("\n\n---\n\n## 参考材料（来自团队前置角色）")
            for spec, content in prior_outputs:
                parts.append(f"\n\n{spec.context_label()}\n\n{content}")

        parts.append(f"\n\n---\n\n请根据以上信息完成你作为 **{self._spec.role}** 的职责。")
        return "".join(parts)


# -----------------------------------------------------------------------
# 主入口：TaskPipeline
# -----------------------------------------------------------------------

class TaskPipeline:
    """
    动态 Agent 团队流水线。

    用法：
        pipeline = TaskPipeline()
        result = await pipeline.solve("实现一个 LRU Cache，支持并发访问")
        print(result.code)
        print(result.test_cases)
        print(result.to_markdown())

    高级用法（指定角色，跳过分析）：
        result = await pipeline.solve(task, roles=["coder", "tester"])
    """

    def __init__(
        self,
        client: openai.OpenAI | None = None,
        model: str | None = None,
        analyzer: TaskAnalyzer | None = None,
        roster: TeamRoster | None = None,
        role_max_tokens: int = 4096,
    ) -> None:
        cfg = get_settings()
        self._client = client or openai.OpenAI(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )
        self._model = model or cfg.llm_model_id
        self._analyzer = analyzer or TaskAnalyzer(client=self._client, model=self._model)
        self._roster = roster or TeamRoster()
        self._role_max_tokens = role_max_tokens

    async def solve(
        self,
        task_description: str,
        roles: list[str] | None = None,
    ) -> TaskResult:
        """
        完整流程：分析 → 组建团队 → 逐角色执行 → 返回结果。

        Args:
            task_description: 任务文档或问题描述
            roles:            可选，直接指定角色跳过 LLM 分析
        """
        t0 = time.monotonic()

        # Step 1: 分析任务 → 角色列表
        if roles:
            specs = self._roles_to_specs(roles)
        else:
            logger.info("TaskPipeline: 分析任务角色...")
            specs = await self._analyzer.analyze(task_description)

        role_names = [s.role for s in specs]
        logger.info("TaskPipeline: 确定角色 %s", role_names)

        # Step 2: 创建 AgentTeam（持久化记录）
        team = self._build_team(task_description, specs)

        # Step 3: 逐角色执行（串行，前置输出累积传递）
        result = TaskResult(
            task_description=task_description,
            roles_used=role_names,
            team_id=team.team_id,
        )
        prior_outputs: list[tuple[RoleSpec, str]] = []

        for spec in specs:
            logger.info("TaskPipeline: 执行角色 [%s]...", spec.role)
            t_role = time.monotonic()

            runner = _RoleRunner(spec=spec, client=self._client, model=self._model, max_tokens=self._role_max_tokens)
            content = await runner.run(task_description, prior_outputs)

            elapsed = time.monotonic() - t_role
            result.outputs[spec.role] = RoleOutput(
                role=spec.role,
                content=content,
                elapsed_seconds=elapsed,
                display_name=spec.effective_display_name(),
            )
            prior_outputs.append((spec, content))
            logger.info(
                "TaskPipeline: [%s] 完成，耗时 %.1fs，输出 %d 字符",
                spec.role,
                elapsed,
                len(content),
            )

        result.total_elapsed_seconds = time.monotonic() - t0
        logger.info(
            "TaskPipeline: 全部完成，总耗时 %.1fs",
            result.total_elapsed_seconds,
        )
        return result

    def _roles_to_specs(self, roles: list[str]) -> list[RoleSpec]:
        from hello_agents.teams.role_spec import ROLE_EXECUTION_ORDER
        ordered = [r for r in ROLE_EXECUTION_ORDER if r in roles]
        # 保留用户指定但不在预定义顺序中的角色（追加到末尾）
        extras = [r for r in roles if r not in ROLE_EXECUTION_ORDER]
        return [RoleSpec.from_role(r, "用户指定") for r in ordered + extras]

    def _build_team(self, task_desc: str, specs: list[RoleSpec]) -> AgentTeam:
        """在 TeamRoster 中创建并持久化本次执行的 AgentTeam。"""
        short_task = task_desc[:40].replace("\n", " ")
        members = [
            {
                "agent_id": f"{s.role}_agent",
                "role": s.role,
                "capabilities": s.capabilities,
            }
            for s in specs
        ]
        shared_rules = [
            "每个角色只输出自身职责范围内的内容",
            "产出需直接可用，不加多余的客套话",
            "代码必须有完整的函数/类结构",
        ]
        team = self._roster.create(
            name=f"task-team: {short_task}",
            members=members,
            shared_rules=shared_rules,
        )
        return team
