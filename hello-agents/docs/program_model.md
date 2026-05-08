# 程序模型视角：父子 Agent 与多 Agent 系统设计

> 本文从 **类结构、接口与设计模式** 角度，解释系统各组件的职责、协作方式与关键数据流。

---

## 1. 类层次总览

```
                        ┌─────────────────┐
                        │   HelloAgent    │  主 Agent，入口
                        │  (agent.py)     │
                        └────────┬────────┘
                                 │ 使用
              ┌──────────────────┼──────────────────────┐
              │                  │                      │
    ┌─────────▼────────┐  ┌──────▼───────┐  ┌──────────▼──────────┐
    │  SubAgentRunner  │  │ ToolRegistry │  │   TaskPipeline      │
    │  (subagent/)     │  │  (tools/)    │  │   (teams/)          │
    └─────────┬────────┘  └──────┬───────┘  └──────────┬──────────┘
              │                  │                      │
              │ 调用             │ 分发                  │ 编排
              ▼                  ▼                      ▼
         openai SDK         tool handlers           _RoleRunner × N
                         (read/write/bash/...)      (每角色独立 LLM 调用)

    ┌─────────────────────────────────────────────────────────┐
    │  多 Agent 基础设施                                        │
    │                                                         │
    │  AgentMessage ──► Mailbox ──► AgentRegistry             │
    │  (protocol.py)   (mailbox.py) (registry.py)             │
    │                                                         │
    │  WorkerAgent ──► Kanban ◄── TaskGraph                   │
    │  (worker.py)    (kanban.py)  (graph.py)                 │
    │                                                         │
    │  TeamCoordinator ──► Mailbox                            │
    │  (coordinator.py)                                       │
    │                                                         │
    │  BackgroundExecutor (tasks/background.py)               │
    └─────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────┐
    │  TaskPipeline 内部                                       │
    │                                                         │
    │  TaskAnalyzer ──► RoleSpec[] ──► _RoleRunner[] ──► TaskResult │
    │  (analyzer.py)   (role_spec.py)  (pipeline.py)         │
    │                                                         │
    │  TeamRoster ──► AgentTeam ──► TeamMember[]              │
    │  (roster.py)    (team.py)                               │
    └─────────────────────────────────────────────────────────┘
```

---

## 2. 父子 Agent 程序模型

### 2.1 SubAgentRunner：隔离上下文的执行单元

```python
class SubAgentRunner:
    _client: openai.OpenAI      # LLM 客户端
    _registry: ToolRegistry     # 可用工具集
    _max_tool_rounds: int       # 最多工具调用轮数

    async def run(task_desc, context_hint="") -> str:
        messages = [system_msg, user_msg]   # 全新上下文，不含历史
        for _ in range(_max_tool_rounds):
            response = await asyncio.to_thread(client.create, messages)
            if tool_calls:
                dispatch each tool → append results to messages
            else:
                return message.content       # 最终文本
```

**设计模式 — Chain of Responsibility**：LLM 决定是否调用工具，`ToolRegistry.dispatch()` 根据工具名路由到对应 handler，结果追加进 messages，下一轮 LLM 继续决策，直到不再产生工具调用。

### 2.2 父子关系数据流

```
父 Agent                         子 Agent (SubAgentRunner)
─────────                        ─────────────────────────
call runner.run("子任务")  ──────►  messages = [system, user]
                                          │
                                   LLM → tool_calls?
                                          │
                                   ToolRegistry.dispatch()
                                          │
                                   LLM → final text
                                          │
◄──────────────────────────────── return text
(父只见到结果，不见中间 tool_calls)
```

---

## 3. AgentMessage 协议

```python
@dataclass
class AgentMessage:
    msg_id: str           # 全局唯一 ID（uuid4 前8位）
    msg_type: MessageType # request/response/event/broadcast/vote/delegate
    from_agent: str       # 发送方 ID
    to_agent: str         # 接收方 ID
    correlation_id: str   # response 指向 request 的 msg_id
    payload: dict         # 业务数据
    created_at: datetime

    def make_response(from_agent, payload) -> AgentMessage:
        # correlation_id = self.msg_id，建立请求-响应关联
```

消息类型状态机：

```
request ──► response   （点对点请求/应答）
event                  （单向通知，无需应答）
broadcast              （一对多广播）
vote ──► vote_reply    （投票/回复）
delegate               （任务委托）
```

### 3.1 Request-Response 关联

```
Agent-A 发送:
  msg_id="abc123", msg_type="request", to="B", payload={task}

Agent-B 收到后调用 make_response():
  msg_id="xyz789", msg_type="response",
  correlation_id="abc123",    ← 关联原请求
  to="A", payload={result}

Agent-A 收到 response:
  if msg.correlation_id == sent_msg.msg_id: # 匹配
```

---

## 4. Mailbox：持久化消息队列

### 4.1 核心接口

```python
class Mailbox:
    # 异步 API（协程中使用）
    async def send(to_agent, msg) -> None
    async def recv(agent_id, timeout=0.0) -> AgentMessage | None

    # 同步 API（工具 dispatch 中使用）
    def send_sync(to_agent, msg) -> None
    def recv_sync(agent_id) -> AgentMessage | None

    # 批量 API
    def batch_send([(to, msg), ...]) -> None
    def read_all(agent_id) -> list[AgentMessage]

    # 维护
    def vacuum_consumed(keep_last=0) -> int
    def pending_count(agent_id) -> int
```

### 4.2 SQLite 表结构

```sql
CREATE TABLE messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    to_agent    TEXT NOT NULL,
    msg_json    TEXT NOT NULL,       -- AgentMessage.to_dict() 序列化
    consumed    INTEGER DEFAULT 0,   -- 0=未消费, 1=已消费
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_to_agent ON messages(to_agent, consumed);
```

### 4.3 原子取出（_db_fetch）

```python
def _db_fetch(agent_id) -> dict | None:
    with _lock:
        conn.execute("BEGIN IMMEDIATE")   # 排他写锁
        row = SELECT ... WHERE to_agent=? AND consumed=0 ORDER BY id LIMIT 1
        if row:
            UPDATE messages SET consumed=1 WHERE id=?
            conn.execute("COMMIT")
            return json.loads(row.msg_json)
        else:
            conn.execute("ROLLBACK")
            return None
```

`BEGIN IMMEDIATE` 保证 SELECT 和 UPDATE 之间不被其他连接穿插，多个 Worker 并发调用时每条消息恰好被取出一次。

---

## 5. 多 Agent 系统：WorkerAgent + Kanban

### 5.1 WorkerAgent 状态机

```
           ┌──────────────────┐
   start   │                  │
──────────►│  POLLING         │◄────────────┐
           │  (await sleep)   │             │
           └────────┬─────────┘             │
                    │ kanban.claim() → task  │
                    ▼                        │
           ┌──────────────────┐             │
           │  EXECUTING       │             │
           │  (await run())   │             │
           └────────┬─────────┘             │
                    │                        │
           ┌────────▼─────────┐             │
           │ complete / fail  │─────────────┘
           └──────────────────┘
```

### 5.2 Kanban 数据流

```
TaskGraph.ready_tasks()
    │  (依赖全部 DONE 的 PENDING 任务)
    ▼
Kanban.push(task)
    │
    ├── WorkerAgent-1: claim() → task.status=IN_PROGRESS
    ├── WorkerAgent-2: claim() → 下一个 PENDING（或 None）
    └── WorkerAgent-3: claim() → None，sleep

WorkerAgent-1 执行完成:
    Kanban.complete(task_id, result)
    └── task.status=DONE

    TaskGraph.ready_tasks() 返回依赖该任务的下一批任务
```

### 5.3 Kanban claim() 原子性

```python
def claim(agent_id) -> Task | None:
    with self._lock:              # 互斥
        for task in _tasks.values():
            if task.status == "PENDING":
                task.status = "IN_PROGRESS"  # 在锁内修改
                task.assignee = agent_id
                return task
    return None
```

锁范围覆盖"查找+修改"，防止 TOCTOU（Time-of-Check-Time-of-Use）竞态。

---

## 6. TeamCoordinator：团队交互

### 6.1 接口

```python
class TeamCoordinator:
    mailbox: Mailbox

    async def broadcast(team, content, from_agent)    # 广播给所有成员
    async def vote(team, question, options, from_agent, timeout) -> {opt: count}
    async def delegate(to_agent, task_desc, from_agent) -> msg_id
```

### 6.2 通信序列图

**广播（broadcast）**：
```
lead ──broadcast──► [member_1, member_2, member_3]
     (AgentMessage, msg_type="broadcast")
```

**委托（delegate）**：
```
lead ──delegate──► member_1
                       │  执行任务
                       │
lead ◄─response───── member_1
     (correlation_id 关联原请求)
```

**投票（vote）**：
```
lead ──vote──► [member_1, member_2]
                    │
                    ▼ (各自决策后)
lead ◄─vote_reply── member_1  (payload: {vote: "yes"})
lead ◄─vote_reply── member_2  (payload: {vote: "no"})

lead: read_all(from_agent) → 统计票数
```

---

## 7. TaskPipeline：动态角色编排

### 7.1 类关系

```
TaskPipeline
├── TaskAnalyzer          # LLM 分析任务 → 生成完整角色定义
│   └── 输出: RoleSpec[]
│         ├── role: str              ("coder")
│         ├── display_name: str      ("代码实现工程师")
│         ├── system_prompt: str     (完整系统提示词)
│         ├── capabilities: list     (["write_code", ...])
│         └── reason: str            (LLM 的选角理由)
│
├── _RoleRunner × N       # 每角色独立 LLM 会话
│   └── 输入: task + prior_outputs[]
│   └── 输出: RoleOutput.content
│
├── TeamRoster            # 持久化本次执行记录
│   └── AgentTeam
│       └── TeamMember[]
│
└── TaskResult            # 聚合所有角色产出
    ├── outputs: {role → RoleOutput}
    ├── .code / .test_cases / .design_doc ...  (快捷属性)
    ├── to_markdown() -> str
    └── save_report(path=None) -> str
```

### 7.2 LLM 角色设计 vs. 预设角色

| | LLM 设计 | 预设角色 (`from_role()`) |
|--|---------|-------------------------|
| 触发 | `solve()` 不传 `roles` 参数 | `solve(roles=["coder","tester"])` |
| system_prompt | LLM 根据任务定制 | `role_spec.py` 中预定义 |
| 兜底 | `_default_specs([researcher, writer, reviewer])` | 无兜底，直接使用 |
| 优势 | 自适应任何类型任务 | 可预测、可测试 |

---

## 8. AgentRegistry：进程单例注册表

```python
class AgentRegistry:
    _agents: dict[str, PeerAgent]

    def register(agent) -> None
    def get(agent_id) -> PeerAgent | None
    def list_agents() -> list[PeerAgent]
    def unregister(agent_id) -> bool

# 模块级单例
_registry = AgentRegistry()

def get_registry() -> AgentRegistry:
    return _registry
```

**设计模式 — Registry**：全局唯一注册表，所有 Agent 通过 `get_registry()` 获取引用，无需依赖注入传递实例。适合进程内 Agent 互相发现。

---

## 9. TaskGraph：DAG 依赖管理

```python
class TaskGraph:
    _tasks: dict[str, Task]

    def add(task) -> None
    def ready_tasks() -> list[Task]    # 依赖全 DONE 的 PENDING 任务
    def topological_order() -> list[Task]  # Kahn 算法拓扑排序
    def has_cycle() -> bool
```

**就绪判断**：
```python
def ready_tasks():
    for task in _tasks.values():
        if task.status != "PENDING": continue
        deps_done = all(
            _tasks[dep].status == "DONE"
            for dep in task.deps
        )
        if deps_done:
            yield task
```

依赖图示例：
```
task-A ──► task-C ──► task-E
task-B ──► task-C

task-C.deps = ["task-A", "task-B"]
task-C 就绪条件: A.status==DONE AND B.status==DONE
```

---

## 10. 设计模式汇总

| 模式 | 位置 | 说明 |
|------|------|------|
| **Chain of Responsibility** | SubAgentRunner + ToolRegistry | LLM 决策 → 工具调用链 |
| **Registry** | AgentRegistry | 进程单例，Agent 互相发现 |
| **Observer/Event** | Mailbox + threading.Event | 消息到达通知，无轮询 |
| **Command** | AgentMessage | 消息即命令对象，含 msg_type + payload |
| **Factory Method** | RoleSpec.from_role() / TaskAnalyzer | 创建 RoleSpec 的两条路径 |
| **Pipeline** | TaskPipeline | 串行角色数据流，前置输出传递 |
| **Worker Pool** | WorkerAgent + Kanban | 自组织任务认领，无中心调度 |
| **Proxy** | asyncio.to_thread | 将阻塞调用包装为异步接口 |

---

## 11. 关键接口边界

```
外部调用者
    │
    ├── TaskPipeline.solve(task) ──► TaskResult
    │   （高层接口，屏蔽 LLM/角色/序列化细节）
    │
    ├── SubAgentRunner.run(task) ──► str
    │   （中层接口，屏蔽 tool_call 循环）
    │
    ├── Mailbox.send/recv ──► AgentMessage
    │   （通信接口，屏蔽 SQLite 细节）
    │
    └── Kanban.claim/complete/fail
        （任务调度接口，屏蔽并发控制细节）
```

所有接口对调用者屏蔽内部实现，调用方只需：
- 知道任务描述 → TaskPipeline.solve()
- 知道消息格式 → Mailbox.send(AgentMessage)
- 知道任务状态转换 → Kanban.claim() / complete()
