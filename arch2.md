hello-agents/
├── hello_agents/
│   ├── config.py                 # ✨新增: pydantic-settings 全局配置（读 .env）
│   ├── agent.py                  # 🤖 Agent 主体（OpenAI Function Calling）
│   │
│   ├── context/                  # 🧩 (✨全新引入) 上下文组装中枢（大模型的"提示词装配车间"）
│   │   ├── builder.py            # ContextBuilder: 核心入口，调度 GSSC 流水线
│   │   ├── gather.py             # Gather (收集): 并发调用 memory.router, rag 和 terminal 收集原始素材
│   │   ├── select.py             # Select (筛选): 基于 Token 预算和相关度阈值，剔除低优先级上下文
│   │   ├── structure.py          # Structure (结构化): 将多源数据转化为易于 LLM 理解的格式 (如 XML 标签)
│   │   └── compress.py           # Compress (压缩): 当 Token 超载时，调用轻量模型进行文本摘要或截断
│   │
│   ├── memory/                   # 🧠 核心记忆系统（主观经验与内在认知）
│   │   ├── base.py               # 基础数据模型（含遗忘曲线字段）
│   │   ├── manager.py            # 记忆调度中枢
│   │   ├── router.py             # 记忆路由器（负责多路召回与重排序）
│   │   ├── reflection.py         # 反思与巩固引擎（Episodic -> Semantic）[✏️ 改: OpenAI chat completions JSON mode]
│   │   ├── events.py             # 异步事件总线
│   │   ├── embedding.py          # 统一嵌入服务 [✏️ 改: OpenAI-compatible 嵌入（text-embedding-v3）]
│   │   │
│   │   ├── types/                # 记忆的认知形态
│   │   │   ├── working.py        # 工作记忆（当前会话）
│   │   │   ├── episodic.py       # 情景记忆（流水账）
│   │   │   ├── semantic.py       # 语义记忆（知识图谱）
│   │   │   └── perceptual.py     # 感知记忆（多模态）[✏️ 改: OpenAI Vision 替换 Gemini Vision]
│   │   │
│   │   └── storage/              # 物理存储适配层
│   │       ├── qdrant_store.py   # 向量库 (Qdrant)
│   │       ├── neo4j_store.py    # 图数据库 (Neo4j)
│   │       └── document_store.py # 文档/关系库 (SQLite)
│   │
│   ├── rag/                      # 📚 外部知识系统（客观世界知识库）
│   │   ├── pipeline.py           # 知识检索管道
│   │   ├── document.py           # 多格式文档解析器
│   │   └── knowledge_base.py     # 知识库管理
│   │
│   └── tools/                    # 🛠️ Agent 动作与工具箱
│       ├── registry.py           # ✨新增: 统一工具注册表 + schema 生成 + dispatch
│       └── builtin/
│           ├── memory_tool.py    # ✏️ 改: OpenAI tool dict 格式
│           ├── rag_tool.py       # ✏️ 改: OpenAI tool dict 格式
│           ├── note_tool.py      # ✨新增: 结构化笔记（SQLite CRUD）
│           ├── terminal_tool.py  # ✨新增: 终端/文件系统（白名单限制）
│           └── web_search_tool.py # ✨新增: Tavily 优先 + SerpAPI 备用
│
└── tests/                        # ✅ 测试套件（145 个用例，pytest + pytest-asyncio）
    ├── conftest.py               # 共享 fixtures（tmp_db、mock_tool_call）
    │
    ├── unit/                     # 单元测试（117 个）——不依赖外部服务，纯本地
    │   ├── test_memory_base.py   # MemoryRecord: 遗忘曲线 decay/reinforce/is_forgotten、序列化 roundtrip
    │   ├── test_working_memory.py # WorkingMemory: add/get/TTL过期/pin保护/trim裁切/多session隔离
    │   ├── test_tool_registry.py  # ToolRegistry: 注册/分发路由、未知工具错误、has_tool
    │   ├── test_note_tool.py      # NoteToolHandler: SQLite CRUD（create/read/update/delete/list）、tag过滤
    │   ├── test_terminal_tool.py  # TerminalToolHandler: 命令白名单/黑名单安全检查、文件读写、目录列举
    │   ├── test_context_select.py # select(): min_score过滤、token预算贪心裁切、截断逻辑
    │   └── test_context_structure.py # structure(): XML标签格式化（memory/knowledge/system_state分组）
    │
    └── integration/              # 集成测试（28 个）——mock 外部 API，验证模块协作
        ├── test_context_builder.py  # ContextBuilder GSSC流水线端到端、低分过滤、compress触发、异常健壮性
        ├── test_web_search_tool.py  # WebSearchToolHandler: Tavily优先/SerpAPI备用/无key错误、参数传递
        └── test_agent.py            # HelloAgent: start/stop生命周期、chat多轮、context注入、Function Calling分发、最大轮次保护
