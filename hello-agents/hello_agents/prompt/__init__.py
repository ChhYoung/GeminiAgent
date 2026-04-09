"""prompt — s10 分段式 System Prompt 组装"""
from hello_agents.prompt.builder import PromptBuilder
from hello_agents.prompt.sections import IDENTITY, CAPABILITIES, RULES

__all__ = ["PromptBuilder", "IDENTITY", "CAPABILITIES", "RULES"]
