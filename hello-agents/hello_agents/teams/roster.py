"""
teams/roster.py — 团队注册表 (s15)

持久化到 ~/.agent/teams/{team_id}.json，支持跨进程共享。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from hello_agents.teams.team import AgentTeam, TeamMember

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".agent" / "teams"


class TeamRoster:
    """
    团队注册表。

    用法：
        roster = TeamRoster()
        team = roster.create("alpha", [{"agent_id": "a1", "role": "coder"}])
        roster.get("alpha-team-id")
        roster.dissolve(team.team_id)
    """

    def __init__(self, directory: Path | str = _DEFAULT_DIR) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, AgentTeam] = {}

    def create(
        self,
        name: str,
        members: list[dict] | None = None,
        shared_rules: list[str] | None = None,
    ) -> AgentTeam:
        """创建并持久化一支新团队。"""
        team = AgentTeam(name=name, shared_rules=shared_rules or [])
        for m in (members or []):
            team.add_member(m["agent_id"], m.get("role", "member"), m.get("capabilities", []))
        self._save(team)
        self._cache[team.team_id] = team
        logger.info("Team created: %s (%s)", team.name, team.team_id)
        return team

    def get(self, team_id: str) -> AgentTeam | None:
        if team_id in self._cache:
            return self._cache[team_id]
        path = self._dir / f"{team_id}.json"
        if not path.exists():
            return None
        try:
            team = AgentTeam.from_dict(json.loads(path.read_text(encoding="utf-8")))
            self._cache[team_id] = team
            return team
        except Exception as exc:
            logger.warning("Failed to load team %s: %s", team_id, exc)
            return None

    def update(self, team: AgentTeam) -> None:
        """更新团队数据（添加/移除成员后调用）。"""
        self._save(team)
        self._cache[team.team_id] = team

    def dissolve(self, team_id: str) -> bool:
        """解散团队（删除持久化文件）。"""
        path = self._dir / f"{team_id}.json"
        self._cache.pop(team_id, None)
        if path.exists():
            path.unlink()
            logger.info("Team dissolved: %s", team_id)
            return True
        return False

    def list_teams(self) -> list[AgentTeam]:
        """列出所有团队（从磁盘读取）。"""
        teams = []
        for p in self._dir.glob("*.json"):
            team = self.get(p.stem)
            if team:
                teams.append(team)
        return teams

    def _save(self, team: AgentTeam) -> None:
        path = self._dir / f"{team.team_id}.json"
        path.write_text(json.dumps(team.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
