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
└── tests/                        # ✅ 测试套件（159 个用例，pytest + pytest-asyncio）
    │
    ├── conftest.py               # 共享 fixtures
    │                             #   • tmp_db      — 返回临时 SQLite 路径（每个测试隔离）
    │                             #   • mock_tool_call — 构造 mock OpenAI tool_call 对象
    │
    ├── run_tests.sh              # 🚀 一键全量执行脚本（见"测试执行策略"）
    │
    ├── unit/                     # 🧪 单元测试（117 个）
    │   │                         #    策略：纯本地、无网络、无外部服务，毫秒级反馈
    │   │                         #    工具：pytest，不依赖 mock 网络
    │   │
    │   ├── test_memory_base.py   # MemoryRecord（22 个）
    │   │                         #   • 创建与默认值：strength/stability/access_count/UUID唯一性
    │   │                         #   • decay()：Ebbinghaus 指数衰减公式验证、不低于0
    │   │                         #   • reinforce()：access_count递增、strength/stability增强
    │   │                         #   • is_forgotten()：新鲜记忆不遗忘、深度衰减超阈值
    │   │                         #   • 序列化：to_storage_dict排除embedding、时间戳字符串化
    │   │                         #   • roundtrip：from_storage_dict完整还原所有字段
    │   │                         #   • MemoryQuery：默认类型列表、top_k默认值、自定义参数
    │   │
    │   ├── test_working_memory.py # WorkingMemory + WorkingMemoryStore（22 个）
    │   │                         #   • add()：返回 MemoryRecord、importance映射score、metadata透传
    │   │                         #   • get()：存在返回记录、不存在返回None、自动reinforce
    │   │                         #   • TTL eviction：过期自动清除、pinned不受TTL影响
    │   │                         #   • get_window()：返回最近N条、不足N时全返回
    │   │                         #   • to_context_string()：[role]: content格式、空时返回""
    │   │                         #   • delete()/clear()：删除存在/不存在记录、清空所有
    │   │                         #   • pin()：保护记录不被trim、unpin()解除保护
    │   │                         #   • WorkingMemoryStore：多session隔离、同session同实例
    │   │
    │   ├── test_tool_registry.py  # ToolRegistry（10 个）
    │   │                         #   • register_handler()：单/多handler注册、schema正确存储
    │   │                         #   • get_schemas()：返回副本防外部篡改、空注册表返回[]
    │   │                         #   • dispatch()：按name路由到正确handler、返回handler结果
    │   │                         #   • dispatch()：未知工具返回 {"error": ...} JSON
    │   │                         #   • has_tool()：已注册返回True、未注册返回False
    │   │
    │   ├── test_note_tool.py      # NoteToolHandler SQLite CRUD（18 个）
    │   │                         #   • create_note：基础/带tags/多条ID递增
    │   │                         #   • read_note：读取存在记录/不存在返回error/含时间戳
    │   │                         #   • update_note：更新title/content/tags各字段独立
    │   │                         #   • delete_note：删除存在/不存在均返回deleted状态
    │   │                         #   • list_notes：全量/空表/tag过滤/limit限制
    │   │                         #   • 错误处理：非法JSON参数/未知tool名
    │   │
    │   ├── test_terminal_tool.py  # TerminalToolHandler（20 个）
    │   │                         #   • _is_safe_command()：白名单通过（ls/cat/python3）
    │   │                         #   • _is_safe_command()：黑名单拦截（rm/sudo/curl/>/空命令）
    │   │                         #   • run_command()：echo执行/cwd参数/截断标志
    │   │                         #   • run_command()：危险命令返回拦截error
    │   │                         #   • read_file()：正常读取/不存在/目录/大文件截断/size字段
    │   │                         #   • list_directory()：列举/不存在/隐藏文件控制/类型区分
    │   │                         #   • 错误处理：非法JSON/未知tool名
    │   │
    │   ├── test_context_select.py # select()（9 个）
    │   │                         #   • 过滤：min_score阈值剔除低相关度条目
    │   │                         #   • 排序：score降序保证高优先级优先填充
    │   │                         #   • token预算：精确填满/截断末尾item(>100chars)/剩余<100不截断
    │   │                         #   • 边界：空输入/全不满足阈值/单条/metadata透传
    │   │
    │   └── test_context_structure.py # structure()（10 个）
    │                             #   • 空输入返回""
    │                             #   • memory组：<memory>标签/score展示/多条编号[1][2]
    │                             #   • rag组：<knowledge>标签/source_file+section来源/unknown兜底
    │                             #   • system_state组：<system_state>标签
    │                             #   • 混合：三组同时存在/未知source忽略/组间\n\n分隔
    │
    └── integration/              # 🔗 集成测试（42 个）
        │                         #    策略：mock外部API调用，验证模块间协作逻辑
        │                         #    工具：pytest-asyncio（异步）+ unittest.mock
        │
        ├── test_context_builder.py  # ContextBuilder GSSC流水线（11 个）
        │                         #   • 无数据源返回""、空记忆返回""
        │                         #   • 有效记忆结果出现在输出中（含<memory>标签）
        │                         #   • 低score条目被select阶段过滤
        │                         #   • max_chars≤阈值不触发compress、超出触发LLM压缩
        │                         #   • compress LLM失败降级为截断
        │                         #   • memory gather异常不崩溃、token_budget自定义
        │
        ├── test_web_search_tool.py  # WebSearchToolHandler（7 个）
        │                         #   • 无key返回配置错误提示
        │                         #   • Tavily key存在时优先调用Tavily
        │                         #   • Tavily失败自动降级SerpAPI
        │                         #   • top_n参数正确透传
        │                         #   • 非法JSON/未知tool名返回error
        │
        ├── test_agent.py            # HelloAgent（12 个）
        │                         #   • start()/stop()调用memory start/stop
        │                         #   • chat()返回assistant文本、空响应返回""
        │                         #   • chat()写入工作记忆（user+assistant双条）
        │                         #   • include_context=True调用ContextBuilder
        │                         #   • include_context=False跳过ContextBuilder
        │                         #   • ContextBuilder异常不影响chat返回
        │                         #   • Function Calling：tool_call被dispatch、返回第二轮文本
        │                         #   • 超过max_tool_rounds(5)自动停止循环
        │                         #   • add_knowledge()：text/file分别调用正确接口
        │
        └── test_env_connectivity.py # 真实API连通性检测（14 个）⚠️ 需外部服务
                                  #   • LLM：API Key配置检查 + 真实completion调用
                                  #   • Embedding：text-embedding-v3向量生成 + 维度校验(1024)
                                  #   • Qdrant：服务连通 + 写入/读取/清理临时集合
                                  #   • Neo4j：服务连通 + Cypher读写/清理临时节点
                                  #   • SQLite：目录可写 + 建表/读写/清理
                                  #   • Tavily：Key配置 + 真实搜索返回结果
                                  #   • SerpAPI：Key配置 + 真实搜索返回结果
                                  #   • 汇总：打印所有服务配置状态摘要
                                  #
                                  # ─────────────────────────────────────────────
                                  # 测试执行策略（run_tests.sh）
                                  # ─────────────────────────────────────────────
                                  # 模式          命令参数          适用场景
                                  # unit          --unit            纯本地，CI/CD 快速反馈
                                  # integration   --integration     mock测试，验证模块协作
                                  # connectivity  --connectivity    真实API，上线前验证
                                  # all (默认)    (无参数)          全量执行 + HTML报告
