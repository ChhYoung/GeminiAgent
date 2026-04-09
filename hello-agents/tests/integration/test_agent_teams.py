"""
tests/integration/test_agent_teams.py — Agent 团队协作集成测试 (s15/s16)
"""

from __future__ import annotations

import pytest

from hello_agents.teams.team import AgentTeam, TeamMember
from hello_agents.teams.roster import TeamRoster
from hello_agents.teams.coordinator import TeamCoordinator
from hello_agents.multi_agent.mailbox import Mailbox
from hello_agents.multi_agent.protocol import AgentMessage


class TestTeamCoordinator:
    def _make_coordinator(self, tmp_path) -> tuple[TeamCoordinator, Mailbox]:
        mailbox = Mailbox(db_path=str(tmp_path / "test_mailbox.db"))
        coordinator = TeamCoordinator(mailbox=mailbox)
        return coordinator, mailbox

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_members(self, tmp_path):
        coordinator, mailbox = self._make_coordinator(tmp_path)
        team = AgentTeam(name="test-team")
        team.add_member("alice", "coder")
        team.add_member("bob", "reviewer")

        await coordinator.broadcast(team, "start task", from_agent="lead")

        # Alice should have received the broadcast
        alice_msgs = mailbox.read_all("alice")
        assert len(alice_msgs) == 1
        assert alice_msgs[0].msg_type == "broadcast"
        assert "start task" in alice_msgs[0].payload["content"]

        # Bob should also have received it
        bob_msgs = mailbox.read_all("bob")
        assert len(bob_msgs) == 1

    @pytest.mark.asyncio
    async def test_broadcast_excludes_sender(self, tmp_path):
        coordinator, mailbox = self._make_coordinator(tmp_path)
        team = AgentTeam(name="test-team")
        team.add_member("lead", "coordinator")
        team.add_member("alice", "coder")

        await coordinator.broadcast(team, "message", from_agent="lead")

        # Lead should NOT receive the broadcast
        lead_msgs = mailbox.read_all("lead")
        assert len(lead_msgs) == 0

    @pytest.mark.asyncio
    async def test_delegate_sends_delegate_message(self, tmp_path):
        coordinator, mailbox = self._make_coordinator(tmp_path)
        msg_id = await coordinator.delegate(
            to_agent="alice",
            task_desc="implement login feature",
            from_agent="lead",
            expected_format="code",
        )
        assert msg_id is not None
        alice_msgs = mailbox.read_all("alice")
        assert len(alice_msgs) == 1
        assert alice_msgs[0].msg_type == "delegate"
        assert "implement login feature" in alice_msgs[0].payload["task_desc"]

    @pytest.mark.asyncio
    async def test_vote_returns_counts(self, tmp_path):
        coordinator, mailbox = self._make_coordinator(tmp_path)
        team = AgentTeam(name="test-team")
        team.add_member("alice", "coder")
        team.add_member("bob", "reviewer")

        # Pre-populate vote replies (simulating agents responding)
        reply = AgentMessage(
            from_agent="alice",
            to_agent="lead",
            msg_type="vote_reply",
            payload={"vote": "yes"},
        )
        mailbox.send_sync(reply.to_agent, reply)

        result = await coordinator.vote(
            team, "should we proceed?", ["yes", "no"], from_agent="lead", timeout=0.1
        )
        assert "yes" in result
        assert "no" in result
        # At least our pre-populated reply should be counted
        assert result["yes"] >= 1


class TestTeamIntegration:
    def test_full_team_lifecycle(self, tmp_path):
        roster = TeamRoster(directory=tmp_path)

        # Create team
        team = roster.create(
            "engineering",
            members=[
                {"agent_id": "alice", "role": "coder"},
                {"agent_id": "bob", "role": "reviewer"},
            ],
            shared_rules=["Review all code before merging"],
        )
        assert team.team_id is not None

        # Retrieve and verify
        team2 = roster.get(team.team_id)
        assert team2 is not None
        assert len(team2.members) == 2
        assert team2.shared_rules == ["Review all code before merging"]

        # Update: add member
        team2.add_member("carol", "tester")
        roster.update(team2)

        team3 = roster.get(team.team_id)
        assert team3 is not None
        assert len(team3.members) == 3

        # Dissolve
        roster.dissolve(team.team_id)
        assert roster.get(team.team_id) is None

    def test_members_with_role_after_update(self, tmp_path):
        roster = TeamRoster(directory=tmp_path)
        team = roster.create(
            "qa",
            members=[
                {"agent_id": "tester1", "role": "tester"},
                {"agent_id": "tester2", "role": "tester"},
                {"agent_id": "lead", "role": "lead"},
            ],
        )
        testers = team.members_with_role("tester")
        assert len(testers) == 2
        leads = team.members_with_role("lead")
        assert len(leads) == 1
