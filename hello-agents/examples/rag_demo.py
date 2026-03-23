"""
examples/rag_demo.py — RAG 知识库演示

演示如何创建知识库、索引文本/文档、检索内容。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from hello_agents.rag.knowledge_base import KnowledgeBaseManager
from hello_agents.rag.pipeline import RAGPipeline
from hello_agents.memory.embedding import EmbeddingService


def main():
    print("初始化 RAG 系统...\n")

    embedding = EmbeddingService()
    pipeline = RAGPipeline(embedding=embedding)
    mgr = KnowledgeBaseManager(pipeline=pipeline)

    # ---- 创建知识库 ----
    print("创建知识库 'company_docs'...")
    kb = mgr.create("company_docs", description="公司内部文档")

    # ---- 索引文本 ----
    sample_texts = [
        ("Python 是一种高级编程语言，以其简洁的语法和强大的库生态系统而闻名。", "python_intro"),
        ("FastAPI 是一个现代的 Python Web 框架，基于标准 Python 类型提示，性能极高。", "fastapi_intro"),
        ("Qdrant 是一个向量数据库，专为高性能相似度搜索而设计，支持过滤和有效载荷存储。", "qdrant_intro"),
        ("Neo4j 是一个图数据库，使用节点、关系和属性来表示和存储数据，非常适合复杂关系查询。", "neo4j_intro"),
        ("RAG（检索增强生成）通过在生成回答前检索相关文档来提升 LLM 的准确性。", "rag_intro"),
    ]

    print("索引 5 条技术文档...")
    for text, source in sample_texts:
        count = kb.add_text(text, source=source)
        print(f"  ✓ [{source}] indexed {count} chunks")

    print()

    # ---- 检索 ----
    queries = ["Python Web 框架", "向量数据库相似度搜索", "图数据库关系查询"]
    for query in queries:
        print(f"检索: '{query}'")
        results = kb.search(query, top_k=2, min_score=0.3)
        for r in results:
            print(f"  [{r.score:.3f}] {r.chunk.text[:80]}...")
        print()

    # ---- 构建上下文 ----
    print("构建 RAG 上下文（用于 Prompt 注入）：")
    ctx = kb.build_context("什么是 RAG？", top_k=3, max_chars=1000)
    print(ctx[:500])

    # ---- 列出知识库 ----
    print("\n当前所有知识库：")
    for kb_meta in mgr.list_all():
        print(f"  - {kb_meta['name']}: {kb_meta.get('description', '')}")


if __name__ == "__main__":
    main()
