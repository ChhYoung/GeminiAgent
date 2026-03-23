"""
tests/integration/test_env_connectivity.py

.env 可用性检测测试 —— 验证所有 API / 数据库服务是否正常连通。
每个 test 独立可运行，失败时给出明确的诊断信息。

运行方式：
    PYTHONPATH=. pytest tests/integration/test_env_connectivity.py -v -s
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from dotenv import load_dotenv

# 确保从项目目录的 .env 加载（而不是 conftest.py 里的默认值）
load_dotenv(
    dotenv_path=Path(__file__).parent.parent.parent / ".env",
    override=True,
)

from hello_agents.config import get_settings

# 重置缓存，确保读取最新 .env
get_settings.cache_clear()
cfg = get_settings()


# ===========================================================================
# 1. LLM — Qwen / Dashscope
# ===========================================================================

class TestLLMAPI:
    """验证 LLM_API_KEY + LLM_BASE_URL + LLM_MODEL_ID 可用。"""

    def test_api_key_configured(self):
        assert cfg.llm_api_key, "❌ LLM_API_KEY 未配置（.env 中为空）"

    def test_llm_basic_completion(self):
        """发送最小请求，验证 key 有效、模型可用。"""
        import openai

        client = openai.OpenAI(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )
        try:
            resp = client.chat.completions.create(
                model=cfg.llm_model_id,
                messages=[{"role": "user", "content": "reply with the single word: ok"}],
                max_tokens=10,
                temperature=0,
            )
            reply = resp.choices[0].message.content.strip()
            assert reply, "❌ LLM 返回空内容"
            print(f"\n  ✅ LLM 响应: {reply!r}")
        except Exception as e:
            pytest.fail(
                f"❌ LLM API 调用失败\n"
                f"  model   : {cfg.llm_model_id}\n"
                f"  base_url: {cfg.llm_base_url}\n"
                f"  error   : {e}"
            )


# ===========================================================================
# 2. Embedding — Dashscope text-embedding-v3
# ===========================================================================

class TestEmbeddingAPI:
    """验证 Embedding 模型可用（使用相同的 LLM_API_KEY）。"""

    def test_embedding_basic(self):
        """对短文本生成向量，验证维度正确。"""
        import openai

        client = openai.OpenAI(
            api_key=cfg.llm_api_key,
            base_url=cfg.llm_base_url,
        )
        try:
            resp = client.embeddings.create(
                model=cfg.embedding_model,
                input="hello world",
            )
            vec = resp.data[0].embedding
            assert len(vec) > 0, "❌ 返回向量为空"
            assert len(vec) == cfg.embedding_dimension, (
                f"❌ 向量维度不符：期望 {cfg.embedding_dimension}，实际 {len(vec)}"
            )
            print(f"\n  ✅ Embedding 维度: {len(vec)}")
        except Exception as e:
            pytest.fail(
                f"❌ Embedding API 调用失败\n"
                f"  model: {cfg.embedding_model}\n"
                f"  error: {e}"
            )


# ===========================================================================
# 3. Qdrant — 本地向量数据库
# ===========================================================================

class TestQdrantConnectivity:
    """验证 Qdrant 服务可达（http://localhost:6333）。"""

    def test_qdrant_reachable(self):
        try:
            from qdrant_client import QdrantClient
            client = QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key, timeout=5)
            info = client.get_collections()
            collections = [c.name for c in info.collections]
            print(f"\n  ✅ Qdrant 连通，现有集合: {collections or '(空)'}")
        except Exception as e:
            pytest.fail(
                f"❌ Qdrant 连接失败\n"
                f"  url  : {cfg.qdrant_url}\n"
                f"  error: {e}\n"
                f"  提示 : 请确认 Qdrant 容器已启动：docker run -d -p 6333:6333 qdrant/qdrant"
            )

    def test_qdrant_write_read(self):
        """写入一条临时向量，读取后删除，验证读写权限。"""
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PointStruct

        client = QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key, timeout=5)
        col = "_connectivity_test_"
        try:
            # 建临时集合（兼容新版 qdrant-client）
            if client.collection_exists(col):
                client.delete_collection(col)
            client.create_collection(
                collection_name=col,
                vectors_config=VectorParams(size=4, distance=Distance.COSINE),
            )
            # 写入
            client.upsert(col, points=[PointStruct(id=1, vector=[0.1, 0.2, 0.3, 0.4])])
            # 读取
            result = client.retrieve(col, ids=[1])
            assert len(result) == 1, "❌ 写入后读取失败"
            print("\n  ✅ Qdrant 读写正常")
        finally:
            client.delete_collection(col)


# ===========================================================================
# 4. Neo4j — 本地图数据库
# ===========================================================================

class TestNeo4jConnectivity:
    """验证 Neo4j 服务可达（bolt://localhost:7687）。"""

    def test_neo4j_reachable(self):
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                cfg.neo4j_uri,
                auth=(cfg.neo4j_user, cfg.neo4j_password),
            )
            driver.verify_connectivity()
            driver.close()
            print(f"\n  ✅ Neo4j 连通: {cfg.neo4j_uri}")
        except Exception as e:
            pytest.fail(
                f"❌ Neo4j 连接失败\n"
                f"  uri  : {cfg.neo4j_uri}\n"
                f"  user : {cfg.neo4j_user}\n"
                f"  error: {e}\n"
                f"  提示 : docker run -d -p 7687:7687 -e NEO4J_AUTH=neo4j/neo4jpassword neo4j"
            )

    def test_neo4j_write_read(self):
        """执行一条写入 + 读取 Cypher，验证读写权限。"""
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            cfg.neo4j_uri,
            auth=(cfg.neo4j_user, cfg.neo4j_password),
        )
        try:
            with driver.session() as session:
                # 写入临时节点
                session.run(
                    "CREATE (n:_ConnTest {id: $id, val: $val})",
                    id="test_node", val="ping",
                )
                # 读取
                result = session.run(
                    "MATCH (n:_ConnTest {id: $id}) RETURN n.val AS val",
                    id="test_node",
                )
                records = result.data()
                assert records and records[0]["val"] == "ping", "❌ 读取值不匹配"
                # 清理
                session.run("MATCH (n:_ConnTest) DELETE n")
            print("\n  ✅ Neo4j 读写正常")
        finally:
            driver.close()


# ===========================================================================
# 5. SQLite — 本地文档存储
# ===========================================================================

class TestSQLiteConnectivity:
    """验证 SQLite 路径可写、读写正常。"""

    def test_sqlite_dir_writable(self):
        db_path = Path(cfg.sqlite_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        assert db_path.parent.exists(), f"❌ 目录无法创建: {db_path.parent}"
        assert os.access(db_path.parent, os.W_OK), f"❌ 目录不可写: {db_path.parent}"
        print(f"\n  ✅ SQLite 目录可写: {db_path.parent}")

    def test_sqlite_create_and_query(self):
        """在配置的路径创建/写入/读取，验证 SQLite 工作正常。"""
        db_path = Path(cfg.sqlite_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _conn_test (id INTEGER PRIMARY KEY, val TEXT)"
            )
            conn.execute("INSERT OR REPLACE INTO _conn_test VALUES (1, 'ping')")
            conn.commit()
            row = conn.execute("SELECT val FROM _conn_test WHERE id=1").fetchone()
            assert row and row[0] == "ping", "❌ SQLite 读取值不匹配"
            conn.execute("DROP TABLE IF EXISTS _conn_test")
            conn.commit()
            conn.close()
            print(f"\n  ✅ SQLite 读写正常: {db_path}")
        except Exception as e:
            pytest.fail(f"❌ SQLite 操作失败\n  path : {db_path}\n  error: {e}")


# ===========================================================================
# 6. Tavily — Web 搜索（优先）
# ===========================================================================

class TestTavilyAPI:
    """验证 TAVILY_API_KEY 有效、搜索返回结果。"""

    def test_tavily_key_configured(self):
        if not cfg.tavily_api_key:
            pytest.skip("TAVILY_API_KEY 未配置，跳过")

    def test_tavily_search(self):
        if not cfg.tavily_api_key:
            pytest.skip("TAVILY_API_KEY 未配置，跳过")
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=cfg.tavily_api_key)
            resp = client.search(query="python", max_results=1)
            results = resp.get("results", [])
            assert len(results) > 0, "❌ Tavily 返回空结果"
            print(f"\n  ✅ Tavily 搜索正常，首条标题: {results[0].get('title', '')!r}")
        except Exception as e:
            pytest.fail(f"❌ Tavily API 调用失败\n  error: {e}")


# ===========================================================================
# 7. SerpAPI — Web 搜索（备用）
# ===========================================================================

class TestSerpAPI:
    """验证 SERPAPI_API_KEY 有效、搜索返回结果。"""

    def test_serpapi_key_configured(self):
        if not cfg.serpapi_api_key:
            pytest.skip("SERPAPI_API_KEY 未配置，跳过")

    def test_serpapi_search(self):
        if not cfg.serpapi_api_key:
            pytest.skip("SERPAPI_API_KEY 未配置，跳过")
        try:
            import httpx
            resp = httpx.get(
                "https://serpapi.com/search",
                params={
                    "q": "python",
                    "api_key": cfg.serpapi_api_key,
                    "num": 1,
                    "output": "json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            # 检查是否有错误
            if "error" in data:
                pytest.fail(f"❌ SerpAPI 返回错误: {data['error']}")
            results = data.get("organic_results", [])
            assert len(results) > 0, "❌ SerpAPI 返回空结果"
            print(f"\n  ✅ SerpAPI 搜索正常，首条标题: {results[0].get('title', '')!r}")
        except Exception as e:
            pytest.fail(f"❌ SerpAPI 调用失败\n  error: {e}")


# ===========================================================================
# 汇总检查 — 打印所有服务状态
# ===========================================================================

def test_print_connectivity_summary():
    """最后打印一份配置摘要，方便快速定位问题。"""
    lines = [
        "\n" + "=" * 55,
        "  .env 配置摘要",
        "=" * 55,
        f"  LLM 模型    : {cfg.llm_model_id}",
        f"  LLM Base URL: {cfg.llm_base_url}",
        f"  LLM API Key : {'✅ 已配置' if cfg.llm_api_key else '❌ 未配置'}",
        f"  Embedding   : {cfg.embedding_model} (dim={cfg.embedding_dimension})",
        f"  Qdrant      : {cfg.qdrant_url}",
        f"  Neo4j       : {cfg.neo4j_uri}  user={cfg.neo4j_user}",
        f"  SQLite      : {cfg.sqlite_db_path}",
        f"  Tavily      : {'✅ 已配置' if cfg.tavily_api_key else '⚠️  未配置'}",
        f"  SerpAPI     : {'✅ 已配置' if cfg.serpapi_api_key else '⚠️  未配置'}",
        "=" * 55,
    ]
    print("\n".join(lines))
