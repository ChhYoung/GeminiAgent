hello-agents/
└── hello_agents/
    ├── memory/                   # 🧠 核心记忆系统（Agent 的主观经验与内在认知）
    │   ├── base.py               # 基础数据模型（新增：access_count, last_accessed 等遗忘曲线字段）
    │   ├── manager.py            # 记忆调度中枢（对外提供统一的 read/write 接口）
    │   ├── router.py             # (✨新增) 记忆路由器（负责多路召回、相关度算分、Re-rank与上下文融合）
    │   ├── reflection.py         # (✨新增) 反思与巩固引擎（后台将 Episodic 提炼压缩为 Semantic 知识图谱）
    │   ├── events.py             # (✨新增) 异步事件总线（解耦耗时的 DB 读写与 Embedding 计算）
    │   ├── embedding.py          # 统一嵌入服务（文本转向量）
    │   │
    │   ├── types/                # 记忆的四种认知形态
    │   │   ├── working.py        # 工作记忆（Session级别，管理当前对话上下文与 TTL）
    │   │   ├── episodic.py       # 情景记忆（流水账与历史事件，带时间戳，依赖 Qdrant）
    │   │   ├── semantic.py       # 语义记忆（提炼出的实体关系与规则，依赖 Neo4j）
    │   │   └── perceptual.py     # 感知记忆（多模态数据的特征存储）
    │   │
    │   └── storage/              # 物理存储适配层（对上层隐藏数据库细节）
    │       ├── qdrant_store.py   # 向量存储引擎（处理高维相似度检索）
    │       ├── neo4j_store.py    # 图存储引擎（处理实体关系与 GraphRAG 查询）
    │       └── document_store.py # 关系型/文档引擎（SQLite，处理元数据与持久化溯源）
    │
    ├── rag/                      # 📚 外部知识系统（Agent 的客观世界知识库，与主观记忆彻底解耦）
    │   ├── pipeline.py           # 知识检索管道（Chunking -> Embedding -> Retrieval）
    │   ├── document.py           # 多格式文档解析器（PDF, Word, Markdown 等）
    │   └── knowledge_base.py     # (✨新增) 知识库管理（连接企业语料库或外部向量库）
    │
    └── tools/                    # 🛠️ Agent 动作与工具箱
        └── builtin/
            ├── memory_tool.py    # 记忆工具（允许 Agent 主动搜索自己的过去，或主动标记重要记忆）
            └── rag_tool.py       # 知识查询工具（允许 Agent 主动翻阅外部参考资料）