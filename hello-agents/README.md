# hello-agents

基于 **Gemini** 的对话 Agent，具备四层记忆架构与 RAG 知识检索能力。

## 架构概览

```
hello_agents/
├── memory/                     # 🧠 核心记忆系统
│   ├── base.py                 # 数据模型（含遗忘曲线字段）
│   ├── manager.py              # 记忆调度中枢（统一 read/write 接口）
│   ├── router.py               # 多路召回 + Re-rank + GraphRAG 融合
│   ├── reflection.py           # 反思引擎（Episodic → Semantic 提炼）
│   ├── events.py               # 异步事件总线
│   ├── embedding.py            # Gemini text-embedding-004 封装
│   ├── types/
│   │   ├── working.py          # 工作记忆（Session 级，带 TTL）
│   │   ├── episodic.py         # 情景记忆（事件流水账，Qdrant）
│   │   ├── semantic.py         # 语义记忆（知识图谱，Neo4j）
│   │   └── perceptual.py       # 感知记忆（多模态特征，Qdrant）
│   └── storage/
│       ├── qdrant_store.py     # 向量存储
│       ├── neo4j_store.py      # 图存储
│       └── document_store.py   # SQLite 元数据
├── rag/                        # 📚 外部知识系统
│   ├── pipeline.py             # 检索管道（Chunking → Embedding → 检索）
│   ├── document.py             # 多格式文档解析器（PDF/Word/Markdown）
│   └── knowledge_base.py       # 知识库管理
├── tools/builtin/              # 🛠️ Agent 工具
│   ├── memory_tool.py          # 记忆操作工具（Function Calling）
│   └── rag_tool.py             # 知识查询工具（Function Calling）
└── agent.py                    # Agent 主体
```

## 快速开始

### 1. 安装依赖

```bash
pip install -e .
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 GEMINI_API_KEY 等配置
```

### 3. 启动基础设施

```bash
# Qdrant（向量数据库）
docker run -d -p 6333:6333 qdrant/qdrant

# Neo4j（图数据库）
docker run -d -p 7687:7687 -e NEO4J_AUTH=neo4j/your_password neo4j
```

### 4. 运行示例

```bash
# 基础对话
python examples/basic_chat.py

# 记忆系统演示
python examples/memory_demo.py

# RAG 知识库演示
python examples/rag_demo.py
```

## 核心概念

### 四层记忆

| 类型 | 存储 | 生命周期 | 用途 |
|------|------|----------|------|
| 工作记忆 | 内存 | Session 级（TTL） | 当前对话上下文 |
| 情景记忆 | Qdrant + SQLite | 长期（遗忘曲线衰减） | 历史事件流水账 |
| 语义记忆 | Neo4j + Qdrant + SQLite | 长期（稳定） | 实体关系知识图谱 |
| 感知记忆 | Qdrant + SQLite | 长期 | 多模态特征 |

### 遗忘曲线

基于 Ebbinghaus 遗忘曲线，每条记忆有 `strength` 和 `stability` 字段：

- `strength(t) = exp(-elapsed_days / stability)`
- 每次被访问时，`stability` 增长，`strength` 恢复
- 强度低于阈值的记忆可被垃圾回收

### 反思引擎

后台定期将情景记忆提炼为语义记忆（受 "Generative Agents" 论文启发）：

1. 取出近期高重要性的情景记忆
2. 用 Gemini 抽取实体和关系
3. 写入 Neo4j 知识图谱

## API 快速参考

```python
from hello_agents.agent import HelloAgent

agent = HelloAgent.from_env()
await agent.start()

# 对话
response = await agent.chat("你好，我叫小明", session_id="user_001")

# 添加知识库文档
agent.add_knowledge("company_docs", file_path="/path/to/doc.pdf")

await agent.stop()
```

```python
from hello_agents.memory.manager import MemoryManager
from hello_agents.memory.base import MemoryType, ImportanceLevel

manager = MemoryManager.from_env()
await manager.start()

# 写入
manager.write("用户喜欢 Python", memory_type=MemoryType.EPISODIC)

# 读取
results = manager.read("编程语言偏好")

# 获取可注入 Prompt 的上下文
ctx = manager.build_context("Python 编程")
```
