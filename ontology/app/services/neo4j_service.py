"""Neo4j service — reads the ontology graph to build schema context.

The graph contains metadata-only nodes (no raw data):

    (:Table)-[:HAS_COLUMN]->(:Column)
    (:Table)-[:JOINS_TO]->(:Table)        — edge carries ``sql_snippet``
    (:Table)-[:BELONGS_TO]->(:Domain)
    (:JoinPath)                           — precomputed multi-hop join paths
    (:BusinessConcept)                    — domain-level concepts
    (:QueryPattern)                       — canonical question templates

Full-text indexes ``searchTables`` and ``searchConcepts`` are assumed to
already exist in the database.
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

logger = logging.getLogger(__name__)


class Neo4jService:
    """Async wrapper around the Neo4j Python driver for ontology look-ups."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        """Create the async driver.  The actual TCP handshake happens lazily.

        Args:
            uri: Bolt URI, e.g. ``bolt://localhost:7687``.
            user: Neo4j username.
            password: Neo4j password.
        """
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri, auth=(user, password)
        )
        logger.info("Neo4jService initialised (uri=%s, user=%s)", uri, user)

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Gracefully close the driver and release all connections."""
        await self._driver.close()
        logger.info("Neo4jService connection closed.")

    async def verify_connectivity(self) -> bool:
        """Return ``True`` when the database is reachable."""
        try:
            await self._driver.verify_connectivity()
            return True
        except Exception:
            logger.exception("Neo4j connectivity check failed")
            return False

    # ── table discovery ─────────────────────────────────────────────────────

    async def find_relevant_tables(self, question: str) -> list[dict[str, Any]]:
        """Use the ``searchTables`` full-text index to find tables matching
        the natural-language *question*.

        Returns a list of dicts with keys:
            ``table_name``, ``description``, ``business_purpose``,
            ``common_aliases``, ``score``.
        """
        query = """
            CALL db.index.fulltext.queryNodes('searchTables', $question)
            YIELD node, score
            RETURN node.table_name      AS table_name,
                   node.description     AS description,
                   node.business_purpose AS business_purpose,
                   node.common_aliases  AS common_aliases,
                   score
            ORDER BY score DESC
            LIMIT 10
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(query, question=question)
                records = await result.data()
                logger.debug(
                    "find_relevant_tables matched %d table(s)", len(records)
                )
                return records
        except Exception:
            logger.exception("find_relevant_tables failed for q=%r", question)
            return []

    # ── join relationships ──────────────────────────────────────────────────

    async def get_join_paths(self, table_names: list[str]) -> list[dict[str, Any]]:
        """Return direct ``JOINS_TO`` relationships between the given tables.

        Each result dict contains:
            ``from_table``, ``to_table``, ``sql_snippet``,
            ``from_column``, ``to_column``, ``join_type``.
        """
        query = """
            MATCH (a:Table)-[j:JOINS_TO]->(b:Table)
            WHERE a.table_name IN $tables AND b.table_name IN $tables
            RETURN a.table_name  AS from_table,
                   b.table_name  AS to_table,
                   j.sql_snippet AS sql_snippet,
                   j.from_column AS from_column,
                   j.to_column   AS to_column,
                   j.join_type   AS join_type
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(query, tables=table_names)
                records = await result.data()
                logger.debug("get_join_paths returned %d path(s)", len(records))
                return records
        except Exception:
            logger.exception("get_join_paths failed for tables=%s", table_names)
            return []

    async def get_precomputed_paths(
        self, table_names: list[str]
    ) -> list[dict[str, Any]]:
        """Find :class:`JoinPath` nodes whose ``tables_in_order`` list
        overlaps with the given *table_names*.

        Returns dicts with ``path_name``, ``tables_in_order``,
        ``full_sql_snippet``, and ``description``.
        """
        query = """
            MATCH (jp:JoinPath)
            WHERE ANY(t IN jp.tables_in_order WHERE t IN $tables)
            RETURN jp.path_name        AS path_name,
                   jp.tables_in_order  AS tables_in_order,
                   jp.full_sql_snippet AS full_sql_snippet,
                   jp.description      AS description
            ORDER BY SIZE(
                [t IN jp.tables_in_order WHERE t IN $tables]
            ) DESC
            LIMIT 5
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(query, tables=table_names)
                records = await result.data()
                logger.debug(
                    "get_precomputed_paths returned %d path(s)", len(records)
                )
                return records
        except Exception:
            logger.exception(
                "get_precomputed_paths failed for tables=%s", table_names
            )
            return []

    # ── business concepts ───────────────────────────────────────────────────

    async def get_business_concepts(
        self, question: str
    ) -> list[dict[str, Any]]:
        """Use the ``searchConcepts`` full-text index to surface
        :class:`BusinessConcept` nodes relevant to *question*.
        """
        query = """
            CALL db.index.fulltext.queryNodes('searchConcepts', $question)
            YIELD node, score
            RETURN node.name        AS concept_name,
                   node.description AS description,
                   node.sql_logic   AS sql_logic,
                   node.tables_used AS tables_used,
                   score
            ORDER BY score DESC
            LIMIT 5
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(query, question=question)
                records = await result.data()
                logger.debug(
                    "get_business_concepts matched %d concept(s)", len(records)
                )
                return records
        except Exception:
            logger.exception(
                "get_business_concepts failed for q=%r", question
            )
            return []

    # ── query patterns ──────────────────────────────────────────────────────

    async def get_query_patterns(
        self, question: str
    ) -> list[dict[str, Any]]:
        """Return :class:`QueryPattern` nodes whose example questions are
        similar to *question*.

        Uses the ``searchConcepts`` index (patterns are indexed alongside
        concepts) or a dedicated pattern index if available.
        """
        query = """
            MATCH (qp:QueryPattern)
            WHERE ANY(ex IN qp.example_questions
                      WHERE toLower(ex) CONTAINS toLower($question))
               OR toLower(qp.description) CONTAINS toLower($question)
            RETURN qp.pattern_name       AS pattern_name,
                   qp.description        AS description,
                   qp.sql_template       AS sql_template,
                   qp.example_questions  AS example_questions,
                   qp.tables_used        AS tables_used
            LIMIT 3
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(query, question=question)
                records = await result.data()
                logger.debug(
                    "get_query_patterns returned %d pattern(s)", len(records)
                )
                return records
        except Exception:
            logger.exception(
                "get_query_patterns failed for q=%r", question
            )
            return []

    # ── columns & table details ─────────────────────────────────────────────

    async def get_columns_for_table(
        self, table_name: str
    ) -> list[dict[str, Any]]:
        """Return every :class:`Column` attached to *table_name* via
        ``HAS_COLUMN``.
        """
        query = """
            MATCH (t:Table {table_name: $table_name})-[:HAS_COLUMN]->(c:Column)
            RETURN c.column_name  AS column_name,
                   c.data_type    AS data_type,
                   c.description  AS description,
                   c.is_nullable  AS is_nullable,
                   c.is_key       AS is_key,
                   c.sample_values AS sample_values
            ORDER BY c.column_name
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(query, table_name=table_name)
                records = await result.data()
                logger.debug(
                    "get_columns_for_table(%s) -> %d col(s)",
                    table_name,
                    len(records),
                )
                return records
        except Exception:
            logger.exception(
                "get_columns_for_table failed for table=%s", table_name
            )
            return []

    async def get_table_details(self, table_name: str) -> dict[str, Any]:
        """Return all properties of the :class:`Table` node for *table_name*.

        Returns an empty dict when the table is not found.
        """
        query = """
            MATCH (t:Table {table_name: $table_name})
            RETURN t { .* } AS props
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(query, table_name=table_name)
                record = await result.single()
                if record is None:
                    logger.warning("Table %r not found in graph", table_name)
                    return {}
                return dict(record["props"])
        except Exception:
            logger.exception(
                "get_table_details failed for table=%s", table_name
            )
            return {}

    # ── domain context ──────────────────────────────────────────────────────

    async def get_domain_context(
        self, table_names: list[str]
    ) -> list[dict[str, Any]]:
        """Return :class:`Domain` nodes linked to the given tables via
        ``BELONGS_TO``.
        """
        query = """
            MATCH (t:Table)-[:BELONGS_TO]->(d:Domain)
            WHERE t.table_name IN $tables
            RETURN DISTINCT
                   d.name        AS domain_name,
                   d.description AS description,
                   COLLECT(t.table_name) AS tables
        """
        try:
            async with self._driver.session() as session:
                result = await session.run(query, tables=table_names)
                records = await result.data()
                logger.debug(
                    "get_domain_context returned %d domain(s)", len(records)
                )
                return records
        except Exception:
            logger.exception(
                "get_domain_context failed for tables=%s", table_names
            )
            return []

    # ── orchestration ───────────────────────────────────────────────────────

    async def build_schema_context(self, question: str) -> dict[str, Any]:
        """Orchestrate every look-up into a single structured context dict
        that the LLM can consume to generate accurate SQL.

        The returned dict has keys:
            ``tables``, ``columns``, ``joins``, ``precomputed_paths``,
            ``business_concepts``, ``query_patterns``, ``domains``.
        """
        logger.info("Building schema context for q=%r", question)

        # Step 1 – discover relevant tables via full-text search
        tables = await self.find_relevant_tables(question)
        table_names = [t["table_name"] for t in tables]

        if not table_names:
            logger.warning("No tables found for question — returning empty context")
            return {
                "tables": [],
                "columns": {},
                "joins": [],
                "precomputed_paths": [],
                "business_concepts": [],
                "query_patterns": [],
                "domains": [],
            }

        # Step 2 – fan-out: columns, joins, concepts, patterns, domains
        columns: dict[str, list[dict[str, Any]]] = {}
        for tname in table_names:
            columns[tname] = await self.get_columns_for_table(tname)

        joins = await self.get_join_paths(table_names)
        precomputed = await self.get_precomputed_paths(table_names)
        concepts = await self.get_business_concepts(question)
        patterns = await self.get_query_patterns(question)
        domains = await self.get_domain_context(table_names)

        context: dict[str, Any] = {
            "tables": tables,
            "columns": columns,
            "joins": joins,
            "precomputed_paths": precomputed,
            "business_concepts": concepts,
            "query_patterns": patterns,
            "domains": domains,
        }

        logger.info(
            "Schema context built: %d table(s), %d join(s), %d concept(s)",
            len(tables),
            len(joins),
            len(concepts),
        )
        return context
