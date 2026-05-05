# arch4 — 架构对比分析

> **arch3（hello-agents）** vs **claude-code-v1**
> 优缺点分析 + 适用场景

---

## 一、基本信息速览

| 维度 | arch3 (hello-agents) | claude-code-v1 |
|------|----------------------|----------------|
| 语言/运行时 | Python 3.9 + asyncio | TypeScript + Bun |
| 代码规模 | ~3,500 行（35 个核心文件） | ~数万行（1,900+ .ts/.tsx 文件） |
| 测试覆盖 | 248 个 pytest 用例（分层） | 无公开测试套件 |
| 用户界面 | 无（纯 API） | 完整 TUI（React + Ink） |
| 对话方式 | 等待完整回复返回 | 流式 AsyncGenerator 实时输出 |
| 记忆深度 | 4 层认知记忆 + 遗忘曲线 | claude.md 文件 + 会话历史 |
| 工具数量 | 8 个内置工具 | 42 个工具 |
| 多 Agent | Kanban + Mailbox + WorkerAgent | AgentTool（临时子进程） |
| 外部扩展 | ToolRegistry（代码注册） | MCP 协议 + Skills + 插件 |
| 权限控制 | 无 | default / auto / bypass 三模式 |

---

## 二、优缺点逐维对比

### 2.1 记忆系统

#### arch3 ✅ 优势
- **4 层认知记忆**：Working / Episodic / Semantic / Perceptual，仿人类认知层次
- **遗忘曲线**：Ebbinghaus 指数衰减，记忆自然老化，GC 清理已遗忘条目
- **反思引擎**：高价值情景记忆定期提炼为语义记忆（Episodic → Semantic）
- **向量检索**：Qdrant + text-embedding，语义相似度检索，不依赖关键词
- **图谱存储**：Neo4j 存实体关系，支持图遍历推理
- **跨会话持久化**：记忆在进程重启后依然存在

#### arch3 ❌ 劣势
- 需要 Qdrant + Neo4j 两个外部服务，本地部署成本高
- 记忆写入是同步路径，高并发时可能成为瓶颈
- 无原生 token 级别的记忆检索（只能按字符/向量距离）

#### claude-code-v1 ✅ 优势
- **零依赖记忆**：claude.md 纯文件，无外部服务，部署简单
- **SessionMemory**：会话历史自动持久化，断线可恢复
- **loadMemoryFiles**：支持多个 claude.md 文件分目录加载，灵活

#### claude-code-v1 ❌ 劣势
- 无语义检索，只能靠 LLM 自己从全文 claude.md 中找信息
- 无遗忘机制，记忆只增不减，claude.md 无限膨胀
- 无跨话题的知识图谱，关系推理能力弱
- 记忆完全暴露在纯文本文件中，隐私保护差

---

### 2.2 工具系统

#### arch3 ✅ 优势
- **ToolRegistry 解耦**：新工具只需实现 handler + schema，不改 loop（s02）
- **单一 loop 原则**（s01）：扩展点清晰，心智负担低
- **类型安全的 dispatch**：Python dataclass + JSON 校验，错误定位快
- **完整的工具测试**：每个工具都有独立 unit test

#### arch3 ❌ 劣势
- 仅 8 个工具，缺少文件写入、notebook 编辑、diff 工具
- 工具执行无权限拦截，危险命令依赖白名单静态过滤
- 无工具输出流式展示（返回完整 JSON 后才交给 LLM）

#### claude-code-v1 ✅ 优势
- **42 个工具**：文件读写/编辑、ripgrep 搜索、Git、notebook、MCP、AgentTool 等
- **三级权限控制**：default（询问）/ auto（启发式）/ bypass（允许）
- **不可绕过的危险拦截**：`rm -rf` 等即使 bypass 模式也强制询问
- **Zod schema 校验**：工具参数强类型校验，异常有意义的报错
- **isEnabled 门控**：工具可按上下文动态禁用

#### claude-code-v1 ❌ 劣势
- 工具分散在 42 个目录，新增工具需理解整套注册体系
- 无工具级别的测试套件（公开部分）
- 工具执行在主进程，崩溃影响整个会话

---

### 2.3 多 Agent 协作

#### arch3 ✅ 优势
- **持久化 PeerAgent**：配置可序列化，跨进程存在
- **Kanban 自组织**（s11）：WorkerAgent 自主轮询认领，无需中心调度器
- **DAG 任务图**（s07）：显式依赖建模，拓扑排序，循环检测
- **AgentMessage 协议**（s10）：统一 request/response/event，correlation_id 关联
- **隔离上下文**（s04）：SubAgentRunner 使用独立 messages[]，不污染主对话
- **Worktree 隔离**（s12）：每个子任务独立 git worktree，文件操作互不干扰
- **后台执行**（s08）：慢操作丢线程池，主 Agent 继续响应用户

#### arch3 ❌ 劣势
- Mailbox 基于 SQLite 轮询（poll_interval），非事件驱动，有延迟
- WorkerAgent 无心跳/超时检测，僵死任务需手动处理
- 无 Agent 间负载均衡，任务认领先到先得
- 跨机器多 Agent 未支持（Mailbox 是本地 SQLite）

#### claude-code-v1 ✅ 优势
- **AgentTool**：启动子进程，操作系统级隔离，崩溃不影响主进程
- **UDS 消息通道**：Unix Domain Socket，事件驱动，延迟低于 SQLite 轮询
- **Swarm 模式**：`useSwarmInitialization` 支持多 Agent 协同初始化

#### claude-code-v1 ❌ 劣势
- AgentTool 是临时子进程，生命周期随任务结束，无持久化队友
- 无任务依赖图，并行任务间无协调机制
- 无任务持久化，进程崩溃后任务状态丢失
- Swarm 细节未公开，可控性差

---

### 2.4 上下文管理

#### arch3 ✅ 优势
- **GSSC 流水线**：Gather → Select → Structure → Compress，各阶段可独立测试
- **三层压缩策略**（s06）：滑窗（毫秒）→ LLM摘要（秒）→ 卸载记忆（异步），按需触发
- **知识按需注入**（s05）：RAG/记忆通过 tool_result 拉取，system prompt 保持精简
- **Token 预算选择**：select 阶段按 token 预算精确截断低分条目

#### arch3 ❌ 劣势
- 无 token 计数（按字符数估算），实际用量可能超出预期
- 压缩触发阈值为静态常量，无法根据模型动态调整
- 无 Layer 3 自动触发机制，需调用方手动判断 `needs_offload()`

#### claude-code-v1 ✅ 优势
- **QueryEngine 内置压缩**：Token 预算超出时自动删除旧消息，无需外部触发
- **精确 Token 计数**：直接使用 API 返回的 token 统计，不靠估算
- **流式上下文**：边生成边消费，无需等完整响应后再构建上下文

#### claude-code-v1 ❌ 劣势
- 压缩策略较粗暴（删旧消息），无 arch3 的摘要/记忆卸载等精细分层
- 单一压缩路径，无按内容类型差异化处理
- `services/compact/` 文档稀少，策略不透明

---

### 2.5 可扩展性

#### arch3 ✅ 优势
- **学习曲线平缓**：12 条原则（s01–s12）串联所有设计决策，新人 1 天内可上手
- **模块边界清晰**：每个文件 < 200 行，单一职责
- **纯 Python**：无需特殊运行时，pip install 即可运行

#### arch3 ❌ 劣势
- 扩展必须修改代码，无插件/技能动态加载机制
- 无功能门控，所有模块始终加载
- 无 MCP 支持，无法接入社区已有工具服务器

#### claude-code-v1 ✅ 优势
- **MCP 协议**：stdio / SSE / WebSocket 三种接入方式，工具动态发现，无需重启
- **Skills 系统**：用户自定义技能，放置于 `~/.claude/skills/` 即可加载
- **插件系统**：版本化插件管理，支持热更新
- **功能门控**：GrowthBook + bun 构建时 tree-shaking，按需开启

#### claude-code-v1 ❌ 劣势
- MCP 增加了运维复杂度（需维护外部服务器）
- 技能系统与核心 LLM 调用紧密耦合，测试困难
- 1,900 个文件，新增功能前需大量上下文理解

---

### 2.6 生产就绪度

#### arch3 ✅ 优势
- **248 个测试**：单元/集成/连通性三层，CI 友好
- **明确的错误处理**：每个 handler 捕获并返回 JSON error
- **测试策略清晰**：`--unit` / `--integration` / `--connectivity` 分开执行

#### arch3 ❌ 劣势
- 无流式响应，大模型回复需等待完整生成（体验差）
- 无 graceful degradation：任一组件崩溃影响整个 Agent
- 无重试/退避逻辑（LLM API 调用失败直接抛出）
- 无 rate limit 处理、无遥测、无成本追踪

#### claude-code-v1 ✅ 优势
- **流式输出**：AsyncGenerator 实时展示 token，体验接近原生 CLI
- **指数退避重试**：API 临时失败自动恢复
- **优雅降级**：TUI 崩溃 → readline REPL，MCP 断连 → 跳过该工具
- **并行初始化**：启动耗时 <1s
- **遥测 + 成本统计**：token 用量实时展示

#### claude-code-v1 ❌ 劣势
- 无测试套件（公开部分），回归风险高
- 全局可变状态（`bootstrap/state.ts`）线程安全隐患
- 强依赖 Bun，无法用 Node.js 运行

---

## 三、核心差异一句话总结

```
arch3      = 认知仿真 Agent 框架（深度记忆 + 任务图 + 自组织多Agent）
               → 关注"Agent 怎么思考和协作"

claude-v1  = 生产级 AI 编程助手（流式TUI + 42工具 + MCP生态）
               → 关注"用户怎么高效使用 AI 工具"
```

---

## 四、适合场景

### arch3（hello-agents）适合

| 场景 | 原因 |
|------|------|
| **长期记忆研究** | Episodic→Semantic 反思、遗忘曲线，适合认知计算实验 |
| **知识密集型 RAG 应用** | Qdrant 向量库 + Neo4j 图谱，多知识库语义检索 |
| **多 Agent 任务分发系统** | Kanban 自组织认领，DAG 依赖建模，Worktree 隔离 |
| **Agent 架构教学/学习** | 模块边界清晰，s01–s12 有设计意图说明，适合逐步拆解 |
| **后端服务嵌入** | 纯 Python API，无 UI 耦合，易于集成进 FastAPI/Flask |
| **需要自定义记忆策略** | 4 层记忆可独立替换后端存储（换 Chroma/Weaviate 等） |
| **批量任务处理** | 后台线程 + 看板，适合离线批量文档处理、数据标注等 |
| **可解释性要求高** | 每条记忆有 strength/stability 字段，状态完全可观测 |

### claude-code-v1 适合

| 场景 | 原因 |
|------|------|
| **开发者交互式编程助手** | 42 工具覆盖完整开发工作流，流式响应，TUI 体验好 |
| **企业安全合规场景** | 三模式权限系统 + 危险操作强制确认，可满足审计要求 |
| **MCP 生态对接** | 接入已有 MCP 服务器（数据库、文件系统、第三方 API） |
| **团队技能共享** | Skills 系统支持团队自定义技能包并共享 |
| **流式体验要求高** | AsyncGenerator 实时输出，适合对话延迟敏感的产品 |
| **多平台工作流** | Bridge 模式连接 Claude.ai Web，桌面 + Web 无缝切换 |
| **插件化扩展** | 第三方插件版本管理，适合构建平台级 AI 助手 |
| **Git 密集型任务** | 内置 git.ts + worktree 支持，/commit、/review 命令完备 |

---

## 五、互补融合方向

两套架构并非对立，可取长补短：

```
arch3 的深度记忆  ←──融合──→ claude-code-v1 的流式 TUI
    │                               │
    ▼                               ▼
长期知识持久化                  实时交互体验

arch3 的 DAG 任务图 ←──融合──→ claude-code-v1 的 MCP 协议
    │                               │
    ▼                               ▼
任务依赖精确建模               工具动态扩展

arch3 的 248 个测试 ←──融合──→ claude-code-v1 的权限系统
    │                               │
    ▼                               ▼
回归保障                       生产安全

arch3 的 Kanban 自组织 ←──融合──→ claude-code-v1 的 AgentTool 进程隔离
    │                               │
    ▼                               ▼
无中心调度                     操作系统级隔离
```

**如果只能选一个出发点**：
- 做研究/教学/定制化后端 → **从 arch3 出发**，加上流式响应和权限控制
- 做产品/工具链/开发者体验 → **从 claude-code-v1 出发**，加上深度记忆和任务图
