"""
tasks/cron.py — Cron 定时调度器 (s14)

纯 asyncio 实现，无外部依赖。
支持标准 5 字段 cron 表达式（分 时 日 月 周），精度为分钟级。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PERSIST_PATH = Path.home() / ".agent" / "cron_jobs.json"


@dataclass
class CronJob:
    """一条 Cron 任务记录。"""
    job_id: str
    cron_expr: str          # "分 时 日 月 周"，* 表示任意
    tool_name: str
    args: dict[str, Any]
    last_run: datetime | None = None
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "cron_expr": self.cron_expr,
            "tool_name": self.tool_name,
            "args": self.args,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CronJob":
        return cls(
            job_id=d["job_id"],
            cron_expr=d["cron_expr"],
            tool_name=d["tool_name"],
            args=d.get("args", {}),
            last_run=datetime.fromisoformat(d["last_run"]) if d.get("last_run") else None,
            enabled=d.get("enabled", True),
        )


def _matches(cron_expr: str, dt: datetime) -> bool:
    """检查 datetime 是否匹配 cron 表达式（5 字段：分 时 日 月 周）。"""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    fields = [
        (parts[0], dt.minute, 0, 59),
        (parts[1], dt.hour, 0, 23),
        (parts[2], dt.day, 1, 31),
        (parts[3], dt.month, 1, 12),
        (parts[4], dt.isoweekday(), 1, 7),  # 1=Mon … 7=Sun (ISO 8601)
    ]
    for expr, val, lo, hi in fields:
        if not _field_matches(expr, val, lo, hi):
            return False
    return True


def _field_matches(expr: str, val: int, lo: int, hi: int) -> bool:
    if expr == "*":
        return True
    if expr.startswith("*/"):
        step = int(expr[2:])
        return (val - lo) % step == 0
    if "-" in expr and "," not in expr:
        a, b = expr.split("-", 1)
        return int(a) <= val <= int(b)
    if "," in expr:
        return val in {int(x) for x in expr.split(",")}
    return val == int(expr)


class CronScheduler:
    """
    Cron 调度器。

    用法：
        scheduler = CronScheduler()
        job_id = scheduler.add_job("0 9 * * 1-5", "web_search", {"query": "news"})
        await scheduler.start()
        # ... 运行中 ...
        await scheduler.shutdown()
    """

    def __init__(
        self,
        persist_path: Path | str = _PERSIST_PATH,
        trigger_fn: Callable[[str, dict], None] | None = None,
    ) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._persist_path = Path(persist_path)
        self._trigger_fn = trigger_fn or self._default_trigger
        self._task: asyncio.Task | None = None
        self._running = False
        self._load_persisted()

    # ------------------------------------------------------------------
    # 管理接口
    # ------------------------------------------------------------------

    def add_job(
        self,
        cron_expr: str,
        tool_name: str,
        args: dict | None = None,
        job_id: str | None = None,
    ) -> str:
        """注册一条 Cron 任务，返回 job_id。"""
        jid = job_id or str(uuid.uuid4())[:8]
        self._jobs[jid] = CronJob(
            job_id=jid,
            cron_expr=cron_expr,
            tool_name=tool_name,
            args=args or {},
        )
        self._persist()
        logger.info("CronJob added: %s (%s → %s)", jid, cron_expr, tool_name)
        return jid

    def remove_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._persist()
            return True
        return False

    def list_jobs(self) -> list[CronJob]:
        return list(self._jobs.values())

    def get_job(self, job_id: str) -> CronJob | None:
        return self._jobs.get(job_id)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._tick_loop())
        logger.info("CronScheduler started")

    async def shutdown(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CronScheduler stopped")

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        """每分钟检查一次，触发匹配的任务。"""
        while self._running:
            now = datetime.now().replace(second=0, microsecond=0)
            for job in list(self._jobs.values()):
                if not job.enabled:
                    continue
                if _matches(job.cron_expr, now):
                    # 遗漏补跑：同一分钟只触发一次
                    if job.last_run and job.last_run.replace(second=0, microsecond=0) == now:
                        continue
                    job.last_run = now
                    logger.info("CronJob triggered: %s → %s", job.job_id, job.tool_name)
                    try:
                        self._trigger_fn(job.tool_name, job.args)
                    except Exception as exc:
                        logger.warning("CronJob %s trigger error: %s", job.job_id, exc)
            # 等到下一分钟
            await asyncio.sleep(60 - datetime.now().second)

    @staticmethod
    def _default_trigger(tool_name: str, args: dict) -> None:
        logger.info("[Cron] trigger %s(%s)", tool_name, args)

    def _persist(self) -> None:
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = [j.to_dict() for j in self._jobs.values()]
            self._persist_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("CronScheduler persist failed: %s", exc)

    def _load_persisted(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for d in data:
                job = CronJob.from_dict(d)
                self._jobs[job.job_id] = job
            logger.info("CronScheduler: loaded %d jobs from disk", len(self._jobs))
        except Exception as exc:
            logger.warning("CronScheduler load failed: %s", exc)
