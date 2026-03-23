"""
memory/storage/neo4j_store.py — Neo4j 图存储引擎

负责语义记忆中实体、关系的存储与 GraphRAG 查询。
节点标签：Entity | Memory
关系类型：RELATES_TO | DERIVED_FROM | INSTANCE_OF
"""

from __future__ import annotations

import logging
import os
from typing import Any

from neo4j import GraphDatabase, AsyncGraphDatabase
from neo4j.exceptions import ServiceUnavailable

logger = logging.getLogger(__name__)

_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
_NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# ------------------------------------------------------------------
# Cypher 语句
# ------------------------------------------------------------------

_UPSERT_MEMORY_NODE = """
MERGE (m:Memory {id: $id})
SET m += $props
RETURN m
"""

_UPSERT_ENTITY = """
MERGE (e:Entity {name: $name, type: $entity_type})
SET e.updated_at = $updated_at
RETURN e
"""

_UPSERT_RELATION = """
MATCH (a:Entity {name: $from_name}), (b:Entity {name: $to_name})
MERGE (a)-[r:RELATES_TO {relation: $relation}]->(b)
SET r.weight = $weight, r.memory_id = $memory_id
RETURN r
"""

_LINK_MEMORY_TO_ENTITY = """
MATCH (m:Memory {id: $memory_id}), (e:Entity {name: $entity_name})
MERGE (m)-[:MENTIONS]->(e)
"""

_SEARCH_ENTITIES = """
MATCH (e:Entity)
WHERE e.name CONTAINS $keyword OR e.type = $entity_type
RETURN e LIMIT $limit
"""

_GRAPH_NEIGHBORS = """
MATCH (e:Entity {name: $name})-[r]-(neighbor)
RETURN e, r, neighbor LIMIT $limit
"""

_GET_MEMORY_SUBGRAPH = """
MATCH (m:Memory {id: $memory_id})-[:MENTIONS]->(e:Entity)-[r:RELATES_TO*1..2]-(neighbor:Entity)
RETURN m, e, r, neighbor LIMIT 50
"""


class Neo4jStore:
    """同步 Neo4j 存储，用于语义记忆的实体关系图谱。"""

    def __init__(
        self,
        uri: str = _NEO4J_URI,
        user: str = _NEO4J_USER,
        password: str = _NEO4J_PASSWORD,
    ) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_constraints()

    def _ensure_constraints(self) -> None:
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE (e.name, e.type) IS UNIQUE"
            )

    def close(self) -> None:
        self._driver.close()

    # ------------------------------------------------------------------
    # 记忆节点
    # ------------------------------------------------------------------

    def upsert_memory_node(self, memory_id: str, props: dict[str, Any]) -> None:
        with self._driver.session() as session:
            session.run(_UPSERT_MEMORY_NODE, id=memory_id, props=props)

    def delete_memory_node(self, memory_id: str) -> None:
        with self._driver.session() as session:
            session.run(
                "MATCH (m:Memory {id: $id}) DETACH DELETE m", id=memory_id
            )

    # ------------------------------------------------------------------
    # 实体与关系
    # ------------------------------------------------------------------

    def upsert_entity(
        self,
        name: str,
        entity_type: str,
        updated_at: str,
    ) -> None:
        with self._driver.session() as session:
            session.run(
                _UPSERT_ENTITY,
                name=name,
                entity_type=entity_type,
                updated_at=updated_at,
            )

    def upsert_relation(
        self,
        from_name: str,
        to_name: str,
        relation: str,
        weight: float = 1.0,
        memory_id: str = "",
    ) -> None:
        with self._driver.session() as session:
            session.run(
                _UPSERT_RELATION,
                from_name=from_name,
                to_name=to_name,
                relation=relation,
                weight=weight,
                memory_id=memory_id,
            )

    def link_memory_to_entity(self, memory_id: str, entity_name: str) -> None:
        with self._driver.session() as session:
            session.run(
                _LINK_MEMORY_TO_ENTITY,
                memory_id=memory_id,
                entity_name=entity_name,
            )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def search_entities(
        self,
        keyword: str = "",
        entity_type: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(
                _SEARCH_ENTITIES,
                keyword=keyword,
                entity_type=entity_type,
                limit=limit,
            )
            return [dict(record["e"]) for record in result]

    def get_graph_neighbors(
        self, entity_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self._driver.session() as session:
            result = session.run(
                _GRAPH_NEIGHBORS, name=entity_name, limit=limit
            )
            rows = []
            for record in result:
                rows.append(
                    {
                        "entity": dict(record["e"]),
                        "relation": dict(record["r"]),
                        "neighbor": dict(record["neighbor"]),
                    }
                )
            return rows

    def get_memory_subgraph(self, memory_id: str) -> list[dict[str, Any]]:
        """获取与某条记忆关联的 2 跳子图，用于 GraphRAG 上下文扩展。"""
        with self._driver.session() as session:
            result = session.run(_GET_MEMORY_SUBGRAPH, memory_id=memory_id)
            rows = []
            for record in result:
                rows.append(
                    {
                        "memory": dict(record["m"]),
                        "entity": dict(record["e"]),
                        "neighbor": dict(record["neighbor"]),
                    }
                )
            return rows

    def run_cypher(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """执行任意 Cypher 语句并返回结果列表。"""
        with self._driver.session() as session:
            result = session.run(cypher, **(params or {}))
            return [dict(record) for record in result]

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        try:
            with self._driver.session() as session:
                session.run("RETURN 1")
            return True
        except ServiceUnavailable:
            return False
