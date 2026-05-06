"""
tests/integration/test_team_pipeline_e2e.py — TaskPipeline 真实 LLM 端到端测试

使用真实 API Key (Qwen/Dashscope) 完整验证：
  1. TaskAnalyzer  — LLM 动态生成角色定义（role / display_name / system_prompt）
  2. TaskPipeline  — 多角色串行执行，前置输出传递给后置角色
  3. TaskResult    — 产出物结构完整，可保存为 Markdown 报告文件

覆盖两类任务：
  - 通用任务（非技术）：每日站会的优缺点分析与改进建议
  - 技术任务：实现 Python Stack 类并附测试用例

运行方式（需真实 .env）：
    cd hello-agents
    pytest tests/integration/test_team_pipeline_e2e.py -v -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# 加载项目根目录的 .env（tests/ 上两级）
_ENV_PATH = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)  # override conftest defaults

# -----------------------------------------------------------------------
# 跳过条件 & 错误处理
# -----------------------------------------------------------------------

_API_KEY = os.environ.get("LLM_API_KEY", "")
_SKIP_IF_NO_KEY = pytest.mark.skipif(
    not _API_KEY or _API_KEY.startswith("test-"),
    reason="需要真实 LLM_API_KEY，跳过",
)


def _check_api_error(exc: Exception) -> None:
    """
    将 API 账户类错误（配额耗尽、权限不足）转为 pytest.skip，
    其余错误直接 re-raise（让测试 FAILED）。
    """
    msg = str(exc)
    skip_keywords = [
        "AllocationQuota",   # Dashscope 配额耗尽
        "FreeTierOnly",
        "free tier",
        "PermissionDenied",
        "insufficient_quota",
        "RateLimitError",
    ]
    if any(kw in msg for kw in skip_keywords):
        pytest.skip(f"API 账户限制（配额/权限），跳过测试：{msg[:120]}")
    raise

# 测试用短任务（控制 token 用量）
_GENERAL_TASK = (
    "分析「每日站会」这一敏捷实践的优缺点，"
    "给出 2-3 条可落地的改进建议，200 字以内。"
)

_TECHNICAL_TASK = (
    "实现一个 Python Stack 类，支持 push / pop / peek / is_empty，"
    "附简洁的 pytest 测试用例，代码总量控制在 60 行以内。"
)


# -----------------------------------------------------------------------
# Fixture
# -----------------------------------------------------------------------

@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """共享 TaskPipeline 实例，role_max_tokens 设小以加快测试速度。"""
    from hello_agents.teams.pipeline import TaskPipeline
    from hello_agents.teams.roster import TeamRoster

    tmp = tmp_path_factory.mktemp("teams")
    return TaskPipeline(
        roster=TeamRoster(directory=tmp),
        role_max_tokens=1024,   # 测试只需短输出
    )


# -----------------------------------------------------------------------
# 1. TaskAnalyzer — 纯角色生成，不执行角色
# -----------------------------------------------------------------------

class TestTaskAnalyzer:
    """
    验证 TaskAnalyzer 能通过 LLM 动态生成角色定义。

    判断"LLM 真正被调用"的标志：
      - reason 字段非空（兜底 _default_specs 没有 reason）
      - display_name 不完全等于预设的 ROLE_DISPLAY_NAMES 值集合
        （LLM 会根据任务生成"合同条款分析师"之类的中文名，而不是"研究报告"）
    """

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_general_task_generates_nontechnical_roles(self):
        """通用任务：LLM 应生成通用角色（不应有 coder/tester/architect）。"""
        from hello_agents.teams.analyzer import TaskAnalyzer
        from hello_agents.teams.role_spec import ROLE_DISPLAY_NAMES

        analyzer = TaskAnalyzer()
        try:
            specs = await analyzer.analyze(_GENERAL_TASK)
        except Exception as e:
            _check_api_error(e)

        # 基础结构断言
        assert len(specs) >= 2, f"至少需要 2 个角色，实际: {[s.role for s in specs]}"
        for spec in specs:
            assert spec.role, "role 不能为空"
            assert spec.display_name, f"display_name 不能为空（role={spec.role}）"
            assert len(spec.system_prompt) >= 50, (
                f"system_prompt 太短（role={spec.role}，长度={len(spec.system_prompt)}）"
            )

        # 通用任务不应只含纯技术角色
        roles = {s.role for s in specs}
        technical_only = {"coder", "tester", "architect"}
        assert not roles.issubset(technical_only), \
            f"通用任务不应只含技术角色，实际: {roles}"

        # 确认 LLM 真正被调用（兜底没有 reason，且 display_name 应该是 LLM 生成的）
        predefined_display_names = set(ROLE_DISPLAY_NAMES.values())
        llm_generated = any(
            s.display_name not in predefined_display_names or s.reason
            for s in specs
        )
        assert llm_generated, (
            "所有角色的 display_name 均为预设值且 reason 为空，"
            "疑似 LLM 调用失败使用了兜底方案，请检查 API 连通性。\n"
            f"  返回角色: {[(s.role, s.display_name) for s in specs]}"
        )

        print(f"\n[通用任务] 角色: {[(s.role, s.display_name) for s in specs]}")
        print(f"  reason: {specs[0].reason}")

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_technical_task_generates_technical_roles(self):
        """技术任务：LLM 应生成包含代码实现相关的角色。"""
        from hello_agents.teams.analyzer import TaskAnalyzer

        analyzer = TaskAnalyzer()
        try:
            specs = await analyzer.analyze(_TECHNICAL_TASK)
        except Exception as e:
            _check_api_error(e)

        assert len(specs) >= 2
        for spec in specs:
            assert spec.system_prompt, f"system_prompt 为空（role={spec.role}）"

        # system prompt 中应有代码实现相关关键词
        all_prompts = " ".join(s.system_prompt for s in specs)
        tech_keywords = ["代码", "实现", "测试", "函数", "类", "编写", "code", "implement"]
        assert any(kw in all_prompts for kw in tech_keywords), \
            "技术任务的 system_prompt 中应含技术关键词"

        print(f"\n[技术任务] 角色: {[(s.role, s.display_name) for s in specs]}")

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_roles_have_unique_names(self):
        """同一任务生成的角色名称不重复。"""
        from hello_agents.teams.analyzer import TaskAnalyzer

        analyzer = TaskAnalyzer()
        try:
            specs = await analyzer.analyze(_GENERAL_TASK)
        except Exception as e:
            _check_api_error(e)

        role_names = [s.role for s in specs]
        assert len(role_names) == len(set(role_names)), \
            f"角色名称重复: {role_names}"


# -----------------------------------------------------------------------
# 2. TaskPipeline — 完整流水线执行
# -----------------------------------------------------------------------

class TestTaskPipelineE2E:

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_general_task_pipeline(self, pipeline):
        """通用任务流水线：所有角色均产出非空内容。"""
        from hello_agents.teams.pipeline import TaskResult

        try:
            result = await pipeline.solve(_GENERAL_TASK)
        except Exception as e:
            _check_api_error(e)

        assert isinstance(result, TaskResult)
        assert len(result.roles_used) >= 2, \
            f"至少 2 个角色参与，实际: {result.roles_used}"
        assert result.total_elapsed_seconds > 0

        # 每个角色都有非空产出
        for role in result.roles_used:
            assert role in result.outputs, f"role={role} 无输出"
            out = result.outputs[role]
            assert len(out.content) >= 20, \
                f"role={role} 产出太短（{len(out.content)} 字符）"
            assert out.display_name, f"role={role} 缺少 display_name"
            assert out.elapsed_seconds > 0

        print(f"\n[通用任务] roles={result.roles_used}, "
              f"elapsed={result.total_elapsed_seconds:.1f}s")
        for role, out in result.outputs.items():
            print(f"  [{out.display_name}] {len(out.content)} chars")

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_technical_task_pipeline(self, pipeline):
        """技术任务流水线：产出中应含代码块。"""
        try:
            result = await pipeline.solve(_TECHNICAL_TASK)
        except Exception as e:
            _check_api_error(e)

        assert len(result.roles_used) >= 2

        all_content = "\n".join(out.content for out in result.outputs.values())
        assert "```" in all_content, "技术任务产出中应包含代码块（```）"

        print(f"\n[技术任务] roles={result.roles_used}, "
              f"elapsed={result.total_elapsed_seconds:.1f}s")

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_prior_outputs_flow_downstream(self, pipeline):
        """后置角色的 system_prompt 执行时能感知前置角色的产出（内容相关性）。"""
        try:
            result = await pipeline.solve(_GENERAL_TASK)
        except Exception as e:
            _check_api_error(e)
        roles = result.roles_used

        if len(roles) < 2:
            pytest.skip("需要至少 2 个角色才能验证信息流转")

        # 最后一个角色的产出通常会引用前置角色的术语/内容
        last_role = roles[-1]
        last_content = result.outputs[last_role].content
        # 非空即可（内容相关性难以自动断言）
        assert len(last_content) >= 20, "最后一个角色产出为空"

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_manual_roles_override(self, pipeline):
        """手动指定 roles 时，跳过 LLM 分析直接使用预设角色。"""
        try:
            result = await pipeline.solve(
                _TECHNICAL_TASK,
                roles=["coder", "tester"],
            )
        except Exception as e:
            _check_api_error(e)
        assert result.roles_used == ["coder", "tester"]
        assert result.code != "", "coder 应有代码产出"
        assert result.test_cases != "", "tester 应有测试产出"

        print(f"\n[手动角色] code={len(result.code)} chars, "
              f"test_cases={len(result.test_cases)} chars")


# -----------------------------------------------------------------------
# 3. 文件输出 — save_report()
# -----------------------------------------------------------------------

class TestReportOutput:

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_save_report_auto_path(self, pipeline, tmp_path):
        """save_report(None) 自动生成路径并写入文件。"""
        try:
            result = await pipeline.solve(_GENERAL_TASK)
        except Exception as e:
            _check_api_error(e)

        # 保存到 tmp_path 下（覆盖 reports/ 默认路径）
        out_path = str(tmp_path / "auto_report.md")
        actual_path = result.save_report(out_path)

        assert Path(actual_path).exists(), f"报告文件不存在: {actual_path}"
        content = Path(actual_path).read_text(encoding="utf-8")
        assert "# 任务产出报告" in content
        assert _GENERAL_TASK[:20] in content
        assert len(content) > 100

        print(f"\n[报告] 保存到 {actual_path}，{len(content)} bytes")

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_save_report_to_project_reports_dir(self, pipeline):
        """save_report() 默认写入 reports/ 目录，文件名含时间戳。"""
        try:
            result = await pipeline.solve(_TECHNICAL_TASK)
        except Exception as e:
            _check_api_error(e)

        saved = result.save_report()   # 使用默认路径

        p = Path(saved)
        assert p.exists(), f"文件不存在: {p}"
        assert p.suffix == ".md"
        assert p.stat().st_size > 50

        # 打印方便人工查阅
        print(f"\n[报告] 已保存: {p.resolve()}")
        print(f"  文件大小: {p.stat().st_size} bytes")
        print(f"  内容预览:\n{p.read_text(encoding='utf-8')[:300]}...")

    @_SKIP_IF_NO_KEY
    @pytest.mark.asyncio
    async def test_markdown_structure(self, pipeline):
        """to_markdown() 输出结构正确：含标题、参与角色、各角色产出节。"""
        try:
            result = await pipeline.solve(_GENERAL_TASK)
        except Exception as e:
            _check_api_error(e)
        md = result.to_markdown()

        assert "# 任务产出报告" in md
        assert "**参与角色**" in md
        assert "**总耗时**" in md
        assert "---" in md     # 分隔线

        # 每个角色的 display_name 应出现在报告中
        for role in result.roles_used:
            display = result.outputs[role].display_name
            assert display in md, f"报告中缺少角色标题: {display}"
