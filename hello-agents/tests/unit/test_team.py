"""
tests/unit/test_team.py — Agent 团队测试 (s15)
"""

from __future__ import annotations

import pytest

from hello_agents.teams.team import AgentTeam, TeamMember
from hello_agents.teams.roster import TeamRoster


class TestAgentTeam:
    def test_create_team(self):
        team = AgentTeam(name="alpha")
        assert team.name == "alpha"
        assert len(team.team_id) > 0
        assert team.members == []

    def test_add_member(self):
        team = AgentTeam(name="alpha")
        m = team.add_member("alice", "coder", ["python", "testing"])
        assert m.agent_id == "alice"
        assert m.role == "coder"
        assert "python" in m.capabilities
        assert len(team.members) == 1

    def test_add_duplicate_member_overwrites(self):
        team = AgentTeam(name="alpha")
        team.add_member("alice", "coder")
        team.add_member("alice", "reviewer")  # same agent_id
        assert len(team.members) == 1
        assert team.members[0].role == "reviewer"

    def test_remove_member(self):
        team = AgentTeam(name="alpha")
        team.add_member("alice", "coder")
        ok = team.remove_member("alice")
        assert ok is True
        assert len(team.members) == 0

    def test_remove_nonexistent_member(self):
        team = AgentTeam(name="alpha")
        assert team.remove_member("ghost") is False

    def test_get_member(self):
        team = AgentTeam(name="alpha")
        team.add_member("bob", "reviewer")
        m = team.get_member("bob")
        assert m is not None
        assert m.role == "reviewer"

    def test_get_nonexistent_member(self):
        team = AgentTeam(name="alpha")
        assert team.get_member("ghost") is None

    def test_members_with_role(self):
        team = AgentTeam(name="alpha")
        team.add_member("a1", "coder")
        team.add_member("a2", "coder")
        team.add_member("a3", "reviewer")
        coders = team.members_with_role("coder")
        assert len(coders) == 2

    def test_members_with_capability(self):
        team = AgentTeam(name="alpha")
        team.add_member("a1", "coder", ["python"])
        team.add_member("a2", "coder", ["javascript"])
        python_devs = team.members_with_capability("python")
        assert len(python_devs) == 1

    def test_shared_memory_ns_auto_set(self):
        team = AgentTeam(name="test")
        assert team.shared_memory_ns.startswith("team:")

    def test_to_dict_from_dict_roundtrip(self):
        team = AgentTeam(name="roundtrip")
        team.add_member("a1", "coder")
        team.shared_rules = ["rule1", "rule2"]
        d = team.to_dict()
        team2 = AgentTeam.from_dict(d)
        assert team2.team_id == team.team_id
        assert team2.name == team.name
        assert len(team2.members) == 1
        assert team2.shared_rules == ["rule1", "rule2"]


class TestTeamRoster:
    def test_create_and_get(self, tmp_path):
        roster = TeamRoster(directory=tmp_path)
        team = roster.create("beta", [{"agent_id": "x", "role": "worker"}])
        retrieved = roster.get(team.team_id)
        assert retrieved is not None
        assert retrieved.name == "beta"
        assert len(retrieved.members) == 1

    def test_dissolve(self, tmp_path):
        roster = TeamRoster(directory=tmp_path)
        team = roster.create("gamma")
        ok = roster.dissolve(team.team_id)
        assert ok is True
        assert roster.get(team.team_id) is None

    def test_dissolve_nonexistent(self, tmp_path):
        roster = TeamRoster(directory=tmp_path)
        assert roster.dissolve("ghost") is False

    def test_list_teams(self, tmp_path):
        roster = TeamRoster(directory=tmp_path)
        roster.create("t1")
        roster.create("t2")
        teams = roster.list_teams()
        assert len(teams) == 2

    def test_update(self, tmp_path):
        roster = TeamRoster(directory=tmp_path)
        team = roster.create("delta")
        team.add_member("new_agent", "coder")
        roster.update(team)
        team2 = roster.get(team.team_id)
        assert team2 is not None
        assert len(team2.members) == 1
