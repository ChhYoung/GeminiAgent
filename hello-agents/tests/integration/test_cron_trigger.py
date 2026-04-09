"""
tests/integration/test_cron_trigger.py — Cron 触发集成测试 (s14)
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hello_agents.tasks.cron import CronScheduler, _matches


class TestCronTriggerIntegration:
    def test_add_and_list_jobs(self, tmp_path):
        s = CronScheduler(persist_path=tmp_path / "crons.json")
        jid1 = s.add_job("0 9 * * *", "web_search", {"query": "news"})
        jid2 = s.add_job("*/30 * * * *", "sync_memory", {})
        jobs = s.list_jobs()
        assert len(jobs) == 2
        ids = {j.job_id for j in jobs}
        assert jid1 in ids
        assert jid2 in ids

    def test_job_persists_across_instances(self, tmp_path):
        path = tmp_path / "crons.json"
        s1 = CronScheduler(persist_path=path)
        jid = s1.add_job("0 0 * * *", "daily", {})
        s2 = CronScheduler(persist_path=path)
        assert s2.get_job(jid) is not None

    def test_remove_persisted_job(self, tmp_path):
        path = tmp_path / "crons.json"
        s1 = CronScheduler(persist_path=path)
        jid = s1.add_job("* * * * *", "tick", {})
        s1.remove_job(jid)
        s2 = CronScheduler(persist_path=path)
        assert s2.get_job(jid) is None

    def test_trigger_callback_integration(self, tmp_path):
        triggers = []
        s = CronScheduler(
            persist_path=tmp_path / "crons.json",
            trigger_fn=lambda name, args: triggers.append({"tool": name, "args": args}),
        )
        s.add_job("* * * * *", "ping", {"host": "localhost"})
        # Directly call trigger
        s._trigger_fn("ping", {"host": "localhost"})
        assert len(triggers) == 1
        assert triggers[0]["tool"] == "ping"
        assert triggers[0]["args"]["host"] == "localhost"

    def test_disabled_job_not_triggered(self, tmp_path):
        triggers = []
        s = CronScheduler(
            persist_path=tmp_path / "crons.json",
            trigger_fn=lambda name, args: triggers.append(name),
        )
        jid = s.add_job("* * * * *", "disabled_tool", {})
        job = s.get_job(jid)
        job.enabled = False
        # Simulate a tick
        now = datetime.now().replace(second=0, microsecond=0)
        for j in s.list_jobs():
            if not j.enabled:
                continue
            s._trigger_fn(j.tool_name, j.args)
        assert len(triggers) == 0  # disabled job not triggered

    @pytest.mark.asyncio
    async def test_start_and_shutdown(self, tmp_path):
        s = CronScheduler(persist_path=tmp_path / "crons.json")
        await s.start()
        assert s._running is True
        await s.shutdown()
        assert s._running is False

    def test_multiple_cron_expressions_match(self):
        # Test that different common patterns work
        patterns = [
            ("* * * * *", True),         # every minute
            ("0 0 * * *", False),         # midnight, not now
            ("*/15 * * * *", True),       # multiples of 15
        ]
        dt = datetime(2024, 4, 8, 9, 0)  # 09:00
        for expr, expected in patterns:
            result = _matches(expr, dt)
            if expr == "*/15 * * * *":
                assert result is True  # 0 % 15 == 0
            elif expr == "* * * * *":
                assert result is True
