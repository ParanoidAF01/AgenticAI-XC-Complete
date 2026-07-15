"""Neo4j graph query utilities."""

from __future__ import annotations

from typing import Any

from skc.config import Neo4jConfig
from skc.graph.schema import SKC_GRAPH_SCHEMA


class GraphReader:
    """Small read-only helper for validating graph state."""

    def __init__(self, config: Neo4jConfig) -> None:
        self.config = config
        self.driver: Any = None

    def connect(self) -> None:
        if self.config.dry_run:
            raise RuntimeError("GraphReader requires neo4j.dry_run=false")
        try:
            from neo4j import GraphDatabase
        except Exception as exc:
            raise RuntimeError("neo4j package is required for graph reads") from exc
        self.driver = GraphDatabase.driver(
            self.config.uri,
            auth=(self.config.username, self.config.password),
        )

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    def __enter__(self) -> GraphReader:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def count_nodes_by_label(self, label: str) -> int:
        """Return the count of nodes for a label."""
        self._ensure_connected()
        statement = f"MATCH (n:{label}) RETURN count(n) AS count"
        with self.driver.session(database=self.config.database) as session:
            return int(session.run(statement).single()["count"])

    def count_relationships_by_type(self, relationship_type: str) -> int:
        """Return the count of relationships for a type."""
        self._ensure_connected()
        statement = f"MATCH ()-[r:{relationship_type}]->() RETURN count(r) AS count"
        with self.driver.session(database=self.config.database) as session:
            return int(session.run(statement).single()["count"])

    def get_entity_subgraph(self, entity_name: str) -> list[dict[str, Any]]:
        """Return a shallow entity subgraph for inspection."""
        self._ensure_connected()
        statement = """
        MATCH (entity:BusinessEntity {name: $entity_name})
        OPTIONAL MATCH (entity)-[relationship]-(neighbor)
        RETURN entity, relationship, neighbor
        """
        with self.driver.session(database=self.config.database) as session:
            return [record.data() for record in session.run(statement, {"entity_name": entity_name})]

    def node_label_counts(self) -> dict[str, int]:
        """Return counts for all SKC node labels."""
        return {
            label.label: self.count_nodes_by_label(label.label)
            for label in SKC_GRAPH_SCHEMA.node_labels
        }

    def relationship_type_counts(self) -> dict[str, int]:
        """Return counts for all SKC relationship types."""
        return {
            rel.type_name: self.count_relationships_by_type(rel.type_name)
            for rel in SKC_GRAPH_SCHEMA.relationship_types
        }

    def graph_stats(self) -> dict[str, Any]:
        """Return graph-level node and relationship statistics."""
        node_counts = self.node_label_counts()
        relationship_counts = self.relationship_type_counts()
        return {
            "nodes": node_counts,
            "relationships": relationship_counts,
            "total_nodes": sum(node_counts.values()),
            "total_relationships": sum(relationship_counts.values()),
        }

    def export_graph(self, limit: int | None = None) -> dict[str, Any]:
        """Export graph nodes and relationships into a JSON-friendly payload."""
        self._ensure_connected()
        node_sql = """
        MATCH (n)
        RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS properties
        ORDER BY element_id
        """
        relationship_sql = """
        MATCH (from)-[relationship]->(to)
        RETURN elementId(relationship) AS element_id,
               type(relationship) AS type,
               properties(relationship) AS properties,
               coalesce(from.id, elementId(from)) AS from_id,
               coalesce(to.id, elementId(to)) AS to_id,
               labels(from) AS from_labels,
               labels(to) AS to_labels
        ORDER BY element_id
        """
        if limit is not None:
            node_sql += "\nLIMIT $limit"
            relationship_sql += "\nLIMIT $limit"

        params = {"limit": limit} if limit is not None else {}
        with self.driver.session(database=self.config.database) as session:
            nodes = [record.data() for record in session.run(node_sql, params)]
            relationships = [
                record.data()
                for record in session.run(relationship_sql, params)
            ]
        return {"nodes": nodes, "relationships": relationships}

    def _ensure_connected(self) -> None:
        if self.driver is None:
            self.connect()
