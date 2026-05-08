"""
tests/unit/test_agent_design_patterns.py — Agent 设计模式单元测试

覆盖：
  1. 父子 Agent 上下文隔离（SubAgentRunner 独立 messages[]）
  2. AgentMessage correlation_id 请求-响应关联
  3. Mailbox FIFO 顺序与多 Agent 收件箱隔离
  4. Kanban claim() 原子性（多 Worker 并发不重复认领）
  5. WorkerAgent 自主认领与完成任务
  6. TeamCoordinator delegate/broadcast
  7. TaskGraph 依赖就绪判断与循环检测
"""

from __future__ import annotations

import asyncio
import threading
import time
import unittest.mock as mock

import pytest

from hello_agents.multi_agent.mailbox import Mailbox
from hello_agents.multi_agent.protocol import AgentMessage
from hello_agents.multi_agent.registry import AgentRegistry
from hello_agents.tasks.kanban import Kanban
from hello_agents.tasks.models import Task
from hello_agents.tasks.graph import TaskGraph
from hello_agents.tasks.background import BackgroundExecutor


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------

def _make_msg(
    from_a: str = "a",
    to_a: str = "b",
    msg_type: str = "request",
    payload: dict | None = None,
) -> AgentMessage:
    return AgentMessage(
        from_agent=from_a,
        to_agent=to_a,
        msg_type=msg_type,  # type: ignore[arg-type]
        payload=payload or {"content": "hello"},
    )


def _make_task(goal: str = "do something", deps: list[str] | None = None) -> Task:
    return Task(goal=goal, deps=deps or [])


# ---------------------------------------------------------------------------
# 1. 父子 Agent：上下文隔离
# ---------------------------------------------------------------------------

class TestSubAgentContextIsolation:
    """SubAgentRunner 的 messages[] 独立性（不依赖 LLM，通过 mock 验证）。"""

    @pytest.mark.asyncio
    async def test_fresh_messages_each_run(self):
        """每次 run() 使用全新 messages[]，不携带上次调用的历史。"""
        from hello_agents.subagent.runner import SubAgentRunner

        call_messages: list[list] = []

        def fake_create(**kwargs):
            call_messages.append([m.copy() for m in kwargs["messages"]])
            resp = mock.MagicMock()
            resp.choices[0].message.tool_calls = None
            resp.choices[0].message.content = "done"
            return resp

        client = mock.MagicMock()
        client.chat.completions.create.side_effect = fake_create

        runner = SubAgentRunner(client=client, model="test-model")

        await runner.run("任务 A")
        await runner.run("任务 B")

        assert len(call_messages) == 2

        # 第一次调用只有 system + user
        assert call_messages[0][1]["content"] == "任务 A"
        # 第二次调用同样只有 system + user，不含"任务 A"痕迹
        assert call_messages[1][1]["content"] == "任务 B"
        assert len(call_messages[1]) == 2, "第二次调用不应包含第一次的消息历史"

    @pytest.mark.asyncio
    async def test_tool_calls_not_leaked_to_parent(self):
        """子 Agent 内部 tool_call 循环对父调用方不可见，父只收到最终文本。"""
        from hello_agents.subagent.runner import SubAgentRunner

        call_count = 0

        def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            resp = mock.MagicMock()
            if call_count == 1:
                # 第一轮：返回 tool_call
                tc = mock.MagicMock()
                tc.id = "tc_1"
                tc.function.name = "dummy_tool"
                tc.function.arguments = "{}"
                resp.choices[0].message.tool_calls = [tc]
                resp.choices[0].message.content = None
                resp.choices[0].message.model_dump.return_value = {"role": "assistant", "content": None}
            else:
                # 第二轮：返回最终文本
                resp.choices[0].message.tool_calls = None
                resp.choices[0].message.content = "最终结果"
            return resp

        registry = mock.MagicMock()
        registry.get_schemas.return_value = [{"name": "dummy_tool"}]
        registry.dispatch.return_value = "tool result"

        client = mock.MagicMock()
        client.chat.completions.create.side_effect = fake_create

        runner = SubAgentRunner(client=client, model="test-model", registry=registry)
        result = await runner.run("执行带工具的任务")

        assert result == "最终结果"
        assert call_count == 2  # 内部经历了 2 轮
        # 父 Agent 只拿到文本结果，不知道有过 tool_call


# ---------------------------------------------------------------------------
# 2. AgentMessage：correlation_id 请求-响应关联
# ---------------------------------------------------------------------------

class TestAgentMessageProtocol:

    def test_make_response_sets_correlation_id(self):
        """make_response 的 correlation_id 应等于原请求的 msg_id。"""
        req = _make_msg(from_a="a", to_a="b", msg_type="request")
        resp = req.make_response(from_agent="b", payload={"result": "ok"})

        assert resp.msg_type == "response"
        assert resp.from_agent == "b"
        assert resp.to_agent == "a"
        assert resp.correlation_id == req.msg_id

    def test_msg_id_unique_per_message(self):
        """每条消息的 msg_id 唯一，不重复。"""
        msgs = [_make_msg() for _ in range(100)]
        ids = [m.msg_id for m in msgs]
        assert len(set(ids)) == 100

    def test_to_dict_from_dict_roundtrip(self):
        """序列化/反序列化应保留所有字段。"""
        original = AgentMessage(
            from_agent="alice",
            to_agent="bob",
            msg_type="delegate",
            correlation_id="abc123",
            payload={"task": "write tests", "priority": 1},
        )
        restored = AgentMessage.from_dict(original.to_dict())

        assert restored.msg_id == original.msg_id
        assert restored.msg_type == original.msg_type
        assert restored.from_agent == original.from_agent
        assert restored.to_agent == original.to_agent
        assert restored.correlation_id == original.correlation_id
        assert restored.payload == original.payload

    def test_make_response_new_msg_id(self):
        """response 的 msg_id 与原 request 不同。"""
        req = _make_msg()
        resp = req.make_response("b", {})
        assert resp.msg_id != req.msg_id


# ---------------------------------------------------------------------------
# 3. Mailbox：FIFO 顺序与多 Agent 收件箱隔离
# ---------------------------------------------------------------------------

class TestMailboxFifoAndIsolation:

    def test_fifo_order(self, tmp_path):
        """消息按 send 顺序返回（FIFO）。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        for i in range(5):
            mb.send_sync("alice", _make_msg(payload={"seq": i}))

        received = []
        while True:
            msg = mb.recv_sync("alice")
            if msg is None:
                break
            received.append(msg.payload["seq"])

        assert received == list(range(5))

    def test_per_agent_inbox_isolation(self, tmp_path):
        """发给 alice 的消息不出现在 bob 的收件箱，反之亦然。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        mb.send_sync("alice", _make_msg(to_a="alice", payload={"for": "alice"}))
        mb.send_sync("bob",   _make_msg(to_a="bob",   payload={"for": "bob"}))

        alice_msg = mb.recv_sync("alice")
        bob_msg   = mb.recv_sync("bob")

        assert alice_msg is not None and alice_msg.payload["for"] == "alice"
        assert bob_msg   is not None and bob_msg.payload["for"]   == "bob"

        # 两人收件箱均已清空
        assert mb.recv_sync("alice") is None
        assert mb.recv_sync("bob")   is None

    def test_consumed_message_not_returned_twice(self, tmp_path):
        """已消费的消息不会被重复返回。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        mb.send_sync("alice", _make_msg())

        first  = mb.recv_sync("alice")
        second = mb.recv_sync("alice")

        assert first  is not None
        assert second is None

    def test_pending_count_accurate(self, tmp_path):
        """pending_count 准确反映未消费消息数。"""
        mb = Mailbox(db_path=tmp_path / "mb.db")
        assert mb.pending_count("alice") == 0

        mb.send_sync("alice", _make_msg())
        mb.send_sync("alice", _make_msg())
        assert mb.pending_count("alice") == 2

        mb.recv_sync("alice")
        assert mb.pending_count("alice") == 1


# ---------------------------------------------------------------------------
# 4. Kanban：claim() 原子性
# ---------------------------------------------------------------------------

class TestKanbanAtomicClaim:

    def test_claim_changes_status(self):
        """claim 后任务状态变为 IN_PROGRESS，assignee 为 agent_id。"""
        kanban = Kanban()
        task = _make_task("test task")
        kanban.push(task)

        claimed = kanban.claim("worker-1")

        assert claimed is not None
        assert claimed.id == task.id
        assert claimed.status == "IN_PROGRESS"
        assert claimed.assignee == "worker-1"

    def test_no_duplicate_claim(self):
        """同一任务只能被认领一次，第二个 claim 应返回 None（或其他任务）。"""
        kanban = Kanban()
        task = _make_task()
        kanban.push(task)

        # 两个 worker 竞争，只有一个能认领
        results = [None, None]

        def try_claim(idx):
            results[idx] = kanban.claim(f"worker-{idx}")

        t1 = threading.Thread(target=try_claim, args=(0,))
        t2 = threading.Thread(target=try_claim, args=(1,))
        t1.start(); t2.start()
        t1.join();  t2.join()

        claimed_count = sum(1 for r in results if r is not None)
        assert claimed_count == 1, f"一个任务只能被认领一次，实际被认领 {claimed_count} 次"

    def test_concurrent_no_duplicate_with_multiple_tasks(self):
        """10 个 Worker 并发认领 5 个任务，每个任务最多被认领一次。"""
        kanban = Kanban()
        n_tasks = 5
        n_workers = 10
        for i in range(n_tasks):
            kanban.push(_make_task(f"task-{i}"))

        claimed_ids: list[str] = []
        lock = threading.Lock()

        def try_claim(worker_id):
            task = kanban.claim(f"worker-{worker_id}")
            if task:
                with lock:
                    claimed_ids.append(task.id)

        threads = [threading.Thread(target=try_claim, args=(i,)) for i in range(n_workers)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert len(claimed_ids) == n_tasks, f"期望 {n_tasks} 个任务被认领，实际 {len(claimed_ids)}"
        assert len(set(claimed_ids)) == n_tasks, "存在重复认领"

    def test_complete_changes_status_to_done(self):
        """complete() 将任务改为 DONE 并记录结果。"""
        kanban = Kanban()
        task = _make_task()
        kanban.push(task)
        kanban.claim("w1")
        kanban.complete(task.id, "task finished")

        assert task.status == "DONE"
        assert task.result == "task finished"

    def test_release_stale_resets_timed_out_task(self):
        """release_stale 将超时的 IN_PROGRESS 任务重置为 PENDING。"""
        kanban = Kanban()
        task = _make_task()
        kanban.push(task)
        kanban.claim("w1")

        # 强制将心跳时间设为过去（模拟超时）
        from datetime import datetime, timedelta
        past = datetime.utcnow() - timedelta(seconds=700)
        task.updated_at = past
        kanban._last_seen[task.id] = past

        released = kanban.release_stale(timeout_s=600)

        assert task.id in released
        assert task.status == "PENDING"
        assert task.assignee is None


# ---------------------------------------------------------------------------
# 5. WorkerAgent：自主认领与完成
# ---------------------------------------------------------------------------

class TestWorkerAgent:

    @pytest.mark.asyncio
    async def test_worker_claims_and_completes_task(self):
        """WorkerAgent 应自动认领 PENDING 任务并调用 runner.run()。"""
        from hello_agents.multi_agent.worker import WorkerAgent

        kanban = Kanban()
        task = _make_task("compute pi")
        kanban.push(task)

        runner = mock.AsyncMock()
        runner.run.return_value = "3.14159"

        worker = WorkerAgent("w1", kanban=kanban, runner=runner, poll_interval=0.05)
        worker_task = asyncio.create_task(worker.run_forever())

        # 等待任务被处理
        deadline = time.monotonic() + 2.0
        while task.status != "DONE" and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

        worker.stop()
        await asyncio.wait_for(worker_task, timeout=1.0)

        assert task.status == "DONE"
        assert task.result == "3.14159"
        runner.run.assert_called_once_with("compute pi")

    @pytest.mark.asyncio
    async def test_worker_marks_failed_on_exception(self):
        """runner.run() 抛出异常时，Worker 应将任务标记为 FAILED。"""
        from hello_agents.multi_agent.worker import WorkerAgent

        kanban = Kanban()
        task = _make_task("risky task")
        kanban.push(task)

        runner = mock.AsyncMock()
        runner.run.side_effect = RuntimeError("LLM 不可用")

        worker = WorkerAgent("w1", kanban=kanban, runner=runner, poll_interval=0.05)
        worker_task = asyncio.create_task(worker.run_forever())

        deadline = time.monotonic() + 2.0
        while task.status not in ("DONE", "FAILED") and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

        worker.stop()
        await asyncio.wait_for(worker_task, timeout=1.0)

        assert task.status == "FAILED"
        assert "LLM 不可用" in (task.result or "")


# ---------------------------------------------------------------------------
# 6. TeamCoordinator：delegate / broadcast
# ---------------------------------------------------------------------------

class TestTeamCoordinator:

    @pytest.mark.asyncio
    async def test_delegate_sends_message(self, tmp_path):
        """delegate() 应向目标 Agent 发送 delegate 消息。"""
        from hello_agents.teams.coordinator import TeamCoordinator

        mb = Mailbox(db_path=tmp_path / "mb.db")
        coord = TeamCoordinator(mailbox=mb)

        msg_id = await coord.delegate(
            to_agent="worker_1",
            task_desc="分析日志文件",
            from_agent="lead",
        )

        # worker_1 应收到委托消息
        msg = mb.recv_sync("worker_1")
        assert msg is not None
        assert msg.msg_type == "delegate"
        assert msg.payload["task_desc"] == "分析日志文件"
        assert msg.from_agent == "lead"
        assert msg.msg_id == msg_id

    @pytest.mark.asyncio
    async def test_broadcast_reaches_all_members(self, tmp_path):
        """broadcast() 应向所有非发送方成员发送消息。"""
        from hello_agents.teams.coordinator import TeamCoordinator
        from hello_agents.teams.team import AgentTeam, TeamMember

        mb = Mailbox(db_path=tmp_path / "mb.db")
        coord = TeamCoordinator(mailbox=mb)

        # 构造有 3 个成员的团队
        members = [
            TeamMember(agent_id="lead",     role="coordinator"),
            TeamMember(agent_id="member_1", role="coder"),
            TeamMember(agent_id="member_2", role="tester"),
        ]
        team = AgentTeam(
            team_id="t1",
            name="test team",
            members=members,
            shared_rules=[],
        )

        await coord.broadcast(team, content="开始任务", from_agent="lead")

        # member_1 和 member_2 应收到广播
        msg1 = mb.recv_sync("member_1")
        msg2 = mb.recv_sync("member_2")
        assert msg1 is not None and msg1.msg_type == "broadcast"
        assert msg2 is not None and msg2.msg_type == "broadcast"

        # lead 不应收到自己的广播
        assert mb.recv_sync("lead") is None

    @pytest.mark.asyncio
    async def test_delegate_response_correlation(self, tmp_path):
        """委托方能通过 correlation_id 将 response 与原始 delegate 关联。"""
        from hello_agents.teams.coordinator import TeamCoordinator

        mb = Mailbox(db_path=tmp_path / "mb.db")
        coord = TeamCoordinator(mailbox=mb)

        msg_id = await coord.delegate("worker_1", "分析任务", "lead")

        # 模拟 worker_1 回复
        original = mb.recv_sync("worker_1")
        assert original is not None
        reply = original.make_response("worker_1", {"result": "完成"})
        mb.send_sync("lead", reply)

        # lead 收到 response
        response = mb.recv_sync("lead")
        assert response is not None
        assert response.msg_type == "response"
        assert response.correlation_id == msg_id  # 关联正确


# ---------------------------------------------------------------------------
# 7. TaskGraph：依赖就绪判断与循环检测
# ---------------------------------------------------------------------------

class TestTaskGraph:

    def test_no_deps_task_is_immediately_ready(self):
        """无依赖的任务应在 PENDING 状态下立即出现在 ready_tasks()。"""
        graph = TaskGraph()
        task = _make_task("independent task")
        graph.add(task)

        ready = graph.ready_tasks()
        assert len(ready) == 1
        assert ready[0].id == task.id

    def test_task_not_ready_until_dep_done(self):
        """有依赖的任务在依赖完成前不应出现在 ready_tasks()。"""
        graph = TaskGraph()
        task_a = _make_task("task A")
        task_b = _make_task("task B", deps=[task_a.id])
        graph.add(task_a)
        graph.add(task_b)

        # task_a 未完成时，只有 task_a 就绪
        ready = graph.ready_tasks()
        ready_ids = [t.id for t in ready]
        assert task_a.id in ready_ids
        assert task_b.id not in ready_ids

        # task_a 完成后，task_b 就绪
        task_a.status = "DONE"
        ready = graph.ready_tasks()
        ready_ids = [t.id for t in ready]
        assert task_b.id in ready_ids

    def test_topological_order_respects_dependencies(self):
        """拓扑排序中，依赖项排在被依赖项之前。"""
        graph = TaskGraph()
        task_a = _make_task("A")
        task_b = _make_task("B", deps=[task_a.id])
        task_c = _make_task("C", deps=[task_b.id])
        graph.add(task_a)
        graph.add(task_b)
        graph.add(task_c)

        order = graph.topological_order()
        ids = [t.id for t in order]

        assert ids.index(task_a.id) < ids.index(task_b.id)
        assert ids.index(task_b.id) < ids.index(task_c.id)

    def test_cycle_detection(self):
        """循环依赖应被检测到，has_cycle() 返回 True，topological_order 抛出异常。"""
        graph = TaskGraph()
        task_a = _make_task("A")
        task_b = _make_task("B", deps=[task_a.id])
        task_a.deps = [task_b.id]   # 人工制造循环
        graph.add(task_a)
        graph.add(task_b)

        assert graph.has_cycle() is True

        with pytest.raises(ValueError, match="Circular dependency"):
            graph.topological_order()

    def test_multiple_deps_all_must_be_done(self):
        """多个前置依赖全部完成，任务才就绪（AND 语义）。"""
        graph = TaskGraph()
        task_a = _make_task("A")
        task_b = _make_task("B")
        task_c = _make_task("C", deps=[task_a.id, task_b.id])
        graph.add(task_a)
        graph.add(task_b)
        graph.add(task_c)

        task_a.status = "DONE"
        # 只有 A 完成，C 不就绪
        ready_ids = [t.id for t in graph.ready_tasks()]
        assert task_c.id not in ready_ids

        task_b.status = "DONE"
        # A 和 B 都完成，C 就绪
        ready_ids = [t.id for t in graph.ready_tasks()]
        assert task_c.id in ready_ids


# ---------------------------------------------------------------------------
# 8. AgentRegistry：进程单例注册与查找
# ---------------------------------------------------------------------------

class TestAgentRegistry:

    def test_register_and_get(self):
        """注册后能通过 agent_id 查找。"""
        from hello_agents.multi_agent.peer import PeerAgent

        registry = AgentRegistry()
        agent = PeerAgent(
            agent_id="agent-1",
            name="Test Agent",
            speciality="testing",
            system_prompt="You are a test agent.",
        )
        registry.register(agent)

        found = registry.get("agent-1")
        assert found is agent

    def test_get_unknown_returns_none(self):
        """查找不存在的 agent_id 返回 None。"""
        registry = AgentRegistry()
        assert registry.get("nonexistent") is None

    def test_unregister(self):
        """注销后 get() 返回 None。"""
        from hello_agents.multi_agent.peer import PeerAgent

        registry = AgentRegistry()
        agent = PeerAgent("a1", "A", "spec", "prompt")
        registry.register(agent)
        assert registry.unregister("a1") is True
        assert registry.get("a1") is None

    def test_list_agents(self):
        """list_agents 返回所有已注册的 agent。"""
        from hello_agents.multi_agent.peer import PeerAgent

        registry = AgentRegistry()
        for i in range(3):
            registry.register(PeerAgent(f"a{i}", f"Agent {i}", "spec", "prompt"))

        agents = registry.list_agents()
        assert len(agents) == 3


# ---------------------------------------------------------------------------
# 9. BackgroundExecutor：后台任务与回调
# ---------------------------------------------------------------------------

class TestBackgroundExecutor:

    def test_submit_returns_job_id(self):
        """submit() 立即返回 job_id（不阻塞）。"""
        executor = BackgroundExecutor()
        job_id = executor.submit(lambda: time.sleep(0.1))
        assert isinstance(job_id, str) and len(job_id) > 0
        executor.shutdown()

    def test_poll_running_then_done(self):
        """先 poll 为 running，等待完成后 poll 为 done。"""
        executor = BackgroundExecutor()
        job_id = executor.submit(lambda: (time.sleep(0.1), "result")[1])

        status = executor.poll(job_id)
        # 可能已完成（快速机器）或还在运行
        assert status["status"] in ("running", "done")

        # 等待完成
        deadline = time.monotonic() + 2.0
        while executor.poll(job_id)["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)

        final = executor.poll(job_id)
        assert final["status"] == "done"
        executor.shutdown()

    def test_on_complete_callback_triggered(self):
        """任务完成后 on_complete 回调被调用。"""
        executor = BackgroundExecutor()
        results: list[dict] = []

        job_id = executor.submit(lambda: "callback_result")
        executor.on_complete(job_id, lambda r: results.append(r))

        deadline = time.monotonic() + 2.0
        while not results and time.monotonic() < deadline:
            time.sleep(0.02)

        assert len(results) == 1
        assert results[0]["status"] == "done"
        executor.shutdown()

    def test_submit_command_returns_output(self):
        """submit_command 执行 shell 命令，poll() 返回输出。"""
        executor = BackgroundExecutor()
        job_id = executor.submit_command("echo hello_world")

        deadline = time.monotonic() + 5.0
        while executor.poll(job_id)["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)

        result = executor.poll(job_id)
        assert result["status"] == "done"
        assert "hello_world" in result["result"]
        executor.shutdown()
