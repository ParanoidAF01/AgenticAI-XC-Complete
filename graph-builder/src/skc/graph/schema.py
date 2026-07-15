"""Neo4j graph schema definitions for the Semantic Knowledge Graph.

Defines all node labels, relationship types, constraints, and indexes
as data structures. The GraphWriter (Phase 5) will consume these
definitions to create the actual Neo4j schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodeLabel:
    """Definition of a Neo4j node label with its properties and constraints.

    Each ``NodeLabel`` describes one label in the graph, listing every
    property the node may carry, which of those properties are required
    (non-optional), an optional uniqueness constraint, and any composite
    indexes that should be created.

    Attributes:
        label: The Neo4j node label name (e.g. ``"Table"``).
        properties: All property names that nodes with this label may have.
        required_properties: Property names that must be present on every
            node with this label.
        unique_constraint: An optional list of property names whose
            combination must be unique across all nodes with this label.
            ``None`` means no uniqueness constraint is defined.
        indexes: A list of property-name lists.  Each inner list describes
            one composite (or single-property) index to create.
    """

    label: str
    properties: list[str]
    required_properties: list[str]
    unique_constraint: list[str] | None = None
    indexes: list[list[str]] = field(default_factory=list)


@dataclass
class RelationshipType:
    """Definition of a Neo4j relationship type.

    Captures the relationship's type name, the source and target node
    labels, any properties carried on the relationship, and a
    human-readable description.

    Attributes:
        type_name: The Neo4j relationship type name (e.g.
            ``"FOREIGN_KEY_TO"``).
        from_label: The label of the source node.
        to_label: The label of the target node.
        properties: Property names stored on the relationship.
        description: A brief human-readable description of the
            relationship's semantics.
    """

    type_name: str
    from_label: str
    to_label: str
    properties: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class GraphSchema:
    """Complete Neo4j graph schema expressed as pure data structures.

    ``GraphSchema`` aggregates all :class:`NodeLabel` and
    :class:`RelationshipType` definitions and provides helper methods to
    look up individual definitions and to generate Cypher DDL statements
    for constraints and indexes.

    Attributes:
        node_labels: All node-label definitions in the schema.
        relationship_types: All relationship-type definitions in the
            schema.
    """

    node_labels: list[NodeLabel] = field(default_factory=list)
    relationship_types: list[RelationshipType] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_node_label(self, label: str) -> NodeLabel | None:
        """Return the :class:`NodeLabel` whose label matches *label*.

        Args:
            label: The node label name to search for (case-sensitive).

        Returns:
            The matching ``NodeLabel`` instance, or ``None`` if no
            definition with that label exists.
        """
        for nl in self.node_labels:
            if nl.label == label:
                return nl
        return None

    def get_relationship_type(self, type_name: str) -> RelationshipType | None:
        """Return the :class:`RelationshipType` whose type matches *type_name*.

        Args:
            type_name: The relationship type name to search for
                (case-sensitive).

        Returns:
            The matching ``RelationshipType`` instance, or ``None`` if
            no definition with that type name exists.
        """
        for rt in self.relationship_types:
            if rt.type_name == type_name:
                return rt
        return None

    # ------------------------------------------------------------------
    # Cypher DDL generation
    # ------------------------------------------------------------------

    def get_constraint_cypher(self) -> list[str]:
        """Generate ``CREATE CONSTRAINT`` Cypher statements for all unique constraints.

        For single-property constraints the generated statement uses
        ``REQUIRE n.<prop> IS UNIQUE``.  For multi-property (composite)
        constraints it uses ``REQUIRE … IS NODE KEY`` which enforces both
        existence and composite uniqueness.

        Returns:
            A list of Cypher ``CREATE CONSTRAINT … IF NOT EXISTS``
            statements ready to be executed against a Neo4j instance.
        """
        statements: list[str] = []
        for nl in self.node_labels:
            if nl.unique_constraint is None:
                continue
            props = nl.unique_constraint
            label_lower = nl.label.lower()
            if len(props) == 1:
                prop = props[0]
                constraint_name = f"{label_lower}_{prop}_unique"
                stmt = (
                    f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                    f"FOR (n:{nl.label}) REQUIRE n.{prop} IS UNIQUE"
                )
            else:
                props_joined = "_".join(props)
                constraint_name = f"{label_lower}_{props_joined}_unique"
                prop_refs = ", ".join(f"n.{p}" for p in props)
                stmt = (
                    f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                    f"FOR (n:{nl.label}) REQUIRE ({prop_refs}) IS NODE KEY"
                )
            statements.append(stmt)
        return statements

    def get_index_cypher(self) -> list[str]:
        """Generate ``CREATE INDEX`` Cypher statements for all defined indexes.

        Each inner list in a :pyattr:`NodeLabel.indexes` specification
        produces one composite (or single-property) index statement.

        Returns:
            A list of Cypher ``CREATE INDEX … IF NOT EXISTS`` statements
            ready to be executed against a Neo4j instance.
        """
        statements: list[str] = []
        for nl in self.node_labels:
            for idx_props in nl.indexes:
                label_lower = nl.label.lower()
                props_joined = "_".join(idx_props)
                index_name = f"{label_lower}_{props_joined}_idx"
                on_clause = ", ".join(f"n.{p}" for p in idx_props)
                stmt = (
                    f"CREATE INDEX {index_name} IF NOT EXISTS "
                    f"FOR (n:{nl.label}) ON ({on_clause})"
                )
                statements.append(stmt)
        return statements


# ======================================================================
# Module-level schema constant
# ======================================================================

SKC_GRAPH_SCHEMA = GraphSchema(
    node_labels=[
        NodeLabel(
            label="Database",
            properties=["id", "name", "dialect", "build_version"],
            required_properties=["name", "dialect"],
            unique_constraint=["id"],
        ),
        NodeLabel(
            label="Schema",
            properties=["id", "name", "database", "build_version"],
            required_properties=["id", "name"],
            unique_constraint=["id"],
            indexes=[["name"]],
        ),
        NodeLabel(
            label="Table",
            properties=["id", "name", "schema", "database", "full_name", "table_type", "row_count", "topology", "build_version"],
            required_properties=["id", "name", "table_type"],
            unique_constraint=["id"],
            indexes=[["name"]],
        ),
        NodeLabel(
            label="Column",
            properties=["id", "name", "table", "schema", "database", "full_name", "data_type", "normalized_type", "is_nullable", "is_primary_key", "is_foreign_key", "build_version"],
            required_properties=["id", "name", "data_type"],
            unique_constraint=["id"],
            indexes=[["name"]],
        ),
        NodeLabel(
            label="BusinessEntity",
            properties=[
                "id",
                "name",
                "description",
                "entity_type",
                "confidence_score",
                "review_status",
                "build_version",
                "build_id",
                "logical_id",
                "content_hash",
                "deprecated",
                "deprecated_at",
            ],
            required_properties=["id", "name"],
            unique_constraint=["id"],
            indexes=[["name"]],
        ),
        NodeLabel(
            label="BusinessConcept",
            properties=[
                "id",
                "name",
                "description",
                "category",
                "confidence_score",
                "review_status",
                "build_version",
                "build_id",
                "logical_id",
                "content_hash",
                "deprecated",
                "deprecated_at",
            ],
            required_properties=["id", "name"],
            unique_constraint=["id"],
            indexes=[["name"]],
        ),
        NodeLabel(
            label="Metric",
            properties=[
                "id",
                "name",
                "description",
                "formula",
                "formula_type",
                "unit",
                "confidence_score",
                "review_status",
                "build_version",
                "build_id",
                "logical_id",
                "content_hash",
                "deprecated",
                "deprecated_at",
            ],
            required_properties=["id", "name"],
            unique_constraint=["id"],
            indexes=[["name"]],
        ),
        NodeLabel(
            label="BusinessRule",
            properties=[
                "id",
                "name",
                "description",
                "rule_type",
                "expression",
                "confidence_score",
                "review_status",
                "build_version",
                "build_id",
                "logical_id",
                "content_hash",
                "deprecated",
                "deprecated_at",
            ],
            required_properties=["id", "name"],
            unique_constraint=["id"],
        ),
        NodeLabel(
            label="Synonym",
            properties=[
                "id",
                "term",
                "canonical_name",
                "language",
                "confidence_score",
                "build_version",
                "build_id",
                "logical_id",
                "content_hash",
                "deprecated",
                "deprecated_at",
            ],
            required_properties=["id", "term"],
            unique_constraint=["id"],
        ),
        NodeLabel(
            label="TimeIntelligence",
            properties=[
                "id",
                "column_ref",
                "time_role",
                "granularity",
                "timezone",
                "build_version",
                "build_id",
                "logical_id",
                "content_hash",
                "deprecated",
                "deprecated_at",
            ],
            required_properties=["id", "column_ref"],
            unique_constraint=["id"],
        ),
        NodeLabel(
            label="SecurityTag",
            properties=[
                "id",
                "scope",
                "classification",
                "build_version",
                "build_id",
                "logical_id",
                "content_hash",
                "deprecated",
                "deprecated_at",
            ],
            required_properties=["id"],
            unique_constraint=["id"],
        ),
        NodeLabel(
            label="Provenance",
            properties=[
                "id",
                "source_type",
                "source_id",
                "source_detail",
                "timestamp",
                "build_version",
            ],
            required_properties=["id", "source_type", "source_id"],
            unique_constraint=["id"],
        ),
        NodeLabel(
            label="Build",
            properties=[
                "id",
                "build_id",
                "build_version",
                "started_at",
                "completed_at",
                "status",
            ],
            required_properties=["id", "build_id", "build_version"],
            unique_constraint=["id"],
        ),
    ],
    relationship_types=[
        RelationshipType(
            type_name="CONTAINS_SCHEMA",
            from_label="Database",
            to_label="Schema",
            description="Database contains schema",
        ),
        RelationshipType(
            type_name="CONTAINS_TABLE",
            from_label="Schema",
            to_label="Table",
            description="Schema contains table",
        ),
        RelationshipType(
            type_name="HAS_COLUMN",
            from_label="Table",
            to_label="Column",
            description="Table has column",
        ),
        RelationshipType(
            type_name="FOREIGN_KEY_TO",
            from_label="Column",
            to_label="Column",
            properties=["fk_name"],
            description="Foreign key reference",
        ),
        RelationshipType(
            type_name="MAPS_TO_TABLE",
            from_label="BusinessEntity",
            to_label="Table",
            properties=["confidence"],
            description="Entity maps to physical table",
        ),
        RelationshipType(
            type_name="MAPS_TO_COLUMN",
            from_label="BusinessConcept",
            to_label="Column",
            properties=["confidence"],
            description="Concept maps to physical column",
        ),
        RelationshipType(
            type_name="RELATED_TO",
            from_label="BusinessEntity",
            to_label="BusinessEntity",
            properties=["logical_id", "content_hash", "build_version", "relationship_type", "cardinality", "description"],
            description="Business relationship between entities",
        ),
        RelationshipType(
            type_name="HAS_METRIC",
            from_label="BusinessEntity",
            to_label="Metric",
            description="Entity has metric",
        ),
        RelationshipType(
            type_name="HAS_RULE",
            from_label="BusinessEntity",
            to_label="BusinessRule",
            description="Entity has business rule",
        ),
        RelationshipType(
            type_name="ENTITY_HAS_SYNONYM",
            from_label="BusinessEntity",
            to_label="Synonym",
            description="Entity has synonym",
        ),
        RelationshipType(
            type_name="CONCEPT_HAS_SYNONYM",
            from_label="BusinessConcept",
            to_label="Synonym",
            description="Concept has synonym",
        ),
        RelationshipType(
            type_name="HAS_TIME_INTELLIGENCE",
            from_label="Column",
            to_label="TimeIntelligence",
            description="Column has time intelligence",
        ),
        RelationshipType(
            type_name="TABLE_HAS_SECURITY",
            from_label="Table",
            to_label="SecurityTag",
            description="Table has security tag",
        ),
        RelationshipType(
            type_name="COLUMN_HAS_SECURITY",
            from_label="Column",
            to_label="SecurityTag",
            description="Column has security tag",
        ),
        RelationshipType(
            type_name="HAS_PROVENANCE",
            from_label="_Any",
            to_label="Provenance",
            description="Node has provenance record",
        ),
        RelationshipType(
            type_name="HAS_GRAIN",
            from_label="BusinessEntity",
            to_label="Column",
            properties=["grain_role"],
            description="Entity has grain column",
        ),
        RelationshipType(
            type_name="SUPERSEDES",
            from_label="_Versioned",
            to_label="_Versioned",
            description="Newer version supersedes older version",
        ),
        RelationshipType(
            type_name="PART_OF_BUILD",
            from_label="_Any",
            to_label="Build",
            description="Node belongs to build",
        ),
    ],
)
