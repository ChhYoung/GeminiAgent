"""
tests/unit/test_cron.py — Cron 调度器测试 (s14)
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hello_agents.tasks.cron import CronScheduler, CronJob, _matches, _field_matches


class TestCronExpression:
    def test_wildcard_matches_any(self):
        dt = datetime(2024, 4, 8, 9, 30)  # Mon 09:30
        assert _matches("* * * * *", dt) is True

    def test_exact_minute_match(self):
        dt = datetime(2024, 4, 8, 9, 30)
        assert _matches("30 9 * * *", dt) is True

    def test_exact_minute_no_match(self):
        dt = datetime(2024, 4, 8, 9, 31)
        assert _matches("30 9 * * *", dt) is False

    def test_workdays_match_monday(self):
        dt = datetime(2024, 4, 8, 9, 0)  # Monday
        assert _matches("0 9 * * 1-5", dt) is True

    def test_workdays_no_match_sunday(self):
        dt = datetime(2024, 4, 7, 9, 0)  # Sunday = isoweekday 7
        assert _matches("0 9 * * 1-5", dt) is False

    def test_step_expression(self):
        # */15 means every 15 minutes
        dt0 = datetime(2024, 4, 8, 9, 0)
        dt15 = datetime(2024, 4, 8, 9, 15)
        dt30 = datetime(2024, 4, 8, 9, 30)
        dt7 = datetime(2024, 4, 8, 9, 7)
        assert _matches("*/15 * * * *", dt0) is True
        assert _matches("*/15 * * * *", dt15) is True
        assert _matches("*/15 * * * *", dt30) is True
        assert _matches("*/15 * * * *", dt7) is False

    def test_list_expression(self):
        dt1 = datetime(2024, 4, 8, 9, 1)
        dt2 = datetime(2024, 4, 8, 9, 2)
        dt3 = datetime(2024, 4, 8, 9, 3)
        assert _matches("1,2 * * * *", dt1) is True
        assert _matches("1,2 * * * *", dt2) is True
        assert _matches("1,2 * * * *", dt3) is False

    def test_invalid_expression_returns_false(self):
        dt = datetime(2024, 4, 8, 9, 0)
        assert _matches("* *", dt) is False  # too few fields


class TestCronScheduler:
    def test_add_job(self, tmp_path):
        s = CronScheduler(persist_path=tmp_path / "crons.json")
        jid = s.add_job("0 9 * * *", "web_search", {"query": "news"})
        assert jid is not None
        assert len(s.list_jobs()) == 1

    def test_remove_job(self, tmp_path):
        s = CronScheduler(persist_path=tmp_path / "crons.json")
        jid = s.add_job("0 9 * * *", "web_search", {})
        ok = s.remove_job(jid)
        assert ok is True
        assert len(s.list_jobs()) == 0

    def test_remove_nonexistent(self, tmp_path):
        s = CronScheduler(persist_path=tmp_path / "crons.json")
        assert s.remove_job("ghost") is False

    def test_get_job(self, tmp_path):
        s = CronScheduler(persist_path=tmp_path / "crons.json")
        jid = s.add_job("*/5 * * * *", "ping", {})
        job = s.get_job(jid)
        assert job is not None
        assert job.tool_name == "ping"
        assert job.cron_expr == "*/5 * * * *"

    def test_persistence_round_trip(self, tmp_path):
        path = tmp_path / "crons.json"
        s1 = CronScheduler(persist_path=path)
        jid = s1.add_job("0 0 * * *", "daily_report", {"format": "json"})

        s2 = CronScheduler(persist_path=path)
        job = s2.get_job(jid)
        assert job is not None
        assert job.tool_name == "daily_report"
        assert job.args == {"format": "json"}

    def test_custom_trigger_fn_called(self, tmp_path):
        triggered = []
        s = CronScheduler(
            persist_path=tmp_path / "crons.json",
            trigger_fn=lambda name, args: triggered.append((name, args)),
        )
        jid = s.add_job("* * * * *", "test_tool", {"k": "v"})
        # Manually invoke trigger by calling _trigger_fn directly
        s._trigger_fn("test_tool", {"k": "v"})
        assert len(triggered) == 1
        assert triggered[0] == ("test_tool", {"k": "v"})

    def test_cron_job_serialization(self):
        job = CronJob(
            job_id="j1",
            cron_expr="0 9 * * *",
            tool_name="web_search",
            args={"query": "test"},
        )
        d = job.to_dict()
        job2 = CronJob.from_dict(d)
        assert job2.job_id == job.job_id
        assert job2.cron_expr == job.cron_expr
        assert job2.tool_name == job.tool_name
        assert job2.args == job.args
