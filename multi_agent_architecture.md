# hello-agents 多 Agent 系统架构解析

> 基于 `hello-agents/hello_agents/` 源码逐文件分析
> 版本：v5（含 s00–s19 全架构）

---

## 零、设计动机与核心问题

### 为什么需要多 Agent？

单个 LLM Agent 面临三类本质限制：

**1. 上下文窗口瓶颈**
一个 Agent 处理复杂任务时，历史对话、工具结果、中间推理会迅速填满 context window。任务越长，遗忘越严重，最终导致决策质量下降。多 Agent 的解法是**上下文隔离**——每个子任务由独立的 `SubAgentRunner` 用全新 `messages[]` 执行，父 Agent 只收到最终结论，中间过程不污染主对话（s04）。

**2. 单线程串行瓶颈**
复杂任务往往包含可并行的子任务（如：同时搜集资料、同时编写多个模块）。单 Agent 必须串行执行，等待慢操作（网络、shell 命令）时完全阻塞。多 Agent 的解法是**并行执行**——`WorkerAgent` 并发认领 Kanban 中的任务，`BackgroundExecutor` 将慢操作丢入线程池，主 Agent 继续响应用户（s08/s11）。

**3. 能力边界瓶颈**
没有哪个 Agent 能精通所有领域。单 Agent 用同一个 system prompt 承担"研究员 + 程序员 + 审查员"多种角色，容易产生角色混淆和决策质量下降。多 Agent 的解法是**专业化分工**——每个 `PeerAgent` 有独立的 `speciality`、`system_prompt` 和 `tool_names` 白名单，路由决策基于专长而非随机（s09）。

---

### 核心设计问题与对应方案

| 问题 | 症状 | 本系统方案 |
|------|------|-----------|
| **任务状态如何不丢失？** | 进程崩溃后所有进行中任务消失 | `TaskStore` 磁盘持久化 + `CheckpointStore` 断点续跑 |
| **多个 Worker 如何避免抢同一任务？** | 两个 Worker 同时认领同一 PENDING 任务，重复执行 | `Kanban.claim()` 在 `threading.Lock` 内原子地查找+修改状态 |
| **僵死任务如何检测与恢复？** | Worker 崩溃后任务永远停在 IN_PROGRESS | `AutonomousAgent` 每 30s 心跳，`Kanban.release_stale()` 超时重置为 PENDING |
| **Agent 间如何异步通信？** | 直接函数调用要求双方同时在线，紧耦合 | `Mailbox`（SQLite 持久化队列）解耦发送方和接收方，消息可跨进程重启存活 |
| **子任务结果如何不污染主对话？** | 子任务的 100 轮 tool_calls 全挤进主 Agent context | `SubAgentRunner` 独立 `messages[]`，父 Agent 只收文本结论 |
| **并行任务间如何管理依赖？** | 任务 B 依赖任务 A 的结果，但 B 提前开始执行 | `TaskGraph` DAG 建模，`ready_tasks()` 只返回依赖全部 DONE 的任务 |
| **并行文件操作如何互不干扰？** | 两个 Worker 同时修改同一文件，产生冲突 | `WorktreeManager` 为每个任务分配独立 git worktree（s18） |
| **主 Agent context 如何不爆炸？** | 工具返回大结果（如日志文件）直接塞入 messages | 三层压缩：大结果落盘→旧结果折叠→LLM 摘要，每轮 LLM 调用前自动执行 |

---

### 设计哲学

```
"单一循环 + 可扩展工具"

核心 loop 永远是：
    while True:
        response = LLM(messages, tools)
        if response.tool_calls:
            result = dispatch(tool_call)   ← 所有能力在这里扩展
            messages.append(result)
        else:
            return response.text

多 Agent = 把 dispatch() 的边界延伸到另一个进程/线程的 LLM。
```

这个设计使得：
- **主 Agent 代码不因能力扩展而膨胀**（s01/s02）：新能力 = 新 handler，loop 不变
- **子 Agent 对主 Agent 透明**：从主 Agent 视角看，调用 `send_to_agent` 和调用 `run_command` 没有区别，都是一个 tool_call
- **水平扩展自然**：再加一个 `WorkerAgent` 实例，Kanban 自动分摊负载，无需修改任何调度代码

---

## 一、总览

```
用户
  │
  ▼
HelloAgent (agent.py)          ← 主 Agent，唯一对外入口
  ├── ToolRegistry              ← 工具分发（s02）
  ├── ContextBuilder (GSSC)     ← 上下文组装（s05）
  ├── MemoryManager             ← 四层记忆系统
  ├── Scheduler + TaskGraph     ← DAG 任务调度（s07）
  ├── BackgroundExecutor        ← 后台线程池（s08/s13）
  ├── Mailbox + AgentRegistry   ← Agent 间通信（s09/s10）
  │
  ├── SubAgentRunner            ← 隔离上下文子 Agent（s04）
  │     └── WorkerAgent         ← 自组织认领 Kanban（s11）
  │
  └── AgentTeam + TeamCoordinator  ← 团队协作（s15/s16）
        └── AutonomousAgent         ← 自治 + 心跳 + 续跑（s17）
```

---

## 二、核心设计原则

| 编号 | 原则 | 体现位置 |
|------|------|---------|
| s01 | `_generate_with_tools` 是**唯一**循环，≤20 行 | `agent.py:238` |
| s02 | 新工具只需 `register_handler`，不改 loop | `tools/registry.py` |
| s03 | 可选 Planner 先拆步骤再执行 | `planner/planner.py` |
| s04 | 子任务用独立 `messages[]`，不污染主对话 | `subagent/runner.py` |
| s05 | 记忆/知识按需注入（tool_result），system prompt 精简 | `context/builder.py` |
| s07 | DAG 任务图 + 拓扑排序 + 循环检测 | `tasks/graph.py` |
| s08 | 慢操作丢线程池，主 Agent 继续响应 | `tasks/background.py` |
| s09 | 每个 Agent 有 SQLite 持久化邮箱 | `multi_agent/mailbox.py` |
| s10 | 所有跨 Agent 通信强制走 `AgentMessage` 格式 | `multi_agent/protocol.py` |
| s11 | WorkerAgent 自主轮询看板认领，无需中心调度器 | `multi_agent/worker.py` |
| s12 | Kanban 三列看板原子 claim，防止重复认领 | `tasks/kanban.py` |
| s13 | BackgroundExecutor 支持完成回调 | `tasks/background.py` |
| s15 | AgentTeam 持久化成员/角色/共享规则 | `teams/team.py` |
| s16 | TeamCoordinator 广播/投票/委托 | `teams/coordinator.py` |
| s17 | AutonomousAgent 心跳 + 超时释放 + 断点续跑 | `teams/autonomous.py` |
| s18 | Git worktree 隔离 + 命名通道 + 定时 GC | `tasks/worktree.py` |

---

## 三、主 Agent：HelloAgent

**文件**：`agent.py`

```python
class HelloAgent:
    def __init__(self, memory_manager, kb_manager, ...)
    async def chat(user_message, session_id) -> str   # 对外入口
    async def _generate_with_tools(messages) -> str   # s01 唯一循环
```

### 3.1 工具注册（s02）

```
HelloAgent.from_env() 中注册：

MemoryToolHandler  ← store_memory / search_memory / delete_memory
RAGToolHandler     ← search_knowledge / list_knowledge_bases
NoteToolHandler    ← create_note / list_notes / get_note
TerminalToolHandler← run_command（白名单过滤危险命令）
WebSearchToolHandler← web_search
TaskToolHandler    ← create_task / list_tasks / update_task_status
BackgroundToolHandler← run_background / poll_background
AgentToolHandler   ← send_to_agent / read_mailbox / list_agents
```

### 3.2 对话流程（一轮）

```
用户输入
  │
  ├─ 1. 工作记忆取最近 10 条历史（WorkingMemory.to_context_string）
  ├─ 2. ContextBuilder.build() 拉取相关记忆/知识（GSSC）
  ├─ 3. 拼装 system + 历史 + 用户消息 → messages[]
  │
  └─ _generate_with_tools(messages)   ← s01 唯一循环
       for _ in range(max_tool_rounds=5):
           apply_all_layers(messages)  ← 三层压缩
           call_llm(messages, tools)
           if tool_calls:
               run_one_tool() → append tool_result
           else:
               return final text
  │
  ├─ 4. 记录到 WorkingMemory
  └─ 5. 异步存入 EpisodicMemory（不阻塞响应）
```

---

## 四、工具系统

**文件**：`tools/registry.py`、`tools/builtin/`

### 4.1 ToolRegistry

```python
class ToolRegistry:
    register_handler(handler, tool_schemas)   # 注册 handler
    dispatch(tool_call) -> str                # 统一分发（同步）
    get_schemas() -> list[dict]               # 返回所有 tool schema
```

- 每个 `handler.TOOL_NAMES` 集合决定它处理哪些工具名
- dispatch 返回字符串 JSON，直接作为 `role=tool` 消息的 content

### 4.2 Agent 间通信工具（s09/s10）

**文件**：`tools/builtin/agent_tool.py`

| 工具 | 参数 | 功能 |
|------|------|------|
| `send_to_agent` | `to_agent`, `content`, `task_id?` | 向目标 Agent 投递 request 消息 |
| `read_mailbox` | `agent_id` | 取出邮箱下一条消息（FIFO） |
| `list_agents` | — | 列出 AgentRegistry 中所有已注册 Agent |

---

## 五、多 Agent 协作子系统

### 5.1 PeerAgent — 持久化 Agent 描述（s09）

**文件**：`multi_agent/peer.py`

```python
@dataclass
class PeerAgent:
    agent_id: str       # 唯一 ID
    name: str
    speciality: str     # 路由决策依据
    system_prompt: str  # 该 Agent 的角色指令
    tool_names: list[str]  # 可用工具白名单
```

- `to_dict()` / `from_dict()` 支持序列化，跨进程持久化

### 5.2 AgentRegistry — 全局注册表

**文件**：`multi_agent/registry.py`

```python
_registry = AgentRegistry()  # 进程级单例
get_registry() -> AgentRegistry
```

- `register(agent)` / `get(agent_id)` / `list_agents()` / `unregister()`
- AgentToolHandler 的 `list_agents` 工具从此处读取

### 5.3 AgentMessage — 统一消息协议（s10）

**文件**：`multi_agent/protocol.py`

```python
@dataclass
class AgentMessage:
    msg_id: str          # UUID[:8]
    msg_type: Literal["request","response","event","broadcast","vote","vote_reply","delegate"]
    from_agent: str
    to_agent: str
    correlation_id: str | None  # response 指向对应 request 的 msg_id
    payload: dict[str, Any]     # 业务数据
    created_at: datetime
```

- `make_response()` 自动填 `correlation_id`，保证请求-响应可追踪

### 5.4 Mailbox — SQLite 持久化邮箱（s09）

**文件**：`multi_agent/mailbox.py`

```
Schema: messages(id, to_agent, msg_json, consumed, created_at)
Index:  (to_agent, consumed)
```

| API | 用途 |
|-----|------|
| `send_sync(to_agent, msg)` | 同步投递（tool dispatch 内调用） |
| `recv_sync(agent_id)` | 同步取消息，consumed=1 |
| `send(to_agent, msg)` | 异步投递（带 asyncio.Lock） |
| `recv(agent_id, timeout)` | 异步取消息，可带超时轮询 |
| `read_all(agent_id)` | 取出所有未消费消息 |
| `pending_count(agent_id)` | 查询待处理消息数 |

- **持久化**：进程重启后消息不丢失
- **并发安全**：async 路径带锁，sync 路径各自连接

### 5.5 WorkerAgent — 自组织 Worker（s11）

**文件**：`multi_agent/worker.py`

```python
class WorkerAgent:
    def __init__(self, agent_id, kanban, runner, poll_interval=2.0)
    async def run_forever()   # 主循环
    def stop()                # 优雅退出
```

**认领循环**：
```
while running:
    task = kanban.claim(agent_id)     # 原子认领
    if task:
        result = await runner.run(task.goal)
        kanban.complete(task.id, result)
    else:
        await sleep(poll_interval)
```

- 多个 WorkerAgent 并发认领同一 Kanban 不会重复（Kanban 加锁）
- 失败自动调用 `kanban.fail(task_id, reason)`

---

## 六、任务调度子系统

### 6.1 Task & Step 数据模型（s07）

**文件**：`tasks/models.py`

```python
TaskStatus = Literal["PENDING", "IN_PROGRESS", "DONE", "FAILED"]

@dataclass
class Step:
    id, desc, tool_hint, deps: list[str], status

@dataclass
class Task:
    id, goal, steps: list[Step]
    status: TaskStatus
    assignee: str | None
    deps: list[str]         # 依赖的其他 task_id 列表
    worktree: str | None    # 关联的 git worktree 路径
    result: str | None
    created_at, updated_at: datetime
    touch()                 # 更新 updated_at
```

### 6.2 TaskGraph — DAG 依赖管理（s07）

**文件**：`tasks/graph.py`

```python
class TaskGraph:
    add(task)             # 加入图
    ready_tasks()         # 依赖全部 DONE 的 PENDING 任务
    topological_order()   # Kahn 算法拓扑排序
    has_cycle()           # 循环检测
```

- `ready_tasks()` 是 Scheduler/WorkerAgent 获取下一批可并行任务的入口
- 循环依赖时 `topological_order()` 抛 `ValueError`

### 6.3 Scheduler — 调度门面（s07）

**文件**：`tasks/scheduler.py`

```
Scheduler = TaskGraph + TaskStore（持久化）
```

- `add(task)` → 写图 + 写磁盘
- `next_ready()` → 返回第一个就绪任务
- `update_status(task_id, status, result)` → 更新 + 持久化

### 6.4 Kanban — 三列看板（s12/s17）

**文件**：`tasks/kanban.py`

```
PENDING → claim() → IN_PROGRESS → complete()/fail() → DONE/FAILED
```

```python
class Kanban:
    push(task)                    # 推入 PENDING 任务
    claim(agent_id) -> Task|None  # 原子认领（threading.Lock）
    complete(task_id, result)
    fail(task_id, reason)
    touch(task_id, agent_id)      # 心跳更新（v5 s17）
    release_stale(timeout_s=600)  # 超时重置为 PENDING（v5 s17）
    pending() / in_progress() / done() / all_tasks()
```

- `claim()` 在锁内查找第一个 PENDING 并立即改为 IN_PROGRESS，保证原子性
- `release_stale()` 由外部定时调用，释放无心跳的僵死任务

### 6.5 BackgroundExecutor — 后台线程池（s08/s13）

**文件**：`tasks/background.py`

```python
class BackgroundExecutor:
    submit(fn, *args) -> job_id            # 任意可调用对象
    submit_command(command) -> job_id      # shell 命令
    poll(job_id) -> {"status": ..., "result": ...}
    on_complete(job_id, callback)          # 注册完成回调（v5 s13）
    cancel(job_id)
    shutdown()
```

- `status` 可能值：`running` / `done` / `error`
- 回调在任务完成时自动触发（或任务已完成时立即触发）

### 6.6 WorktreeManager — Git Worktree 隔离（s18）

**文件**：`tasks/worktree.py`

```
.worktrees/
├── <task_id>/           ← create(task_id)
├── main/<task_id>/      ← create_named("main", task_id)
├── agent-alice/<task_id>/
└── review/<task_id>/
```

| 方法 | 说明 |
|------|------|
| `create(task_id, branch?)` | 创建 git worktree（失败降级 mkdir） |
| `create_named(lane, task_id)` | 命名通道隔离 |
| `remove(task_id)` | 移除 worktree（force） |
| `path_for(task_id)` | 查 worktree 路径 |
| `list_lanes()` | 列出所有通道名 |
| `gc(ttl_hours=24)` | 异步清理过期 worktree |
| `start_gc_loop(interval, ttl)` | 后台定时 GC |

---

## 七、团队协作子系统

### 7.1 AgentTeam — 持久化团队（s15）

**文件**：`teams/team.py`

```python
@dataclass
class TeamMember:
    agent_id, role, capabilities: list[str]

@dataclass
class AgentTeam:
    team_id, name
    members: list[TeamMember]
    shared_rules: list[str]         # 协调规则（自然语言）
    shared_memory_ns: str           # 共享记忆命名空间（"team:<id>"）
```

查询接口：
- `members_with_role(role)` — 按角色筛选
- `members_with_capability(cap)` — 按能力筛选

### 7.2 TeamCoordinator — 协调器（s16）

**文件**：`teams/coordinator.py`

```python
class TeamCoordinator:
    async broadcast(team, content, from_agent)       # 向所有成员广播
    async vote(team, question, options, from_agent)  # 发起投票（超时收集）
    async delegate(to_agent, task_desc, from_agent)  # 委托单个成员
```

- 所有操作底层都通过 `Mailbox.send_sync` 投递 `AgentMessage`
- `vote()` 使用 `msg_type="vote"`，回复使用 `"vote_reply"`

### 7.3 AutonomousAgent — 自治 Agent（s17）

**文件**：`teams/autonomous.py`

```python
class AutonomousAgent:
    async run()    # asyncio.gather(_claim_loop, _heartbeat_loop)
    async resume(task_id)  # 从 CheckpointStore 断点续跑
    stop()
```

**并发结构**：
```
asyncio.gather(
    _claim_loop()       ← 轮询认领 + asyncio.wait_for(timeout)
    _heartbeat_loop()   ← 每 30s 更新 kanban last_seen
)
```

- 任务执行有 `task_timeout`（默认 600s）超时保护
- 崩溃前先 `checkpoint.save(task_id, [], step_idx=0)`
- 超时后调用 `kanban.fail(task_id, "timeout")`

---

## 八、上下文管理（GSSC 流水线 + 三层压缩）

### 8.1 ContextBuilder — GSSC（s05）

**文件**：`context/builder.py`

```
Gather  → 从记忆/知识库拉取候选上下文
Select  → 按 token 预算打分截断
Structure → 格式化为结构化文本
Compress  → 长文本调用 LLM 摘要
```

### 8.2 三层压缩（每轮 LLM 调用前执行）

**文件**：`context/compress.py` → `apply_all_layers(messages)`

```
Layer 1 — 大结果落盘（spill_large_results）
    工具结果 > 3000 chars → 写 /tmp/agent_context_spill/<id>.txt
    messages 中只保留 300 chars 预览 + 文件路径

Layer 2 — 旧结果折叠（fold_old_results）
    保留最近 6 条 tool_result 原文
    更早的替换为 "[已折叠: <tool_name> 结果已归档]"

Layer 3 — 整体摘要（summarize_history）
    messages 总字符 > 20000 → 调用 LLM 生成连续性摘要
    保留最近 4 轮对话原文，旧部分替换为单条 system 摘要消息
    可选：同时提取结构化会话状态（目标/已完成/修改文件/待完成/关键决策）
```

### 8.3 SessionState — 结构化会话跟踪（s05 扩展）

**文件**：`context/session_state.py`

```python
@dataclass
class SessionState:
    current_goal: str
    completed_actions: list[str]
    modified_files: list[str]
    pending_steps: list[str]
    key_decisions: list[str]
```

---

## 九、记忆系统（四层认知记忆）

### 9.1 四种记忆类型

| 类型 | 文件 | 生命周期 | 存储后端 |
|------|------|---------|---------|
| WorkingMemory | `memory/types/working.py` | 会话内，滑窗 | 进程内 dict |
| EpisodicMemory | `memory/types/episodic.py` | 跨会话，带遗忘曲线 | Qdrant 向量库 |
| SemanticMemory | `memory/types/semantic.py` | 长期知识 | Qdrant + Neo4j 图谱 |
| PerceptualMemory | `memory/types/perceptual.py` | 短期感知 | 进程内（TTL 清理） |

### 9.2 MemoryManager — 统一入口

**文件**：`memory/manager.py`

```python
class MemoryManager:
    write(content, type, importance, metadata, session_id)
    read(query, session_id) -> list[MemorySearchResult]
    get_working_memory(session_id) -> WorkingMemory
    async start() / stop()
```

- `MemoryRouter` 根据 `MemoryType` 路由到对应存储后端
- `ReflectionEngine` 定期将高价值 EpisodicMemory 提炼为 SemanticMemory
- `MemoryGC` 按 Ebbinghaus 遗忘曲线计算 `strength`，清理已遗忘条目
- `EventBus` 在写入/读取时发布 `MemoryEvent`，供反思引擎订阅

### 9.3 存储后端

| 后端 | 文件 | 用途 |
|------|------|------|
| QdrantStore | `memory/storage/qdrant_store.py` | 向量语义检索 |
| Neo4jStore | `memory/storage/neo4j_store.py` | 实体关系图遍历 |
| DocumentStore | `memory/storage/document_store.py` | 降级：内存/文件 |

---

## 十、SubAgentRunner — 隔离上下文（s04）

**文件**：`subagent/runner.py`

```python
class SubAgentRunner:
    async run(task_desc, context_hint="") -> str
```

- 每次调用使用**全新**的 `messages[]`（无主对话历史）
- 有独立的 tool-calling 循环（最多 `max_tool_rounds=5` 轮）
- 父 Agent 只收到最终文本结果，中间 tool_calls 不暴露
- `temperature=0.3`（比主 Agent 0.7 更确定性，适合执行任务）

---

## 十一、完整数据流：WorkerAgent 执行一个任务

```
① 主 Agent 通过 TaskToolHandler 调用 create_task("分析日志")
   └── Scheduler.add(Task(goal="分析日志", deps=[]))
   └── TaskStore 持久化到磁盘

② WorkerAgent.run_forever() 轮询
   └── Kanban.claim("worker-1") → Task(status=IN_PROGRESS, assignee="worker-1")

③ WorktreeManager.create(task.id)
   └── git worktree add .worktrees/task-abc123

④ SubAgentRunner.run("分析日志")
   └── 独立 messages[] + tool_calls（TerminalTool 执行命令）
   └── return "发现 3 种错误模式：..."

⑤ Kanban.complete(task.id, result)
   └── status = DONE，result = "发现 3 种错误模式：..."

⑥ 主 Agent 调用 list_tasks / poll_background 查询结果
   └── 可通过 AgentToolHandler.read_mailbox 接收通知消息
```

---

## 十二、Agent 间通信完整流程

```
主 Agent (agent_id="main")
   │
   │  ToolCall: send_to_agent(to="researcher", content="请搜集关于 X 的资料")
   ▼
AgentToolHandler._send_to_agent()
   └── AgentMessage(from="main", to="researcher", type="request", payload={...})
   └── Mailbox.send_sync("researcher", msg)         ← SQLite 持久化
                                                        ↓
                                              researcher 的轮询
                                                        ↓
                                           Mailbox.recv_sync("researcher")
                                                        ↓
                                           SubAgentRunner.run("搜集关于 X 的资料")
                                                        ↓
                                           AgentMessage(type="response", correlation_id=...)
                                           Mailbox.send_sync("main", reply)
   │
   │  ToolCall: read_mailbox(agent_id="main")
   ▼
AgentToolHandler._read_mailbox("main")
   └── Mailbox.recv_sync("main") → {"from": "researcher", "payload": {...}}
```

---

## 十三、关键依赖关系图

```
HelloAgent
├── ToolRegistry
│   ├── AgentToolHandler ──→ Mailbox ──→ AgentRegistry (PeerAgent)
│   ├── TaskToolHandler  ──→ Scheduler ──→ TaskGraph + TaskStore
│   └── BackgroundToolHandler ──→ BackgroundExecutor
│
├── ContextBuilder (GSSC)
│   └── apply_all_layers (三层压缩)
│
└── MemoryManager
    ├── WorkingMemory (per session)
    ├── EpisodicMemory → QdrantStore
    ├── SemanticMemory → QdrantStore + Neo4jStore
    └── ReflectionEngine (Episodic → Semantic)

WorkerAgent ──→ Kanban ←── AutonomousAgent
WorkerAgent ──→ SubAgentRunner
AutonomousAgent ──→ CheckpointStore (断点续跑)

TeamCoordinator ──→ Mailbox (广播/投票/委托)
AgentTeam ──→ TeamMember (role + capabilities)
```

---

## 十五、任务下发与角色协作完整流程

> 场景：Lead 接到顶层任务"开发用户登录功能"，需要 researcher / coder / reviewer 三个角色串行协作完成。

### 15.1 全局流程图

```
用户/上层系统
    │ 下发顶层任务
    ▼
Lead Agent
    │
    │ 1. 任务拆分 → TaskGraph
    │    T1(researcher) ──→ T2(coder) ──→ T3(reviewer)
    │
    │ 2. 持久化 → TaskStore（tasks.jsonl）
    │
    ╔═══════════════════════════════════════╗
    ║    每轮推进（直到全部 DONE）            ║
    ║                                       ║
    ║  ① ready_tasks() → 取就绪任务          ║
    ║  ② 按角色 → coordinator.delegate()    ║
    ║  ③ Mailbox 落盘（SQLite）              ║
    ║  ④ Worker 读取 → SubAgentRunner 执行   ║
    ║  ⑤ make_response() → 写 Lead Mailbox  ║
    ║  ⑥ Lead 读取 → scheduler.update DONE  ║
    ║  ⑦ TaskGraph 自动解锁下一批就绪任务    ║
    ╚═══════════════════════════════════════╝
    │
    │ 3. 汇总三份结果
    ▼
最终交付
```

---

### 15.2 Step 1 — 任务拆分与 DAG 建模

Lead 接到任务后，将其拆解为**子任务 + 依赖关系**，写入 `TaskGraph` 和 `TaskStore`：

```python
t1 = Task(goal="researcher: 分析用户登录需求")
t2 = Task(goal="coder: 实现登录功能",    deps=[t1.id])  # T1 完成后才能开始
t3 = Task(goal="reviewer: 审查登录代码", deps=[t2.id])  # T2 完成后才能开始

for t in [t1, t2, t3]:
    scheduler.add(t)  # 写 TaskGraph + TaskStore（磁盘持久化）
```

此时 `TaskGraph` 状态：

```
T1(PENDING) ──deps──▶ T2(PENDING) ──deps──▶ T3(PENDING)
     ↑
 唯一就绪
```

**为什么用 DAG？**
- 显式建模依赖，T2 的输入依赖 T1 的输出，不能并发执行
- `topological_order()` 保证任何调度策略都不会违反依赖顺序
- 并行无依赖的任务（如 T_a 和 T_b）会同时出现在 `ready_tasks()`，可同步委托

---

### 15.3 Step 2 — 依赖守门：ready_tasks()

每轮推进前，Lead 调用 `scheduler._graph.ready_tasks()`：

```python
ready = scheduler._graph.ready_tasks()
# 返回：deps 全部为 DONE 且自身为 PENDING 的任务列表
```

**守门机制**（`tasks/graph.py:43`）：

```python
def ready_tasks(self):
    for task in self._tasks.values():
        if task.status != "PENDING":
            continue
        deps_ok = all(
            self._tasks[dep_id].status == "DONE"
            for dep_id in task.deps
        )
        if deps_ok:
            yield task
```

- 初始只有 T1 就绪（无依赖）
- T1 变为 DONE → T2 解锁
- T2 变为 DONE → T3 解锁
- 调度器**不可能**在 T1 未完成时派发 T2

---

### 15.4 Step 3 — 角色路由：Coordinator → Mailbox

Lead 根据任务 goal 前缀（约定格式 `"role: 描述"`）映射到 agent_id，调用 `TeamCoordinator.delegate()`：

```python
role_to_agent = {"researcher": "researcher", "coder": "coder", "reviewer": "reviewer"}

role     = task.goal.split(":")[0]          # "researcher"
agent_id = role_to_agent[role]

msg_id = await coordinator.delegate(
    to_agent=agent_id,         # "researcher"
    task_desc=task.goal,
    from_agent="lead",
)
scheduler.update_status(task.id, "IN_PROGRESS")
```

底层：`TeamCoordinator.delegate()` 创建 `AgentMessage(msg_type="delegate")` 并调用 `Mailbox.send_sync(agent_id, msg)`，消息写入 SQLite：

```sql
INSERT INTO messages (to_agent, msg_json) VALUES ('researcher', '{"msg_type":"delegate",...}')
```

此时 **researcher 的邮箱有 1 条消息，coder 和 reviewer 为 0**，精确路由。

---

### 15.5 Step 4 — Worker 执行与回复

Worker（真实系统中为 `WorkerAgent` 或 `AutonomousAgent`）轮询自己的 Mailbox：

```python
# Worker: researcher
incoming = mailbox.recv_sync("researcher")  # 取出委托消息，consumed=1
# incoming.msg_type == "delegate"
# incoming.payload == {"task_desc": "researcher: 分析用户登录需求", ...}

# 调用 SubAgentRunner 执行（隔离上下文，不污染主对话）
result = await runner.run(incoming.payload["task_desc"])

# 构造回复，correlation_id 自动指向原始 msg_id
reply = incoming.make_response(
    from_agent="researcher",
    payload={"result": result, "task_id": task.id},
)
mailbox.send_sync("lead", reply)
```

`make_response()` 的关键作用：

```python
def make_response(self, from_agent, payload):
    return AgentMessage(
        from_agent=from_agent,
        to_agent=self.from_agent,        # 回给 lead
        msg_type="response",
        correlation_id=self.msg_id,      # ← 与原 request 关联
        payload=payload,
    )
```

**为什么用 correlation_id？**
Lead 可能同时向多个 Worker 发出委托（并行任务），回复乱序到达时，`correlation_id == request.msg_id` 确保 Lead 能精确匹配"哪条回复对应哪个请求"。

---

### 15.6 Step 5 — Lead 处理回复，推进 DAG

```python
response = mailbox.recv_sync("lead")
# response.correlation_id == incoming.msg_id  ← 可追溯

result_text  = response.payload["result"]
completed_id = response.payload["task_id"]

scheduler.update_status(completed_id, "DONE", result_text)
# ↑ 写 TaskGraph（task.status = DONE）+ TaskStore（追加快照到磁盘）
```

`update_status` 完成后，`TaskGraph.ready_tasks()` 在下一轮自动解锁 T2（因为它的 dep T1 现在是 DONE）。

---

### 15.7 三轮完整时序图

```
Lead              TaskGraph          Mailbox(SQLite)       researcher  coder   reviewer
 │                   │                    │                    │         │         │
 │ add(T1,T2,T3)     │                    │                    │         │         │
 │─────────────────▶│                    │                    │         │         │
 │                   │                    │                    │         │         │
 │ ready=[T1]        │                    │                    │         │         │
 │◀─────────────────│                    │                    │         │         │
 │ delegate(researcher, T1)              │                    │         │         │
 │──────────────────────────────────────▶ send(researcher)   │         │         │
 │ update(T1, IN_PROGRESS)              │                    │         │         │
 │─────────────────▶│                    │                    │         │         │
 │                   │                   recv(researcher)──▶ │         │         │
 │                   │                    │                  runner.run()         │
 │                   │                   send(lead,reply) ◀─ │         │         │
 │ recv(lead)        │                    │◀──────────────────│         │         │
 │ update(T1, DONE)  │                    │                    │         │         │
 │─────────────────▶│  [T2 解锁]          │                    │         │         │
 │                   │                    │                    │         │         │
 │ ready=[T2]        │                    │                    │         │         │
 │◀─────────────────│                    │                    │         │         │
 │ delegate(coder, T2)                   │                              │         │
 │──────────────────────────────────────▶ send(coder)                  │         │
 │                   │                   recv(coder)──────────────────▶│         │
 │                   │                   send(lead,reply)◀─────────────│         │
 │ update(T2, DONE)  │                    │                              │         │
 │─────────────────▶│  [T3 解锁]          │                              │         │
 │                   │                    │                              │         │
 │ ready=[T3]        │                    │                              │         │
 │◀─────────────────│                    │                              │         │
 │ delegate(reviewer, T3)                │                                        │
 │──────────────────────────────────────▶ send(reviewer)                         │
 │                   │                   recv(reviewer)──────────────────────────▶│
 │                   │                   send(lead,reply)◀────────────────────────│
 │ update(T3, DONE)  │                    │                                        │
 │─────────────────▶│  [全部 DONE]        │                                        │
 │                   │                    │                                        │
 │ 汇总三份结果，任务完成                   │                                        │
```

---

### 15.8 并行任务扩展

当多个子任务**没有相互依赖**时，`ready_tasks()` 会同时返回多个任务，Lead 可以**并发委托**：

```python
ready = scheduler._graph.ready_tasks()
# ready = [T_a(researcher), T_b(coder)]  ← 两个同时就绪

for task in ready:
    agent_id = ROLE_TO_AGENT[_role_of(task)]
    await coordinator.delegate(agent_id, task.goal, "lead")
    scheduler.update_status(task.id, "IN_PROGRESS")

# 此时 researcher 和 coder 的 Mailbox 各有 1 条消息，并行执行
# T_final(reviewer, deps=[T_a.id, T_b.id]) 等两者都 DONE 后才解锁
```

---

### 15.9 各组件角色对照

| 组件 | 在流程中承担的职责 |
|------|-----------------|
| `TaskGraph` | 存储 DAG，`ready_tasks()` 守门，`topological_order()` 保序 |
| `TaskStore` | 持久化每次状态变更（append-only JSONL），进程崩溃可恢复 |
| `Scheduler` | TaskGraph + TaskStore 的门面，对外提供 `add / next_ready / update_status` |
| `AgentTeam` | 声明角色成员关系（researcher / coder / reviewer 的能力与分工） |
| `TeamCoordinator` | 将就绪任务按角色路由到对应 Agent（delegate / broadcast / vote） |
| `Mailbox` | SQLite 持久化消息队列，解耦 Lead 和 Worker 的时序，支持跨进程 |
| `AgentMessage` | 统一消息格式，`correlation_id` 关联请求与回复，`msg_type` 区分语义 |
| `SubAgentRunner` | Worker 的执行核心，独立 `messages[]` 避免污染 Lead 的对话上下文 |
| `WorkerAgent` | 封装"轮询 Kanban + 调用 Runner"的自组织循环，支持多实例并发 |

---

## 十四、扩展点

| 扩展类型 | 方法 |
|---------|------|
| 新工具 | 实现 `handler.dispatch(tool_call)` + schema，调用 `registry.register_handler()` |
| 新 Agent | `PeerAgent(...)` + `get_registry().register(peer)` |
| 新记忆后端 | 实现 `QdrantStore`/`Neo4jStore` 接口替换 |
| 新 Skill | 放入 `skills/builtin/`，实现 `run()` 方法 |
| MCP 工具服务器 | `mcp/client.py` + `mcp/registry.py` 动态发现 |
| Cron 定时任务 | `tasks/cron.py` + `tools/builtin/cron_tool.py` |
| 权限控制 | `permissions/gate.py` + `permissions/policy.py` + `permissions/deny_list.py` |
