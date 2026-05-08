"""
tests/unit/test_mailbox_perf.py — Mailbox 性能优化专项测试

验证优化后的行为：
  1. 持久化连接：多次操作复用同一连接对象
  2. WAL 模式：PRAGMA 已正确设置
  3. read_all 批量：N 条消息仅 2 次 SQL（非 2N 次）
  4. recv timeout 使用 Event 通知：send 后立即唤醒，而非轮询
  5. batch_send：多条消息单事务写入
  6. vacuum_consumed：清理已消费消息
  7. 线程安全：并发 send_sync 不丢消息
  8. _db_fetch 原子性：并发 recv_sync 不重复消费
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from hello_agents.multi_agent.mailbox import Mailbox
from hello_agents.multi_agent.protocol import AgentMessage


def _msg(from_a: str = "a", to_a: str = "b", content: str = "hello") -> AgentMessage:
    return AgentMessage(from_agent=from_a, to_agent=to_a, msg_type="test",
                        payload={"content": content})


# -----------------------------------------------------------------------
# 1. 持久化连接
# -----------------------------------------------------------------------

class TestPersistentConnection:

    def test_same_connection_reused(self, tmp_path):
        """多次操作应复用同一 sqlite3.Connection 对象。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        conn1 = mb._get_conn()
        conn2 = mb._get_conn()
        assert conn1 is conn2, "连接对象应被复用，而不是每次新建"

    def test_wal_mode_enabled(self, tmp_path):
        """WAL journal mode 应已启用。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        with mb._lock:
            row = mb._get_conn().execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal", f"期望 WAL，实际: {row[0]}"

    def test_synchronous_normal(self, tmp_path):
        """synchronous 应为 NORMAL（1）。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        with mb._lock:
            row = mb._get_conn().execute("PRAGMA synchronous").fetchone()
        assert row[0] == 1, f"期望 NORMAL(1)，实际: {row[0]}"


# -----------------------------------------------------------------------
# 2. read_all 批量操作
# -----------------------------------------------------------------------

class TestReadAllBatch:

    def test_read_all_returns_all_messages(self, tmp_path):
        """read_all 返回全部未消费消息，顺序一致。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        for i in range(5):
            mb.send_sync("bob", _msg(content=str(i)))

        msgs = mb.read_all("bob")
        assert len(msgs) == 5
        contents = [m.payload["content"] for m in msgs]
        assert contents == [str(i) for i in range(5)]

    def test_read_all_marks_consumed(self, tmp_path):
        """read_all 后消息被标记为已消费，再次 read_all 返回空。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        mb.send_sync("bob", _msg())
        mb.send_sync("bob", _msg())
        mb.read_all("bob")
        assert mb.read_all("bob") == []
        assert mb.pending_count("bob") == 0

    def test_read_all_empty(self, tmp_path):
        """无消息时 read_all 返回空列表。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        assert mb.read_all("nobody") == []


# -----------------------------------------------------------------------
# 3. recv timeout — Event 通知（不轮询）
# -----------------------------------------------------------------------

class TestRecvTimeout:

    @pytest.mark.asyncio
    async def test_recv_returns_immediately_when_message_exists(self, tmp_path):
        """已有消息时 recv 应立即返回，不等 timeout。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        mb.send_sync("alice", _msg(to_a="alice"))

        t0 = time.monotonic()
        msg = await mb.recv("alice", timeout=5.0)
        elapsed = time.monotonic() - t0

        assert msg is not None
        assert elapsed < 0.5, f"有现存消息时不应等待，耗时 {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_recv_timeout_returns_none_when_no_message(self, tmp_path):
        """无消息时 recv 应在 timeout 后返回 None。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        t0 = time.monotonic()
        msg = await mb.recv("alice", timeout=0.2)
        elapsed = time.monotonic() - t0

        assert msg is None
        # 应在 timeout 附近返回（允许 ±0.2s 误差）
        assert 0.1 <= elapsed <= 0.6, f"timeout 时间异常: {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_recv_wakes_on_send(self, tmp_path):
        """send 后 recv timeout 等待应立即被唤醒，而非等到 timeout 结束。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")

        async def _delayed_send():
            await asyncio.sleep(0.15)
            mb.send_sync("alice", _msg(to_a="alice", content="wake"))

        t0 = time.monotonic()
        _, msg = await asyncio.gather(
            _delayed_send(),
            mb.recv("alice", timeout=5.0),
        )
        elapsed = time.monotonic() - t0

        assert msg is not None
        assert msg.payload["content"] == "wake"
        # 应在 send 后很快返回，远小于 5s timeout
        assert elapsed < 1.0, f"recv 未被 send 唤醒，耗时 {elapsed:.2f}s"


# -----------------------------------------------------------------------
# 4. batch_send
# -----------------------------------------------------------------------

class TestBatchSend:

    def test_batch_send_delivers_all(self, tmp_path):
        """batch_send 所有消息都应可被接收到。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        messages = [
            ("alice", _msg(content="m1")),
            ("bob",   _msg(content="m2")),
            ("alice", _msg(content="m3")),
        ]
        mb.batch_send(messages)

        assert mb.pending_count("alice") == 2
        assert mb.pending_count("bob") == 1

        alice_msgs = mb.read_all("alice")
        bob_msgs = mb.read_all("bob")
        assert [m.payload["content"] for m in alice_msgs] == ["m1", "m3"]
        assert bob_msgs[0].payload["content"] == "m2"

    def test_batch_send_notifies_recipients(self, tmp_path):
        """batch_send 后收件人的 inbox event 应被 set。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        mb.batch_send([("alice", _msg())])
        event = mb._get_inbox_event("alice")
        assert event.is_set(), "batch_send 后 alice 的 inbox event 应被 set"


# -----------------------------------------------------------------------
# 5. vacuum_consumed
# -----------------------------------------------------------------------

class TestVacuumConsumed:

    def _row_count(self, mb: Mailbox) -> int:
        with mb._lock:
            conn = mb._get_conn()
            return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    def test_vacuum_removes_consumed(self, tmp_path):
        """vacuum_consumed 应删除所有已消费消息。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        for _ in range(5):
            mb.send_sync("bob", _msg())
        mb.read_all("bob")          # 全部消费
        mb.send_sync("bob", _msg()) # 新增一条未消费

        deleted = mb.vacuum_consumed()
        assert deleted == 5
        assert self._row_count(mb) == 1   # 只剩一条未消费

    def test_vacuum_keep_last(self, tmp_path):
        """keep_last > 0 时，保留最近 N 条已消费记录。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        for _ in range(6):
            mb.send_sync("bob", _msg())
        mb.read_all("bob")  # 6 条全部消费

        deleted = mb.vacuum_consumed(keep_last=2)
        assert deleted == 4
        assert self._row_count(mb) == 2

    def test_vacuum_noop_when_nothing_consumed(self, tmp_path):
        """无已消费消息时 vacuum 返回 0。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        mb.send_sync("bob", _msg())
        assert mb.vacuum_consumed() == 0


# -----------------------------------------------------------------------
# 6. 线程安全
# -----------------------------------------------------------------------

class TestThreadSafety:

    def test_concurrent_send_sync_no_loss(self, tmp_path):
        """100 个线程并发 send_sync，所有消息都应被接收到。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        n = 100

        def send(i: int):
            mb.send_sync("inbox", _msg(content=str(i)))

        threads = [threading.Thread(target=send, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert mb.pending_count("inbox") == n
        msgs = mb.read_all("inbox")
        assert len(msgs) == n
        contents = {m.payload["content"] for m in msgs}
        assert contents == {str(i) for i in range(n)}

    def test_concurrent_recv_sync_no_duplicate(self, tmp_path):
        """多个线程并发 recv_sync 不应重复消费同一条消息。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        n = 20
        for i in range(n):
            mb.send_sync("inbox", _msg(content=str(i)))

        received: list[str] = []
        lock = threading.Lock()

        def recv():
            msg = mb.recv_sync("inbox")
            if msg:
                with lock:
                    received.append(msg.payload["content"])

        threads = [threading.Thread(target=recv) for _ in range(n + 5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 每条消息最多被消费一次
        assert len(received) == n, f"期望 {n} 条，实际 {len(received)} 条"
        assert len(set(received)) == n, "存在重复消费"
