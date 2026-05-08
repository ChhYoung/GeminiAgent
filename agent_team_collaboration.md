# 多角色 Agent 团队协作深度解析

> 本文聚焦于"**平行 Peer Agent 团队**"的协作模式，与父子工具调用式 Agent 的本质区别，以及团队内部如何通过消息、角色、任务图实现真正的自治协作。

---

## 零、先厘清：Peer Team 与工具调用式 Agent 的根本差异

工具调用式（父子）模型通常长这样：

```
用户
 └── 主 Agent（调用工具）
        └── tool_call: run_sub_agent("写代码")
               └── SubAgentRunner.run()   ← 作为一个工具调用阻塞执行
                      └── 返回字符串结果给主 Agent
```

这里子 Agent 只是一个**同步函数**。主 Agent 不继续运行直到子 Agent 返回，子 Agent 没有自己的身份、记忆或主动行为，本质上是一个封装了 LLM 调用的工具。

**Peer Agent 团队模型**根本不同：

```
用户
 └── Lead Agent（协调者）     researcher Agent     coder Agent     reviewer Agent
        │                         │                    │                │
        │    ← 持久化 Mailbox 消息队列 →               │                │
        │                         │                    │                │
        │  各自独立运行自己的 LLM 循环，有独立的系统提示、工具白名单、记忆上下文  │
        │                         │                    │                │
        └─── 通过 AgentMessage 异步通信，互不阻塞，可跨进程重启存活 ──────────┘
```

核心差异对比：

| 维度 | 工具调用式（父子） | Peer Agent 团队 |
|------|-----------------|----------------|
| **执行模型** | 同步阻塞，子 Agent 作为工具调用 | 各自独立异步循环，互不阻塞 |
| **通信方式** | 函数返回值（字符串） | 持久化消息队列（SQLite Mailbox） |
| **Agent 身份** | 无，仅为封装函数 | 有唯一 ID、专长、系统提示、工具白名单 |
| **生命周期** | 随工具调用开始/结束 | 长期运行，可跨进程重启 |
| **主动性** | 被动，等待调用 | 主动轮询 Mailbox 和 Kanban |
| **故障处理** | 父 Agent 直接收到异常 | 消息持久化，崩溃后消息不丢失 |
| **上下文隔离** | 依赖父子调用栈 | 完全独立的 `messages[]` |
| **并行能力** | 需要父 Agent 显式管理线程 | 多 Worker 自然并发认领 |

---

## 一、团队的建模：角色、能力、规则

### 1.1 角色成员：TeamMember

```python
@dataclass
class TeamMember:
    agent_id: str           # 对应 AgentRegistry 中的 PeerAgent
    role: str               # "researcher" / "coder" / "reviewer" / "lead"
    capabilities: list[str] # ["web_search", "data_analysis"] 能力标签
```

角色（role）是粗粒度的职位描述，能力（capabilities）是细粒度的技能清单。路由时优先按 role 匹配，当多个 agent 担任同一 role 时，再按 capabilities 筛选最合适的执行者。

### 1.2 团队：AgentTeam

```python
@dataclass
class AgentTeam:
    team_id: str
    name: str
    members: list[TeamMember]
    shared_rules: list[str]       # ["所有结果必须附来源", "代码必须通过 lint"]
    shared_memory_ns: str         # "team:<team_id>" — 共享记忆命名空间
```

`shared_rules` 是自然语言写的协作约定，会注入每个成员的 system prompt 前缀，约束整个团队的行为标准，无需在每条消息里重复。

`shared_memory_ns` 使得团队成员可以写入同一命名空间的 SemanticMemory，后来加入的成员能读取团队积累的知识图谱。

### 1.3 个体 Agent：PeerAgent

```python
@dataclass
class PeerAgent:
    agent_id: str
    name: str
    speciality: str        # "Python 后端专家，擅长性能优化"
    system_prompt: str     # 完整的角色指令，定义人格、行为、输出格式
    tool_names: list[str]  # 工具白名单，["run_command", "search_knowledge"]
```

每个 PeerAgent 都有独立的 `system_prompt`，决定了它的"人格"。researcher 和 coder 看到的是完全不同的系统提示。这不是靠 role 字符串实现的，而是通过 `LLM(system=peer.system_prompt, ...)` 在每次调用时注入。

---

## 二、通信基础设施：消息如何在 Agent 之间流动

### 2.1 AgentMessage：统一消息协议

所有跨 Agent 通信强制使用 `AgentMessage` 格式：

```python
@dataclass
class AgentMessage:
    msg_id: str           # UUID[:8]，消息唯一标识
    msg_type: Literal[
        "request",        # 请求对方做某事
        "response",       # 对 request 的回复
        "event",          # 通知型，不需要回复
        "broadcast",      # 广播给所有成员
        "vote",           # 发起投票
        "vote_reply",     # 投票回复
        "delegate",       # 委托执行任务
    ]
    from_agent: str
    to_agent: str
    correlation_id: str | None  # response/vote_reply 指向原始消息的 msg_id
    payload: dict[str, Any]     # 业务数据
    created_at: datetime
```

`msg_type` 区分了**语义**，`correlation_id` 实现了**请求-响应追踪**，`payload` 承载**业务数据**。三者分工明确，接收方不需要额外上下文就能理解消息含义。

`make_response()` 方法自动填充 `correlation_id`：

```python
def make_response(self, from_agent: str, payload: dict) -> "AgentMessage":
    return AgentMessage(
        from_agent=from_agent,
        to_agent=self.from_agent,      # 自动回给发送方
        msg_type="response",
        correlation_id=self.msg_id,    # ← 关联到原始 request
        payload=payload,
    )
```

这确保了 Lead 同时向多个 Worker 发出委托时，乱序回复也能精确匹配。

### 2.2 Mailbox：SQLite 持久化队列

```
Schema: messages(id INTEGER, to_agent TEXT, msg_json TEXT, consumed INTEGER, created_at TEXT)
Index:  (to_agent, consumed)   ← 高效查询特定 agent 的未读消息
```

```python
class Mailbox:
    # 同步接口（在 tool dispatch 内使用）
    send_sync(to_agent: str, msg: AgentMessage)
    recv_sync(agent_id: str) -> AgentMessage | None   # FIFO，consumed=1

    # 异步接口（在协程内使用，带 asyncio.Lock 防并发）
    async send(to_agent: str, msg: AgentMessage)
    async recv(agent_id: str, timeout: float) -> AgentMessage | None

    # 批量查询
    read_all(agent_id: str) -> list[AgentMessage]
    pending_count(agent_id: str) -> int
```

**为什么用 SQLite 而不是内存队列？**

- **跨进程**：researcher 跑在进程 A，Lead 跑在进程 B，两者共享同一个 SQLite 文件
- **持久化**：进程崩溃后，已投递但未消费的消息不丢失
- **FIFO 保序**：`ORDER BY id` 确保消息按投递顺序被消费
- **可观测**：直接用 sqlite3 命令行就能查看所有历史消息，调试友好

### 2.3 消息的生命周期

```
发送方                    SQLite                    接收方
   │                        │                          │
   │ send_sync(to, msg)      │                          │
   │──────────────────────▶ │ INSERT (consumed=0)      │
   │                        │                          │
   │                        │         recv_sync(id)    │
   │                        │ ◀────────────────────────│
   │                        │ SELECT WHERE consumed=0  │
   │                        │ UPDATE SET consumed=1    │
   │                        │──────────────────────────▶│
   │                        │         返回 AgentMessage │
   │                        │                          │
   │                (消息永久保留在 DB，仅 consumed 标记变化)
```

消息不会被物理删除，`consumed=1` 只是标记已读。这使得整个通信历史可以被审计和回放。

---

## 三、三种协调模式的内部机制

`TeamCoordinator` 是团队的"对话层"，它把高层协调意图转化为底层 Mailbox 消息。

### 3.1 Broadcast（广播）：通知所有成员

**使用场景**：Lead 发现需求变更，需要通知所有正在工作的 Agent 更新方向；系统故障广播；里程碑完成通知。

```python
async def broadcast(self, team: AgentTeam, content: str, from_agent: str):
    msg = AgentMessage(
        msg_type="broadcast",
        from_agent=from_agent,
        to_agent="*",           # 逻辑广播标识
        payload={"content": content},
    )
    for member in team.members:
        if member.agent_id != from_agent:    # 不发给自己
            self.mailbox.send_sync(member.agent_id, msg)
```

广播没有 `correlation_id`，接收方不需要回复。这是"fire and forget"语义。

**接收方如何处理广播？**

```python
msg = mailbox.recv_sync("researcher")
if msg.msg_type == "broadcast":
    # 注入到自己的 LLM 上下文作为 system 级别的上下文更新
    messages.insert(0, {"role": "system", "content": f"[团队通知] {msg.payload['content']}"})
    # 继续执行当前任务，但带着更新后的上下文
```

### 3.2 Vote（投票）：集体决策

**使用场景**：架构选型、技术方案争议、优先级决定。让每个专业 Agent 从自己的视角投票，比单一 Lead 决策更全面。

```python
async def vote(
    self,
    team: AgentTeam,
    question: str,
    options: list[str],
    from_agent: str,
    timeout: float = 30.0,
) -> dict[str, str]:   # {agent_id: chosen_option}

    vote_msg = AgentMessage(
        msg_type="vote",
        from_agent=from_agent,
        payload={"question": question, "options": options},
    )

    # 同时向所有成员发送投票请求
    for member in team.members:
        vote_msg_copy = replace(vote_msg, to_agent=member.agent_id)
        self.mailbox.send_sync(member.agent_id, vote_msg_copy)

    # 等待收集所有回复（带超时）
    results = {}
    deadline = time.time() + timeout
    while len(results) < len(team.members) and time.time() < deadline:
        for member in team.members:
            if member.agent_id in results:
                continue
            reply = await self.mailbox.recv(member.agent_id, timeout=1.0)
            if reply and reply.msg_type == "vote_reply":
                results[member.agent_id] = reply.payload["choice"]

    return results
```

**成员如何投票？**

每个 Agent 的 Mailbox 轮询循环收到 `msg_type="vote"` 时：

```python
if msg.msg_type == "vote":
    # 让自己的 LLM 根据专长做出判断
    choice = await self._llm_decide(
        f"请从以下选项中选择最合适的方案：{msg.payload['options']}\n"
        f"问题：{msg.payload['question']}\n"
        f"请从你的专业视角（{self.speciality}）给出判断"
    )
    reply = msg.make_response(
        from_agent=self.agent_id,
        payload={"choice": choice}
    )
    self.mailbox.send_sync(msg.from_agent, reply)
```

**结果汇总**：Lead 统计各选项票数，或直接用大模型分析投票理由做出最终决策。超时未回复的成员视为弃权，不影响结果。

### 3.3 Delegate（委托）：任务下发

**使用场景**：这是最核心的协调原语。Lead 将具体可执行任务分配给最合适的角色。

```python
async def delegate(
    self,
    to_agent: str,
    task_desc: str,
    from_agent: str,
) -> str:   # 返回 msg_id，供后续 correlation 追踪

    msg = AgentMessage(
        msg_type="delegate",
        from_agent=from_agent,
        to_agent=to_agent,
        payload={
            "task_desc": task_desc,
            "priority": "normal",
            "deadline": None,
        },
    )
    self.mailbox.send_sync(to_agent, msg)
    return msg.msg_id
```

接收方收到 `delegate` 消息后，调用 `SubAgentRunner.run()` 在独立上下文中执行，完成后发回 `response`。

**关键**：`delegate` 的返回值是 `msg_id`，Lead 保存这个 ID 用来关联后续的 `response.correlation_id`，实现"哪个回复对应哪个委托"的精确匹配。

---

## 四、任务编排：DAG 如何驱动角色间的串行与并行

### 4.1 为什么需要 DAG

角色协作中最难解决的问题是**依赖顺序**：coder 必须等 researcher 的需求分析完成才能开始；reviewer 必须等 coder 的代码完成才能开始。

直接用"消息轮询等待"实现这种顺序会导致：
- 忙等待（busy wait）浪费资源
- 依赖关系隐式化（埋在消息处理逻辑里）
- 无法表达并行（两个独立子任务必须串行执行）

DAG（有向无环图）把依赖关系**显式化、结构化**：

```
T1(researcher) ──deps──▶ T2(coder) ──deps──▶ T3(reviewer)

T_a(researcher) ──deps──▶ T_final(reviewer)
T_b(coder)      ──deps──▶ T_final(reviewer)
# T_a 和 T_b 无依赖，可以并行；T_final 等两者都完成
```

### 4.2 TaskGraph 的守门机制

```python
def ready_tasks(self) -> Iterator[Task]:
    """只返回依赖全部完成且自身待执行的任务"""
    for task in self._tasks.values():
        if task.status != "PENDING":
            continue
        deps_all_done = all(
            self._tasks[dep_id].status == "DONE"
            for dep_id in task.deps
        )
        if deps_all_done:
            yield task
```

这个函数是 Lead 每轮推进的入口。它保证了：
- **不会提前下发**：dep 没完成的任务永远不出现在结果里
- **自然并行**：无依赖的任务同时出现，Lead 可以同时委托
- **无需 Lead 跟踪顺序**：顺序逻辑完全在 TaskGraph 里，Lead 只管"拿就绪任务 → 委托 → 等回复 → 更新状态"

### 4.3 Scheduler：状态变更的持久化门面

```
Scheduler = TaskGraph (内存) + TaskStore (磁盘 JSONL)
```

每次 `update_status(task_id, "DONE", result)` 都会：
1. 更新 `TaskGraph` 中该节点的 `status`
2. 将完整的 Task 快照 append 到 `tasks.jsonl`

磁盘文件是 append-only 的，进程重启后可以重放日志恢复 TaskGraph 状态。这使得整个团队协作过程**可中断、可恢复**。

---

## 五、自治执行：Worker 如何独立运转

### 5.1 WorkerAgent：自组织认领

```python
class WorkerAgent:
    async def run_forever(self):
        while self._running:
            task = self.kanban.claim(self.agent_id)   # 原子认领
            if task:
                try:
                    result = await self.runner.run(task.goal)
                    self.kanban.complete(task.id, result)
                except Exception as e:
                    self.kanban.fail(task.id, str(e))
            else:
                await asyncio.sleep(self.poll_interval)
```

`claim()` 在 `threading.Lock` 内原子地查找第一个 PENDING 任务并立即改为 IN_PROGRESS。多个 WorkerAgent 同时调用 `claim()` 时，只有一个会成功拿到任务，不会重复执行。

### 5.2 AutonomousAgent：心跳 + 断点续跑

`AutonomousAgent` 是更完整的自治版本，在 WorkerAgent 基础上增加了：

```python
async def run(self):
    await asyncio.gather(
        self._claim_loop(),      # 轮询认领 + 执行
        self._heartbeat_loop(),  # 每 30s 更新 last_seen
    )
```

**心跳的作用**：每次 `kanban.touch(task_id, agent_id)` 更新 `last_seen` 时间戳。`Kanban.release_stale(timeout_s=600)` 定期扫描，将超过 10 分钟没有心跳的 IN_PROGRESS 任务重置为 PENDING，供其他 Worker 重新认领。

**断点续跑**：任务开始前保存 checkpoint：

```python
async def _execute_with_checkpoint(self, task):
    self.checkpoint.save(task.id, context=[], step_idx=0)
    
    try:
        result = await asyncio.wait_for(
            self.runner.run(task.goal),
            timeout=self.task_timeout,    # 默认 600s
        )
        self.kanban.complete(task.id, result)
    except asyncio.TimeoutError:
        self.kanban.fail(task.id, "timeout")
```

进程崩溃重启后，`resume(task_id)` 从 `CheckpointStore` 读取上次保存的 `step_idx`，跳过已完成的步骤继续执行。

---

## 六、端到端完整协作流程

### 场景：Lead 带领三角色团队完成"开发用户登录功能"

#### 6.1 初始化：注册团队成员

```python
# 注册 PeerAgent（定义身份）
researcher = PeerAgent(
    agent_id="researcher",
    name="需求分析师",
    speciality="需求挖掘、技术方案调研",
    system_prompt="你是一位资深需求分析师。分析用户需求时，必须考虑安全性、可扩展性和用户体验...",
    tool_names=["web_search", "search_knowledge", "store_memory"],
)
coder = PeerAgent(
    agent_id="coder",
    name="后端开发",
    speciality="Python 后端，FastAPI，JWT 认证",
    system_prompt="你是一位 Python 后端工程师。写代码时必须遵循 PEP8，添加类型注解，代码必须可测试...",
    tool_names=["run_command", "search_knowledge", "create_note"],
)
reviewer = PeerAgent(
    agent_id="reviewer",
    name="代码审查",
    speciality="安全审查、代码质量、性能分析",
    system_prompt="你是一位安全专家兼代码审查员。审查代码时必须检查 OWASP Top 10 漏洞...",
    tool_names=["run_command", "search_knowledge"],
)

for agent in [researcher, coder, reviewer]:
    get_registry().register(agent)

# 组建团队（声明角色关系）
team = AgentTeam(
    team_id="login-team",
    name="登录功能开发团队",
    members=[
        TeamMember("researcher", role="researcher", capabilities=["requirements", "research"]),
        TeamMember("coder",      role="coder",      capabilities=["python", "api", "auth"]),
        TeamMember("reviewer",   role="reviewer",   capabilities=["security", "review"]),
    ],
    shared_rules=[
        "所有 API 接口必须添加速率限制",
        "密码相关代码必须使用 bcrypt，禁止 MD5/SHA1",
        "代码合并前必须通过 reviewer 审查",
    ],
    shared_memory_ns="team:login-team",
)
```

#### 6.2 Lead 拆分任务，建立 DAG

```python
# Lead 接到顶层任务，拆解为有依赖关系的子任务
t1 = Task(
    goal="researcher: 分析用户登录功能需求，输出技术方案文档",
    deps=[],                 # 无依赖，立即可执行
)
t2 = Task(
    goal="coder: 根据需求文档实现登录 API（JWT + bcrypt）",
    deps=[t1.id],            # 必须等 t1 完成
)
t3 = Task(
    goal="reviewer: 对登录代码进行安全审查，输出审查报告",
    deps=[t2.id],            # 必须等 t2 完成
)

for task in [t1, t2, t3]:
    scheduler.add(task)   # 写入 TaskGraph + TaskStore（磁盘持久化）
```

此时 TaskGraph 状态：

```
T1(PENDING, no deps)
    └──deps──▶ T2(PENDING, blocked)
                    └──deps──▶ T3(PENDING, blocked)
```

#### 6.3 推进循环：Lead 驱动 DAG

```python
async def lead_drive_loop(scheduler, coordinator, team, mailbox):
    pending_delegations = {}   # {msg_id: task_id} 追踪委托

    while True:
        # 取所有当前就绪任务（deps 全完成的 PENDING 任务）
        ready = list(scheduler._graph.ready_tasks())

        for task in ready:
            # 根据任务 goal 前缀路由到对应角色
            role = task.goal.split(":")[0].strip()
            agent_id = ROLE_TO_AGENT[role]

            # 委托给对应 Agent（写入 Mailbox）
            msg_id = await coordinator.delegate(
                to_agent=agent_id,
                task_desc=task.goal,
                from_agent="lead",
            )
            scheduler.update_status(task.id, "IN_PROGRESS")
            pending_delegations[msg_id] = task.id   # 记录追踪关系

        # 等待任意一个回复
        reply = await mailbox.recv("lead", timeout=5.0)
        if reply and reply.msg_type == "response":
            task_id = pending_delegations.pop(reply.correlation_id, None)
            if task_id:
                result = reply.payload["result"]
                scheduler.update_status(task_id, "DONE", result)
                # TaskGraph 自动解锁依赖此任务的下游任务

        # 检查是否全部完成
        all_tasks = list(scheduler._graph._tasks.values())
        if all(t.status == "DONE" for t in all_tasks):
            break

    return {t.id: t.result for t in all_tasks}
```

#### 6.4 各角色 Worker 的执行

每个 Worker 都运行独立的异步循环：

```python
# researcher Worker 的处理逻辑（简化）
async def researcher_loop(mailbox, runner, agent_id="researcher"):
    while True:
        msg = await mailbox.recv(agent_id, timeout=2.0)
        if not msg:
            continue

        if msg.msg_type == "delegate":
            # SubAgentRunner 用 researcher 的 system_prompt 执行
            # messages[] 完全隔离，不含 Lead 的对话历史
            result = await runner.run(
                task=msg.payload["task_desc"],
                system_prompt=researcher.system_prompt,
                tools=researcher.tool_names,
            )
            reply = msg.make_response(
                from_agent=agent_id,
                payload={"result": result},
            )
            mailbox.send_sync("lead", reply)

        elif msg.msg_type == "broadcast":
            # 将广播内容注入下次执行的上下文
            self.context_updates.append(msg.payload["content"])
```

#### 6.5 完整时序图

```
Lead              TaskGraph            Mailbox(SQLite)        researcher    coder    reviewer
 │                    │                     │                      │           │          │
 │─ add(T1,T2,T3) ──▶│                     │                      │           │          │
 │                    │                     │                      │           │          │
 │◀─ ready=[T1] ─────│                     │                      │           │          │
 │─ delegate ─────────────────────────────▶│─ send(researcher) ──▶│           │          │
 │─ update(T1, IN_PROGRESS) ─────────────▶│                      │           │          │
 │                    │                    │                      │           │          │
 │                    │                   recv(researcher) ──────▶│           │          │
 │                    │                    │                   runner.run()   │          │
 │                    │                   send(lead, reply) ◀──── │           │          │
 │◀─ recv(lead) ──────────────────────────│                      │           │          │
 │─ update(T1, DONE) ─────────────────────▶│ [T2 自动解锁]        │           │          │
 │                    │                    │                      │           │          │
 │◀─ ready=[T2] ─────│                     │                      │           │          │
 │─ delegate ─────────────────────────────▶│─ send(coder) ────────────────────▶│         │
 │─ update(T2, IN_PROGRESS) ─────────────▶│                                   │          │
 │                    │                    │                      recv(coder) ─▶│         │
 │                    │                    │                               runner.run()   │
 │                    │                   send(lead, reply) ◀──────────────────│          │
 │◀─ recv(lead) ──────────────────────────│                                              │
 │─ update(T2, DONE) ─────────────────────▶│ [T3 自动解锁]                               │
 │                    │                    │                                              │
 │◀─ ready=[T3] ─────│                     │                                              │
 │─ delegate ─────────────────────────────▶│─ send(reviewer) ───────────────────────────▶│
 │                    │                   recv(reviewer) ─────────────────────────────────▶│
 │                    │                    │                                          runner.run()
 │                    │                   send(lead, reply) ◀──────────────────────────────│
 │─ update(T3, DONE) ─────────────────────▶│ [全部 DONE]                                  │
 │                    │                    │                                              │
 │ 汇总三份结果，任务完成
```

---

## 七、并行协作：无依赖任务的同时执行

当多个子任务没有相互依赖时，`ready_tasks()` 同时返回它们，Lead 可以并发委托：

```
需求分析（researcher）─────────────────▶ 最终集成（reviewer）
                                         ↑
安全方案设计（researcher-2）────────────┘
```

```python
# T_a 和 T_b 同时就绪
ready = list(scheduler._graph.ready_tasks())
# ready = [T_a(researcher), T_b(security_researcher)]

# 同时委托两个任务（非阻塞）
for task in ready:
    agent_id = ROLE_TO_AGENT[_role_of(task)]
    msg_id = await coordinator.delegate(agent_id, task.goal, "lead")
    scheduler.update_status(task.id, "IN_PROGRESS")
    pending[msg_id] = task.id

# researcher 和 security_researcher 的 Mailbox 各有 1 条消息
# 它们在各自的 Worker 循环里并发执行，互不阻塞
# Lead 等待两者的回复（乱序到达也能通过 correlation_id 匹配）
```

并行执行的关键保证：
- **消息独立**：两条 delegate 消息写入不同 Agent 的 Mailbox，互不干扰
- **执行隔离**：每个 SubAgentRunner 有独立的 `messages[]`，不共享状态
- **结果匹配**：`correlation_id` 确保乱序到达的 response 能被正确关联
- **下游守门**：T_final 的 `deps=[T_a.id, T_b.id]`，两者都 DONE 后才解锁

---

## 八、投票决策：团队集体智慧

### 场景：架构方案选型

```python
# Lead 不确定使用 JWT 还是 Session，发起团队投票
results = await coordinator.vote(
    team=team,
    question="用户登录方案选型：哪种更适合我们的场景？",
    options=["JWT（无状态，适合微服务）", "Session（有状态，适合单体应用）", "OAuth2（第三方集成）"],
    from_agent="lead",
    timeout=30.0,
)
# results = {
#     "researcher": "JWT（无状态，适合微服务）",
#     "coder":      "JWT（无状态，适合微服务）",
#     "reviewer":   "OAuth2（第三方集成）",
# }

# Lead 汇总：JWT 2票，OAuth2 1票
# 可以进一步让 LLM 分析各方理由，做出最终决策
winning_option = max(set(results.values()), key=list(results.values()).count)
```

投票的价值不只是票数，而是每个专业角色**从自己视角**给出的判断。Lead 可以把投票结果（含每个 Agent 的理由）喂给 LLM 做二次分析，获得比多数票更细腻的决策建议。

---

## 九、故障恢复：Agent 崩溃后如何继续

### 场景：coder Worker 在执行过程中崩溃

```
T2(coder, IN_PROGRESS, last_seen=10:00:00)
        ↓ coder 进程在 10:05 崩溃
        ↓ 没有新的 heartbeat
        ↓ 10:10:00 — Kanban.release_stale(timeout_s=600) 扫描
T2(PENDING, assignee=None)   ← 重置回 PENDING
        ↓
        ↓ 另一个 coder Worker 实例启动（或原进程重启）
T2(IN_PROGRESS, assignee="coder-2")
        ↓
        ↓ 如有 Checkpoint：从上次 step_idx 继续
        ↓ 否则：重新执行完整任务
T2(DONE)
```

关键机制：
1. **心跳**：每 30s 调用 `kanban.touch(task_id, agent_id)` 更新 `last_seen`
2. **超时检测**：`release_stale()` 对比 `last_seen` 和当前时间，超时则重置
3. **消息不丢失**：Lead 发出的 delegate 消息仍在 Mailbox，只是新 Worker 会重新认领 Kanban 任务，而非通过 Mailbox 再次接收（两种机制可配合使用）
4. **断点续跑**：`CheckpointStore` 保存执行进度，避免从头重做

---

## 十、与父子工具调用的对比总结

```
父子工具调用式（浅层并行）：
┌─────────────────────────────────────────┐
│ 主 Agent                                │
│   tool_call: run_sub_agent("写代码")    │
│   [阻塞等待]                             │
│   tool_call: run_sub_agent("做审查")    │
│   [阻塞等待]                             │
│   返回最终结果                           │
└─────────────────────────────────────────┘
缺点：主 Agent 串行阻塞；子 Agent 无身份；上下文污染；进程崩溃全丢

Peer Agent 团队式（真正分布式协作）：
┌──────────┐    Mailbox     ┌────────────┐
│   Lead   │ ─────────────▶ │ researcher │ 独立 LLM 循环
│          │ ◀───────────── │            │ 独立记忆上下文
└──────────┘                └────────────┘
      │         Mailbox     ┌────────────┐
      │─────────────────────▶│   coder   │ 独立工具白名单
      │◀────────────────────│            │ 独立系统提示
      │                      └────────────┘
      │         Mailbox     ┌────────────┐
      │─────────────────────▶│ reviewer  │ 独立能力边界
      │◀────────────────────│            │ 心跳 + 断点续跑
                             └────────────┘

优点：
✓ 各 Agent 独立运行，互不阻塞
✓ 消息持久化，进程崩溃后继续
✓ 角色专业化，system_prompt 完全不同
✓ DAG 自动管理依赖，无需 Lead 手动排序
✓ 并行任务自然并发，不需要显式线程管理
✓ 可观测：所有消息存 SQLite，任务状态存 JSONL
✓ 可扩展：新增 Worker 实例，Kanban 自动分摊
```

---

## 附：核心组件速查表

| 组件 | 文件 | 职责 |
|------|------|------|
| `PeerAgent` | `multi_agent/peer.py` | 定义 Agent 身份（ID、专长、system_prompt、工具白名单） |
| `AgentTeam` | `teams/team.py` | 声明团队成员、角色、共享规则、共享记忆命名空间 |
| `TeamCoordinator` | `teams/coordinator.py` | 广播 / 投票 / 委托三种协调原语 |
| `AgentMessage` | `multi_agent/protocol.py` | 统一消息格式，`correlation_id` 追踪请求-响应 |
| `Mailbox` | `multi_agent/mailbox.py` | SQLite 持久化消息队列，解耦时序，跨进程存活 |
| `AgentRegistry` | `multi_agent/registry.py` | 进程级 Agent 注册表，支持按 ID 查询 |
| `TaskGraph` | `tasks/graph.py` | DAG 建模依赖，`ready_tasks()` 守门，循环检测 |
| `Scheduler` | `tasks/scheduler.py` | TaskGraph + TaskStore 门面，状态变更自动持久化 |
| `Kanban` | `tasks/kanban.py` | 三列看板，`claim()` 原子认领，防重复执行 |
| `WorkerAgent` | `multi_agent/worker.py` | 自组织轮询认领，`run_forever()` 主循环 |
| `AutonomousAgent` | `teams/autonomous.py` | Worker + 心跳 + 断点续跑 |
| `SubAgentRunner` | `subagent/runner.py` | 隔离 `messages[]` 执行，父 Agent 只收文本结论 |
