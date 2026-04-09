"""coding_skill — 代码生成专项技能"""
from hello_agents.skills.registry import Skill

SKILL = Skill(
    name="coding",
    description="代码生成、调试和代码审查专项技能",
    prompt_snippet=(
        "你正在使用代码生成技能。\n"
        "- 优先提供完整、可运行的代码示例\n"
        "- 对每个关键步骤添加注释\n"
        "- 指出潜在的边界情况和错误处理\n"
        "- 使用 run_terminal 工具验证代码可执行性"
    ),
    tools=["run_terminal", "create_note", "web_search"],
)
