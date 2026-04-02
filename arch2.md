# arch v2 — commit 2 (becc3f9)
> OpenAI-compatible 重构：GSSC 上下文流水线 + 统一 ToolRegistry + 完整测试套件

**版本标注说明**
- `[v1]`     首次引入于 v1（Initial commit）
- `[v2 ✨]`  v2 全新引入
- `[v2 ✏️]`  v2 修改已有文件

hello-agents/
├── hello_agents/
│   ├── config.py                 # [v2 ✨] pydantic-settings 全局配置（读 .env）
│   ├── agent.py                  # [v2 ✏️] 重写为 OpenAI Function Calling 主体
│   │
│   ├── context/                  # [v2 ✨] 上下文组装中枢（GSSC 流水线）
│   │   ├── builder.py            # [v2 ✨] ContextBuilder: 核心入口，调度 GSSC 流水线
│   │   ├── gather.py             # [v2 ✨] Gather: 并发收集 memory/rag/terminal 原始素材
│   │   ├── select.py             # [v2 ✨] Select: 基于 Token 预算和相关度阈值过滤
│   │   ├── structure.py          # [v2 ✨] Structure: 将多源数据转化为 XML 标签格式
│   │   └── compress.py           # [v2 ✨] Compress: Token 超载时调用 LLM 摘要/截断
│   │
│   ├── memory/                   # 🧠 核心记忆系统
│   │   ├── base.py               # [v1]   基础数据模型（含遗忘曲线字段）
│   │   ├── manager.py            # [v1]   记忆调度中枢
│   │   ├── router.py             # [v1]   记忆路由器（多路召回与重排序）
│   │   ├── reflection.py         # [v2 ✏️] OpenAI chat completions JSON mode 重写
│   │   ├── events.py             # [v1]   异步事件总线
│   │   ├── embedding.py          # [v2 ✏️] 切换为 OpenAI-compatible 嵌入接口
│   │   │
│   │   ├── types/
│   │   │   ├── working.py        # [v1]   工作记忆（当前会话）
│   │   │   ├── episodic.py       # [v1]   情景记忆（流水账）
│   │   │   ├── semantic.py       # [v1]   语义记忆（知识图谱）
│   │   │   └── perceptual.py     # [v2 ✏️] OpenAI Vision 替换 Gemini Vision
│   │   │
│   │   └── storage/
│   │       ├── qdrant_store.py   # [v1]   向量库 (Qdrant)
│   │       ├── neo4j_store.py    # [v1]   图数据库 (Neo4j)
│   │       └── document_store.py # [v1]   文档/关系库 (SQLite)
│   │
│   ├── rag/                      # 📚 外部知识系统
│   │   ├── pipeline.py           # [v1]   知识检索管道
│   │   ├── document.py           # [v1]   多格式文档解析器
│   │   └── knowledge_base.py     # [v1]   知识库管理
│   │
│   └── tools/                    # 🛠️ Agent 工具箱
│       ├── registry.py           # [v2 ✨] 统一工具注册表 + schema 生成 + dispatch
│       └── builtin/
│           ├── memory_tool.py    # [v2 ✏️] 改为 OpenAI tool dict 格式
│           ├── rag_tool.py       # [v2 ✏️] 改为 OpenAI tool dict 格式
│           ├── note_tool.py      # [v2 ✨] 结构化笔记（SQLite CRUD）
│           ├── terminal_tool.py  # [v2 ✨] 终端/文件系统（白名单限制）
│           └── web_search_tool.py # [v2 ✨] Tavily 优先 + SerpAPI 备用
│
└── tests/                        # ✅ 测试套件（159 个用例）
    │
    ├── conftest.py               # [v2 ✨] 共享 fixtures（tmp_db / mock_tool_call）
    ├── run_tests.sh              # [v2 ✨] 一键全量执行脚本
    │
    ├── unit/                     # 🧪 单元测试（117 个）
    │   ├── test_memory_base.py   # [v2 ✨] MemoryRecord（22 个）
    │   ├── test_working_memory.py # [v2 ✨] WorkingMemory + WorkingMemoryStore（22 个）
    │   ├── test_tool_registry.py  # [v2 ✨] ToolRegistry（10 个）
    │   ├── test_note_tool.py      # [v2 ✨] NoteToolHandler SQLite CRUD（18 个）
    │   ├── test_terminal_tool.py  # [v2 ✨] TerminalToolHandler（20 个）
    │   ├── test_context_select.py # [v2 ✨] select()（9 个）
    │   └── test_context_structure.py # [v2 ✨] structure()（10 个）
    │
    └── integration/              # 🔗 集成测试（42 个）
        ├── test_context_builder.py  # [v2 ✨] ContextBuilder GSSC 流水线（11 个）
        ├── test_web_search_tool.py  # [v2 ✨] WebSearchToolHandler（7 个）
        ├── test_agent.py            # [v2 ✨] HelloAgent（12 个）
        └── test_env_connectivity.py # [v2 ✨] 真实 API 连通性检测（14 个）⚠️ 需外部服务
        #
        # ─────────────────────────────────────────────
        # 测试执行策略（run_tests.sh）
        # ─────────────────────────────────────────────
        # 模式          命令参数          适用场景
        # unit          --unit            纯本地，CI/CD 快速反馈
        # integration   --integration     mock测试，验证模块协作
        # connectivity  --connectivity    真实API，上线前验证
        # all (默认)    (无参数)          全量执行 + HTML报告
