# arch v4 — commit 4
> s01–s12 原则落地：Planner + SubAgent + 任务图 + 后台执行 + 多 Agent 协作

> commit 3 = a4636f5（add docker-compose），不涉及代码架构，故本文件为 v4。

# arch3: 从单 Agent 到多 Agent 协作系统

> 在 arch2（单 Agent + 记忆 + RAG + 工具）的基础上，按 s01–s12 十二条原则逐层扩展。

**版本标注说明**
- `[v1]`     首次引入于 v1（Initial commit）
- `[v2]`     首次引入于 v2（OpenAI-compatible 重构）
- `[v2 ✏️]`  v2 修改，v4 继续沿用
- `[v4 ✨]`  v4 全新引入
- `[v4 ✏️]`  v4 修改已有文件

---

## 一、目录全貌

```
hello-agents/
├── hello_agents/
│   │
│   ├── config.py                      [v2]    pydantic-settings 全局配置
│   │
│   ├── agent.py                       [v4 ✏️] 主 Agent — 提取 _call_llm/_run_one_tool，
│   │                                           注册 task/background/agent 三组新工具
│   │
│   ├── planner/                       [v4 ✨] s03 — 计划引擎（先列步骤再动手）
│   │   ├── __init__.py
│   │   └── planner.py                          将用户请求转成有序 Step 列表
│   │
│   ├── subagent/                      [v4 ✨] s04 — 子 Agent（独立 messages[]，不污染主对话）
│   │   ├── __init__.py
│   │   └── runner.py                           SubAgentRunner：隔离上下文跑一个子任务
│   │
│   ├── context/                       [v2]    GSSC 流水线（整体引入于 v2）
│   │   ├── builder.py                 [v2]    ContextBuilder（GSSC 入口）
│   │   ├── gather.py                  [v2]    Gather
│   │   ├── select.py                  [v2]    Select
│   │   ├── structure.py               [v2]    Structure
│   │   └── compress.py                [v4 ✏️] s06 扩展为三层压缩：滑窗 → LLM摘要 → 卸载记忆
│   │
│   ├── memory/                        [v1]    记忆系统（v2 部分改动，v4 不变）
│   │   ├── base.py                    [v1]
│   │   ├── manager.py                 [v1]
│   │   ├── router.py                  [v1]
│   │   ├── reflection.py              [v2 ✏️]
│   │   ├── events.py                  [v1]
│   │   ├── embedding.py               [v2 ✏️]
│   │   ├── types/
│   │   │   ├── working.py             [v1]
│   │   │   ├── episodic.py            [v1]
│   │   │   ├── semantic.py            [v1]
│   │   │   └── perceptual.py          [v2 ✏️]
│   │   └── storage/
│   │       ├── qdrant_store.py        [v1]
│   │       ├── neo4j_store.py         [v1]
│   │       └── document_store.py      [v1]
│   │
│   ├── rag/                           [v1]    RAG 系统（v4 不变）
│   │   ├── pipeline.py                [v1]
│   │   ├── document.py                [v1]
│   │   └── knowledge_base.py          [v1]
│   │
│   ├── tasks/                         [v4 ✨] s07/s08/s11/s12 — 任务图 + 后台执行 + 看板
│   │   ├── __init__.py
│   │   ├── models.py                  [v4 ✨] Task / Step 数据模型（status/deps/assignee）
│   │   ├── graph.py                   [v4 ✨] s07 DAG 任务图，拓扑排序，依赖检查
│   │   ├── store.py                   [v4 ✨] s07 JSON Lines 磁盘持久化
│   │   ├── scheduler.py               [v4 ✨] s07 调度器：按拓扑顺序推送 ready 任务
│   │   ├── background.py              [v4 ✨] s08 后台线程池 + poll 查询
│   │   ├── kanban.py                  [v4 ✨] s11 看板：PENDING / IN_PROGRESS / DONE 三列
│   │   └── worktree.py                [v4 ✨] s12 task_id ↔ git worktree 目录绑定
│   │
│   ├── multi_agent/                   [v4 ✨] s09/s10/s11 — 多 Agent 协作基础设施
│   │   ├── __init__.py
│   │   ├── peer.py                    [v4 ✨] s09 PeerAgent：持久化配置 + 独立工具集
│   │   ├── mailbox.py                 [v4 ✨] s09 SQLite 异步邮箱（sync+async 双 API）
│   │   ├── protocol.py                [v4 ✨] s10 统一消息格式 AgentMessage（request/response/event）
│   │   ├── registry.py                [v4 ✨] 已启动 PeerAgent 的进程级注册表
│   │   └── worker.py                  [v4 ✨] s11 WorkerAgent：轮询看板 → 认领 → 执行
│   │
│   └── tools/                         [v2]    Agent 工具箱
│       ├── registry.py                [v2]    ToolRegistry（dispatch map，v4 不变）
│       └── builtin/
│           ├── memory_tool.py         [v2 ✏️] （v4 不变）
│           ├── rag_tool.py            [v2 ✏️] （v4 不变）
│           ├── note_tool.py           [v2 ✨] （v4 不变）
│           ├── terminal_tool.py       [v2 ✨] （v4 不变）
│           ├── web_search_tool.py     [v2 ✨] （v4 不变）
│           ├── task_tool.py           [v4 ✨] s07 任务读写工具（create_task / list_tasks / update_status）
│           ├── background_tool.py     [v4 ✨] s08 后台执行工具（run_background / poll_background）
│           └── agent_tool.py          [v4 ✨] s09/s10 发消息给队友（send_to_agent / read_mailbox）
│
└── tests/
    ├── conftest.py                    [v2]
    ├── run_tests.sh                   [v2]
    ├── unit/
    │   ├── test_memory_base.py        [v2]   （v4 不变）
    │   ├── test_working_memory.py     [v2]   （v4 不变）
    │   ├── test_tool_registry.py      [v2]   （v4 不变）
    │   ├── test_note_tool.py          [v2]   （v4 不变）
    │   ├── test_terminal_tool.py      [v2]   （v4 不变）
    │   ├── test_context_select.py     [v2]   （v4 不变）
    │   ├── test_context_structure.py  [v2]   （v4 不变）
    │   ├── test_planner.py            [v4 ✨] 计划引擎单元测试（12 个）
    │   ├── test_task_models.py        [v4 ✨] Task / Step 模型 + DAG 拓扑（15 个）
    │   ├── test_kanban.py             [v4 ✨] 看板三列状态机 + 并发认领（11 个）
    │   ├── test_protocol.py           [v4 ✨] AgentMessage 序列化 / 验证（7 个）
    │   └── test_compress_layers.py    [v4 ✨] 三层压缩各层独立测试（15 个）
    └── integration/
        ├── test_context_builder.py    [v2]   （v4 不变）
        ├── test_web_search_tool.py    [v2]   （v4 不变）
        ├── test_agent.py              [v2]   （v4 不变）
        ├── test_env_connectivity.py   [v2]   （v4 不变）⚠️ 需外部服务
        ├── test_subagent.py           [v4 ✨] SubAgentRunner 上下文隔离验证（6 个）
        ├── test_background.py         [v4 ✨] 后台执行 + poll 时序（11 个）
        ├── test_multi_agent.py        [v4 ✨] PeerAgent / Mailbox / AgentTool 协作（18 个）
        └── test_worktree.py           [v4 ✨] task_id → worktree 绑定 + 清理（8 个）
```

---

## 二、各原则的落地位置

### s01 — One loop & Bash is all you need [v4 ✏️ agent.py]
> 一个工具 + 一个循环 = 一个 Agent

`agent.py` 中循环体拆出 `_call_llm()` 和 `_run_one_tool()` 两个私有方法，
**for 循环本身保持 ≤15 行**，是系统中唯一的 tool-calling loop。

```
agent.py
└── _generate_with_tools()
    ├── for _ in range(max_tool_rounds):   ← 唯一循环，永不拆分
    │   ├── await _call_llm()
    │   ├── if tool_calls → _run_one_tool() → append tool_result
    │   └── else → return text
    └── 所有能力通过往 dispatch map 加 handler 扩展，循环本身不变
```

---

### s02 — 加一个工具, 只加一个 handler [v4 ✨ task/background/agent_tool.py]
> 循环不用动，新工具注册进 dispatch map 就行

| 文件 | 版本 | 工具名 | 触发场景 |
|------|------|--------|----------|
| `task_tool.py` | [v4 ✨] | `create_task` / `list_tasks` / `update_task_status` | agent 自主管理任务图 |
| `background_tool.py` | [v4 ✨] | `run_background` / `poll_background` | 启动慢操作、查询进度 |
| `agent_tool.py` | [v4 ✨] | `send_to_agent` / `read_mailbox` / `list_agents` | 跨 agent 发消息 |

---

### s03 — 没有计划的 agent 走哪算哪 [v4 ✨ planner/]
> 先列步骤再动手，完成率翻倍

```python
# planner/planner.py  [v4 ✨]
class Planner:
    async def make_plan(self, goal: str) -> list[Step]:
        # 调用 LLM，输出 JSON Steps：
        # [{"id": "1", "desc": "...", "tool_hint": "...", "deps": []}]
```

---

### s04 — 大任务拆小, 每个小任务干净的上下文 [v4 ✨ subagent/]
> Subagent 用独立 messages[]，不污染主对话

```python
# subagent/runner.py  [v4 ✨]
class SubAgentRunner:
    async def run(self, task_desc: str, context_hint: str = "") -> str:
        messages = [system, user]   # 全新 messages[]，不含主对话历史
        # 独立跑 tool-calling loop，返回最终文本
```

---

### s05 — 用到什么知识, 临时加载什么知识 [v4 ✏️ agent.py]
> 通过 tool_result 注入，不塞 system prompt

`agent.py` 调整：system prompt 只保留固定部分（≤500 token），
记忆/RAG 通过 `search_memory` / `search_knowledge` 工具按需拉取注入 tool_result。

---

### s06 — 上下文总会满, 要有办法腾地方 [v4 ✏️ context/compress.py]
> 三层压缩策略，换来无限会话

```
Layer 1 — sliding_window()  [v4 ✨]  毫秒，丢最早条目，不调 LLM
Layer 2 — llm_summarize()   [v4 ✏️]  秒级，调轻量模型生成摘要（原 compress() 重命名）
Layer 3 — needs_offload()   [v4 ✨]  分钟级，判断是否超阈值建议卸载到 EpisodicMemory
compress()                  [v2]    向后兼容入口，内部委托 llm_summarize()
```

---

### s07 — 大目标要拆成小任务, 排好序, 记在磁盘上 [v4 ✨ tasks/]
> 文件持久化的任务图，为多 agent 协作打基础

```
tasks/models.py    [v4 ✨]  Task + Step 数据模型
tasks/graph.py     [v4 ✨]  DAG + Kahn 拓扑排序
tasks/store.py     [v4 ✨]  JSON Lines append-only 持久化
tasks/scheduler.py [v4 ✨]  graph + store 门面：add / next_ready / update_status
```

---

### s08 — 慢操作丢后台, agent 继续想下一步 [v4 ✨ tasks/background.py]
> 后台线程跑命令，完成后注入通知

```
tasks/background.py  [v4 ✨]  ThreadPoolExecutor + submit/poll API
background_tool.py   [v4 ✨]  run_background → job_id；poll_background → 状态
```

---

### s09 — 任务太大一个人干不完, 要能分给队友 [v4 ✨ multi_agent/]
> 持久化队友 + 异步邮箱

```
multi_agent/peer.py    [v4 ✨]  PeerAgent 配置描述
multi_agent/mailbox.py [v4 ✨]  SQLite 邮箱（sync + async 双 API）
multi_agent/registry.py [v4 ✨] 进程级 PeerAgent 注册表
```

---

### s10 — 队友之间要有统一的沟通规矩 [v4 ✨ multi_agent/protocol.py]
> 一个 request-response 模式驱动所有协商

```python
# multi_agent/protocol.py  [v4 ✨]
@dataclass
class AgentMessage:
    msg_id: str;  msg_type: "request"|"response"|"event"
    from_agent: str;  to_agent: str
    correlation_id: str | None   # response 指向 request 的 msg_id
    payload: dict
```

---

### s11 — 队友自己看看板, 有活就认领 [v4 ✨ tasks/kanban.py + multi_agent/worker.py]
> 不需要领导逐个分配，自组织

```
tasks/kanban.py       [v4 ✨]  线程安全三列看板，claim() 原子操作
multi_agent/worker.py [v4 ✨]  WorkerAgent：轮询 → claim → SubAgentRunner → complete
```

---

### s12 — 各干各的目录, 互不干扰 [v4 ✨ tasks/worktree.py]
> 任务管目标，worktree 管目录，按 ID 绑定

```
tasks/worktree.py  [v4 ✨]  WorktreeManager：create/remove/path_for
                            git worktree 失败时降级为 plain mkdir，保证测试可用
```

---

## 三、测试覆盖汇总

| 文件 | 版本 | 测试数 | 覆盖点 |
|------|------|--------|--------|
| `unit/test_memory_base.py` | [v2] | 22 | MemoryRecord 遗忘曲线 |
| `unit/test_working_memory.py` | [v2] | 22 | WorkingMemory TTL/pin |
| `unit/test_tool_registry.py` | [v2] | 10 | ToolRegistry dispatch |
| `unit/test_note_tool.py` | [v2] | 18 | NoteToolHandler CRUD |
| `unit/test_terminal_tool.py` | [v2] | 20 | 白名单/黑名单命令 |
| `unit/test_context_select.py` | [v2] | 9 | select 阈值/token预算 |
| `unit/test_context_structure.py` | [v2] | 10 | XML 标签结构化 |
| `unit/test_planner.py` | [v4 ✨] | 12 | Step 解析、JSON 格式校验 |
| `unit/test_task_models.py` | [v4 ✨] | 15 | Task/Step + DAG 拓扑 |
| `unit/test_kanban.py` | [v4 ✨] | 11 | 三列状态机 + 并发认领 |
| `unit/test_protocol.py` | [v4 ✨] | 7 | AgentMessage 序列化 |
| `unit/test_compress_layers.py` | [v4 ✨] | 15 | 三层压缩各层 |
| `integration/test_context_builder.py` | [v2] | 11 | GSSC 流水线 |
| `integration/test_web_search_tool.py` | [v2] | 7 | Tavily/SerpAPI 降级 |
| `integration/test_agent.py` | [v2] | 12 | HelloAgent 全链路 |
| `integration/test_env_connectivity.py` | [v2] | 14 | 真实 API ⚠️ |
| `integration/test_subagent.py` | [v4 ✨] | 6 | context 隔离 |
| `integration/test_background.py` | [v4 ✨] | 11 | submit→poll 时序 |
| `integration/test_multi_agent.py` | [v4 ✨] | 18 | mailbox 一问一答 |
| `integration/test_worktree.py` | [v4 ✨] | 8 | worktree 绑定+清理 |
| **v2 小计** | | **159** | |
| **v4 新增** | | **89** | |
| **总计（248 实际通过）** | | **248** | |

---

## 四、演进路线

```
v1 (fccb355) — Initial commit
  单 Agent + 记忆系统（working/episodic/semantic/perceptual）
  + RAG 检索 + 基础工具（memory/rag）

v2 (becc3f9) — OpenAI-compatible 重构
  + config.py（pydantic-settings）
  + context/（GSSC 流水线：gather→select→structure→compress）
  + ToolRegistry（统一 dispatch map）
  + 5 个内置工具（memory/rag/note/terminal/web_search）
  + 159 个测试

v3 (a4636f5) — 基础设施
  + docker-compose.yml（Qdrant + Neo4j 本地服务）
  （不涉及代码架构）

v4 (当前) — 多 Agent 协作（s01–s12）
  + planner/（s03）
  + subagent/（s04）
  + context/compress.py 三层压缩（s06）
  + tasks/（s07/s08/s11/s12）
  + multi_agent/（s09/s10/s11）
  + 3 个新工具（task/background/agent）
  + 89 个新测试，总计 248 个
```
