"""research_skill — 研究调查专项技能"""
from hello_agents.skills.registry import Skill

SKILL = Skill(
    name="research",
    description="深度研究、信息检索和报告撰写专项技能",
    prompt_snippet=(
        "你正在使用研究调查技能。\n"
        "- 先搜索多个来源（web_search + search_knowledge）再综合\n"
        "- 明确区分事实和推断\n"
        "- 列出信息来源，提高可信度\n"
        "- 用 create_note 记录关键发现供后续参考"
    ),
    tools=["web_search", "search_knowledge", "search_memory", "create_note"],
)
