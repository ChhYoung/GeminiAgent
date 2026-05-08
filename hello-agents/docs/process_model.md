# 进程模型视角：父子 Agent 与多 Agent 系统设计

> 本文从 **Python 运行时的进程/线程/协程模型** 角度，解释系统内各类 Agent 的并发结构、通信机制与任务分发策略。

---

## 1. Python 运行时三层并发模型

```
┌─────────────────────────────────────────────────────────┐
│  OS Process  (单进程，单 CPython 解释器 + GIL)            │
│                                                         │
│  ┌────────────────────────────────────────────────┐     │
│  │  主线程  (asyncio Event Loop)                   │     │
│  │                                                │     │
│  │   协程 A ──await──► 协程 B ──await──► 协程 C   │     │
│  │   (HelloAgent)   (SubAgentRunner)  (LLM I/O)   │     │
│  │                                                │     │
│  └────────────────────────────────────────────────┘     │
│                                                         │
│  ┌─────────────────────────────────────────────┐        │
│  │  ThreadPoolExecutor  (asyncio.to_thread)    │        │
│  │                                             │        │
│  │   Worker-1: sqlite3 操作 / LLM 同步调用     │        │
│  │   Worker-2: shell subprocess               │        │
│  │   Worker-3: BackgroundExecutor 任务         │        │
│  └─────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

| 层级 | 机制 | 用途 |
|------|------|------|
| 协程 (coroutine) | `asyncio.Task` + `await` | Agent 逻辑、消息等待 |
| 线程 (thread) | `asyncio.to_thread` | 阻塞 I/O（sqlite3、openai 同步 SDK） |
| 进程 (process) | 单进程（CPython） | 当前系统不跨进程，Mailbox 提供跨进程扩展接口 |

---

## 2. 父子 Agent：同进程协程调用

### 2.1 调用结构

```
父 Agent（HelloAgent / TaskPipeline）
    │
    │  await runner.run("子任务描述")
    │
    ▼
SubAgentRunner.run()
    │
    ├── 创建独立 messages[] = [system, user]
    │   （不携带父 Agent 任何对话历史）
    │
    ├── loop (max_tool_rounds=5):
    │   ├── await asyncio.to_thread(openai_client.create, ...)
    │   │         │
    │   │         └── 在线程池执行阻塞 HTTP 请求，不阻塞 Event Loop
    │   │
    │   ├── if tool_calls:
    │   │   └── registry.dispatch(tc)  ← 同步执行工具
    │   │
    │   └── else: return message.content
    │
    └── 返回纯文本结果给父 Agent
```

### 2.2 关键特性

**上下文隔离**：每次 `runner.run()` 都从空的 `messages[]` 开始，子任务无法读写父 Agent 的对话历史，失败也不污染主上下文。

**阻塞转非阻塞**：OpenAI SDK 是同步的，通过 `asyncio.to_thread()` 放入线程池，主 Event Loop 可同时调度其他协程（如定时器、其他 WorkerAgent）。

**父等子**：`await runner.run()` 是阻塞等待，父 Agent 暂停执行，子任务完成后继续。如需并发，父 Agent 可用 `asyncio.gather()` 同时启动多个 runner。

```python
# 并发执行多个子任务
results = await asyncio.gather(
    runner.run("子任务 A"),
    runner.run("子任务 B"),
    runner.run("子任务 C"),
)
```

---

## 3. 团队流水线（TaskPipeline）：串行协程链

### 3.1 进程模型

```
TaskPipeline.solve()  ←  一个协程
    │
    ├── await TaskAnalyzer.analyze()      # LLM 生成角色列表
    │         └── asyncio.to_thread(openai)
    │
    ├── for spec in specs:                # 串行逐角色
    │   └── await _RoleRunner.run(task, prior_outputs)
    │             └── asyncio.to_thread(openai)
    │
    └── return TaskResult
```

串行设计保证后置角色能感知所有前置角色的输出（`prior_outputs` 累积传递）。每个角色是独立的 `_RoleRunner` 实例，拥有全新的 `messages[]`。

### 3.2 扩展至并行

若角色间无依赖，可改为 `asyncio.gather()`：

```python
# 并行执行独立角色（需角色间无数据依赖）
outputs = await asyncio.gather(*[
    _RoleRunner(spec).run(task, [])
    for spec in independent_specs
])
```

---

## 4. 多 Agent 系统：WorkerAgent + Kanban

### 4.1 并发模型

```
asyncio Event Loop
    │
    ├── asyncio.Task: WorkerAgent "w1".run_forever()
    │       loop:
    │         task = kanban.claim("w1")     ← threading.Lock 保护
    │         if task:
    │           result = await runner.run(task.goal)
    │           kanban.complete(task.id, result)
    │         else:
    │           await asyncio.sleep(poll_interval)  ← 让出 Loop
    │
    ├── asyncio.Task: WorkerAgent "w2".run_forever()
    │       (同上)
    │
    └── asyncio.Task: WorkerAgent "w3".run_forever()
            (同上)
```

三个 `asyncio.Task` 在同一 Event Loop 上交替执行（协作式多任务），通过 `await asyncio.sleep()` 让出控制权，实现伪并发。

### 4.2 Kanban 原子认领

```
WorkerAgent-1               WorkerAgent-2
      │                           │
      │  kanban.claim("w1")       │
      │  └─ acquire _lock ─────►  │ (等待)
      │     PENDING → IN_PROGRESS │
      │  release _lock            │
      │◄──────────────────────────┘
                                  │  kanban.claim("w2")
                                  │  └─ acquire _lock
                                  │     下一个 PENDING → IN_PROGRESS
                                  │  release _lock
```

`threading.Lock` 保证同一任务不被两个 Worker 同时认领，即使在多线程场景（`asyncio.to_thread` 路径）下也正确。

### 4.3 僵死任务恢复

Worker 执行中若崩溃，`kanban.release_stale(timeout_s=600)` 会将超时 IN_PROGRESS 任务重置为 PENDING，其他 Worker 可重新认领。

---

## 5. Mailbox：进程内/进程间通信

### 5.1 架构

```
Agent-A  ─── send_sync(to="B", msg) ──►  SQLite DB (mailboxes.db)
                                              │
Agent-B  ◄── recv_sync("B") ─────────────────┘
```

Mailbox 基于 SQLite，天然支持：
- **进程内通信**：同一进程中多个 Agent 共享 Mailbox 实例（或各自连接同一 DB 文件）
- **进程间通信**：不同进程连接同一 DB 文件，SQLite WAL 模式支持并发读写

### 5.2 通知机制（无轮询）

```
send_sync(to="B", msg)
    ├── INSERT INTO messages ...  (持有 _lock)
    └── _notify_inbox("B")
            └── inbox_events["B"].set()   ← 通知等待的 recv

recv("B", timeout=5.0)
    ├── _db_fetch("B")             # 先直接查
    │   → None (无消息)
    ├── event.clear()
    ├── _db_fetch("B")             # double-check 竞态
    │   → None
    └── asyncio.to_thread(event.wait, 5.0)
            ↑ 阻塞在线程池，不占 Event Loop
            │
            send_sync 触发 event.set()
            │
            └── _db_fetch("B")    # 被唤醒后取消息
```

关键优化：`threading.Event.wait()` 替代 100ms 定时 DB 查询，消息到达即唤醒。

### 5.3 线程安全层次

| 保护对象 | 机制 |
|----------|------|
| SQLite 连接 | `threading.Lock` (`_lock`) |
| 原子 SELECT+UPDATE | `BEGIN IMMEDIATE` 事务 |
| Event 通知 | `threading.Event` per agent |

---

## 6. BackgroundExecutor：慢操作后台化

```
主 Agent 协程
    │
    │  job_id = executor.submit_command("./build.sh")
    │  (立即返回，不阻塞)
    │
    │  # Agent 继续思考、处理其他消息...
    │
    │  result = executor.poll(job_id)
    │  if result["status"] == "done": ...
    │
    ▼

ThreadPoolExecutor
    └── Worker: subprocess.run("./build.sh")  ← 独立线程执行
            └── 完成时触发 on_complete 回调
```

`BackgroundExecutor` 将阻塞式 shell 命令放入线程池，主 Agent 不需要 `await`，以轮询（`poll()`）或回调（`on_complete()`）获取结果。

---

## 7. 并发拓扑总览

```
asyncio Event Loop (主线程)
├── HelloAgent                 ─── await ──► SubAgentRunner
│                                               └── to_thread ──► openai SDK
├── WorkerAgent "w1"           ─── await ──► SubAgentRunner
├── WorkerAgent "w2"           ─── await ──► SubAgentRunner
├── TaskPipeline               ─── await ──► _RoleRunner × N
│                                               └── to_thread ──► openai SDK
└── TeamCoordinator            ─── await ──► Mailbox.send/recv
                                               └── to_thread ──► sqlite3

ThreadPoolExecutor (线程池)
├── openai 同步 HTTP 调用
├── sqlite3 读写操作
├── BackgroundExecutor 任务 (shell 命令等)
└── threading.Event.wait (recv timeout)

共享数据结构
├── Kanban             (threading.Lock)
├── Mailbox._conn      (threading.Lock + BEGIN IMMEDIATE)
├── AgentRegistry      (进程单例，只读访问)
└── TaskGraph          (只在主协程修改，无需锁)
```

---

## 8. 设计原则总结

| 原则 | 体现 |
|------|------|
| **上下文隔离** | SubAgentRunner 每次创建独立 messages[]，子任务失败不影响父 Agent |
| **协作式并发** | asyncio.Task 通过 await 让出控制，避免线程切换开销 |
| **阻塞转非阻塞** | 所有 IO 密集操作通过 asyncio.to_thread 移入线程池 |
| **无中心调度** | WorkerAgent 自主轮询 Kanban，认领任务，可横向扩展 |
| **持久化通信** | Mailbox 基于 SQLite，进程重启后消息不丢 |
| **零轮询等待** | threading.Event 实现消息到达即唤醒，无 DB 轮询 |
