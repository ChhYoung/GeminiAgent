"""teams — s15/s16/s17 Agent 团队协作 + 动态任务流水线"""
from hello_agents.teams.team import AgentTeam, TeamMember
from hello_agents.teams.roster import TeamRoster
from hello_agents.teams.role_spec import RoleSpec, ROLE_SYSTEM_PROMPTS, ROLE_CAPABILITIES
from hello_agents.teams.analyzer import TaskAnalyzer
from hello_agents.teams.pipeline import TaskPipeline, TaskResult, RoleOutput

__all__ = [
    "AgentTeam",
    "TeamMember",
    "TeamRoster",
    "RoleSpec",
    "ROLE_SYSTEM_PROMPTS",
    "ROLE_CAPABILITIES",
    "TaskAnalyzer",
    "TaskPipeline",
    "TaskResult",
    "RoleOutput",
]
