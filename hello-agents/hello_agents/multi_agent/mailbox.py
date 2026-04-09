"""
multi_agent/mailbox.py — 异步邮箱 (s09)

每个 Agent 有一个 SQLite 持久化邮箱，消息按序投递。
提供 async (send/recv) 和 sync (send_sync/recv_sync) 两套 API，
sync 版本供 tool dispatch（同步上下文）使用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hello_agents.multi_agent.protocol import AgentMessage

logger = logging.getLogger(__name__)

_DEFAULT_DB = "mailboxes.db"


class Mailbox:
    """
    SQLite 持久化的异步邮箱。

    用法（async）：
        mailbox = Mailbox()
        await mailbox.send("agent_b", msg)
        incoming = await mailbox.recv("agent_b")

    用法（sync，tool dispatch 内）：
        mailbox.send_sync("agent_b", msg)
        incoming = mailbox.recv_sync("agent_b")
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB) -> None:
        self._db_path = str(db_path)
        self._async_lock = asyncio.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    to_agent TEXT NOT NULL,
                    msg_json TEXT NOT NULL,
                    consumed INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_to_agent "
                "ON messages(to_agent, consumed)"
            )
            conn.commit()

    # ---- Sync API (for tool dispatch) ----

    def send_sync(self, to_agent: str, msg: "AgentMessage") -> None:
        """同步发送消息（不持锁，适合单线程 tool dispatch）。"""
        msg_json = json.dumps(msg.to_dict(), ensure_ascii=False)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO messages (to_agent, msg_json) VALUES (?, ?)",
                (to_agent, msg_json),
            )
            conn.commit()
        logger.debug("Mailbox: %s -> %s [%s]", msg.from_agent, to_agent, msg.msg_id)

    def recv_sync(self, agent_id: str) -> "AgentMessage | None":
        """同步取出下一条消息（消费后标记 consumed=1）。"""
        from hello_agents.multi_agent.protocol import AgentMessage

        d = self._db_fetch(agent_id)
        return AgentMessage.from_dict(d) if d else None

    def pending_count(self, agent_id: str) -> int:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE to_agent=? AND consumed=0",
                (agent_id,),
            ).fetchone()
            return row[0] if row else 0

    # ---- Async API ----

    async def send(self, to_agent: str, msg: "AgentMessage") -> None:
        """异步发送消息（带锁保证并发安全）。"""
        async with self._async_lock:
            msg_json = json.dumps(msg.to_dict(), ensure_ascii=False)
            await asyncio.to_thread(self._db_insert, to_agent, msg_json)
        logger.debug("Mailbox: %s -> %s [%s]", msg.from_agent, to_agent, msg.msg_id)

    async def recv(self, agent_id: str, timeout: float = 0.0) -> "AgentMessage | None":
        """
        异步取出下一条消息。

        Args:
            agent_id: 接收方 agent ID
            timeout:  等待超时秒数（0 表示不等待）
        """
        from hello_agents.multi_agent.protocol import AgentMessage

        d = await asyncio.to_thread(self._db_fetch, agent_id)
        if d is not None:
            return AgentMessage.from_dict(d)

        if timeout > 0:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.1)
                d = await asyncio.to_thread(self._db_fetch, agent_id)
                if d is not None:
                    return AgentMessage.from_dict(d)

        return None

    # ---- DB helpers ----

    def read_all(self, agent_id: str) -> "list[AgentMessage]":
        """读取 agent 所有未消费消息（全部标记为 consumed）。"""
        from hello_agents.multi_agent.protocol import AgentMessage
        msgs = []
        while True:
            d = self._db_fetch(agent_id)
            if d is None:
                break
            msgs.append(AgentMessage.from_dict(d))
        return msgs

    def _db_insert(self, to_agent: str, msg_json: str) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO messages (to_agent, msg_json) VALUES (?, ?)",
                (to_agent, msg_json),
            )
            conn.commit()

    def _db_fetch(self, agent_id: str) -> dict | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT id, msg_json FROM messages "
                "WHERE to_agent=? AND consumed=0 ORDER BY id LIMIT 1",
                (agent_id,),
            ).fetchone()
            if row is None:
                return None
            msg_id_db, msg_json = row
            conn.execute(
                "UPDATE messages SET consumed=1 WHERE id=?", (msg_id_db,)
            )
            conn.commit()
            return json.loads(msg_json)
