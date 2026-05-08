"""
multi_agent/mailbox.py — 异步邮箱 (s09)

每个 Agent 有一个 SQLite 持久化邮箱，消息按序投递。
提供 async (send/recv) 和 sync (send_sync/recv_sync) 两套 API，
sync 版本供 tool dispatch（同步上下文）使用。

性能优化（相对初始版本）：
  - 持久化连接：复用单一 sqlite3.Connection，避免每次操作重建连接
  - WAL 模式：允许并发读+写，消除读写互锁
  - threading.Lock：保证多线程安全（asyncio.to_thread 路径）
  - read_all 批量：1×SELECT + 1×UPDATE，原 N×(SELECT+UPDATE)
  - recv timeout 用 threading.Event 通知，send 后立即唤醒等待者，
    消除 100ms 定时轮询 DB
  - _db_fetch 在 BEGIN IMMEDIATE 事务内原子执行 SELECT+UPDATE
  - vacuum_consumed() 清理已消费消息，防止表无限增长
  - batch_send() 批量写入，多条消息共享一个事务
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
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
        incoming = await mailbox.recv("agent_b", timeout=5.0)

    用法（sync，tool dispatch 内）：
        mailbox.send_sync("agent_b", msg)
        incoming = mailbox.recv_sync("agent_b")
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB) -> None:
        self._db_path = str(db_path)
        # 单一持久化连接，check_same_thread=False + _lock 保证线程安全
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        # 每个 agent 一个 Event：send 时 set()，recv timeout 等待 set() 而非轮询 DB
        self._inbox_events: dict[str, threading.Event] = {}
        self._init_db()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        """获取持久化连接（懒初始化，调用方须持有 _lock）。"""
        if self._conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")       # 并发读写不互锁
            conn.execute("PRAGMA synchronous=NORMAL")     # 平衡安全与速度
            conn.execute("PRAGMA cache_size=-4096")       # 4 MB page cache
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.commit()
            self._conn = conn
        return self._conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
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

    # ------------------------------------------------------------------
    # Inbox event helpers（用于 recv timeout 通知，避免 DB 轮询）
    # ------------------------------------------------------------------

    def _get_inbox_event(self, agent_id: str) -> threading.Event:
        """获取或创建 agent 的收件通知 Event（线程安全）。"""
        with self._lock:
            if agent_id not in self._inbox_events:
                self._inbox_events[agent_id] = threading.Event()
            return self._inbox_events[agent_id]

    def _notify_inbox(self, to_agent: str) -> None:
        """新消息到达时通知等待中的 recv（_lock 外调用）。"""
        event = self._get_inbox_event(to_agent)
        event.set()

    # ------------------------------------------------------------------
    # Sync API（for tool dispatch）
    # ------------------------------------------------------------------

    def send_sync(self, to_agent: str, msg: "AgentMessage") -> None:
        """同步发送消息。"""
        msg_json = json.dumps(msg.to_dict(), ensure_ascii=False)
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO messages (to_agent, msg_json) VALUES (?, ?)",
                (to_agent, msg_json),
            )
            conn.commit()
        self._notify_inbox(to_agent)
        logger.debug("Mailbox: %s -> %s [%s]", msg.from_agent, to_agent, msg.msg_id)

    def recv_sync(self, agent_id: str) -> "AgentMessage | None":
        """同步取出下一条消息（消费后标记 consumed=1）。"""
        from hello_agents.multi_agent.protocol import AgentMessage

        d = self._db_fetch(agent_id)
        return AgentMessage.from_dict(d) if d else None

    def pending_count(self, agent_id: str) -> int:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE to_agent=? AND consumed=0",
                (agent_id,),
            ).fetchone()
            return row[0] if row else 0

    # ------------------------------------------------------------------
    # Async API
    # ------------------------------------------------------------------

    async def send(self, to_agent: str, msg: "AgentMessage") -> None:
        """异步发送消息。"""
        msg_json = json.dumps(msg.to_dict(), ensure_ascii=False)
        await asyncio.to_thread(self._insert_and_notify, to_agent, msg_json)
        logger.debug("Mailbox: %s -> %s [%s]", msg.from_agent, to_agent, msg.msg_id)

    async def recv(self, agent_id: str, timeout: float = 0.0) -> "AgentMessage | None":
        """
        异步取出下一条消息。

        timeout > 0 时等待新消息到达（用 threading.Event 通知，不轮询 DB）。
        """
        from hello_agents.multi_agent.protocol import AgentMessage

        d = await asyncio.to_thread(self._db_fetch, agent_id)
        if d is not None:
            return AgentMessage.from_dict(d)

        if timeout > 0:
            event = self._get_inbox_event(agent_id)
            event.clear()
            # 再检一次：防止 clear() 前消息已到达但事件尚未 set 的竞态
            d = await asyncio.to_thread(self._db_fetch, agent_id)
            if d is not None:
                return AgentMessage.from_dict(d)
            # 阻塞等待通知（在线程池中，不占用 event loop）
            notified = await asyncio.to_thread(event.wait, timeout)
            if notified:
                d = await asyncio.to_thread(self._db_fetch, agent_id)
                return AgentMessage.from_dict(d) if d else None

        return None

    # ------------------------------------------------------------------
    # 批量 API
    # ------------------------------------------------------------------

    def batch_send(self, messages: list[tuple[str, "AgentMessage"]]) -> None:
        """
        批量发送消息（所有消息在单个事务内写入）。

        Args:
            messages: [(to_agent, msg), ...] 列表
        """
        rows = [
            (to, json.dumps(msg.to_dict(), ensure_ascii=False))
            for to, msg in messages
        ]
        with self._lock:
            conn = self._get_conn()
            conn.executemany(
                "INSERT INTO messages (to_agent, msg_json) VALUES (?, ?)", rows
            )
            conn.commit()
        # 逐一通知收件人
        notified: set[str] = set()
        for to, _ in messages:
            if to not in notified:
                self._notify_inbox(to)
                notified.add(to)
        logger.debug("Mailbox: batch_send %d messages", len(messages))

    def read_all(self, agent_id: str) -> "list[AgentMessage]":
        """
        读取 agent 所有未消费消息（批量标记 consumed）。

        原 N×(SELECT+UPDATE) 优化为 1×SELECT + 1×UPDATE。
        """
        from hello_agents.multi_agent.protocol import AgentMessage

        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT id, msg_json FROM messages "
                "WHERE to_agent=? AND consumed=0 ORDER BY id",
                (agent_id,),
            ).fetchall()
            if not rows:
                return []
            ids = [row[0] for row in rows]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE messages SET consumed=1 WHERE id IN ({placeholders})", ids
            )
            conn.commit()

        return [AgentMessage.from_dict(json.loads(row[1])) for row in rows]

    # ------------------------------------------------------------------
    # 维护 API
    # ------------------------------------------------------------------

    def vacuum_consumed(self, keep_last: int = 0) -> int:
        """
        删除已消费的消息，返回删除行数。

        Args:
            keep_last: 保留最近 N 条已消费消息（0 = 全部删除）
        """
        with self._lock:
            conn = self._get_conn()
            if keep_last > 0:
                # 保留 id 最大的 keep_last 条已消费记录
                row = conn.execute(
                    "SELECT id FROM messages WHERE consumed=1 "
                    "ORDER BY id DESC LIMIT 1 OFFSET ?",
                    (keep_last,),
                ).fetchone()
                if row is None:
                    return 0
                cutoff_id = row[0]
                cur = conn.execute(
                    "DELETE FROM messages WHERE consumed=1 AND id <= ?",
                    (cutoff_id,),
                )
            else:
                cur = conn.execute("DELETE FROM messages WHERE consumed=1")
            conn.commit()
            deleted = cur.rowcount
        logger.info("Mailbox: vacuum removed %d consumed messages", deleted)
        return deleted

    # ------------------------------------------------------------------
    # 内部 DB 方法（须在 _lock 外调用，内部自行加锁）
    # ------------------------------------------------------------------

    def _insert_and_notify(self, to_agent: str, msg_json: str) -> None:
        """写入单条消息并触发通知（供 asyncio.to_thread 调用）。"""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO messages (to_agent, msg_json) VALUES (?, ?)",
                (to_agent, msg_json),
            )
            conn.commit()
        self._notify_inbox(to_agent)

    def _db_fetch(self, agent_id: str) -> dict | None:
        """
        原子地取出下一条消息（BEGIN IMMEDIATE 保证 SELECT+UPDATE 不被穿插）。
        """
        with self._lock:
            conn = self._get_conn()
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT id, msg_json FROM messages "
                    "WHERE to_agent=? AND consumed=0 ORDER BY id LIMIT 1",
                    (agent_id,),
                ).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return None
                msg_id_db, msg_json = row
                conn.execute(
                    "UPDATE messages SET consumed=1 WHERE id=?", (msg_id_db,)
                )
                conn.execute("COMMIT")
                return json.loads(msg_json)
            except Exception:
                conn.execute("ROLLBACK")
                raise
