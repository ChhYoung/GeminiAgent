# arch v5 — s00–s19 完整架构

> 基于 arch3（v4，s01–s12 落地）扩展：新增 s00 全局地图 + s13–s19 七个高级模块
>
> **版本标注说明**
> - `[v1]`     首次引入于 v1（Initial commit）
> - `[v2]`     首次引入于 v2（OpenAI-compatible 重构）
> - `[v4]`     首次引入于 v4（多 Agent 协作）
> - `[v4 ✏️]`  v4 引入，v5 修改
> - `[v5 ✨]`  v5 全新引入
> - `[v5 ✏️]`  v5 修改已有文件
> - `[~]`      v5 删除或合并

---

## 一、架构演进总览（变更摘要）

| 章节 | 原则名称 | v4 状态 | v5 变更 |
|------|----------|---------|---------|
| s00 | Architecture Overview | ❌ 无 | ✨ 新增：全局地图 + 学习顺序 |
| s01 | Agent Loop | ✅ agent.py | 不变 |
| s02 | Tool Use | ✅ tools/registry.py | 不变 |
| s03 | Todo / Planning | ✅ planner/ | 不变 |
| s04 | Subagent | ✅ subagent/ | 不变 |
| s05 | Skills | ✅ agent.py 按需注入 | ✏️ 独立为 skills/ 目录 |
| s06 | Context Compact | ✅ context/compress.py | 不变 |
| s07 | Permission System | ❌ 无 | ✨ 新增：permissions/ 安全门控 |
| s08 | Hook System | ❌ 无 | ✨ 新增：hooks/ 扩展点 |
| s09 | Memory System | ✅ memory/ | ✏️ 新增 memory/auto_gc 策略 |
| s10 | System Prompt | ❌ 无结构 | ✨ 新增：prompt/ 分段组装 |
| s11 | Error Recovery | ❌ 无 | ✨ 新增：recovery/ 续跑与重试 |
| s12 | Task System | ✅ tasks/ | ✏️ 合并原 s07/s08 |
| s13 | Background Tasks | ✅ tasks/background.py | ✏️ 升级为事件驱动 + 取消支持 |
| s14 | Cron Scheduler | ❌ 无 | ✨ 新增：tasks/cron.py |
| s15 | Agent Teams | ✅ multi_agent/peer.py | ✏️ 升级为 teams/ 持久化团队 |
| s16 | Team Protocols | ✅ multi_agent/protocol.py | ✏️ 扩展协调规则 |
| s17 | Autonomous Agents | ✅ multi_agent/worker.py | ✏️ 自认领 + 断点续跑 |
| s18 | Worktree Isolation | ✅ tasks/worktree.py | ✏️ 命名通道 + 清理策略 |
| s19 | MCP & Plugin | ❌ 无 | ✨ 新增：mcp/ 外部能力路由 |

> **注意**：v4 原则编号（s01–s12）与 v5 编号有偏移
> - v4 s07 → v5 s12（Task System）
> - v4 s08 → v5 s13（Background Tasks）
> - v4 s09/s10/s11 → v5 s15/s16/s17
> - v4 s12 → v5 s18（Worktree Isolation）

---

## 二、目录全貌

```
hello-agents/
├── hello_agents/
│   │
│   ├── config.py                          [v2]    pydantic-settings 全局配置
│   │
│   ├── agent.py                           [v5 ✏️] 主 Agent — 注入 hook 调用点，
│   │                                               接入 permission 检查，引用 prompt/
│   │
│   ├── prompt/                            [v5 ✨] s10 — System Prompt 分段组装
│   │   ├── __init__.py
│   │   ├── builder.py                              PromptBuilder：收集各段，按优先级拼装
│   │   ├── sections.py                             内置段：identity / capabilities / rules / context
│   │   └── loader.py                               从文件 / env / memory 动态加载补充段
│   │
│   ├── permissions/                       [v5 ✨] s07 — 权限安全门控
│   │   ├── __init__.py
│   │   ├── gate.py                                 PermissionGate：工具执行前的审批入口
│   │   ├── policy.py                               Policy 定义（default / auto / bypass）
│   │   ├── deny_list.py                            永不放行的危险命令黑名单
│   │   └── prompt_user.py                          终端侧用户审批 prompt
│   │
│   ├── hooks/                             [v5 ✨] s08 — 扩展点 Hook 系统
│   │   ├── __init__.py
│   │   ├── registry.py                             HookRegistry：注册 / 触发生命周期钩子
│   │   └── events.py                               HookEvent 枚举（pre_tool / post_tool /
│   │                                               pre_llm / post_llm / on_error / on_reply）
│   │
│   ├── recovery/                          [v5 ✨] s11 — 错误恢复与续跑
│   │   ├── __init__.py
│   │   ├── retry.py                                RetryPolicy：指数退避 + jitter
│   │   ├── checkpoint.py                           CheckpointStore：保存/恢复对话快照
│   │   └── fallback.py                             FallbackChain：工具降级链
│   │
│   ├── skills/                            [v5 ✨] s05 独立化 — 按需加载专项知识
│   │   ├── __init__.py
│   │   ├── registry.py                             SkillRegistry：发现 + 惰性加载
│   │   ├── loader.py                               从 ~/.agent/skills/ 目录热加载
│   │   └── builtin/
│   │       ├── coding_skill.py                     代码生成专项 prompt + 工具集
│   │       └── research_skill.py                   研究调查专项 prompt + 工具集
│   │
│   ├── planner/                           [v4]    s03 — 计划引擎
│   │   └── planner.py
│   │
│   ├── subagent/                          [v4]    s04 — 子 Agent 上下文隔离
│   │   └── runner.py
│   │
│   ├── context/                           [v2]    GSSC 上下文流水线
│   │   ├── builder.py                     [v2]
│   │   ├── gather.py                      [v2]
│   │   ├── select.py                      [v2]
│   │   ├── structure.py                   [v2]
│   │   └── compress.py                    [v4]    三层压缩（不变）
│   │
│   ├── memory/                            [v1]    s09 — 记忆系统
│   │   ├── base.py                        [v1]
│   │   ├── manager.py                     [v5 ✏️] 新增 auto_gc()：按遗忘曲线定期清理
│   │   ├── router.py                      [v1]
│   │   ├── reflection.py                  [v2 ✏️]
│   │   ├── events.py                      [v1]
│   │   ├── embedding.py                   [v2 ✏️]
│   │   ├── gc.py                          [v5 ✨] GarbageCollector：定时扫描 + 弱记忆删除
│   │   ├── types/
│   │   │   ├── working.py                 [v1]
│   │   │   ├── episodic.py                [v1]
│   │   │   ├── semantic.py                [v1]
│   │   │   └── perceptual.py              [v2 ✏️]
│   │   └── storage/
│   │       ├── qdrant_store.py            [v1]
│   │       ├── neo4j_store.py             [v1]
│   │       └── document_store.py          [v1]
│   │
│   ├── rag/                               [v1]    RAG 外部知识系统（不变）
│   │   ├── pipeline.py
│   │   ├── document.py
│   │   └── knowledge_base.py
│   │
│   ├── tasks/                             [v4]    s12/s13/s14 — 任务图 + 后台 + 定时
│   │   ├── models.py                      [v4]    Task / Step 数据模型
│   │   ├── graph.py                       [v4]    DAG + 拓扑排序
│   │   ├── store.py                       [v4]    JSON Lines 持久化
│   │   ├── scheduler.py                   [v4]    任务调度器
│   │   ├── kanban.py                      [v4]    三列看板
│   │   ├── background.py                  [v5 ✏️] s13 升级：事件回调 + cancel() + 进度流
│   │   ├── cron.py                        [v5 ✨] s14 Cron 调度器（APScheduler 封装）
│   │   └── worktree.py                    [v5 ✏️] s18 升级：命名通道 + TTL 清理策略
│   │
│   ├── teams/                             [v5 ✨] s15/s16/s17 — Agent 团队协作
│   │   ├── __init__.py
│   │   ├── team.py                                 AgentTeam：持久化团队定义（成员 + 角色 + 共享规则）
│   │   ├── roster.py                               TeamRoster：团队注册表，支持跨进程共享
│   │   ├── protocol.py                    [v5 ✏️] s16 扩展：加入 broadcast / vote / delegate 消息类型
│   │   ├── coordinator.py                 [v5 ✨] s16 Coordinator：团队级任务分发 + 仲裁
│   │   └── autonomous.py                  [v5 ✨] s17 AutonomousAgent：自认领 + 断点续跑 + 心跳检测
│   │
│   ├── mcp/                               [v5 ✨] s19 — MCP & Plugin 外部能力路由
│   │   ├── __init__.py
│   │   ├── client.py                               MCPClient：stdio / SSE / WebSocket 三种接入
│   │   ├── registry.py                             MCPRegistry：动态发现 + 健康检查
│   │   ├── router.py                               MCPRouter：将 MCP 工具桥接到 ToolRegistry
│   │   └── plugin.py                               PluginManager：版本化插件加载 / 热更新
│   │
│   └── tools/                             [v2]    Agent 工具箱
│       ├── registry.py                    [v2]    ToolRegistry（dispatch map）
│       └── builtin/
│           ├── memory_tool.py             [v2 ✏️]
│           ├── rag_tool.py                [v2 ✏️]
│           ├── note_tool.py               [v2 ✨]
│           ├── terminal_tool.py           [v2 ✨]
│           ├── web_search_tool.py         [v2 ✨]
│           ├── task_tool.py               [v4 ✨]  s12 任务管理（create/list/update）
│           ├── background_tool.py         [v5 ✏️] s13 新增 cancel_background / stream_progress
│           ├── agent_tool.py              [v4 ✨]  s15 跨 Agent 消息（不变）
│           ├── cron_tool.py               [v5 ✨] s14 cron 管理（add_cron / list_crons / remove_cron）
│           ├── team_tool.py               [v5 ✨] s15/s16 团队操作（form_team / broadcast / vote）
│           ├── skill_tool.py              [v5 ✨] s05 技能激活（activate_skill / list_skills）
│           └── mcp_tool.py                [v5 ✨] s19 MCP 工具透传（call_mcp / list_mcp_servers）
│
└── tests/
    ├── conftest.py                        [v2]
    ├── run_tests.sh                       [v5 ✏️] 新增 --v5 标签分组
    │
    ├── unit/
    │   ├── test_memory_base.py            [v2]    22 个（不变）
    │   ├── test_working_memory.py         [v2]    22 个（不变）
    │   ├── test_tool_registry.py          [v2]    10 个（不变）
    │   ├── test_note_tool.py              [v2]    18 个（不变）
    │   ├── test_terminal_tool.py          [v2]    20 个（不变）
    │   ├── test_context_select.py         [v2]    9 个（不变）
    │   ├── test_context_structure.py      [v2]    10 个（不变）
    │   ├── test_planner.py                [v4]    12 个（不变）
    │   ├── test_task_models.py            [v4]    15 个（不变）
    │   ├── test_kanban.py                 [v4]    11 个（不变）
    │   ├── test_protocol.py               [v5 ✏️] 7→12 个：新增 broadcast/vote/delegate
    │   ├── test_compress_layers.py        [v4]    15 个（不变）
    │   ├── test_permissions.py            [v5 ✨] 16 个：policy/deny_list/gate
    │   ├── test_hooks.py                  [v5 ✨] 12 个：注册/触发/异常隔离
    │   ├── test_recovery.py               [v5 ✨] 14 个：retry 退避 / checkpoint 存取 / fallback
    │   ├── test_prompt_builder.py         [v5 ✨] 10 个：分段拼装 / 优先级覆盖
    │   ├── test_cron.py                   [v5 ✨] 13 个：cron 表达式解析 / 触发时序
    │   ├── test_team.py                   [v5 ✨] 18 个：组建/广播/投票/解散
    │   ├── test_autonomous.py             [v5 ✨] 15 个：自认领 / 心跳 / 续跑
    │   ├── test_memory_gc.py              [v5 ✨] 10 个：遗忘曲线 GC 触发条件
    │   ├── test_skills.py                 [v5 ✨] 11 个：注册/惰性加载/激活
    │   └── test_mcp_registry.py           [v5 ✨] 12 个：发现 / 健康检查 / 路由
    │
    └── integration/
        ├── test_context_builder.py        [v2]    11 个（不变）
        ├── test_web_search_tool.py        [v2]    7 个（不变）
        ├── test_agent.py                  [v2]    12 个（不变）
        ├── test_env_connectivity.py       [v2]    14 个（不变）⚠️ 需外部服务
        ├── test_subagent.py               [v4]    6 个（不变）
        ├── test_background.py             [v5 ✏️] 11→16 个：新增 cancel / 流式进度
        ├── test_multi_agent.py            [v4]    18 个（不变）
        ├── test_worktree.py               [v5 ✏️] 8→13 个：命名通道 / TTL 清理
        ├── test_cron_trigger.py           [v5 ✨] 9 个：定时触发 + 遗漏补跑
        ├── test_agent_teams.py            [v5 ✨] 22 个：多 Agent 完整协作流
        ├── test_autonomous_resume.py      [v5 ✨] 10 个：模拟崩溃 + 自动续跑
        ├── test_mcp_bridge.py             [v5 ✨] 14 个：MCPClient ↔ ToolRegistry 桥接⚠️ 需 MCP 服务
        └── test_permission_gate.py        [v5 ✨] 8 个：危险操作拦截全链路
```

---

## 三、各原则落地（v5 变化重点）

### s00 — Architecture Overview [v5 ✨]
> 全局地图、核心术语、推荐学习顺序

无对应运行时模块；以本文档 + README 形式存在。

**学习路径（从核心到外围）**：
```
s01 Agent Loop
 └─→ s02 Tool Use
      └─→ s03 Todo/Planning
           ├─→ s04 Subagent
           ├─→ s05 Skills
           └─→ s06 Context Compact
                └─→ s07 Permission System
                     └─→ s08 Hook System
                          ├─→ s09 Memory System
                          ├─→ s10 System Prompt
                          └─→ s11 Error Recovery
                               └─→ s12 Task System
                                    ├─→ s13 Background Tasks
                                    ├─→ s14 Cron Scheduler
                                    └─→ s15 Agent Teams
                                         ├─→ s16 Team Protocols
                                         ├─→ s17 Autonomous Agents
                                         ├─→ s18 Worktree Isolation
                                         └─→ s19 MCP & Plugin
```

---

### s05 — Skills（独立化）[v4 ✏️ → v5 ✨ skills/]
> 从 agent.py 内联注入升级为独立目录，支持热加载

v4 仅在 agent.py 中通过 tool_result 注入；v5 提取为 `skills/` 目录。

```python
# skills/registry.py  [v5 ✨]
class SkillRegistry:
    def register(self, skill: Skill): ...
    def activate(self, name: str) -> Skill: ...   # 惰性加载
    def list_available(self) -> list[str]: ...

# skills/loader.py  [v5 ✨]
# 扫描 ~/.agent/skills/*.py，动态 importlib 加载
```

---

### s07 — Permission System [v5 ✨ permissions/]
> 工具执行前的安全门控，v4 无此模块

```
permissions/gate.py       ← 工具执行前 check(tool_name, args) → bool
permissions/policy.py     ← default（询问）/ auto（启发式）/ bypass（直通）
permissions/deny_list.py  ← rm -rf / DROP TABLE 等永不放行
permissions/prompt_user.py ← 终端 [y/N] 审批
```

工具执行流程变更：
```
v4: _run_one_tool(name, args)  →  handler(args)
v5: _run_one_tool(name, args)  →  gate.check()  →  handler(args)
                                       ↓ denied
                                   return PermissionDeniedError
```

---

### s08 — Hook System [v5 ✨ hooks/]
> Loop 各阶段的扩展点，v4 无此模块

```python
# hooks/events.py  [v5 ✨]
class HookEvent(Enum):
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    PRE_LLM = "pre_llm"
    POST_LLM = "post_llm"
    ON_ERROR = "on_error"
    ON_REPLY = "on_reply"

# hooks/registry.py  [v5 ✨]
class HookRegistry:
    def on(self, event: HookEvent, fn: Callable): ...
    async def fire(self, event: HookEvent, payload: dict): ...
    # hook 异常不中断主循环，写 warning 日志后继续
```

`agent.py` 在以下位置插入 `await hooks.fire(...)` 调用点：
- `_call_llm()` 前后 → PRE_LLM / POST_LLM
- `_run_one_tool()` 前后 → PRE_TOOL / POST_TOOL
- 工具抛异常时 → ON_ERROR
- 最终回复时 → ON_REPLY

---

### s09 — Memory System [v5 ✏️ memory/gc.py 新增]
> 4 层记忆架构不变，新增自动垃圾回收

```python
# memory/gc.py  [v5 ✨]
class MemoryGarbageCollector:
    def __init__(self, manager: MemoryManager, min_strength: float = 0.1):
        ...
    async def run_once(self) -> int:          # 返回删除条目数
        # 扫描 EpisodicMemory，按遗忘曲线计算当前 strength
        # strength < min_strength → 从 Qdrant 删除
        ...
    async def start_background(self, interval_s: int = 3600): ...
```

`memory/manager.py` 新增 `auto_gc(enabled: bool)` 开关，默认 True，启动时后台运行 GC。

---

### s10 — System Prompt [v5 ✨ prompt/]
> 分段式 Prompt 组装，取代 agent.py 中的硬编码字符串

```python
# prompt/sections.py  [v5 ✨]
IDENTITY    = "You are a capable AI agent..."
CAPABILITIES = "You can use tools to..."
RULES       = "Always plan before acting..."

# prompt/builder.py  [v5 ✨]
class PromptBuilder:
    def add_section(self, key: str, content: str, priority: int = 0): ...
    def build(self, max_tokens: int = 500) -> str:
        # 按 priority 降序拼装，超出截断低优先级段
```

`agent.py` 在初始化时调用 `PromptBuilder.build()`，替代原硬编码 system prompt。

---

### s11 — Error Recovery [v5 ✨ recovery/]
> 续跑 + 重试分支，v4 无此模块

```python
# recovery/retry.py  [v5 ✨]
@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 1.0      # 秒
    max_delay: float = 60.0
    jitter: bool = True
    retryable: tuple = (RateLimitError, TimeoutError)

    async def execute(self, fn: Callable, *args, **kwargs): ...

# recovery/checkpoint.py  [v5 ✨]
class CheckpointStore:
    def save(self, session_id: str, messages: list, step_idx: int): ...
    def load(self, session_id: str) -> tuple[list, int] | None: ...
    # 持久化为 ~/.agent/checkpoints/{session_id}.json

# recovery/fallback.py  [v5 ✨]
class FallbackChain:
    # 工具降级链：primary_tool → backup_tool → error_message
    def add(self, primary: str, backup: str): ...
    async def call(self, tool_name: str, args: dict, registry: ToolRegistry): ...
```

---

### s12 — Task System [v4 tasks/ → 重新对齐编号]

> v4 s07 对应此章节，代码不变，仅重新映射原则编号

```
tasks/models.py    [v4]  Task + Step 数据模型
tasks/graph.py     [v4]  DAG + Kahn 拓扑排序
tasks/store.py     [v4]  JSON Lines 持久化
tasks/scheduler.py [v4]  add / next_ready / update_status
tasks/kanban.py    [v4]  线程安全三列看板
```

---

### s13 — Background Tasks [v4 s08 ✏️ → v5 升级]
> 从 ThreadPool + poll 升级为事件驱动 + 取消支持

**v4 局限**：只有 `submit(fn) → job_id` + `poll(job_id) → status`，无取消、无回调、无进度流

**v5 新增**：

```python
# tasks/background.py  [v5 ✏️]
class BackgroundExecutor:
    # v4 已有
    async def submit(self, fn, *args) -> str: ...          # → job_id
    def poll(self, job_id: str) -> JobStatus: ...

    # v5 新增
    def cancel(self, job_id: str) -> bool: ...             # 发送取消信号
    async def stream_progress(self, job_id: str):          # AsyncGenerator[ProgressEvent]
        ...
    def on_complete(self, job_id: str, callback: Callable): ...   # 完成回调

# tools/builtin/background_tool.py  [v5 ✏️]
# 新增工具：cancel_background(job_id) / stream_progress(job_id)
```

---

### s14 — Cron Scheduler [v5 ✨ tasks/cron.py]
> 时间驱动的任务触发，v4 无此模块

```python
# tasks/cron.py  [v5 ✨]
from apscheduler.schedulers.asyncio import AsyncIOScheduler

class CronScheduler:
    def __init__(self): self._scheduler = AsyncIOScheduler()

    def add_job(self, cron_expr: str, tool_name: str, args: dict,
                job_id: str | None = None) -> str: ...
    # cron_expr: "0 9 * * 1-5"（工作日 9 点）

    def remove_job(self, job_id: str): ...
    def list_jobs(self) -> list[CronJob]: ...

    async def start(self): ...
    async def shutdown(self): ...

    # 遗漏补跑：scheduler 崩溃重启后，检查最后触发时间
    # 如果错过触发窗口，立即补跑一次（misfire_grace_time=300）
```

```python
# tools/builtin/cron_tool.py  [v5 ✨]
# add_cron(cron_expr, tool_name, args) → job_id
# list_crons() → list[CronJob]
# remove_cron(job_id) → bool
```

持久化：`CronJob` 序列化到 `~/.agent/cron_jobs.json`，重启后自动恢复注册。

---

### s15 — Agent Teams [v4 multi_agent/ ✏️ → v5 teams/]
> 从临时 PeerAgent 注册表升级为持久化团队对象

**v4 局限**：`PeerAgent` 仅是配置描述 + 进程级 registry，无团队概念，无共享规则

**v5 新增**：

```python
# teams/team.py  [v5 ✨]
@dataclass
class AgentTeam:
    team_id: str
    name: str
    members: list[TeamMember]     # {agent_id, role, capabilities}
    shared_rules: list[str]       # 所有成员遵守的协调规则
    shared_memory_ns: str         # 团队共享记忆命名空间
    created_at: datetime

    def add_member(self, agent_id: str, role: str): ...
    def remove_member(self, agent_id: str): ...

# teams/roster.py  [v5 ✨]
class TeamRoster:
    # 持久化到 ~/.agent/teams/{team_id}.json
    def create(self, name: str, members: list) -> AgentTeam: ...
    def get(self, team_id: str) -> AgentTeam: ...
    def dissolve(self, team_id: str): ...
```

```python
# tools/builtin/team_tool.py  [v5 ✨]
# form_team(name, members) → team_id
# join_team(team_id) → bool
# broadcast(team_id, message) → list[response]
# vote(team_id, question, options) → VoteResult
```

---

### s16 — Team Protocols [v4 multi_agent/protocol.py ✏️ → v5 teams/protocol.py]
> 在 request/response/event 基础上增加团队协调消息类型

**v4 AgentMessage**：`msg_type ∈ {request, response, event}`

**v5 扩展**：

```python
# teams/protocol.py  [v5 ✏️]
class MsgType(str, Enum):
    REQUEST    = "request"
    RESPONSE   = "response"
    EVENT      = "event"
    # v5 新增
    BROADCAST  = "broadcast"    # 一对多，无需 to_agent
    VOTE       = "vote"         # 发起投票
    VOTE_REPLY = "vote_reply"   # 投票回应
    DELEGATE   = "delegate"     # 任务委托，带预期产出格式

# teams/coordinator.py  [v5 ✨]
class TeamCoordinator:
    async def distribute(self, task: Task, team: AgentTeam): ...
    # 按 capability 匹配成员 → send DELEGATE → 收集 response
    async def arbitrate(self, conflict: Conflict) -> Resolution: ...
    # 多 agent 输出冲突时，发起 VOTE 仲裁
```

---

### s17 — Autonomous Agents [v4 multi_agent/worker.py ✏️ → v5 teams/autonomous.py]
> 从"轮询看板"升级为"自认领 + 断点续跑 + 心跳检测"

**v4 局限**：WorkerAgent 轮询间隔固定，无心跳、无超时检测，崩溃后任务永远 IN_PROGRESS

**v5 新增**：

```python
# teams/autonomous.py  [v5 ✨]
class AutonomousAgent:
    """自治 Agent：事件驱动自认领 + 断点续跑 + 心跳"""

    heartbeat_interval: int = 30        # 秒
    task_timeout: int = 600             # 秒，超时自动释放

    async def run(self):
        # 1. 注册心跳协程（每 30s 更新 kanban 中的 last_seen）
        # 2. 监听 Kanban PENDING 事件（事件驱动，替代 sleep poll）
        # 3. claim() 原子认领 → SubAgentRunner.run()
        # 4. 完成 / 失败 → update kanban status

    async def resume(self, task_id: str):
        # 从 CheckpointStore 恢复 messages + step_idx
        # 继续执行未完成的步骤

# 心跳超时检测（由 TeamCoordinator 负责）：
# 扫描 kanban IN_PROGRESS 列，last_seen > task_timeout → 重置为 PENDING
```

```
tasks/kanban.py  [v5 ✏️]  新增 last_seen 字段 + release_stale(timeout) 方法
```

---

### s18 — Worktree Isolation [v4 tasks/worktree.py ✏️ → v5 升级]
> 从"按 task_id 绑定目录"升级为"命名通道 + TTL 清理"

**v4 局限**：`WorktreeManager` 按 task_id 创建目录，无 TTL，无命名通道概念，积累垃圾

**v5 新增**：

```python
# tasks/worktree.py  [v5 ✏️]
class WorktreeManager:
    # v4 已有
    def create(self, task_id: str) -> Path: ...
    def remove(self, task_id: str): ...
    def path_for(self, task_id: str) -> Path: ...

    # v5 新增
    def create_named(self, lane: str, task_id: str) -> Path:
        # 命名通道：worktrees/{lane}/{task_id}
        # lane 可为 "agent-alice" / "feature-x" / "review"
        ...

    def list_lanes(self) -> list[str]: ...

    async def gc(self, ttl_hours: int = 24):
        # 扫描所有 worktree，mtime > ttl → git worktree remove
        ...

    async def start_gc_loop(self, interval_hours: int = 6): ...
```

命名通道规范：
```
worktrees/
├── main/           ← 主 Agent 默认通道
├── agent-alice/    ← Alice AgentTeam 成员专属通道
├── agent-bob/
└── review/         ← 代码审查专用隔离通道
```

---

### s19 — MCP & Plugin [v5 ✨ mcp/]
> 外部能力路由，v4 无此模块

```python
# mcp/client.py  [v5 ✨]
class MCPClient:
    """支持 stdio / SSE / WebSocket 三种传输协议"""
    async def connect(self, transport: str, endpoint: str): ...
    async def list_tools(self) -> list[MCPTool]: ...
    async def call_tool(self, name: str, args: dict) -> MCPResult: ...
    async def close(self): ...

# mcp/registry.py  [v5 ✨]
class MCPRegistry:
    servers: dict[str, MCPClient]

    async def discover(self, config_path: str = "~/.agent/mcp_servers.json"):
        # 读取配置，逐个连接，拉取 tool list
        ...

    async def health_check(self) -> dict[str, bool]: ...

    def get_client(self, server_name: str) -> MCPClient: ...

# mcp/router.py  [v5 ✨]
class MCPRouter:
    """将 MCPRegistry 中的工具桥接到 ToolRegistry"""
    def bridge(self, mcp_registry: MCPRegistry, tool_registry: ToolRegistry):
        for server, tools in mcp_registry.all_tools():
            for tool in tools:
                # 动态注册 handler：tool_registry.register(f"mcp:{server}/{tool.name}", ...)
                ...

# mcp/plugin.py  [v5 ✨]
class PluginManager:
    """版本化插件管理 + 热更新"""
    def load(self, plugin_path: str): ...
    def unload(self, plugin_id: str): ...
    def reload(self, plugin_id: str): ...
    def list_plugins(self) -> list[PluginMeta]: ...
```

MCP 配置文件（`~/.agent/mcp_servers.json`）：
```json
{
  "filesystem": {"transport": "stdio", "cmd": "npx @modelcontextprotocol/server-filesystem /tmp"},
  "github":     {"transport": "sse",   "endpoint": "http://localhost:3001/sse"},
  "postgres":   {"transport": "ws",    "endpoint": "ws://localhost:3002/ws"}
}
```

工具名称命名规范：`mcp:{server}/{tool_name}`，例如 `mcp:filesystem/read_file`

---

## 四、测试覆盖汇总（v5）

| 文件 | 版本 | 测试数 | 覆盖点 |
|------|------|--------|--------|
| `unit/test_memory_base.py` | [v2] | 22 | MemoryRecord 遗忘曲线 |
| `unit/test_working_memory.py` | [v2] | 22 | WorkingMemory TTL/pin |
| `unit/test_tool_registry.py` | [v2] | 10 | ToolRegistry dispatch |
| `unit/test_note_tool.py` | [v2] | 18 | NoteToolHandler CRUD |
| `unit/test_terminal_tool.py` | [v2] | 20 | 白名单/黑名单命令 |
| `unit/test_context_select.py` | [v2] | 9 | select 阈值/token预算 |
| `unit/test_context_structure.py` | [v2] | 10 | XML 标签结构化 |
| `unit/test_planner.py` | [v4] | 12 | Step 解析、JSON 格式 |
| `unit/test_task_models.py` | [v4] | 15 | Task/Step + DAG 拓扑 |
| `unit/test_kanban.py` | [v4] | 11 | 三列状态机 + 并发认领 |
| `unit/test_protocol.py` | [v5 ✏️] | **12** | +broadcast/vote/delegate |
| `unit/test_compress_layers.py` | [v4] | 15 | 三层压缩各层 |
| `unit/test_permissions.py` | [v5 ✨] | 16 | gate/policy/deny_list |
| `unit/test_hooks.py` | [v5 ✨] | 12 | 注册/触发/异常隔离 |
| `unit/test_recovery.py` | [v5 ✨] | 14 | retry/checkpoint/fallback |
| `unit/test_prompt_builder.py` | [v5 ✨] | 10 | 分段拼装/优先级覆盖 |
| `unit/test_cron.py` | [v5 ✨] | 13 | cron 表达式/触发时序 |
| `unit/test_team.py` | [v5 ✨] | 18 | 组建/广播/投票/解散 |
| `unit/test_autonomous.py` | [v5 ✨] | 15 | 自认领/心跳/续跑 |
| `unit/test_memory_gc.py` | [v5 ✨] | 10 | 遗忘曲线 GC 触发 |
| `unit/test_skills.py` | [v5 ✨] | 11 | 注册/惰性加载/激活 |
| `unit/test_mcp_registry.py` | [v5 ✨] | 12 | 发现/健康检查/路由 |
| `integration/test_context_builder.py` | [v2] | 11 | GSSC 流水线 |
| `integration/test_web_search_tool.py` | [v2] | 7 | Tavily/SerpAPI 降级 |
| `integration/test_agent.py` | [v2] | 12 | HelloAgent 全链路 |
| `integration/test_env_connectivity.py` | [v2] | 14 | 真实 API ⚠️ |
| `integration/test_subagent.py` | [v4] | 6 | context 隔离 |
| `integration/test_background.py` | [v5 ✏️] | **16** | +cancel/流式进度 |
| `integration/test_multi_agent.py` | [v4] | 18 | mailbox 一问一答 |
| `integration/test_worktree.py` | [v5 ✏️] | **13** | +命名通道/TTL 清理 |
| `integration/test_cron_trigger.py` | [v5 ✨] | 9 | 定时触发+遗漏补跑 |
| `integration/test_agent_teams.py` | [v5 ✨] | 22 | 多 Agent 完整协作流 |
| `integration/test_autonomous_resume.py` | [v5 ✨] | 10 | 模拟崩溃+自动续跑 |
| `integration/test_mcp_bridge.py` | [v5 ✨] | 14 | MCPClient↔ToolRegistry ⚠️ |
| `integration/test_permission_gate.py` | [v5 ✨] | 8 | 危险操作拦截全链路 |
| **v4 继承（248 个）** | | **248** | |
| **v5 新增** | | **+194** | |
| **v5 总计** | | **~442** | |

---

## 五、演进路线

```
v1 (fccb355) — Initial commit
  单 Agent + 4 层记忆 + RAG + 基础工具（memory/rag）

v2 (becc3f9) — OpenAI-compatible 重构
  + config.py / context/（GSSC）/ ToolRegistry
  + 5 个内置工具 / 159 个测试

v3 (a4636f5) — 基础设施
  + docker-compose（Qdrant + Neo4j）

v4 (a3d3336) — 多 Agent 协作（s01–s12）
  + planner/ subagent/ tasks/ multi_agent/
  + 3 个新工具 / 89 个新测试 → 248 个总计

v5 (规划中) — 完整 s00–s19 架构
  ✨ 新增：permissions/ hooks/ recovery/ prompt/
           skills/ teams/ mcp/
           tasks/cron.py memory/gc.py
  ✏️ 升级：tasks/background.py tasks/worktree.py
           teams/protocol.py tasks/kanban.py
  + 12 个新工具（cron/team/skill/mcp/permission）
  + ~194 个新测试 → ~442 个总计

  关键里程碑：
  [ ] s07 permissions/ — 安全门控（建议优先，生产必备）
  [ ] s08 hooks/ — 扩展点（解耦核心与外围）
  [ ] s11 recovery/ — 错误恢复（生产稳定性）
  [ ] s14 tasks/cron.py — 定时任务
  [ ] s15–s17 teams/ — 持久化团队 + 自治 Agent
  [ ] s19 mcp/ — 外部生态对接
```

---

## 六、依赖变更（v5 新增）

| 包 | 用途 | 章节 |
|----|------|------|
| `apscheduler>=3.10` | Cron 调度器 | s14 |
| `mcp` | MCP 协议客户端 | s19 |
| `anyio` | 事件驱动后台任务 | s13 |

其余依赖（`openai` / `qdrant-client` / `neo4j` / `pydantic` / `aiosqlite`）延续 v4，不变。
