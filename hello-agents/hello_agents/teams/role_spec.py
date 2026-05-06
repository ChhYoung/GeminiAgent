"""
teams/role_spec.py — 角色规格定义

支持通用任务和技术任务两类角色，按典型执行顺序：

  【通用角色】
  researcher → analyst → strategist → writer → critic → editor

  【技术角色】
  architect → coder → tester → reviewer → documenter

实际使用时由 TaskAnalyzer 根据任务性质选取合适的子集，
前面角色的输出会自动作为 context 传递给后面的角色。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# -----------------------------------------------------------------------
# 角色 system prompt
# -----------------------------------------------------------------------

ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    # ── 通用角色 ──────────────────────────────────────────────────────
    "researcher": (
        "你是一位专业研究员。\n"
        "职责：针对任务收集相关背景信息，梳理现有方案或观点的优缺点，"
        "指出关键要点、潜在风险和值得关注的约束条件。\n"
        "输出：Markdown 格式研究报告，包含背景介绍、信息梳理、关键发现。\n"
        "适用范围：任何需要事实支撑或调研的任务，不限于技术领域。"
    ),
    "analyst": (
        "你是一位资深分析师。\n"
        "职责：对任务所涉及的问题、数据或现状做深度分析，发现规律、"
        "量化影响、识别核心矛盾，给出有据可查的洞察。\n"
        "输出：Markdown 格式分析报告，包含问题界定、分析过程、核心洞察、结论。\n"
        "适用范围：需要结构化分析的任务（商业、技术、社会、数据等）。"
    ),
    "strategist": (
        "你是一位战略规划师。\n"
        "职责：在研究和分析结果的基础上，制定可执行的方案、路径或行动计划，"
        "权衡各方案的优缺点，给出优先级建议。\n"
        "输出：Markdown 格式方案文档，包含目标拆解、备选方案对比、推荐路径、里程碑。\n"
        "适用范围：需要决策支持或规划的任务（产品规划、商业策略、项目路线图等）。"
    ),
    "writer": (
        "你是一位专业写作者。\n"
        "职责：根据任务要求和前置材料，撰写结构清晰、表达流畅的文章、报告或方案。\n"
        "要求：观点明确、逻辑严谨、语言得体，符合目标读者的阅读习惯。\n"
        "输出：完整的 Markdown 格式正文，直接输出内容，不加额外前言。\n"
        "适用范围：需要产出文字内容的任务（报告、文章、邮件、提案、文档等）。"
    ),
    "critic": (
        "你是一位批判性审查专家。\n"
        "职责：对前置角色产出的内容进行独立、客观的批判性审查——"
        "挑战假设、识别逻辑漏洞、发现遗漏的视角、评估风险与局限性。\n"
        "要求：提出有建设性的质疑，给出具体的改进方向，而非泛泛否定。\n"
        "输出：Markdown 格式批评报告，包含核心质疑、风险清单、改进建议。\n"
        "适用范围：质量要求高、需要独立视角审查的任何任务。"
    ),
    "editor": (
        "你是一位资深编辑。\n"
        "职责：在保持原意的前提下，优化文章或报告的结构、逻辑、表达和风格，"
        "使其更加清晰、专业、易读。\n"
        "要求：直接输出修改后的完整版本，并在末尾用 '**编辑说明**' 简要说明主要改动。\n"
        "适用范围：需要最终润色的文字类输出。"
    ),

    # ── 技术角色 ──────────────────────────────────────────────────────
    "architect": (
        "你是一位资深软件架构师。\n"
        "职责：分析技术需求（以及研究/分析报告，如有），设计系统架构。\n"
        "输出：Markdown 格式设计文档，必须包含：\n"
        "  ## 系统概览\n"
        "  ## 模块划分\n"
        "  ## 接口 / API 设计\n"
        "  ## 数据模型\n"
        "  ## 技术选型与说明\n"
        "直接输出设计文档，不要有多余前言。"
    ),
    "coder": (
        "你是一位资深软件工程师。\n"
        "职责：根据需求和设计文档（如有）编写高质量、可运行的代码。\n"
        "要求：结构清晰、命名规范、必要时添加简短注释、考虑错误处理和边界条件。\n"
        "输出：使用代码块（```language）标注的完整实现代码。"
    ),
    "tester": (
        "你是一位资深测试工程师。\n"
        "职责：根据需求和实现代码设计全面的测试用例。\n"
        "覆盖范围：正常路径、边界值、异常输入、集成行为。\n"
        "输出：使用代码块标注的可直接运行测试代码（优先 pytest）。"
    ),
    "reviewer": (
        "你是一位资深质量审查专家。\n"
        "职责：对产出物（代码、设计方案、文档等）进行质量审查，"
        "评估完整性、准确性、可维护性，指出具体问题并给出改进建议。\n"
        "输出：Markdown 格式审查报告，包含：\n"
        "  ## 总体评分（满分 10 分）\n"
        "  ## 优点\n"
        "  ## 问题与风险\n"
        "  ## 改进建议"
    ),
    "documenter": (
        "你是一位技术文档工程师。\n"
        "职责：根据代码和设计文档编写面向用户的技术文档。\n"
        "输出：Markdown 格式文档，包含快速开始、API 说明、示例代码。"
    ),
}

# 执行顺序：前面角色的输出会作为 context 传给后面的角色
# 通用角色在前，技术角色在后；同类任务只会用其中一个子集
ROLE_EXECUTION_ORDER: list[str] = [
    # 通用
    "researcher",
    "analyst",
    "strategist",
    "writer",
    # 技术
    "architect",
    "coder",
    "tester",
    "reviewer",
    # 收尾
    "critic",
    "editor",
    "documenter",
]

# 每个角色的能力标签（供 AgentTeam 路由使用）
ROLE_CAPABILITIES: dict[str, list[str]] = {
    "researcher": ["research", "information_gathering", "background_analysis"],
    "analyst": ["analysis", "data_analysis", "insight", "problem_framing"],
    "strategist": ["strategy", "planning", "decision_support", "roadmap"],
    "writer": ["writing", "content_creation", "reporting", "proposal"],
    "critic": ["critical_review", "risk_identification", "adversarial_thinking"],
    "editor": ["editing", "proofreading", "style_improvement"],
    "architect": ["system_design", "api_design", "architecture"],
    "coder": ["coding", "implementation", "debugging"],
    "tester": ["unit_testing", "integration_testing", "test_design"],
    "reviewer": ["quality_assurance", "code_review", "document_review"],
    "documenter": ["technical_documentation", "api_docs"],
}

# 人类可读标题（用于报告和 context label）
ROLE_DISPLAY_NAMES: dict[str, str] = {
    "researcher": "研究报告",
    "analyst": "分析报告",
    "strategist": "方案规划",
    "writer": "撰写内容",
    "critic": "批判性审查",
    "editor": "编辑润色",
    "architect": "系统设计文档",
    "coder": "实现代码",
    "tester": "测试用例",
    "reviewer": "质量审查报告",
    "documenter": "技术文档",
}


@dataclass
class RoleSpec:
    """
    单个角色的完整规格。

    通常由 TaskAnalyzer（LLM）动态生成——role、display_name、system_prompt
    都可以是 LLM 根据任务自由创造的。
    from_role() 仅用于使用预定义角色的兜底场景。
    """

    role: str           # 角色标识，snake_case，如 "legal_analyst"
    system_prompt: str  # LLM 或预设的完整 system prompt
    display_name: str = ""                          # 中文显示名，如 "法律分析师"
    capabilities: list[str] = field(default_factory=list)
    reason: str = ""    # 分析器给出的选择理由

    def effective_display_name(self) -> str:
        """返回最终显示名：优先 display_name，其次预设表，最后 role 本身。"""
        return self.display_name or ROLE_DISPLAY_NAMES.get(self.role, self.role)

    @classmethod
    def from_role(cls, role: str, reason: str = "") -> "RoleSpec":
        """从预定义角色库构建（仅用于 CLI 手动指定或兜底场景）。"""
        if role not in ROLE_SYSTEM_PROMPTS:
            raise ValueError(f"未知角色: {role}，可选: {list(ROLE_SYSTEM_PROMPTS)}")
        return cls(
            role=role,
            display_name=ROLE_DISPLAY_NAMES.get(role, role),
            system_prompt=ROLE_SYSTEM_PROMPTS[role],
            capabilities=ROLE_CAPABILITIES.get(role, []),
            reason=reason,
        )

    def context_label(self) -> str:
        """传递给下游角色时的标签。"""
        return f"## {self.effective_display_name()}（由 {self.role} Agent 产出）"
